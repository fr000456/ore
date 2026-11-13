import argparse
import os
import pickle
import re
import sqlite3
from collections import defaultdict
from datetime import datetime

import lightgbm as lgb
import numpy as np

from feature_engineering import (
    calculate_horse_features,
    parse_date,
)
from train_models_by_condition import (
    get_model_params,
    prepare_features_for_model,
    split_indices_by_race_date,
)


JRA_COURSES = (
    '東京',
    '中山',
    '京都',
    '阪神',
    '新潟',
    '中京',
    '札幌',
    '函館',
    '福島',
    '小倉',
)
DIRT_MAIDEN_TRAINING_FILE = 'training_data_jra_dirt_maiden.pkl'
DIRT_MAIDEN_MODEL_FILE = 'model_jra_dirt_maiden.pkl'
DIRT_MAIDEN_MODEL_GROUP = 'jra_dirt_maiden'
TRAINING_START_DATE = '2016/11/01'
SPECIAL_FEATURE_PREFIX = 'dirt_maiden_'
PREVIOUS_GOOD_FINISH_MAX_POSITION = 5
PREVIOUS_GOOD_FINISH_MAX_MARGIN = 1.0


def canonical_jra_course(course):
    if not isinstance(course, str):
        return None
    return next((name for name in JRA_COURSES if name in course), None)


def is_jra_dirt_maiden(course, surface, race_class):
    try:
        normalized_class = int(race_class)
    except (TypeError, ValueError):
        return False
    return (
        surface == 'ダート'
        and normalized_class == 1
        and canonical_jra_course(course) is not None
    )


def is_debut_horse(features):
    return features.get('total_races', 0) == 0


def _past_races(race_history, target_date):
    parsed_target_date = (
        target_date if isinstance(target_date, datetime) else parse_date(target_date)
    )
    if parsed_target_date is None:
        raise ValueError(f'Invalid target race date: {target_date!r}')
    return sorted(
        (
            race for race in race_history
            if parse_date(race.get('race_date')) is not None
            and parse_date(race.get('race_date')) < parsed_target_date
        ),
        key=lambda race: race.get('race_date', ''),
        reverse=True,
    )


def _top3_count(races):
    return sum(
        1 for race in races
        if isinstance(race.get('finish_position'), (int, float))
        and race['finish_position'] <= 3
    )


def _passing_positions(value):
    if value is None:
        return []
    return [int(number) for number in re.findall(r'\d+', str(value))]


def _brier_score(targets, predictions):
    return float(np.mean((targets - predictions) ** 2))


def _log_loss(targets, predictions):
    clipped = np.clip(predictions, 1e-15, 1 - 1e-15)
    return float(-np.mean(
        targets * np.log(clipped)
        + (1 - targets) * np.log(1 - clipped)
    ))


def _roc_auc(targets, predictions):
    positives = int(np.sum(targets == 1))
    negatives = len(targets) - positives
    if not positives or not negatives:
        return None

    order = np.argsort(predictions, kind='mergesort')
    sorted_predictions = predictions[order]
    ranks = np.empty(len(predictions), dtype=float)
    start = 0
    while start < len(order):
        end = start + 1
        while (
            end < len(order)
            and sorted_predictions[end] == sorted_predictions[start]
        ):
            end += 1
        ranks[order[start:end]] = (start + 1 + end) / 2
        start = end
    positive_rank_sum = float(np.sum(ranks[targets == 1]))
    return (
        positive_rank_sum - positives * (positives + 1) / 2
    ) / (positives * negatives)


