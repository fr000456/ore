import argparse
import pickle
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

sys.modules['pandas'] = None

import lightgbm as lgb
import numpy as np

from dirt_maiden_model import (
    DIRT_MAIDEN_TRAINING_FILE,
    _brier_score,
    _log_loss,
    _roc_auc,
)
from train_models_by_condition import (
    get_model_params,
    prepare_features_for_model,
)


CAREER_FINISH_FEATURE = 'overall_avg_finish_dirt'
RECENT_FINISH_FEATURE = 'recent_3_avg_finish_dirt'
REPLACED_FINISH_FEATURES = {
    'overall_avg_finish',
    'overall_avg_finish_dirt',
    'overall_avg_finish_turf',
    'recent_3_avg_finish',
    'recent_3_avg_finish_dirt',
    'recent_3_avg_finish_turf',
}
DEFAULT_RATIOS = ((1, 5), (1, 2), (1, 1), (2, 1), (5, 1))


@dataclass(frozen=True)
class Fold:
    name: str
    test_start: str
    test_end: str


DEFAULT_FOLDS = (
    Fold('2025-Q3', '2025/07/01', '2025/10/01'),
    Fold('2025-Q4', '2025/10/01', '2026/01/01'),
    Fold('2026-YTD', '2026/01/01', '2026/11/01'),
)


def parse_ratios(value):
    ratios = []
    for item in value.split(','):
        try:
            recent_text, career_text = item.strip().split(':', maxsplit=1)
            recent_weight = float(recent_text)
            career_weight = float(career_text)
        except ValueError as error:
            raise argparse.ArgumentTypeError(
                f'Invalid ratio {item!r}; expected recent:career, e.g. 2:1'
            ) from error
        if (
            not np.isfinite(recent_weight)
            or not np.isfinite(career_weight)
            or recent_weight <= 0
            or career_weight <= 0
        ):
            raise argparse.ArgumentTypeError(
                f'Both weights must be positive finite numbers: {item!r}'
            )
        ratios.append((recent_weight, career_weight))
    if not ratios:
        raise argparse.ArgumentTypeError('At least one ratio is required')
    return tuple(dict.fromkeys(ratios))


def parse_folds(value):
    folds = []
    for item in value.split(','):
        try:
            name, start, end = item.strip().split(':', maxsplit=2)
            datetime.strptime(start, '%Y/%m/%d')
            datetime.strptime(end, '%Y/%m/%d')
        except ValueError as error:
            raise argparse.ArgumentTypeError(
                f'Invalid fold {item!r}; expected name:YYYY/MM/DD:YYYY/MM/DD'
            ) from error
        if start >= end:
            raise argparse.ArgumentTypeError(
                f'Fold start must be before end: {item!r}'
            )
        folds.append(Fold(name, start, end))
    if not folds:
        raise argparse.ArgumentTypeError('At least one fold is required')
    return tuple(folds)


def standardize_finish(values, train_indices):
    values = np.asarray(values, dtype=float)
    train_values = values[train_indices]
    train_values = train_values[np.isfinite(train_values)]
    if not len(train_values):
        raise ValueError('No valid finish values in the training partition')
    mean = float(np.mean(train_values))
    standard_deviation = float(np.std(train_values))
    if standard_deviation <= 0:
        raise ValueError('Finish values have no variation in the training partition')

    scores = (mean - values) / standard_deviation
    missing = ~np.isfinite(scores)
    scores[missing] = 0.0
    return scores, missing, mean, standard_deviation


def complete_races_by_id(features, race_ids, race_dates):
    grouped = defaultdict(list)
    for index, race_id in enumerate(race_ids):
        field_size = features[index].get('target_field_size')
        try:
            field_size = int(field_size)
        except (TypeError, ValueError):
            field_size = None
        grouped[str(race_id)].append(
            (index, field_size, race_dates[index])
        )

    complete = {}
    for race_id, runners in grouped.items():
        field_sizes = {runner[1] for runner in runners}
        if (
            len(field_sizes) == 1
            and None not in field_sizes
            and len(runners) == next(iter(field_sizes))
        ):
            complete[race_id] = runners
    return complete


def build_feature_rows(
    features,
    career_scores,
    recent_scores,
    career_missing,
    recent_missing,
    ratio=None,
):
    rows = []
    for index, original in enumerate(features):
        row = {
            key: value
            for key, value in original.items()
            if key not in REPLACED_FINISH_FEATURES
        }
        if ratio is None:
            row['dirt_career_finish_score'] = float(career_scores[index])
            row['dirt_recent3_finish_score'] = float(recent_scores[index])
        else:
            recent_weight, career_weight = ratio
            available = []
            if not recent_missing[index]:
                available.append(
                    (recent_weight, recent_scores[index])
                )
            if not career_missing[index]:
                available.append(
                    (career_weight, career_scores[index])
                )
            row['dirt_weighted_finish_score'] = (
                sum(weight * score for weight, score in available)
                / sum(weight for weight, _ in available)
                if available
                else 0.0
            )
        row['dirt_career_finish_missing'] = int(career_missing[index])
        row['dirt_recent3_finish_missing'] = int(recent_missing[index])
        rows.append(row)
    return rows


