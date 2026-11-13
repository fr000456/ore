import argparse
import glob
import os
import pickle
import re
import sqlite3
from datetime import datetime

import lightgbm as lgb
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit

from feature_engineering import (
    apply_promotion_second_boost,
    apply_recent_performance_balance,
    apply_unwon_maiden_class_challenge_penalty,
    calculate_horse_features,
    get_horse_race_history,
    get_promotion_second_context_values,
    parse_date,
)
from train_models_by_condition import (
    get_model_params,
    prepare_features_for_model,
    split_indices_by_race_date,
)
from dirt_maiden_model import (
    add_dirt_maiden_features,
    is_jra_dirt_maiden,
    predict_past_jra_dirt_maiden,
)
from jra_turf_2000_upper_model import (
    is_jra_turf_2000_upper,
    predict_past_jra_turf_2000_upper,
)
from jra_turf_1200_upper_model import (
    is_jra_turf_1200_upper,
    predict_past_jra_turf_1200_upper,
)


TRAINING_FILE_PATTERN = re.compile(
    r'training_data_(.+)_(芝|ダート)_(\d+)m_(condition|other)\.pkl'
)

DEBUT_BACKTEST_ERROR = '初出走で過去データがないため、検証不可です。'


def exclude_debut_predictions(predictions):
    for prediction in predictions:
        features = prediction.get('features') or {}
        if features.get('total_races') == 0:
            prediction['probability'] = None
            prediction['excluded'] = True
            prediction['error'] = DEBUT_BACKTEST_ERROR
            if 'model_probability_before_promotion_adjustment' in prediction:
                prediction['model_probability_before_promotion_adjustment'] = None
    return predictions


def format_backtest_prediction(prediction):
    probability = prediction.get('probability')
    if probability is None:
        reason = prediction.get('error') or 'probability unavailable'
        return f"{prediction['horse_id']}: excluded ({reason})"
    return (
        f"{prediction['horse_id']}: {probability:.1%} "
        f"(finish={prediction.get('actual_finish')})"
    )


def apply_recent_performance_balance_to_predictions(predictions):
    for prediction in predictions:
        probability = prediction.get('probability')
        if probability is None or prediction.get('excluded'):
            continue

        prediction['model_probability_before_recent_performance_balance'] = (
            float(probability)
        )
        prediction['probability'] = apply_recent_performance_balance(
            probability,
            prediction.get('features') or {},
            threshold_recent=6,
            threshold_performance=0.3,
            penalty_factor=0.3,
            rescue_factor=1.35,
            bonus_factor=1.0,
        )
        prediction['probability'] = (
            apply_unwon_maiden_class_challenge_penalty(
                prediction['probability'],
                prediction.get('features') or {},
            )
        )
    return predictions


def load_training_data(filename):
    with open(filename, 'rb') as training_file:
        data = pickle.load(training_file)
    if not (
        len(data['features'])
        == len(data['targets'])
        == len(data['race_ids'])
        == len(data['race_dates'])
    ):
        raise ValueError(f'{filename} has inconsistent training data lengths')
    return data


def get_target_race(training_files, target_race_id):
    matches = []
    for filename in training_files:
        match = TRAINING_FILE_PATTERN.fullmatch(os.path.basename(filename))
        if not match:
            continue
        data = load_training_data(filename)
        target_indices = [
            index
            for index, race_id in enumerate(data['race_ids'])
            if str(race_id) == str(target_race_id)
        ]
        if target_indices:
            matches.append((filename, match.groups(), data, target_indices))

    if not matches:
        raise ValueError(
            f'Race {target_race_id} was not found in the condition training data'
        )
    if len(matches) != 1:
        raise ValueError(
            f'Race {target_race_id} matched {len(matches)} training samples files'
        )

    filename, model_info, target_data, target_indices = matches[0]
    first_index = target_indices[0]
    target_date = target_data['race_dates'][first_index]
    if any(target_data['race_dates'][index] != target_date for index in target_indices):
        raise ValueError(f'Race {target_race_id} has inconsistent dates')
    return filename, model_info, target_data, target_indices, target_date