def add_dirt_maiden_features(
    features,
    race_history,
    target_date,
    target_distance,
    target_course,
):
    """Add race-history-only features for JRA dirt maiden predictions."""
    history = _past_races(race_history, target_date)
    course_name = canonical_jra_course(target_course)
    dirt_races = [race for race in history if race.get('surface') == 'ダート']
    turf_races = [race for race in history if race.get('surface') == '芝']
    valid_finishes = [
        race for race in history
        if isinstance(race.get('finish_position'), (int, float))
    ]
    dirt_bad_losses = []
    for race in dirt_races:
        finish = race.get('finish_position')
        try:
            margin = float(race.get('margin'))
        except (TypeError, ValueError):
            continue
        if finish is not None and finish > 5 and margin >= 1.0:
            dirt_bad_losses.append(race)

    target_distance = int(target_distance)
    same_distance = [
        race for race in history
        if race.get('distance') == target_distance
    ]
    same_distance_dirt = [
        race for race in same_distance if race.get('surface') == 'ダート'
    ]
    same_course = [
        race for race in history
        if canonical_jra_course(race.get('course')) == course_name
    ]
    same_course_dirt = [
        race for race in same_course if race.get('surface') == 'ダート'
    ]

    recent_three = valid_finishes[:3]
    older_three = valid_finishes[3:6]
    recent_top3_rate = (
        _top3_count(recent_three) / len(recent_three) if recent_three else None
    )
    older_top3_rate = (
        _top3_count(older_three) / len(older_three) if older_three else None
    )

    previous_race = history[0] if history else {}
    previous_previous_race = history[1] if len(history) > 1 else {}
    is_second_dirt_start = int(len(dirt_races) == 1)
    previous_finish = previous_race.get('finish_position')
    previous_margin = previous_race.get('margin')
    previous_last3f_rank = previous_race.get('last_3f_rank')
    previous_last3f_top3 = int(
        isinstance(previous_last3f_rank, (int, float))
        and previous_last3f_rank <= 3
    )
    previous_good_finish = int(
        isinstance(previous_finish, (int, float))
        and previous_finish <= PREVIOUS_GOOD_FINISH_MAX_POSITION
        and isinstance(previous_margin, (int, float))
        and previous_margin <= PREVIOUS_GOOD_FINISH_MAX_MARGIN
    )
    positive_signal_count = (
        is_second_dirt_start
        + previous_last3f_top3
        + previous_good_finish
    )
    previous_positions = _passing_positions(previous_race.get('passing_order'))
    previous_field_size = previous_race.get('field_size')
    target_course_hits = _top3_count(same_course)
    target_distance_hits = _top3_count(same_distance)

    distances = [
        race.get('distance') for race in history
        if isinstance(race.get('distance'), (int, float))
        and race.get('distance') > 0
    ]
    shorter_distance_second_start = int(
        len(same_distance) == 1
        and bool(history)
        and history[0].get('distance') == target_distance
        and bool(distances[1:])
        and all(distance > target_distance for distance in distances[1:])
    )
    course_values = {
        f'{SPECIAL_FEATURE_PREFIX}course_{course}': int(course == course_name)
        for course in JRA_COURSES
    }

    additional_features = {
        f'{SPECIAL_FEATURE_PREFIX}target_distance': target_distance,
        f'{SPECIAL_FEATURE_PREFIX}dirt_start_count': len(dirt_races),
        f'{SPECIAL_FEATURE_PREFIX}dirt_top3_count': _top3_count(dirt_races),
        f'{SPECIAL_FEATURE_PREFIX}dirt_top3_rate': (
            _top3_count(dirt_races) / len(dirt_races) if dirt_races else None
        ),
        f'{SPECIAL_FEATURE_PREFIX}dirt_bad_loss_count': len(dirt_bad_losses),
        f'{SPECIAL_FEATURE_PREFIX}dirt_bad_loss_recent3_count': sum(
            1 for race in dirt_races[:3] if race in dirt_bad_losses
        ),
        f'{SPECIAL_FEATURE_PREFIX}is_first_dirt_start': int(not dirt_races),
        f'{SPECIAL_FEATURE_PREFIX}turf_start_count': len(turf_races),
        f'{SPECIAL_FEATURE_PREFIX}turf_top3_count': _top3_count(turf_races),
        f'{SPECIAL_FEATURE_PREFIX}turf_best_finish': (
            min(
                race['finish_position'] for race in turf_races
                if isinstance(race.get('finish_position'), (int, float))
            )
            if any(
                isinstance(race.get('finish_position'), (int, float))
                for race in turf_races
            )
            else None
        ),
        f'{SPECIAL_FEATURE_PREFIX}career_top3_count': _top3_count(valid_finishes),
        f'{SPECIAL_FEATURE_PREFIX}career_top3_rate': (
            _top3_count(valid_finishes) / len(valid_finishes)
            if valid_finishes else None
        ),
        f'{SPECIAL_FEATURE_PREFIX}target_distance_start_count': len(same_distance),
        f'{SPECIAL_FEATURE_PREFIX}target_distance_top3_count': target_distance_hits,
        f'{SPECIAL_FEATURE_PREFIX}target_distance_top3_rate': (
            target_distance_hits / len(same_distance) if same_distance else None
        ),
        f'{SPECIAL_FEATURE_PREFIX}target_distance_dirt_start_count': len(
            same_distance_dirt
        ),
        f'{SPECIAL_FEATURE_PREFIX}target_distance_dirt_top3_count': _top3_count(
            same_distance_dirt
        ),
        f'{SPECIAL_FEATURE_PREFIX}target_course_start_count': len(same_course),
        f'{SPECIAL_FEATURE_PREFIX}target_course_top3_count': target_course_hits,
        f'{SPECIAL_FEATURE_PREFIX}target_course_top3_rate': (
            target_course_hits / len(same_course) if same_course else None
        ),
        f'{SPECIAL_FEATURE_PREFIX}target_course_dirt_start_count': len(
            same_course_dirt
        ),
        f'{SPECIAL_FEATURE_PREFIX}target_course_dirt_top3_count': _top3_count(
            same_course_dirt
        ),
        f'{SPECIAL_FEATURE_PREFIX}recent3_top3_rate': recent_top3_rate,
        f'{SPECIAL_FEATURE_PREFIX}older3_top3_rate': older_top3_rate,
        f'{SPECIAL_FEATURE_PREFIX}recent_vs_older_top3_rate_delta': (
            recent_top3_rate - older_top3_rate
            if recent_top3_rate is not None and older_top3_rate is not None
            else None
        ),
        f'{SPECIAL_FEATURE_PREFIX}is_second_dirt_start': is_second_dirt_start,
        f'{SPECIAL_FEATURE_PREFIX}previous_last3f_top3': (
            previous_last3f_top3
        ),
        f'{SPECIAL_FEATURE_PREFIX}previous_good_finish': previous_good_finish,
        f'{SPECIAL_FEATURE_PREFIX}positive_signal_count': (
            positive_signal_count
        ),
        f'{SPECIAL_FEATURE_PREFIX}second_dirt_previous_was_dirt': int(
            len(dirt_races) == 1
            and bool(previous_race)
            and previous_race.get('surface') == 'ダート'
        ),
        f'{SPECIAL_FEATURE_PREFIX}previous_surface_is_dirt': int(
            bool(previous_race)
            and previous_race.get('surface') == 'ダート'
        ),
        f'{SPECIAL_FEATURE_PREFIX}previous_finish': previous_finish,
        f'{SPECIAL_FEATURE_PREFIX}previous_margin': previous_margin,
        f'{SPECIAL_FEATURE_PREFIX}previous_last3f_rank': previous_last3f_rank,
        f'{SPECIAL_FEATURE_PREFIX}previous_running_position_first': (
            previous_positions[0] if previous_positions else None
        ),
        f'{SPECIAL_FEATURE_PREFIX}previous_running_position_last': (
            previous_positions[-1] if previous_positions else None
        ),
        f'{SPECIAL_FEATURE_PREFIX}previous_running_position_ratio': (
            previous_positions[-1] / previous_field_size
            if (
                previous_positions
                and isinstance(previous_field_size, (int, float))
                and previous_field_size > 0
            )
            else None
        ),
        f'{SPECIAL_FEATURE_PREFIX}previous_to_previous_interval': features.get(
            'prev2_to_prev_interval'
        ),
        f'{SPECIAL_FEATURE_PREFIX}previous_to_target_interval': features.get(
            'days_since_last_race'
        ),
        f'{SPECIAL_FEATURE_PREFIX}previous_distance_diff': features.get(
            'prev_distance_diff'
        ),
        f'{SPECIAL_FEATURE_PREFIX}previous_course_match': int(
            bool(previous_race)
            and canonical_jra_course(previous_race.get('course')) == course_name
        ),
        f'{SPECIAL_FEATURE_PREFIX}is_second_start_after_distance_drop': (
            shorter_distance_second_start
        ),
        f'{SPECIAL_FEATURE_PREFIX}distance_drop_from_shortest_prior': (
            min(distances[1:]) - target_distance
            if shorter_distance_second_start
            else 0
        ),
        f'{SPECIAL_FEATURE_PREFIX}previous_previous_distance': (
            previous_previous_race.get('distance')
        ),
    }
    features.update(course_values)
    features.update(additional_features)
    return features


