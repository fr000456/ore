import os
import pickle
import sqlite3
from collections import Counter, defaultdict

import lightgbm as lgb
import numpy as np

from feature_engineering import calculate_horse_features, parse_date
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
UPPER_RACE_CLASSES = frozenset((5, 6, 7, 8, 9))
TRAINING_START_DATE = '2016/11/01'
TRAINING_FILE = 'training_data_jra_turf_2000_upper.pkl'
MODEL_FILE = 'model_jra_turf_2000_upper.pkl'
MODEL_GROUP = 'jra_turf_2000_upper'
TRAINING_FILE_1200 = 'training_data_jra_turf_1200_upper.pkl'
MODEL_FILE_1200 = 'model_jra_turf_1200_upper.pkl'
MODEL_GROUP_1200 = 'jra_turf_1200_upper'


def canonical_jra_course(course):
    if not isinstance(course, str):
        return None
    return next((name for name in JRA_COURSES if name in course), None)


def is_jra_turf_2000_upper(course, surface, distance, race_class):
    return _is_jra_turf_upper(course, surface, distance, race_class, 2000)


def is_jra_turf_1200_upper(course, surface, distance, race_class):
    return _is_jra_turf_upper(course, surface, distance, race_class, 1200)


def _is_jra_turf_upper(course, surface, distance, race_class, target_distance):
    try:
        normalized_distance = int(distance)
        normalized_class = int(race_class)
    except (TypeError, ValueError):
        return False
    return (
        canonical_jra_course(course) is not None
        and surface == '芝'
        and normalized_distance == target_distance
        and normalized_class in UPPER_RACE_CLASSES
    )


def add_jra_course_features(features, course):
    course_name = canonical_jra_course(course)
    for candidate in JRA_COURSES:
        features[f'target_jra_course_{candidate}'] = int(
            candidate == course_name
        )
    return features


def build_jra_turf_2000_upper_training_data(
    db_path='horse_analysis.db',
):
    return _build_jra_turf_upper_training_data(2000, db_path)


def build_jra_turf_1200_upper_training_data(
    db_path='horse_analysis.db',
):
    return _build_jra_turf_upper_training_data(1200, db_path)


def _build_jra_turf_upper_training_data(distance, db_path):
    course_conditions = ' OR '.join('course LIKE ?' for _ in JRA_COURSES)
    course_parameters = [f'%{course}%' for course in JRA_COURSES]
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        target_rows = connection.execute(
            f'''
            SELECT *
            FROM horse_data_dtl
            WHERE surface = ? AND distance = ? AND race_date >= ?
              AND race_class IN ('5', '6', '7', '8', '9')
              AND course IS NOT NULL AND ({course_conditions})
            ORDER BY race_date, race_id, horse_id
            ''',
            (
                '芝',
                distance,
                TRAINING_START_DATE,
                *course_parameters,
            ),
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
    incomplete_race_ids = set()
    class_counts = Counter()
    for race_id, runners in race_groups.items():
        if any(runner['race_class'] is None for runner in runners):
            raise ValueError(f'Race {race_id} has a missing race class')
        race_metadata = {
            (
                runner['race_date'],
                canonical_jra_course(runner['course']),
                runner['surface'],
                int(runner['distance']),
                int(runner['race_class']),
            )
            for runner in runners
        }
        if len(race_metadata) != 1:
            raise ValueError(
                f'Race {race_id} has inconsistent or missing race metadata'
            )
        raw_date, course, surface, distance, race_class = next(
            iter(race_metadata)
        )
        if not _is_jra_turf_upper(
            course,
            surface,
            distance,
            race_class,
            int(distance),
        ):
            continue
        parsed_date = parse_date(raw_date)
        if parsed_date is None:
            continue

        field_sizes = {
            runner['field_size']
            for runner in runners
            if runner['field_size'] is not None
        }
        if field_sizes and len(runners) < max(field_sizes):
            incomplete_race_ids.add(race_id)
        field_size = max(field_sizes, default=len(runners))

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
                distance,
                surface,
                course,
                race_class,
                target_gate=runner.get('gate'),
                target_field_size=field_size,
            )
            if not row_features:
                continue
            add_jra_course_features(row_features, course)
            features.append(row_features)
            targets.append(int(finish <= 3))
            race_ids.append(race_id)
            race_dates.append(parsed_date.strftime('%Y/%m/%d'))
            class_counts[str(race_class)] += 1

    if not features:
        raise ValueError(
            f'No JRA turf {distance}m upper-class samples found since '
            f'{TRAINING_START_DATE}'
        )
    return {
        'features': features,
        'targets': targets,
        'race_ids': race_ids,
        'race_dates': race_dates,
        'metadata': {
            'start_date': min(race_dates),
            'end_date': max(race_dates),
            'race_count': len(set(race_ids)),
            'sample_count': len(features),
            'class_sample_counts': dict(class_counts),
            'incomplete_race_count': len(incomplete_race_ids),
            'observed_top3_rate': float(np.mean(targets)),
        },
    }