def split_past_dates(
    race_dates,
    past_indices,
    validation_fraction,
    minimum_dates=20,
):
    dates = sorted({
        race_dates[index] for index in past_indices
    }, key=lambda value: datetime.strptime(value, '%Y/%m/%d'))
    if len(dates) < minimum_dates:
        raise ValueError(
            f'At least {minimum_dates} past race dates are required; '
            f'found {len(dates)}'
        )
    train_end = int(len(dates) * (1.0 - validation_fraction))
    train_end = min(max(train_end, 1), len(dates) - 1)
    train_dates = set(dates[:train_end])
    validation_dates = set(dates[train_end:])
    train_indices = np.asarray([
        index for index in past_indices
        if race_dates[index] in train_dates
    ], dtype=int)
    validation_indices = np.asarray([
        index for index in past_indices
        if race_dates[index] in validation_dates
    ], dtype=int)
    return train_indices, validation_indices, dates, train_end


def top5_metrics(targets, predictions, test_indices, complete_races):
    index_to_local = {
        global_index: local_index
        for local_index, global_index in enumerate(test_indices)
    }
    hits = 0
    selections = 0
    for runners in complete_races.values():
        local_indices = [
            index_to_local[index]
            for index, _, _ in runners
            if index in index_to_local
        ]
        if not local_indices:
            continue
        top_indices = sorted(
            local_indices,
            key=lambda index: float(predictions[index]),
            reverse=True,
        )[:5]
        hits += int(np.sum(targets[top_indices]))
        selections += len(top_indices)
    return {
        'hits': hits,
        'selections': selections,
        'precision': hits / selections if selections else float('nan'),
    }


def fit_and_evaluate(
    X,
    targets,
    train_indices,
    validation_indices,
    past_indices,
    test_indices,
    complete_test_races,
    feature_columns,
    seed,
):
    if len(np.unique(targets[train_indices])) < 2:
        raise ValueError('The training partition contains only one target class')
    params = get_model_params(feature_columns, 'other')
    params.update({
        'seed': seed,
        'feature_fraction_seed': seed,
        'bagging_seed': seed,
        'data_random_seed': seed,
        'deterministic': True,
        'force_col_wise': True,
        'num_threads': 1,
    })
    training_set = lgb.Dataset(
        X[train_indices],
        label=targets[train_indices],
    )
    validation_set = lgb.Dataset(
        X[validation_indices],
        label=targets[validation_indices],
        reference=training_set,
    )
    validation_model = lgb.train(
        params,
        training_set,
        num_boost_round=1000,
        valid_sets=[validation_set],
        callbacks=[
            lgb.early_stopping(stopping_rounds=50, verbose=False),
        ],
    )
    best_iteration = validation_model.best_iteration or 1000
    model = lgb.train(
        params,
        lgb.Dataset(X[past_indices], label=targets[past_indices]),
        num_boost_round=best_iteration,
    )
    predictions = model.predict(
        X[test_indices],
        num_iteration=best_iteration,
    )
    actual = targets[test_indices]
    return {
        'brier': _brier_score(actual, predictions),
        'log_loss': _log_loss(actual, predictions),
        'auc': _roc_auc(actual, predictions),
        'top5': top5_metrics(
            actual,
            predictions,
            test_indices,
            complete_test_races,
        ),
        'predictions': predictions,
        'best_iteration': best_iteration,
    }


def _validation_metrics(
    X,
    targets,
    train_indices,
    validation_indices,
    feature_columns,
    complete_races,
    seed,
):
    params = get_model_params(feature_columns, 'other')
    params.update({
        'seed': seed,
        'feature_fraction_seed': seed,
        'bagging_seed': seed,
        'data_random_seed': seed,
        'deterministic': True,
        'force_col_wise': True,
        'num_threads': 1,
    })
    training_set = lgb.Dataset(
        X[train_indices],
        label=targets[train_indices],
    )
    validation_set = lgb.Dataset(
        X[validation_indices],
        label=targets[validation_indices],
        reference=training_set,
    )
    model = lgb.train(
        params,
        training_set,
        num_boost_round=1000,
        valid_sets=[validation_set],
        callbacks=[
            lgb.early_stopping(stopping_rounds=50, verbose=False),
        ],
    )
    predictions = model.predict(
        X[validation_indices],
        num_iteration=model.best_iteration or 1000,
    )
    validation_index_set = set(validation_indices)
    validation_races = {
        race_id: runners
        for race_id, runners in complete_races.items()
        if all(index in validation_index_set for index, _, _ in runners)
    }
    top5 = top5_metrics(
        targets[validation_indices],
        predictions,
        validation_indices,
        validation_races,
    )
    return {
        'brier': _brier_score(targets[validation_indices], predictions),
        'top5': top5,
        'best_iteration': model.best_iteration or 1000,
    }