def _training_cutoff():
    today = datetime.now().date()
    try:
        ten_years_ago = today.replace(year=today.year - 10)
    except ValueError:
        ten_years_ago = today.replace(year=today.year - 10, day=28)
    return max(TRAINING_START_DATE, ten_years_ago.strftime('%Y/%m/%d'))


def build_dirt_maiden_training_data(db_path='horse_analysis.db'):
    cutoff_date = _training_cutoff()
    course_conditions = ' OR '.join('course LIKE ?' for _ in JRA_COURSES)
    course_parameters = [f'%{course}%' for course in JRA_COURSES]
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        target_rows = connection.execute(
            f'''
            SELECT *
            FROM horse_data_dtl
            WHERE surface = ? AND race_class = ? AND race_date >= ?
              AND course IS NOT NULL AND ({course_conditions})
            ORDER BY race_date, race_id, horse_id
            ''',
            ('ダート', '1', cutoff_date, *course_parameters),
        ).fetchall()
        history_rows = connection.execute(
            'SELECT * FROM horse_data_dtl ORDER BY horse_id, race_date DESC'
        ).fetchall()
    finally:
        connection.close()

    histories = defaultdict(list)
    for row in history_rows:
        histories[str(row['horse_id'])].append(dict(row))

    race_groups = defaultdict(list)
    for row in target_rows:
        race_groups[str(row['race_id'])].append(dict(row))

    features = []
    targets = []
    race_ids = []
    race_dates = []
    complete_race_ids = set()
    excluded_no_history_sample_count = 0
    for race_id, runners in race_groups.items():
        metadata = {
            (
                runner['race_date'],
                canonical_jra_course(runner['course']),
                runner['surface'],
                runner['distance'],
                str(runner['race_class']),
            )
            for runner in runners
        }
        if len(metadata) != 1:
            continue
        race_date, course, surface, distance, race_class = next(iter(metadata))
        if not is_jra_dirt_maiden(course, surface, race_class):
            continue
        parsed_date = parse_date(race_date)
        if parsed_date is None or course is None or distance is None:
            continue

        field_sizes = {
            runner.get('field_size')
            for runner in runners
            if runner.get('field_size') is not None
        }
        if len(field_sizes) == 1 and len(runners) == next(iter(field_sizes)):
            complete_race_ids.add(str(race_id))
        field_size = max(
            (runner.get('field_size') or len(runners) for runner in runners),
            default=len(runners),
        )
        for runner in runners:
            finish = runner.get('finish_position')
            if not isinstance(finish, (int, float)) or finish < 1:
                continue
            horse_id = str(runner['horse_id'])
            history = histories[horse_id]
            row_features = calculate_horse_features(
                horse_id,
                history,
                parsed_date,
                int(distance),
                surface,
                course,
                1,
                target_gate=runner.get('gate'),
                target_field_size=field_size,
            )
            if not row_features:
                continue
            if is_debut_horse(row_features):
                excluded_no_history_sample_count += 1
                continue
            add_dirt_maiden_features(
                row_features,
                history,
                parsed_date,
                int(distance),
                course,
            )
            features.append(row_features)
            targets.append(int(finish <= 3))
            race_ids.append(race_id)
            race_dates.append(parsed_date.strftime('%Y/%m/%d'))

    if not features:
        raise ValueError(
            f'No JRA dirt maiden samples found on or after {cutoff_date}'
        )
    sample_race_ids = set(map(str, race_ids))
    complete_sample_race_count = len(
        complete_race_ids.intersection(sample_race_ids)
    )
    race_count = len(sample_race_ids)
    data = {
        'features': features,
        'targets': targets,
        'race_ids': race_ids,
        'race_dates': race_dates,
        'metadata': {
            'start_date': cutoff_date,
            'end_date': max(race_dates),
            'race_count': race_count,
            'sample_count': len(features),
            'excluded_no_history_sample_count': (
                excluded_no_history_sample_count
            ),
            'complete_race_count': complete_sample_race_count,
            'incomplete_race_count': race_count - complete_sample_race_count,
            'observed_top3_rate': float(np.mean(targets)),
        },
    }
    return data