def train_past_only_context_model(training_files, target_date):
    context_features = []
    context_targets = []
    for filename in training_files:
        match = TRAINING_FILE_PATTERN.fullmatch(os.path.basename(filename))
        if not match or match.group(4) != 'condition':
            continue
        data = load_training_data(filename)
        for features, target, race_date in zip(
            data['features'],
            data['targets'],
            data['race_dates'],
        ):
            if race_date < target_date and features.get('is_promotion_2nd') == 1:
                context_features.append(features)
                context_targets.append(int(target))

    if len(set(context_targets)) < 2:
        return None

    values = np.asarray([
        [
            np.nan if value is None else float(value)
            for value in get_promotion_second_context_values(features)
        ]
        for features in context_features
    ], dtype=float)
    target_values = np.asarray(context_targets, dtype=float)
    medians = np.nanmedian(values, axis=0)
    valid_columns = ~np.isnan(medians)
    values = values[:, valid_columns]
    medians = medians[valid_columns]
    missing_columns = np.any(np.isnan(values), axis=0)
    imputed_values = np.where(np.isnan(values), medians, values)
    if np.any(missing_columns):
        imputed_values = np.column_stack((
            imputed_values,
            np.isnan(values[:, missing_columns]).astype(float),
        ))

    means = np.mean(imputed_values, axis=0)
    scales = np.std(imputed_values, axis=0)
    scales[scales == 0] = 1
    scaled_values = (imputed_values - means) / scales

    def objective(parameters):
        coefficients = parameters[:-1]
        intercept = parameters[-1]
        logits = scaled_values @ coefficients + intercept
        residuals = expit(logits) - target_values
        loss = (
            np.sum(np.logaddexp(0, logits) - target_values * logits)
            + 0.5 / 0.01 * np.dot(coefficients, coefficients)
        )
        gradient = np.append(
            scaled_values.T @ residuals + coefficients / 0.01,
            np.sum(residuals),
        )
        return loss, gradient

    result = minimize(
        objective,
        np.zeros(scaled_values.shape[1] + 1),
        method='L-BFGS-B',
        jac=True,
        options={'maxiter': 2000},
    )
    if not result.success:
        raise RuntimeError(
            f'Promotion context model did not converge: {result.message}'
        )

    model = {
        'valid_columns': valid_columns,
        'medians': medians,
        'missing_columns': missing_columns,
        'means': means,
        'scales': scales,
        'coefficients': result.x[:-1],
        'intercept': result.x[-1],
    }
    return model, float(np.mean(target_values))


def predict_past_only_context_probability(model, features):
    values = np.asarray([
        np.nan if value is None else float(value)
        for value in get_promotion_second_context_values(features)
    ], dtype=float)[model['valid_columns']]
    missing = np.isnan(values)
    imputed_values = np.where(missing, model['medians'], values)
    if np.any(model['missing_columns']):
        imputed_values = np.append(
            imputed_values,
            missing[model['missing_columns']].astype(float),
        )
    scaled_values = (imputed_values - model['means']) / model['scales']
    return float(expit(scaled_values @ model['coefficients'] + model['intercept']))


def get_actual_finishes(race_id, horse_ids):
    connection = sqlite3.connect('horse_analysis.db')
    try:
        rows = connection.execute(
            '''
            SELECT horse_id, finish_position
            FROM horse_data_dtl
            WHERE race_id = ?
            ''',
            (race_id,),
        ).fetchall()
    finally:
        connection.close()
    return {str(horse_id): finish for horse_id, finish in rows if horse_id in horse_ids}


def get_target_race_features(target_race):
    if not isinstance(target_race, dict):
        raise ValueError('target_race must be an object')
    required = ('race_date', 'course', 'surface', 'distance', 'race_class', 'horses')
    if any(key not in target_race for key in required):
        raise ValueError('Historical race metadata or horse list is incomplete')

    parsed_date = parse_date(target_race['race_date'])
    if parsed_date is None:
        raise ValueError('race_date must be a valid YYYY/MM/DD date')
    target_date = parsed_date.strftime('%Y/%m/%d')
    try:
        distance = int(target_race['distance'])
        race_class = int(target_race['race_class'])
    except (TypeError, ValueError):
        raise ValueError('distance and race_class must be integers') from None
    course = target_race['course']
    surface = target_race['surface']
    if not isinstance(course, str) or not course or surface not in ('芝', 'ダート'):
        raise ValueError('course or surface is invalid')
    if distance <= 0 or not 0 <= race_class <= 9:
        raise ValueError('distance or race_class is invalid')
    horses = target_race['horses']
    if not isinstance(horses, list) or not horses or len(horses) > 30:
        raise ValueError('horses must contain between 1 and 30 entries')

    target_features = []
    seen_horse_ids = set()
    for horse in horses:
        if not isinstance(horse, dict):
            raise ValueError('each horse entry must be an object')
        horse_id = horse.get('horse_id')
        if not isinstance(horse_id, str) or not horse_id:
            raise ValueError('each horse entry must have a horse_id')
        if horse_id in seen_horse_ids:
            raise ValueError(f'duplicate horse_id in target race: {horse_id}')
        seen_horse_ids.add(horse_id)
        history = get_horse_race_history(horse_id)
        features = calculate_horse_features(
            horse_id,
            history,
            parsed_date,
            distance,
            surface,
            course,
            race_class,
            target_gate=horse.get('gate'),
            target_field_size=target_race.get('field_size') or len(horses),
        )
        target_features.append(features)

    model_group = 'condition' if 2 <= race_class <= 4 else 'other'
    course_key = re.sub(r'[0-9]', '', course)
    filename = (
        f'training_data_{course_key}_{surface}_{distance}m_{model_group}.pkl'
    )
    if not os.path.isfile(filename):
        raise ValueError(f'対象条件の学習データがありません: {filename}')
    return (
        filename,
        (course_key, surface, str(distance), model_group),
        load_training_data(filename),
        target_features,
        target_date,
    )