def _load_data(filename):
    with open(filename, 'rb') as training_file:
        data = pickle.load(training_file)
    lengths = {
        len(data[key])
        for key in ('features', 'targets', 'race_ids', 'race_dates')
    }
    if len(lengths) != 1:
        raise ValueError(f'{filename} has inconsistent training-data lengths')
    for race_date in data['race_dates']:
        datetime.strptime(race_date, '%Y/%m/%d')
    return data


def _select_metric(metrics, metric):
    if metric == 'brier':
        return metrics['brier']
    if metric == 'top5':
        return -metrics['top5']['precision']
    raise ValueError(f'Unsupported selection metric: {metric}')


def run_validation(
    data,
    ratios=DEFAULT_RATIOS,
    folds=DEFAULT_FOLDS,
    selection_metric='brier',
    validation_fraction=0.15,
    seed=20261105,
):
    features = data['features']
    targets = np.asarray(data['targets'], dtype=int)
    race_ids = [str(race_id) for race_id in data['race_ids']]
    race_dates = data['race_dates']
    complete_races = complete_races_by_id(features, race_ids, race_dates)
    results = {}

    for fold in folds:
        past_indices = np.asarray([
            index for index, race_date in enumerate(race_dates)
            if race_date < fold.test_start
        ], dtype=int)
        test_races = {
            race_id: runners
            for race_id, runners in complete_races.items()
            if fold.test_start <= runners[0][2] < fold.test_end
        }
        test_indices = np.asarray(sorted(
            index
            for runners in test_races.values()
            for index, _, _ in runners
        ), dtype=int)
        if not len(test_indices):
            raise ValueError(
                f'{fold.name} has no complete held-out races '
                f'between {fold.test_start} and {fold.test_end}'
            )
        train_indices, validation_indices, past_dates, train_end = (
            split_past_dates(
                race_dates,
                past_indices,
                validation_fraction,
            )
        )
        if not len(validation_indices):
            raise ValueError(f'{fold.name} has an empty validation partition')
        validation_index_set = set(validation_indices)
        validation_race_count = sum(
            all(index in validation_index_set for index, _, _ in runners)
            for runners in complete_races.values()
        )
        if selection_metric == 'top5' and validation_race_count < 10:
            raise ValueError(
                f'{fold.name} has only {validation_race_count} complete '
                'validation races; at least 10 are required to select a '
                'ratio by top-5 precision. Use --selection-metric brier or '
                'provide a wider validation window.'
            )

        career_values = np.asarray([
            np.nan if row.get(CAREER_FINISH_FEATURE) is None
            else float(row[CAREER_FINISH_FEATURE])
            for row in features
        ])
        recent_values = np.asarray([
            np.nan if row.get(RECENT_FINISH_FEATURE) is None
            else float(row[RECENT_FINISH_FEATURE])
            for row in features
        ])
        career_scores, career_missing, career_mean, career_std = (
            standardize_finish(career_values, train_indices)
        )
        recent_scores, recent_missing, recent_mean, recent_std = (
            standardize_finish(recent_values, train_indices)
        )
        fold_results = {
            'metadata': {
                'complete_test_races': len(test_races),
                'test_runners': len(test_indices),
                'train_rows': len(train_indices),
                'validation_rows': len(validation_indices),
                'complete_validation_races': validation_race_count,
                'train_dates': (past_dates[0], past_dates[train_end - 1]),
                'validation_dates': (past_dates[train_end], past_dates[-1]),
                'test_dates': (fold.test_start, fold.test_end),
                'recent_missing_test_rate': float(
                    np.mean(recent_missing[test_indices])
                ),
                'career_mean_std': (career_mean, career_std),
                'recent_mean_std': (recent_mean, recent_std),
            },
            'candidates': {},
        }

        candidate_ratios = (None, *ratios)
        for ratio in candidate_ratios:
            candidate_name = (
                'separate' if ratio is None
                else f'{ratio[0]:g}:{ratio[1]:g}'
            )
            rows = build_feature_rows(
                features,
                career_scores,
                recent_scores,
                career_missing,
                recent_missing,
                ratio=ratio,
            )
            matrix, columns = prepare_features_for_model(rows)
            validation_metrics = _validation_metrics(
                matrix,
                targets,
                train_indices,
                validation_indices,
                columns,
                complete_races,
                seed,
            )
            test_metrics = fit_and_evaluate(
                matrix,
                targets,
                train_indices,
                validation_indices,
                past_indices,
                test_indices,
                test_races,
                columns,
                seed,
            )
            fold_results['candidates'][candidate_name] = {
                'ratio': ratio,
                'validation': validation_metrics,
                'test': test_metrics,
            }

        eligible = {
            name: result
            for name, result in fold_results['candidates'].items()
            if name != 'separate'
        }
        selected_name = min(
            eligible,
            key=lambda name: _select_metric(
                eligible[name]['validation'],
                selection_metric,
            ),
        )
        fold_results['selected_ratio'] = selected_name
        results[fold.name] = fold_results
    return results


