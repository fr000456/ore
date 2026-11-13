import argparse
import itertools
from datetime import datetime

import numpy as np

from dirt_maiden_model import DIRT_MAIDEN_TRAINING_FILE
from train_models_by_condition import prepare_features_for_model
from validate_dirt_maiden_balance import (
    DEFAULT_FOLDS,
    _load_data,
    _validation_metrics,
    complete_races_by_id,
    fit_and_evaluate,
    parse_folds,
    split_past_dates,
)


FEATURE_GROUPS = (
    'recent_dirt_form',
    'career_dirt_form',
    'previous_race_quality',
    'dirt_transition',
    'course_distance_surface_context',
    'turf_finish_history',
    'mixed_surface_finish_history',
)
VALIDATION_QUARTERS = 4
MIN_VALIDATION_ROWS = 300


def feature_group(feature):
    if feature in {
        'recent_3_avg_finish_dirt',
        'recent_3_top3_rate_dirt',
        'recent_5_avg_finish_dirt',
        'recent_5_top3_rate_dirt',
        'dirt_maiden_dirt_bad_loss_recent3_count',
    }:
        return 'recent_dirt_form'

    if feature in {
        'overall_avg_finish_dirt',
        'overall_top3_rate_dirt',
        'dirt_maiden_career_top3_count',
        'dirt_maiden_career_top3_rate',
        'dirt_maiden_dirt_start_count',
        'dirt_maiden_dirt_top3_count',
        'dirt_maiden_dirt_top3_rate',
        'dirt_maiden_dirt_bad_loss_count',
    }:
        return 'career_dirt_form'

    if feature in {
        'last_finish',
        'prev_last_3f_rank',
        'prev2_finish',
        'prev_race_class',
        'dirt_maiden_previous_finish',
        'dirt_maiden_previous_good_finish',
        'dirt_maiden_previous_last3f_rank',
        'dirt_maiden_previous_last3f_top3',
        'dirt_maiden_previous_margin',
        'dirt_maiden_previous_running_position_first',
        'dirt_maiden_previous_running_position_last',
        'dirt_maiden_previous_running_position_ratio',
    }:
        return 'previous_race_quality'

    if feature in {
        'is_dirt_2nd',
        'dirt_maiden_is_first_dirt_start',
        'dirt_maiden_is_second_dirt_start',
        'dirt_maiden_is_second_start_after_distance_drop',
        'dirt_maiden_second_dirt_previous_was_dirt',
        'dirt_maiden_previous_surface_is_dirt',
        'dirt_maiden_positive_signal_count',
    }:
        return 'dirt_transition'

    if (
        feature.startswith(('is_distance_', 'prev_distance_', 'prev_course_'))
        or feature.startswith(('target_course_', 'target_distance_'))
        or feature.startswith(('top3_rate_', 'course_gate_group_'))
        or feature.startswith('horse_gate_group_')
        or feature.startswith('dirt_maiden_course_')
        or feature in {
            'is_first_time_distance',
            'is_distance_expanding',
            'is_distance_shortening',
            'is_shortening_2nd',
            'prev_distance',
            'prev_distance_diff',
            'prev_course',
            'prev_course_change_score',
            'target_course_experience_count',
            'target_distance_experience_count',
            'target_distance_surface_experience_count',
            'target_surface_experience_count',
            'target_surface_recent_6_assessable_count',
            'target_surface_recent_6_good_count',
            'target_surface_recent_6_good_rate',
            'target_surface_recent_6_has_good',
            'target_surface_recent_6_race_count',
            'target_gate',
            'target_gate_group',
            'target_gate_position',
            'dirt_maiden_previous_course_match',
            'dirt_maiden_previous_distance_diff',
            'dirt_maiden_previous_previous_distance',
            'dirt_maiden_distance_drop_from_shortest_prior',
            'dirt_maiden_target_course_dirt_start_count',
            'dirt_maiden_target_course_dirt_top3_count',
            'dirt_maiden_target_course_start_count',
            'dirt_maiden_target_course_top3_count',
            'dirt_maiden_target_course_top3_rate',
            'dirt_maiden_target_distance',
            'dirt_maiden_target_distance_dirt_start_count',
            'dirt_maiden_target_distance_dirt_top3_count',
            'dirt_maiden_target_distance_start_count',
            'dirt_maiden_target_distance_top3_count',
            'dirt_maiden_target_distance_top3_rate',
            'course_gate_group_advantage',
            'course_gate_group_expected_rate',
            'course_gate_group_race_count',
            'course_gate_group_starter_count',
            'course_gate_group_top3_rate',
            'horse_gate_group_advantage',
            'horse_gate_group_experience_count',
            'horse_gate_group_top3_rate',
        }
    ):
        return 'course_distance_surface_context'

    if feature.endswith('_turf') or feature.startswith('dirt_maiden_turf_'):
        return 'turf_finish_history'

    if feature in {
        'overall_avg_finish',
        'overall_top3_rate',
        'recent_3_avg_finish',
        'recent_3_top3_rate',
        'recent_5_avg_finish',
        'recent_5_top3_rate',
    }:
        return 'mixed_surface_finish_history'

    return None