def get_target_race_from_database(race_id):
    connection = sqlite3.connect('horse_analysis.db')
    try:
        rows = connection.execute(
            '''
            SELECT horse_id, race_date, course, surface, distance, race_class,
                   gate, field_size
            FROM horse_data_dtl
            WHERE race_id = ?
            ORDER BY horse_number
            ''',
            (race_id,),
        ).fetchall()
    finally:
        connection.close()
    if not rows:
        return None

    race_date, raw_course, surface, distance, race_class = rows[0][1:6]
    course = re.sub(r'[0-9]', '', raw_course)
    normalized_metadata = (race_date, course, surface, distance, str(race_class))
    if any(
        (
            row[1],
            re.sub(r'[0-9]', '', row[2]),
            row[3],
            row[4],
            str(row[5]),
        ) != normalized_metadata
        for row in rows
    ):
        raise ValueError(f'Race {race_id} has inconsistent race metadata in the database')
    return {
        'race_date': race_date,
        'course': course,
        'surface': surface,
        'distance': distance,
        'race_class': race_class,
        'field_size': max((row[7] or 0 for row in rows), default=len(rows)),
        'horses': [
            {'horse_id': str(row[0]), 'gate': row[6]}
            for row in rows
        ],
    }


def backtest_jra_dirt_maiden_race(race_id, target_race):
    parsed_date = parse_date(target_race.get('race_date'))
    if parsed_date is None:
        raise ValueError('race_date must be a valid YYYY/MM/DD date')
    target_date = parsed_date.strftime('%Y/%m/%d')
    try:
        distance = int(target_race['distance'])
    except (KeyError, TypeError, ValueError):
        raise ValueError('distance must be an integer') from None
    course = target_race.get('course')
    if not isinstance(course, str) or not course:
        raise ValueError('course is invalid')
    horses = target_race.get('horses')
    if not isinstance(horses, list) or not horses:
        raise ValueError('horses must be a non-empty list')

    field_size = target_race.get('field_size') or len(horses)
    target_features = []
    seen_horse_ids = set()
    for horse in horses:
        if not isinstance(horse, dict):
            raise ValueError('each horse entry must be an object')
        horse_id = horse.get('horse_id')
        if not isinstance(horse_id, str) or not horse_id:
            raise ValueError('each horse entry must have a horse_id')
        if horse_id in seen_horse_ids:
            raise ValueError(f'duplicate horse_id in target race: {horse_id}')
        seen_horse_ids.add(horse_id)
        history = get_horse_race_history(horse_id)
        features = calculate_horse_features(
            horse_id,
            history,
            parsed_date,
            distance,
            'ダート',
            course,
            1,
            target_gate=horse.get('gate'),
            target_field_size=field_size,
        )
        add_dirt_maiden_features(
            features,
            history,
            parsed_date,
            distance,
            course,
        )
        target_features.append(features)

    predictions = predict_past_jra_dirt_maiden(
        race_id,
        target_date,
        course,
        distance,
        target_features,
    )
    actual_finishes = get_actual_finishes(
        race_id,
        {str(features['horse_id']) for features in target_features},
    )
    for prediction in predictions:
        actual_finish = actual_finishes.get(prediction['horse_id'])
        prediction['actual_finish'] = actual_finish
        prediction['actual_top3'] = (
            int(actual_finish <= 3) if actual_finish is not None else None
        )
    exclude_debut_predictions(predictions)
    apply_recent_performance_balance_to_predictions(predictions)
    predictions.sort(
        key=lambda row: (
            not row.get('excluded', False),
            row.get('probability') or 0,
        ),
        reverse=True,
    )

    print(
        f'Backtest JRA dirt maiden race {race_id} ({target_date}): '
        f'{len(predictions)} horses; trained only on earlier races.'
    )
    for row in predictions:
        print(format_backtest_prediction(row))
    return predictions