def _format_candidate_metrics(candidate):
    validation = candidate['validation']
    test = candidate['test']
    return (
        f"validation Brier={validation['brier']:.5f}, "
        f"validation top5={validation['top5']['precision']:.3f}; "
        f"test Brier={test['brier']:.5f}, "
        f"test AUC={test['auc']:.4f}, "
        f"test top5={test['top5']['precision']:.3f} "
        f"({test['top5']['hits']}/{test['top5']['selections']})"
    )


def print_results(results, selection_metric):
    print(
        'Selection is made on the preceding validation window only; '
        'the held-out fold is for evaluation.'
    )
    print(
        'Ratios combine train-standardized dirt-only overall and recent-3 '
        'finish averages. Other features are retained, except mixed-surface '
        'and duplicate finish-average aliases.'
    )
    for fold_name, fold_result in results.items():
        metadata = fold_result['metadata']
        print(
            f'\n{fold_name}: complete test races='
            f'{metadata["complete_test_races"]}, runners='
            f'{metadata["test_runners"]}; '
            f'train={metadata["train_dates"]}; '
            f'validation={metadata["validation_dates"]}; '
            f'complete validation races='
            f'{metadata["complete_validation_races"]}; '
            f'test={metadata["test_dates"]}; '
            f'recent missing={metadata["recent_missing_test_rate"]:.1%}'
        )
        candidates = fold_result['candidates']
        for name, candidate in candidates.items():
            marker = ' [selected]' if name == fold_result['selected_ratio'] else ''
            print(f'  {name}: {_format_candidate_metrics(candidate)}{marker}')

    selected_test_metrics = [
        fold_result['candidates'][fold_result['selected_ratio']]['test']
        for fold_result in results.values()
    ]
    print(f'\nSelected per fold using validation {selection_metric}:')
    print(
        'ratios='
        + ', '.join(
            f'{fold_name}:{fold_result["selected_ratio"]}'
            for fold_name, fold_result in results.items()
        )
    )
    print(
        f'mean held-out Brier='
        f'{np.mean([metrics["brier"] for metrics in selected_test_metrics]):.5f}; '
        f'mean held-out top5='
        f'{np.mean([metrics["top5"]["precision"] for metrics in selected_test_metrics]):.3f}'
    )
    print(
        '\nTreat the result as exploratory if the winning ratio changes between '
        'folds or the metrics disagree. Incomplete historical races remain in '
        'the training data; only complete races are used for top-5 ranking.'
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            'Compare recent-to-career finish weights for the JRA dirt maiden '
            'model using rolling historical validation.'
        )
    )
    parser.add_argument(
        '--training-data',
        default=DIRT_MAIDEN_TRAINING_FILE,
        help='Path to the generated dirt-maiden training pickle.',
    )
    parser.add_argument(
        '--ratios',
        type=parse_ratios,
        default=DEFAULT_RATIOS,
        help='Comma-separated recent:career ratios; both weights must be positive.',
    )
    parser.add_argument(
        '--folds',
        type=parse_folds,
        default=DEFAULT_FOLDS,
        help=(
            'Comma-separated name:start:end folds, with dates YYYY/MM/DD; '
            'test end is exclusive.'
        ),
    )
    parser.add_argument(
        '--selection-metric',
        choices=('brier', 'top5'),
        default='brier',
        help='Metric used to select a ratio within each validation window.',
    )
    parser.add_argument(
        '--validation-fraction',
        type=float,
        default=0.15,
        help='Fraction of dates before each test fold reserved for validation.',
    )
    parser.add_argument('--seed', type=int, default=20261105)
    arguments = parser.parse_args()
    if not 0.05 <= arguments.validation_fraction <= 0.4:
        parser.error('--validation-fraction must be between 0.05 and 0.4')

    data = _load_data(arguments.training_data)
    results = run_validation(
        data,
        ratios=arguments.ratios,
        folds=arguments.folds,
        selection_metric=arguments.selection_metric,
        validation_fraction=arguments.validation_fraction,
        seed=arguments.seed,
    )
    print_results(results, arguments.selection_metric)


if __name__ == '__main__':
    main()