def _fit_evaluate_model(X, targets, race_ids, race_dates, feature_columns):
    split = split_indices_by_race_date(race_ids, race_dates)
    train_indices = split['indices']['train']
    validation_indices = split['indices']['validation']
    test_indices = split['indices']['test']
    if len(np.unique(targets[train_indices])) < 2:
        raise ValueError('Training period contains only one target class')

    params = get_model_params(feature_columns, 'other')
    train_set = lgb.Dataset(X[train_indices], label=targets[train_indices])
    validation_set = lgb.Dataset(
        X[validation_indices],
        label=targets[validation_indices],
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
    probabilities = validation_model.predict(
        X[test_indices],
        num_iteration=best_iteration,
    )
    test_targets = targets[test_indices]
    baseline_rate = float(np.mean(targets[train_indices]))
    baseline_predictions = np.full(len(test_targets), baseline_rate)
    return {
        'race_counts': split['race_counts'],
        'sample_counts': {
            'train': len(train_indices),
            'validation': len(validation_indices),
            'test': len(test_indices),
        },
        'date_ranges': split['date_ranges'],
        'best_iteration': best_iteration,
        'test_top3_rate': float(np.mean(test_targets)),
        'test_mean_predicted_probability': float(np.mean(probabilities)),
        'baseline_brier_score': float(np.mean(
            (test_targets - baseline_predictions) ** 2
        )),
        'test_brier_score': float(np.mean(
            (test_targets - probabilities) ** 2
        )),
        'test_roc_auc': _roc_auc(test_targets, probabilities),
    }, best_iteration, params


def _roc_auc(targets, predictions):
    positives = int(np.sum(targets == 1))
    negatives = len(targets) - positives
    if not positives or not negatives:
        return None
    order = np.argsort(predictions, kind='mergesort')
    sorted_predictions = predictions[order]
    ranks = np.empty(len(predictions), dtype=float)
    start = 0
    while start < len(predictions):
        end = start + 1
        while (
            end < len(predictions)
            and sorted_predictions[end] == sorted_predictions[start]
        ):
            end += 1
        ranks[order[start:end]] = (start + end - 1) / 2 + 1
        start = end
    positive_rank_sum = float(np.sum(ranks[targets == 1]))
    return (
        positive_rank_sum - positives * (positives + 1) / 2
    ) / (positives * negatives)


def train_jra_turf_2000_upper_model(training_data=None):
    if training_data is None:
        training_data = build_jra_turf_2000_upper_training_data()
    return _train_jra_turf_upper_model(
        training_data,
        2000,
        TRAINING_FILE,
        MODEL_FILE,
    )


def train_jra_turf_1200_upper_model(training_data=None):
    if training_data is None:
        training_data = build_jra_turf_1200_upper_training_data()
    return _train_jra_turf_upper_model(
        training_data,
        1200,
        TRAINING_FILE_1200,
        MODEL_FILE_1200,
    )


def _train_jra_turf_upper_model(
    training_data,
    distance,
    training_file_path,
    model_file_path,
):
    features = training_data['features']
    targets = np.asarray(training_data['targets'], dtype=int)
    race_ids = training_data['race_ids']
    race_dates = training_data['race_dates']
    if len(np.unique(targets)) < 2:
        raise ValueError('Training data contains only one target class')

    X, feature_columns = prepare_features_for_model(features)
    evaluation, best_iteration, params = _fit_evaluate_model(
        X,
        targets,
        race_ids,
        race_dates,
        feature_columns,
    )
    model = lgb.train(
        params,
        lgb.Dataset(X, label=targets),
        num_boost_round=best_iteration,
    )
    metadata = training_data['metadata']
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
            'Training data includes races with fewer registered runners '
            'than field_size; probabilities may be biased.'
            if metadata['incomplete_race_count']
            else None
        ),
    }
    with open(training_file_path, 'wb') as training_file:
        pickle.dump(training_data, training_file)
    with open(model_file_path, 'wb') as model_file:
        pickle.dump(artifact, model_file)

    print(
        f'JRA turf {distance}m upper-class model trained: '
        f"samples={metadata['sample_count']}, "
        f"races={metadata['race_count']}, "
        f"classes={metadata['class_sample_counts']}, "
        f"test Brier={evaluation['test_brier_score']:.4f} "
        f"(baseline={evaluation['baseline_brier_score']:.4f}), "
        f"test AUC={evaluation['test_roc_auc']}, "
        f"saved={model_file_path}"
    )
    return artifact