def _backtest_jra_turf_upper_race(race_id, target_race, target_distance):
    parsed_date = parse_date(target_race.get('race_date'))
    if parsed_date is None:
        raise ValueError('race_date must be a valid YYYY/MM/DD date')
    target_date = parsed_date.strftime('%Y/%m/%d')
    try:
        distance = int(target_race['distance'])
        race_class = int(target_race['race_class'])
    except (KeyError, TypeError, ValueError):
        raise ValueError('distance and race_class must be integers') from None
    course = target_race.get('course')
    is_target_model = (
        is_jra_turf_2000_upper
        if target_distance == 2000
        else is_jra_turf_1200_upper
    )
    if not is_target_model(
        course,
        target_race.get('surface'),
        distance,
        race_class,
    ):
        raise ValueError(
            f'target race is not a JRA turf {target_distance}m upper-class race'
        )
    horses = target_race.get('horses')
    if not isinstance(horses, list) or not horses:
        raise ValueError('horses must be a non-empty list')

    field_size = target_race.get('field_size') or len(horses)
    target_features = []
    seen_horse_ids = set()
    for horse in horses:
        if not isinstance(horse, dict):
            raise ValueError('each horse entry must be an object')
        horse_id = horse.get('horse_id')
        if not isinstance(horse_id, str) or not horse_id:
            raise ValueError('each horse entry must have a horse_id')
        if horse_id in seen_horse_ids:
            raise ValueError(f'duplicate horse_id in target race: {horse_id}')
        seen_horse_ids.add(horse_id)
        history = get_horse_race_history(horse_id)
        features = calculate_horse_features(
            horse_id,
            history,
            parsed_date,
            distance,
            '芝',
            course,
            race_class,
            target_gate=horse.get('gate'),
            target_field_size=field_size,
        )
        target_features.append(features)

    predict_past = (
        predict_past_jra_turf_2000_upper
        if target_distance == 2000
        else predict_past_jra_turf_1200_upper
    )
    predictions = predict_past(
        race_id,
        target_date,
        course,
        target_features,
    )
    actual_finishes = get_actual_finishes(
        race_id,
        {str(features['horse_id']) for features in target_features},
    )
    for prediction in predictions:
        actual_finish = actual_finishes.get(prediction['horse_id'])
        prediction['actual_finish'] = actual_finish
        prediction['actual_top3'] = (
            int(actual_finish <= 3) if actual_finish is not None else None
        )
    exclude_debut_predictions(predictions)
    apply_recent_performance_balance_to_predictions(predictions)
    predictions.sort(
        key=lambda row: (
            not row.get('excluded', False),
            row.get('probability') or 0,
        ),
        reverse=True,
    )

    print(
        f'Backtest JRA turf {target_distance}m upper-class race {race_id} '
        f'({target_date}): {len(predictions)} horses; '
        'trained only on earlier races.'
    )
    for row in predictions:
        print(format_backtest_prediction(row))
    return predictions


def backtest_jra_turf_2000_upper_race(race_id, target_race):
    return _backtest_jra_turf_upper_race(race_id, target_race, 2000)


def backtest_jra_turf_1200_upper_race(race_id, target_race):
    return _backtest_jra_turf_upper_race(race_id, target_race, 1200)


