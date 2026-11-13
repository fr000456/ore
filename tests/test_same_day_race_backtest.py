import datetime
import unittest
from unittest.mock import patch

import numpy as np

from flask_app import app
from backtest_race import apply_recent_performance_balance_to_predictions


class FakeModel:
    best_iteration = 1

    def predict(self, features, num_iteration=None):
        return np.asarray([0.6])


class SameDayRaceBacktestTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            'horse_ids': ['horse-1'],
            'horse_gates': [1],
            'field_size': 1,
            'race_date': datetime.date.today().strftime('%Y/%m/%d'),
            'race_course': '東京',
            'race_distance': 1200,
            'race_surface': 'ダート',
            'race_class': 1,
            'race_id': '202611010101',
        }
        self.client = app.test_client()

    def test_completed_same_day_race_uses_backtest(self):
        backtest_rows = [{
            'horse_id': 'horse-1',
            'probability': None,
            'excluded': True,
            'error': '初出走で過去走がないため、予測対象外です。',
            'actual_finish': 2,
            'features': {},
            'model_group': 'jra_dirt_maiden',
            'training_through_date': '2026/10/25',
        }]
        with (
            patch('flask_app.race_has_recorded_winner', return_value=True),
            patch(
                'backtest_race.backtest_race',
                return_value=backtest_rows,
            ) as backtest,
            patch(
                'flask_app.load_jra_dirt_maiden_model',
                return_value={'data_quality_warning': 'partial data'},
            ),
        ):
            response = self.client.post('/predict', json=self.payload)

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body['prediction_mode'], 'backtest')
        self.assertEqual(body['predictions'][0]['actual_finish'], 2)
        self.assertTrue(body['predictions'][0]['excluded'])
        self.assertIn('初出走', body['predictions'][0]['error'])
        self.assertEqual(body['model_data_quality_warning'], 'partial data')
        backtest.assert_called_once()

    def test_unfinished_same_day_debut_is_excluded_from_live_prediction(self):
        artifact = {
            'model': FakeModel(),
            'feature_columns': [
                'dirt_maiden_is_first_dirt_start',
                'dirt_maiden_target_distance_start_count',
            ],
            'data_quality_warning': None,
        }
        with (
            patch('flask_app.race_has_recorded_winner', return_value=False),
            patch(
                'flask_app.load_jra_dirt_maiden_model',
                return_value=artifact,
            ),
            patch('feature_engineering.get_horse_race_history', return_value=[]),
        ):
            response = self.client.post('/predict', json=self.payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['prediction_mode'], 'live')
        prediction = response.get_json()['predictions'][0]
        self.assertTrue(prediction['excluded'])
        self.assertIsNone(prediction['probability'])
        self.assertIn('初出走', prediction['error'])

    def test_backtest_probabilities_apply_recent_performance_balance(self):
        predictions = [
            {
                'probability': 0.4,
                'features': {
                    'recent_3_avg_finish': 8,
                    'top3_rate_target_course': 0,
                    'top3_rate_target_distance': 0,
                },
            },
            {
                'probability': 0.4,
                'features': {
                    'recent_3_avg_finish': 8,
                    'recent_3_class_margin_finish': 8,
                    'top3_rate_target_course': 0.4,
                    'top3_rate_target_distance': 0,
                },
            },
            {
                'probability': 0.4,
                'features': {
                    'recent_3_avg_finish': 4,
                    'top3_rate_target_course': 0.4,
                    'top3_rate_target_distance': 0,
                },
            },
            {
                'probability': None,
                'excluded': True,
                'features': {},
            },
        ]

        apply_recent_performance_balance_to_predictions(predictions)

        self.assertAlmostEqual(predictions[0]['probability'], 0.12)
        self.assertEqual(
            predictions[0][
                'model_probability_before_recent_performance_balance'
            ],
            0.4,
        )
        self.assertAlmostEqual(predictions[1]['probability'], 0.54)
        self.assertAlmostEqual(predictions[2]['probability'], 0.4)
        self.assertNotIn(
            'model_probability_before_recent_performance_balance',
            predictions[3],
        )

    def test_backtest_probabilities_apply_maiden_class_challenge_penalty(self):
        predictions = [{
            'probability': 0.4,
            'features': {
                'is_unwon_maiden_class_challenge': 1,
            },
        }]

        apply_recent_performance_balance_to_predictions(predictions)

        self.assertAlmostEqual(predictions[0]['probability'], 0.14)


if __name__ == '__main__':
    unittest.main()