def load_jra_turf_2000_upper_training_data():
    return _load_jra_turf_upper_training_data(TRAINING_FILE)


def load_jra_turf_1200_upper_training_data():
    return _load_jra_turf_upper_training_data(TRAINING_FILE_1200)


def _load_jra_turf_upper_training_data(training_file_path):
    if not os.path.isfile(training_file_path):
        raise FileNotFoundError(
            f'{training_file_path} is missing; train the JRA turf upper-class model first'
        )
    with open(training_file_path, 'rb') as training_file:
        return pickle.load(training_file)


def predict_past_jra_turf_2000_upper(
    race_id,
    target_date,
    target_course,
    target_features,
):
    return _predict_past_jra_turf_upper(
        race_id,
        target_date,
        target_course,
        target_features,
        2000,
        load_jra_turf_2000_upper_training_data,
        MODEL_GROUP,
        TRAINING_FILE,
    )


def predict_past_jra_turf_1200_upper(
    race_id,
    target_date,
    target_course,
    target_features,
):
    return _predict_past_jra_turf_upper(
        race_id,
        target_date,
        target_course,
        target_features,
        1200,
        load_jra_turf_1200_upper_training_data,
        MODEL_GROUP_1200,
        TRAINING_FILE_1200,
    )


def _predict_past_jra_turf_upper(
    race_id,
    target_date,
    target_course,
    target_features,
    distance,
    load_training_data,
    model_group,
    training_file_path,
):
    training_data = load_training_data()
    earlier_indices = [
        index for index, race_date in enumerate(training_data['race_dates'])
        if race_date < target_date
    ]
    if not earlier_indices:
        raise ValueError(
            f'No JRA turf {distance}m upper-class samples precede {target_date}'
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
    target_features = [
        add_jra_course_features(row, target_course)
        for row in target_features
    ]
    combined_features = earlier_features + target_features
    X, feature_columns = prepare_features_for_model(combined_features)
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
            'probability': float(probability),
            'model_probability_before_promotion_adjustment': float(probability),
            'actual_top3': None,
            'actual_finish': None,
            'training_through_date': training_through_date,
            'training_file': training_file_path,
            'model_group': model_group,
            'course': canonical_jra_course(target_course) or '',
            'surface': '芝',
            'distance': distance,
            'features': features,
        }
        for features, probability in zip(target_features, probabilities)
    ]


if __name__ == '__main__':
    train_jra_turf_2000_upper_model()
