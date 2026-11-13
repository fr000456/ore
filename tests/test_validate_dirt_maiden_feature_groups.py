import unittest

from validate_dirt_maiden_feature_groups import (
    FEATURE_GROUPS,
    _indices_in_date_range,
    _quarter_bounds,
    _rolling_validation_windows,
    feature_group,
    make_candidate_masks,
)


class DirtMaidenFeatureGroupTests(unittest.TestCase):
    def test_feature_groups_cover_targeted_families(self):
        examples = {
            'recent_3_avg_finish_dirt': 'recent_dirt_form',
            'overall_avg_finish_dirt': 'career_dirt_form',
            'dirt_maiden_previous_margin': 'previous_race_quality',
            'dirt_maiden_is_second_dirt_start': 'dirt_transition',
            'prev_distance_diff': 'course_distance_surface_context',
            'recent_3_avg_finish_turf': 'turf_finish_history',
            'overall_avg_finish': 'mixed_surface_finish_history',
        }
        for feature, expected_group in examples.items():
            with self.subTest(feature=feature):
                self.assertEqual(feature_group(feature), expected_group)

    def test_candidate_masks_exhaust_all_group_combinations(self):
        features = [
            'recent_3_avg_finish_dirt',
            'overall_avg_finish_dirt',
            'dirt_maiden_previous_margin',
            'dirt_maiden_is_second_dirt_start',
            'prev_distance_diff',
            'recent_3_avg_finish_turf',
            'course_gate_group_advantage',
            'overall_avg_finish',
            'avg_last_3f',
        ]
        candidates, groups = make_candidate_masks(features)

        self.assertEqual(len(candidates), 2 ** len(FEATURE_GROUPS))
        self.assertIn('none', {name for name, _, _ in candidates})
        self.assertIn(
            '+'.join(FEATURE_GROUPS),
            {name for name, _, _ in candidates},
        )
        self.assertEqual(groups['course_distance_surface_context'], {4, 6})
        for name, included, keep in candidates:
            if name == 'none':
                self.assertEqual(keep.tolist(), [8])
            if name == 'recent_dirt_form':
                self.assertEqual(keep.tolist(), [0, 8])
            if len(included) == len(FEATURE_GROUPS):
                self.assertEqual(
                    keep.tolist(),
                    list(range(len(features))),
                )

    def test_unclassified_features_remain_available(self):
        self.assertIsNone(feature_group('avg_last_3f'))
        self.assertIsNone(feature_group('target_field_size'))

    def test_quarter_bounds_handle_year_boundary(self):
        self.assertEqual(
            _quarter_bounds('2025/11/15'),
            ('2025/10/01', '2026/01/01'),
        )

    def test_test_period_includes_all_runner_rows_not_only_complete_races(self):
        indices = _indices_in_date_range(
            [
                '2025/06/30',
                '2025/07/01',
                '2025/07/01',
                '2025/09/30',
                '2025/10/01',
            ],
            start='2025/07/01',
            end='2025/10/01',
        )

        self.assertEqual(indices.tolist(), [1, 2, 3])

    def test_rolling_windows_are_chronological_and_exclude_future_rows(self):
        race_dates = [
            '2024/01/10',
            '2024/04/10',
            '2024/07/10',
            '2024/10/10',
            '2025/01/10',
            '2025/04/10',
            '2025/07/10',
            '2025/10/10',
        ]

        windows = _rolling_validation_windows(
            race_dates,
            test_start='2025/10/01',
            window_count=3,
            minimum_rows=1,
        )

        self.assertEqual(
            [window['name'] for window in windows],
            ['2025-Q1', '2025-Q2', '2025-Q3'],
        )
        for window in windows:
            self.assertTrue(
                all(
                    race_dates[index] < window['start']
                    for index in window['train_indices']
                )
            )
            self.assertTrue(
                all(
                    window['start'] <= race_dates[index] < window['end']
                    for index in window['validation_indices']
                )
            )


if __name__ == '__main__':
    unittest.main()