def _fit_evaluate_model(X, y, race_ids, race_dates, feature_columns):
    split = split_indices_by_race_date(race_ids, race_dates)
    train_indices = split['indices']['train']
    validation_indices = split['indices']['validation']
    test_indices = split['indices']['test']
    if len(np.unique(y[train_indices])) < 2:
        raise ValueError('Training period contains only one target class')

    params = get_model_params(feature_columns, 'other')
    train_set = lgb.Dataset(X[train_indices], label=y[train_indices])
    validation_set = lgb.Dataset(
        X[validation_indices],
        label=y[validation_indices],
        reference=train_set,
    )
    validation_model = lgb.train(
        params,
        train_set,
        num_boost_round=1000,
        valid_sets=[validation_set],
        callbacks=[lgb.early_stopping(stopping_rounds=50, verbose=False)],
    )
    best_iteration = validation_model.best_iteration or 1000
    predictions = validation_model.predict(
        X[test_indices],
        num_iteration=best_iteration,
    )
    test_targets = y[test_indices]
    baseline_rate = float(np.mean(y[train_indices]))
    baseline_predictions = np.full(len(test_targets), baseline_rate)
    evaluation = {
        'race_counts': split['race_counts'],
        'sample_counts': {
            'train': len(train_indices),
            'validation': len(validation_indices),
            'test': len(test_indices),
        },
        'date_ranges': split['date_ranges'],
        'best_iteration': best_iteration,
        'test_top3_rate': float(np.mean(test_targets)),
        'test_mean_predicted_probability': float(np.mean(predictions)),
        'baseline_brier_score': _brier_score(
            test_targets, baseline_predictions
        ),
        'test_brier_score': _brier_score(test_targets, predictions),
        'baseline_log_loss': _log_loss(test_targets, baseline_predictions),
        'test_log_loss': _log_loss(test_targets, predictions),
        'test_roc_auc': _roc_auc(test_targets, predictions),
    }
    return evaluation, best_iteration, params


