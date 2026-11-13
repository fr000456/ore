import argparse
import unittest

import numpy as np

from validate_dirt_maiden_balance import (
    Fold,
    build_feature_rows,
    complete_races_by_id,
    parse_folds,
    parse_ratios,
    split_past_dates,
    standardize_finish,
)


class DirtMaidenBalanceValidationTests(unittest.TestCase):
    def test_ratio_parser_requires_both_weights_and_keeps_distinct_ratios(self):
        self.assertEqual(
            parse_ratios('1:1, 2:1, 5:1, 2:1'),
            ((1.0, 1.0), (2.0, 1.0), (5.0, 1.0)),
        )
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_ratios('0:1')

    def test_fold_parser_validates_exclusive_date_range_shape(self):
        self.assertEqual(
            parse_folds('holdout:2026/01/01:2026/04/01'),
            (Fold('holdout', '2026/01/01', '2026/04/01'),),
        )
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_folds('holdout:2026/04/01:2026/01/01')

    def test_finish_standardization_uses_training_only_and_reverses_rank(self):
        scores, missing, mean, standard_deviation = standardize_finish(
            np.asarray([2.0, 4.0, 100.0, np.nan]),
            np.asarray([0, 1]),
        )

        self.assertEqual(mean, 3.0)
        self.assertEqual(standard_deviation, 1.0)
        self.assertEqual(scores[0], 1.0)
        self.assertEqual(scores[1], -1.0)
        self.assertTrue(scores[2] < scores[1])
        self.assertTrue(missing[3])
        self.assertEqual(scores[3], 0.0)

    def test_weighted_rows_keep_other_features_and_remove_finish_aliases(self):
        rows = build_feature_rows(
            [
                {
                    'overall_avg_finish': 8.0,
                    'overall_avg_finish_dirt': 6.0,
                    'overall_avg_finish_turf': 12.0,
                    'recent_3_avg_finish': 4.0,
                    'recent_3_avg_finish_dirt': 4.0,
                    'recent_3_avg_finish_turf': None,
                    'overall_top3_rate_turf': 0.5,
                    'course_gate_group_advantage': 0.1,
                },
                {
                    'overall_avg_finish_dirt': 7.0,
                    'recent_3_avg_finish_dirt': None,
                    'course_gate_group_advantage': -0.1,
                },
            ],
            career_scores=np.asarray([0.0, -1.0]),
            recent_scores=np.asarray([1.0, 0.0]),
            career_missing=np.asarray([False, False]),
            recent_missing=np.asarray([False, True]),
            ratio=(2.0, 1.0),
        )

        self.assertAlmostEqual(rows[0]['dirt_weighted_finish_score'], 2 / 3)
        self.assertEqual(rows[1]['dirt_weighted_finish_score'], -1.0)
        self.assertEqual(rows[1]['dirt_recent3_finish_missing'], 1)
        self.assertNotIn('overall_avg_finish', rows[0])
        self.assertNotIn('recent_3_avg_finish_dirt', rows[0])
        self.assertEqual(rows[0]['overall_top3_rate_turf'], 0.5)
        self.assertEqual(rows[0]['course_gate_group_advantage'], 0.1)

    def test_only_complete_races_are_selected(self):
        complete = complete_races_by_id(
            [
                {'target_field_size': 2},
                {'target_field_size': 2},
                {'target_field_size': 3},
            ],
            ['complete', 'complete', 'partial'],
            ['2026/01/01', '2026/01/01', '2026/01/02'],
        )

        self.assertEqual(set(complete), {'complete'})
        self.assertEqual(len(complete['complete']), 2)

    def test_past_dates_split_chronologically(self):
        train, validation, dates, train_end = split_past_dates(
            [
                '2026/01/01',
                '2026/01/02',
                '2026/01/03',
                '2026/01/04',
                '2026/01/05',
                '2026/01/06',
                '2026/01/07',
            ],
            np.arange(7),
            validation_fraction=0.3,
            minimum_dates=7,
        )

        self.assertEqual(train.tolist(), [0, 1, 2, 3])
        self.assertEqual(validation.tolist(), [4, 5, 6])
        self.assertEqual(train_end, 4)
        self.assertEqual(dates[0], '2026/01/01')
        self.assertEqual(dates[-1], '2026/01/07')


if __name__ == '__main__':
    unittest.main()
