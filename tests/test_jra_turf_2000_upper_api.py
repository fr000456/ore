import datetime
import unittest
from unittest.mock import patch

import numpy as np

from flask_app import app


class FakeModel:
    best_iteration = 1

    def predict(self, features, num_iteration=None):
        return np.asarray([0.6])


class JraTurf2000UpperApiTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            'horse_ids': ['horse-1'],
            'horse_gates': [1],
            'field_size': 1,
            'race_date': (
                datetime.date.today() + datetime.timedelta(days=2)
            ).strftime('%Y/%m/%d'),
            'race_course': '東京',
            'race_distance': 2000,
            'race_surface': '芝',
            'race_class': 9,
            'race_id': '202611010101',
        }
        self.client = app.test_client()

    def test_upper_class_turf_2000_uses_pooled_model(self):
        artifact = {
            'model': FakeModel(),
            'feature_columns': ['target_jra_course_東京'],
            'data_quality_warning': None,
        }
        with (
            patch('flask_app.race_has_recorded_winner', return_value=False),
            patch(
                'flask_app.load_jra_turf_2000_upper_model',
                return_value=artifact,
            ),
            patch(
                'feature_engineering.get_horse_race_history',
                return_value=[],
            ),
            patch(
                'feature_engineering.calculate_horse_features',
                return_value={'horse_id': 'horse-1'},
            ),
            patch('flask_app.load_model_by_condition') as regular_model_loader,
        ):
            response = self.client.post('/predict', json=self.payload)

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body['model_group'], 'jra_turf_2000_upper')
        self.assertEqual(body['predictions'][0]['probability'], 0.6)
        self.assertEqual(
            body['predictions'][0]['features']['target_jra_course_東京'],
            1,
        )
        regular_model_loader.assert_not_called()

    def test_upper_class_turf_1200_uses_pooled_model(self):
        self.payload.update({
            'race_course': '中山',
            'race_distance': 1200,
            'race_class': 9,
        })
        artifact = {
            'model': FakeModel(),
            'feature_columns': ['target_jra_course_中山'],
            'data_quality_warning': None,
        }
        with (
            patch('flask_app.race_has_recorded_winner', return_value=False),
            patch(
                'flask_app.load_jra_turf_1200_upper_model',
                return_value=artifact,
            ),
            patch(
                'feature_engineering.get_horse_race_history',
                return_value=[],
            ),
            patch(
                'feature_engineering.calculate_horse_features',
                return_value={'horse_id': 'horse-1'},
            ),
            patch('flask_app.load_model_by_condition') as regular_model_loader,
        ):
            response = self.client.post('/predict', json=self.payload)

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body['model_group'], 'jra_turf_1200_upper')
        self.assertEqual(body['predictions'][0]['probability'], 0.6)
        self.assertEqual(
            body['predictions'][0]['features']['target_jra_course_中山'],
            1,
        )
        regular_model_loader.assert_not_called()

    def test_regular_race_prediction_initializes_turf_1200_model_flag(self):
        self.payload.update({
            'race_course': '東京',
            'race_distance': 1600,
            'race_class': 3,
        })
        self.payload.pop('race_id')
        artifact = {
            'model': FakeModel(),
            'feature_columns': ['total_races'],
        }
        with (
            patch('flask_app.race_has_recorded_winner', return_value=False),
            patch('flask_app.load_model_by_condition', return_value=artifact),
            patch(
                'feature_engineering.get_horse_race_history',
                return_value=[],
            ),
            patch(
                'feature_engineering.calculate_horse_features',
                return_value={'horse_id': 'horse-1', 'total_races': 1},
            ),
        ):
            response = self.client.post('/predict', json=self.payload)

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body['model_group'], 'condition')
        self.assertEqual(body['predictions'][0]['probability'], 0.6)
        self.assertNotIn('error', body['predictions'][0])

    def test_model_without_feature_columns_fails_before_predicting_horses(self):
        self.payload.update({
            'race_course': '東京',
            'race_distance': 1600,
            'race_class': 5,
        })
        self.payload.pop('race_id')
        with (
            patch('flask_app.load_model_by_condition', return_value={
                'model': FakeModel(),
            }),
            patch('flask_app.race_has_recorded_winner', return_value=False),
        ):
            response = self.client.post('/predict', json=self.payload)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json()['error'],
            'The selected prediction model has no feature columns',
        )

    def test_unwon_maiden_challenger_is_penalized_in_live_prediction(self):
        self.payload.update({
            'race_course': '東京',
            'race_distance': 1600,
            'race_surface': 'ダート',
            'race_class': 2,
        })
        self.payload.pop('race_id')
        artifact = {
            'model': FakeModel(),
            'feature_columns': ['total_races'],
        }
        with (
            patch('flask_app.load_model_by_condition', return_value=artifact),
            patch(
                'feature_engineering.get_horse_race_history',
                return_value=[
                    {'race_class': '1', 'finish_position': 2},
                ],
            ),
            patch(
                'feature_engineering.calculate_horse_features',
                return_value={
                    'horse_id': 'horse-1',
                    'total_races': 1,
                    'is_unwon_maiden_class_challenge': 1,
                },
            ),
        ):
            response = self.client.post('/predict', json=self.payload)

        self.assertEqual(response.status_code, 200)
        prediction = response.get_json()['predictions'][0]
        self.assertAlmostEqual(prediction['probability'], 0.21)


if __name__ == '__main__':
    unittest.main()