def make_candidate_masks(feature_columns):
    groups_by_feature = {
        name: {
            index
            for index, feature in enumerate(feature_columns)
            if feature_group(feature) == name
        }
        for name in FEATURE_GROUPS
    }
    candidates = []
    for selected in itertools.product((False, True), repeat=len(FEATURE_GROUPS)):
        included_groups = tuple(
            name for name, include in zip(FEATURE_GROUPS, selected) if include
        )
        excluded_columns = set().union(*(
            groups_by_feature[name]
            for name, include in zip(FEATURE_GROUPS, selected)
            if not include
        ))
        keep = np.asarray([
            index for index in range(len(feature_columns))
            if index not in excluded_columns
        ], dtype=int)
        name = '+'.join(included_groups) if included_groups else 'none'
        candidates.append((name, included_groups, keep))
    return candidates, groups_by_feature


def _candidate_matrix(matrix, columns, keep_indices):
    return matrix[:, keep_indices], [columns[index] for index in keep_indices]


def _quarter_bounds(race_date):
    year, month = map(int, race_date[:7].split('/'))
    quarter_start_month = ((month - 1) // 3) * 3 + 1
    start = datetime(year, quarter_start_month, 1)
    if quarter_start_month == 10:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, quarter_start_month + 3, 1)
    return start.strftime('%Y/%m/%d'), end.strftime('%Y/%m/%d')


def _indices_in_date_range(race_dates, start, end):
    return np.asarray([
        index for index, race_date in enumerate(race_dates)
        if start <= race_date < end
    ], dtype=int)