def train_jra_dirt_maiden_model(
    training_data=None,
    allow_incomplete_races=False,
):
    if training_data is None:
        training_data = build_dirt_maiden_training_data()
    metadata = training_data['metadata']
    if (
        metadata['incomplete_race_count']
        and not allow_incomplete_races
    ):
        raise ValueError(
            'Refusing to train with incomplete races: '
            f"{metadata['complete_race_count']} of {metadata['race_count']} "
            'races contain all field_size runners. Repair the race data or '
            'rerun with --allow-incomplete-races to opt in to a biased model.'
        )
    with open(DIRT_MAIDEN_TRAINING_FILE, 'wb') as training_file:
        pickle.dump(training_data, training_file)

    features = training_data['features']
    targets = np.asarray(training_data['targets'], dtype=int)
    race_ids = training_data['race_ids']
    race_dates = training_data['race_dates']
    if len(np.unique(targets)) < 2:
        raise ValueError('JRA dirt maiden training data contains only one class')

    X, feature_columns = prepare_features_for_model(features)
    evaluation, best_iteration, params = _fit_evaluate_model(
        X,
        targets,
        race_ids,
        race_dates,
        feature_columns,
    )
    standard_features = [
        {
            key: value
            for key, value in row.items()
            if not key.startswith(SPECIAL_FEATURE_PREFIX)
        }
        for row in features
    ]
    standard_X, standard_columns = prepare_features_for_model(
        standard_features
    )
    standard_evaluation, _, _ = _fit_evaluate_model(
        standard_X,
        targets,
        race_ids,
        race_dates,
        standard_columns,
    )
    evaluation['standard_features_baseline'] = standard_evaluation

    model = lgb.train(
        params,
        lgb.Dataset(X, label=targets),
        num_boost_round=best_iteration,
    )
    artifact = {
        'model': model,
        'feature_columns': feature_columns,
        'feature_importance': dict(zip(
            feature_columns,
            map(float, model.feature_importance(importance_type='gain')),
        )),
        'evaluation': evaluation,
        'training_metadata': metadata,
        'data_quality_warning': (
            'Training data contains incomplete race fields; probabilities '
            'may be biased.'
            if metadata['incomplete_race_count']
            else None
        ),
    }
    with open(DIRT_MAIDEN_MODEL_FILE, 'wb') as model_file:
        pickle.dump(artifact, model_file)

    print(
        'JRA dirt maiden model trained: '
        f"samples={len(targets)}, races={metadata['race_count']}, "
        'excluded debut samples='
        f"{metadata.get('excluded_no_history_sample_count', 0)}, "
        f"complete races={metadata['complete_race_count']}, "
        f"test Brier={evaluation['test_brier_score']:.4f} "
        f"(prevalence baseline={evaluation['baseline_brier_score']:.4f}), "
        f"test LogLoss={evaluation['test_log_loss']:.4f} "
        f"(baseline={evaluation['baseline_log_loss']:.4f}), "
        f"saved={DIRT_MAIDEN_MODEL_FILE}"
    )
    return artifact


