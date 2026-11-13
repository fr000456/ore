import unittest

import numpy as np

from dirt_maiden_model import (
    _roc_auc,
    add_dirt_maiden_features,
    is_debut_horse,
    is_jra_dirt_maiden,
    train_jra_dirt_maiden_model,
)
from feature_engineering import calculate_horse_features, parse_date


class DirtMaidenFeatureTests(unittest.TestCase):
    def test_jra_dirt_maiden_scope(self):
        self.assertTrue(is_jra_dirt_maiden('東京ダート', 'ダート', '1'))
        self.assertTrue(is_jra_dirt_maiden('1東京8', 'ダート', '1'))
        self.assertFalse(is_jra_dirt_maiden('盛岡', 'ダート', '1'))
        self.assertFalse(is_jra_dirt_maiden('東京', '芝', '1'))
        self.assertFalse(is_jra_dirt_maiden('東京', 'ダート', '2'))

    def test_first_dirt_start_and_bad_loss_count(self):
        target_date = parse_date('2026/01/10')
        history = [
            {
                'race_date': '2026/01/01',
                'surface': 'ダート',
                'distance': 1600,
                'finish_position': 5,
                'margin': 1.5,
                'course': '東京',
            },
            {
                'race_date': '2025/12/01',
                'surface': 'ダート',
                'distance': 1600,
                'finish_position': 6,
                'margin': 1.0,
                'course': '中山',
            },
            {
                'race_date': '2026/02/01',
                'surface': 'ダート',
                'distance': 1400,
                'finish_position': 1,
                'margin': 0.0,
                'course': '東京',
            },
        ]
        features = {}
        add_dirt_maiden_features(
            features,
            history,
            target_date,
            1400,
            '東京',
        )
        self.assertEqual(features['dirt_maiden_dirt_start_count'], 2)
        self.assertEqual(features['dirt_maiden_is_first_dirt_start'], 0)
        self.assertEqual(features['dirt_maiden_dirt_bad_loss_count'], 1)
        self.assertEqual(features['dirt_maiden_previous_finish'], 5)

    def test_distance_drop_second_start_and_empty_history(self):
        target_date = parse_date('2026/03/01')
        history = [
            {
                'race_date': '2026/02/01',
                'surface': '芝',
                'distance': 1200,
                'finish_position': 4,
                'margin': 0.5,
                'course': '東京',
            },
            {
                'race_date': '2025/12/01',
                'surface': '芝',
                'distance': 1600,
                'finish_position': 8,
                'margin': 1.2,
                'course': '中山',
            },
        ]
        features = calculate_horse_features(
            'experienced',
            history,
            target_date,
            1200,
            'ダート',
            '東京',
            1,
        )
        add_dirt_maiden_features(
            features,
            history,
            target_date,
            1200,
            '東京',
        )
        self.assertEqual(
            features['dirt_maiden_is_second_start_after_distance_drop'],
            1,
        )
        self.assertEqual(
            features['dirt_maiden_distance_drop_from_shortest_prior'],
            400,
        )
        self.assertFalse(is_debut_horse(features))
        self.assertEqual(features['dirt_maiden_is_first_dirt_start'], 1)

        base_features = calculate_horse_features(
            'debutant',
            [],
            target_date,
            1200,
            'ダート',
            '東京',
            1,
        )
        add_dirt_maiden_features(
            base_features,
            [],
            target_date,
            1200,
            '東京',
        )
        self.assertEqual(
            base_features['dirt_maiden_is_first_dirt_start'],
            1,
        )
        self.assertTrue(is_debut_horse(base_features))
        self.assertEqual(base_features['is_first_time_distance'], 1)

    def test_additive_second_dirt_and_previous_performance_signals(self):
        target_date = parse_date('2026/03/01')
        history = [
            {
                'race_date': '2026/02/01',
                'surface': 'ダート',
                'distance': 1600,
                'finish_position': 4,
                'margin': 0.8,
                'last_3f_rank': 3,
                'course': '東京',
            },
            {
                'race_date': '2025/12/01',
                'surface': '芝',
                'distance': 1400,
                'finish_position': 8,
                'margin': 1.2,
                'last_3f_rank': 5,
                'course': '中山',
            },
        ]
        features = {}

        add_dirt_maiden_features(
            features,
            history,
            target_date,
            1800,
            '東京',
        )

        self.assertEqual(features['dirt_maiden_is_second_dirt_start'], 1)
        self.assertEqual(features['dirt_maiden_previous_last3f_top3'], 1)
        self.assertEqual(features['dirt_maiden_previous_good_finish'], 1)
        self.assertEqual(features['dirt_maiden_positive_signal_count'], 3)

    def test_additive_signal_count_does_not_require_all_conditions(self):
        target_date = parse_date('2026/03/01')
        history = [
            {
                'race_date': '2026/02/01',
                'surface': '芝',
                'distance': 1600,
                'finish_position': 8,
                'margin': 1.2,
                'last_3f_rank': 2,
                'course': '東京',
            },
        ]
        features = {}

        add_dirt_maiden_features(
            features,
            history,
            target_date,
            1800,
            '東京',
        )

        self.assertEqual(features['dirt_maiden_is_second_dirt_start'], 0)
        self.assertEqual(features['dirt_maiden_previous_last3f_top3'], 1)
        self.assertEqual(features['dirt_maiden_previous_good_finish'], 0)
        self.assertEqual(features['dirt_maiden_positive_signal_count'], 1)

    def test_only_horses_without_any_prior_race_are_debutants(self):
        self.assertTrue(is_debut_horse({'total_races': 0}))
        self.assertFalse(is_debut_horse({'total_races': 1}))

    def test_auc_handles_tied_scores(self):
        auc = _roc_auc(
            np.asarray([0, 1, 0, 1]),
            np.asarray([0.2, 0.5, 0.5, 0.8]),
        )
        self.assertEqual(auc, 0.875)

    def test_training_refuses_incomplete_race_data_by_default(self):
        data = {
            'features': [],
            'targets': [],
            'race_ids': [],
            'race_dates': [],
            'metadata': {
                'complete_race_count': 12,
                'race_count': 2205,
                'incomplete_race_count': 2193,
            },
        }
        with self.assertRaisesRegex(ValueError, 'Refusing to train'):
            train_jra_dirt_maiden_model(data)


if __name__ == '__main__':
    unittest.main()