def _rolling_validation_windows(
    race_dates,
    test_start,
    window_count=VALIDATION_QUARTERS,
    minimum_rows=MIN_VALIDATION_ROWS,
):
    quarter_starts = sorted({
        _quarter_bounds(race_date)[0]
        for race_date in race_dates
        if _quarter_bounds(race_date)[1] <= test_start
    })
    windows = []
    for start in quarter_starts:
        _, end = _quarter_bounds(start)
        validation_indices = np.asarray([
            index for index, race_date in enumerate(race_dates)
            if start <= race_date < end
        ], dtype=int)
        train_indices = np.asarray([
            index for index, race_date in enumerate(race_dates)
            if race_date < start
        ], dtype=int)
        if len(validation_indices) < minimum_rows or not len(train_indices):
            continue
        windows.append({
            'name': start[:4] + '-Q' + str((int(start[5:7]) - 1) // 3 + 1),
            'start': start,
            'end': end,
            'train_indices': train_indices,
            'validation_indices': validation_indices,
        })
    return windows[-window_count:]


def run_feature_group_validation(
    data,
    folds=DEFAULT_FOLDS,
    validation_fraction=0.15,
    seed=20261105,
    validation_quarters=VALIDATION_QUARTERS,
    minimum_validation_rows=MIN_VALIDATION_ROWS,
):
    features = data['features']
    targets = np.asarray(data['targets'], dtype=int)
    race_ids = [str(race_id) for race_id in data['race_ids']]
    race_dates = data['race_dates']
    complete_races = complete_races_by_id(features, race_ids, race_dates)
    matrix, columns = prepare_features_for_model(features)
    candidates, groups_by_feature = make_candidate_masks(columns)
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
        test_indices = _indices_in_date_range(
            race_dates,
            fold.test_start,
            fold.test_end,
        )
        if not len(test_indices):
            raise ValueError(
                f'{fold.name} has no complete held-out races '
                f'between {fold.test_start} and {fold.test_end}'
            )
        rolling_windows = _rolling_validation_windows(
            race_dates,
            fold.test_start,
            window_count=validation_quarters,
            minimum_rows=minimum_validation_rows,
        )
        if not rolling_windows:
            raise ValueError(
                f'{fold.name} has no prior quarterly validation windows with '
                f'at least {minimum_validation_rows} runner rows'
            )
        train_indices, validation_indices, past_dates, train_end = (
            split_past_dates(
                race_dates,
                past_indices,
                validation_fraction,
            )
        )
        validation_index_set = set(validation_indices)
        validation_races = {
            race_id: runners
            for race_id, runners in complete_races.items()
            if all(index in validation_index_set for index, _, _ in runners)
        }

        validation_results = {}
        candidate_details = {}
        for name, included_groups, keep in candidates:
            candidate_matrix, candidate_columns = _candidate_matrix(
                matrix, columns, keep
            )
            window_metrics = []
            for window in rolling_windows:
                window_validation_indices = set(window['validation_indices'])
                window_complete_races = {
                    race_id: runners
                    for race_id, runners in complete_races.items()
                    if all(
                        index in window_validation_indices
                        for index, _, _ in runners
                    )
                }
                window_metrics.append(_validation_metrics(
                    candidate_matrix,
                    targets,
                    window['train_indices'],
                    window['validation_indices'],
                    candidate_columns,
                    window_complete_races,
                    seed,
                ))
            total_validation_rows = sum(
                len(window['validation_indices']) for window in rolling_windows
            )
            validation_results[name] = {
                'brier': sum(
                    metrics['brier'] * len(window['validation_indices'])
                    for metrics, window in zip(
                        window_metrics, rolling_windows
                    )
                ) / total_validation_rows,
                'top5': window_metrics[-1]['top5'],
                'windows': window_metrics,
            }
            candidate_details[name] = {
                'included_groups': included_groups,
                'keep': keep,
                'columns': candidate_columns,
            }

        selected_name = min(
            validation_results,
            key=lambda name: validation_results[name]['brier'],
        )
        baseline_name = '+'.join(FEATURE_GROUPS)
        tested_names = [baseline_name]
        if selected_name != baseline_name:
            tested_names.append(selected_name)
        test_results = {}
        for name in tested_names:
            details = candidate_details[name]
            candidate_matrix, candidate_columns = _candidate_matrix(
                matrix, columns, details['keep']
            )
            test_results[name] = fit_and_evaluate(
                candidate_matrix,
                targets,
                train_indices,
                validation_indices,
                past_indices,
                test_indices,
                test_races,
                candidate_columns,
                seed,
            )

        results[fold.name] = {
            'metadata': {
                'complete_test_races': len(test_races),
                'test_runners': len(test_indices),
                'complete_validation_races': len(validation_races),
                'selection_windows': [
                    {
                        'name': window['name'],
                        'start': window['start'],
                        'end': window['end'],
                        'rows': len(window['validation_indices']),
                        'complete_races': sum(
                            all(
                                index in set(window['validation_indices'])
                                for index, _, _ in runners
                            )
                            for runners in complete_races.values()
                        ),
                    }
                    for window in rolling_windows
                ],
                'train_dates': (past_dates[0], past_dates[train_end - 1]),
                'validation_dates': (past_dates[train_end], past_dates[-1]),
                'test_dates': (fold.test_start, fold.test_end),
                'feature_count': len(columns),
                'group_sizes': {
                    name: len(indices)
                    for name, indices in groups_by_feature.items()
                },
            },
            'selected': selected_name,
            'selected_validation': validation_results[selected_name],
            'baseline_validation': validation_results[baseline_name],
            'candidate_validation': validation_results,
            'test': test_results,
        }
    return results


def print_results(results):
    print(
        'Searches all combinations of seven feature families. Candidate '
        'selection uses the pooled Brier score over up to four prior '
        'quarterly walk-forward windows; each window trains only on earlier '
        'races. Features outside these families stay in every model.'
    )
    for fold_name, result in results.items():
        metadata = result['metadata']
        print(
            f'\n{fold_name}: test runners='
            f'{metadata["test_runners"]}; '
            f'complete races for top5={metadata["complete_test_races"]}; '
            f'test={metadata["test_dates"]}'
        )
        print(
            '  selection windows: '
            + ', '.join(
                f'{window["name"]} rows={window["rows"]}, '
                f'complete races={window["complete_races"]}'
                for window in metadata['selection_windows']
            )
        )
        if fold_name == next(iter(results)):
            print(
                '  feature-family sizes: '
                + ', '.join(
                    f'{name}={size}'
                    for name, size in metadata['group_sizes'].items()
                )
            )
        selected_validation = result['selected_validation']
        baseline_validation = result['baseline_validation']
        print(
            f'  selected={result["selected"]}; rolling validation Brier '
            f'{selected_validation["brier"]:.5f} vs all-groups '
            f'{baseline_validation["brier"]:.5f}'
        )
        for name, metrics in result['test'].items():
            top5 = metrics['top5']
            print(
                f'  test {name}: Brier={metrics["brier"]:.5f}, '
                f'AUC={metrics["auc"]:.4f}, top5='
                f'{top5["precision"]:.3f} '
                f'({top5["hits"]}/{top5["selections"]})'
            )


def main():
    parser = argparse.ArgumentParser(
        description=(
            'Search JRA dirt maiden feature-family combinations using '
            'nested quarterly walk-forward validation.'
        )
    )
    parser.add_argument(
        '--training-data',
        default=DIRT_MAIDEN_TRAINING_FILE,
        help='Path to the generated dirt-maiden training pickle.',
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
        '--validation-fraction',
        type=float,
        default=0.15,
        help='Fraction of dates before each test fold reserved for validation.',
    )
    parser.add_argument(
        '--validation-quarters',
        type=int,
        default=VALIDATION_QUARTERS,
        help='Number of most recent quarterly windows used for selection.',
    )
    parser.add_argument(
        '--minimum-validation-rows',
        type=int,
        default=MIN_VALIDATION_ROWS,
        help='Minimum runner rows required in a quarterly selection window.',
    )
    parser.add_argument('--seed', type=int, default=20261105)
    arguments = parser.parse_args()
    if not 0.05 <= arguments.validation_fraction <= 0.4:
        parser.error('--validation-fraction must be between 0.05 and 0.4')
    if arguments.validation_quarters < 1:
        parser.error('--validation-quarters must be at least 1')
    if arguments.minimum_validation_rows < 1:
        parser.error('--minimum-validation-rows must be at least 1')

    results = run_feature_group_validation(
        _load_data(arguments.training_data),
        folds=arguments.folds,
        validation_fraction=arguments.validation_fraction,
        seed=arguments.seed,
        validation_quarters=arguments.validation_quarters,
        minimum_validation_rows=arguments.minimum_validation_rows,
    )
    print_results(results)


if __name__ == '__main__':
    main()