def load_jra_dirt_maiden_training_data():
    if not os.path.isfile(DIRT_MAIDEN_TRAINING_FILE):
        raise FileNotFoundError(
            f'{DIRT_MAIDEN_TRAINING_FILE} is missing; train the JRA dirt maiden model first'
        )
    with open(DIRT_MAIDEN_TRAINING_FILE, 'rb') as training_file:
        data = pickle.load(training_file)
    if not (
        len(data['features'])
        == len(data['targets'])
        == len(data['race_ids'])
        == len(data['race_dates'])
    ):
        raise ValueError('JRA dirt maiden training data has inconsistent lengths')
    return data


def predict_past_jra_dirt_maiden(
    race_id,
    target_date,
    course,
    distance,
    target_features,
):
    training_data = load_jra_dirt_maiden_training_data()
    earlier_indices = [
        index for index, race_date in enumerate(training_data['race_dates'])
        if race_date < target_date
    ]
    if not earlier_indices:
        raise ValueError(
            f'No JRA dirt maiden training samples precede {target_date}'
        )
    earlier_features = [
        training_data['features'][index] for index in earlier_indices
    ]
    earlier_targets = np.asarray(
        [training_data['targets'][index] for index in earlier_indices],
        dtype=int,
    )
    earlier_race_ids = [
        training_data['race_ids'][index] for index in earlier_indices
    ]
    earlier_dates = [
        training_data['race_dates'][index] for index in earlier_indices
    ]
    split = split_indices_by_race_date(
        earlier_race_ids,
        earlier_dates,
        minimum_races=20,
    )
    earlier_features.extend(target_features)
    X, feature_columns = prepare_features_for_model(earlier_features)
    target_start = len(earlier_indices)
    X_past = X[:target_start]
    X_target = X[target_start:]
    params = get_model_params(feature_columns, 'other')
    train_indices = split['indices']['train']
    validation_indices = split['indices']['validation']
    if len(np.unique(earlier_targets[train_indices])) < 2:
        raise ValueError(
            f'Race {race_id} has only one class in the past training partition'
        )

    train_set = lgb.Dataset(
        X_past[train_indices],
        label=earlier_targets[train_indices],
    )
    validation_set = lgb.Dataset(
        X_past[validation_indices],
        label=earlier_targets[validation_indices],
        reference=train_set,
    )
    validation_model = lgb.train(
        params,
        train_set,
        num_boost_round=1000,
        valid_sets=[validation_set],
        callbacks=[lgb.early_stopping(stopping_rounds=50, verbose=False)],
    )
    best_iteration = validation_model.best_iteration or 1000
    model = lgb.train(
        params,
        lgb.Dataset(X_past, label=earlier_targets),
        num_boost_round=best_iteration,
    )
    probabilities = model.predict(X_target, num_iteration=best_iteration)
    training_through_date = max(earlier_dates)
    return [
        {
            'race_id': str(race_id),
            'race_date': target_date,
            'horse_id': str(features['horse_id']),
            'probability': None if is_debut_horse(features) else float(probability),
            'model_probability_before_promotion_adjustment': (
                None
                if is_debut_horse(features)
                else float(probability)
            ),
            'excluded': is_debut_horse(features),
            'error': (
                '初出走で過去走がないため、予測対象外です。'
                if is_debut_horse(features)
                else None
            ),
            'actual_top3': None,
            'actual_finish': None,
            'training_through_date': training_through_date,
            'training_file': DIRT_MAIDEN_TRAINING_FILE,
            'model_group': DIRT_MAIDEN_MODEL_GROUP,
            'course': canonical_jra_course(course) or '',
            'surface': 'ダート',
            'distance': distance,
            'features': features,
        }
        for features, probability in zip(target_features, probabilities)
    ]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Train the JRA dirt maiden top-3 prediction model.'
    )
    parser.add_argument(
        '--allow-incomplete-races',
        action='store_true',
        help='Train despite missing runners in the source race data.',
    )
    train_jra_dirt_maiden_model(
        allow_incomplete_races=parser.parse_args().allow_incomplete_races
    )