def backtest_race(race_id, target_race=None):
    training_files = sorted(glob.glob('training_data_*_condition.pkl'))
    training_files += sorted(glob.glob('training_data_*_other.pkl'))
    if target_race is None:
        target_race = get_target_race_from_database(race_id)

    if target_race is not None and is_jra_dirt_maiden(
        target_race.get('course'),
        target_race.get('surface'),
        target_race.get('race_class'),
    ):
        return backtest_jra_dirt_maiden_race(race_id, target_race)
    if target_race is not None and is_jra_turf_2000_upper(
        target_race.get('course'),
        target_race.get('surface'),
        target_race.get('distance'),
        target_race.get('race_class'),
    ):
        return backtest_jra_turf_2000_upper_race(race_id, target_race)
    if target_race is not None and is_jra_turf_1200_upper(
        target_race.get('course'),
        target_race.get('surface'),
        target_race.get('distance'),
        target_race.get('race_class'),
    ):
        return backtest_jra_turf_1200_upper_race(race_id, target_race)

    if target_race is not None:
        (
            filename,
            model_info,
            target_data,
            target_features,
            target_date,
        ) = get_target_race_features(target_race)
        course, surface, distance, model_group = model_info
    else:
        filename, model_info, target_data, target_indices, target_date = get_target_race(
            training_files,
            race_id,
        )
        datetime.strptime(target_date, '%Y/%m/%d')
        course, surface, distance, model_group = model_info
        target_features = [
            target_data['features'][index]
            for index in target_indices
        ]

    earlier_indices = [
        index
        for index, race_date in enumerate(target_data['race_dates'])
        if race_date < target_date
    ]
    if not earlier_indices:
        raise ValueError(f'No earlier training samples are available for {race_id}')

    earlier_race_ids = [target_data['race_ids'][index] for index in earlier_indices]
    earlier_dates = [target_data['race_dates'][index] for index in earlier_indices]
    split = split_indices_by_race_date(
        earlier_race_ids,
        earlier_dates,
        minimum_races=7,
    )

    earlier_features = [target_data['features'][index] for index in earlier_indices]
    all_features = earlier_features + target_features
    X, feature_columns = prepare_features_for_model(all_features)
    y = np.asarray(
        [target_data['targets'][index] for index in earlier_indices],
        dtype=int,
    )
    target_start = len(earlier_indices)
    X_past = X[:target_start]
    X_target = X[target_start:]

    train_indices = split['indices']['train']
    validation_indices = split['indices']['validation']
    if len(np.unique(y[train_indices])) < 2:
        raise ValueError(
            f'Race {race_id} has only one class in the past training partition'
        )

    params = get_model_params(feature_columns, model_group)
    train_data = lgb.Dataset(X_past[train_indices], label=y[train_indices])
    validation_data = lgb.Dataset(
        X_past[validation_indices],
        label=y[validation_indices],
        reference=train_data,
    )
    validation_model = lgb.train(
        params,
        train_data,
        num_boost_round=1000,
        valid_sets=[validation_data],
        callbacks=[lgb.early_stopping(stopping_rounds=50, verbose=False)],
    )
    best_iteration = validation_model.best_iteration or 1000

    final_model = lgb.train(
        params,
        lgb.Dataset(X_past, label=y),
        num_boost_round=best_iteration,
    )
    raw_probabilities = final_model.predict(
        X_target,
        num_iteration=best_iteration,
    )

    context_model = None
    if model_group == 'condition':
        context_model = train_past_only_context_model(training_files, target_date)

    context_probabilities = {}
    if context_model is not None:
        model, _ = context_model
        for features in target_features:
            if features.get('is_promotion_2nd') == 1:
                context_probabilities[features['horse_id']] = (
                    predict_past_only_context_probability(model, features)
                )

    horse_ids = {str(features['horse_id']) for features in target_features}
    actual_finishes = get_actual_finishes(int(race_id), horse_ids)
    output_rows = []
    for features, raw_probability in zip(target_features, raw_probabilities):
        actual_finish = actual_finishes.get(str(features['horse_id']))
        actual_top3 = (
            int(actual_finish <= 3)
            if actual_finish is not None
            else None
        )
        context_probability = context_probabilities.get(features['horse_id'])
        final_probability = apply_promotion_second_boost(
            raw_probability,
            features.get('is_promotion_2nd'),
            context_probability=context_probability,
            context_base_rate=context_model[1] if context_model else None,
        )
        output_rows.append({
            'race_date': target_date,
            'race_id': str(race_id),
            'horse_id': str(features['horse_id']),
            'course': course,
            'surface': surface,
            'distance': distance,
            'model_group': model_group,
            'actual_finish': actual_finish,
            'actual_top3': actual_top3,
            'probability': float(final_probability),
            'model_probability_before_promotion_adjustment': float(raw_probability),
            'promotion_context_adjustment_available': int(context_model is not None),
            'features': features,
            'training_through_date': max(earlier_dates),
            'training_file': filename,
        })

    exclude_debut_predictions(output_rows)
    apply_recent_performance_balance_to_predictions(output_rows)
    output_rows.sort(
        key=lambda row: (
            not row.get('excluded', False),
            row.get('probability') or 0,
        ),
        reverse=True,
    )

    print(
        f'Backtest race {race_id} ({target_date}): '
        f'{len(output_rows)} horses; trained only on races before {target_date}.'
    )
    for row in output_rows:
        print(format_backtest_prediction(row))
    return output_rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Predict one historical race using only earlier race results.'
    )
    parser.add_argument('--race-id', required=True, help='Historical race ID')
    arguments = parser.parse_args()
    backtest_race(arguments.race_id)
