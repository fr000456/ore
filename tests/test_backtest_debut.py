import unittest

from backtest_race import (
    exclude_debut_predictions,
    format_backtest_prediction,
)
from feature_engineering import calculate_horse_features


class DebutBacktestTests(unittest.TestCase):
    def test_target_debut_features_use_full_shared_feature_calculation(self):
        features = calculate_horse_features(
            'horse-1',
            [],
            '2026/11/01',
            1800,
            'ダート',
            '東京',
            0,
            target_gate=2,
            target_field_size=12,
        )

        self.assertEqual(features['horse_id'], 'horse-1')
        self.assertEqual(features['total_races'], 0)
        self.assertEqual(features['target_gate'], 2)
        self.assertEqual(features['target_field_size'], 12)
        self.assertIn('target_gate_position', features)

    def test_debut_prediction_is_marked_untestable(self):
        predictions = [{
            'horse_id': 'horse-1',
            'probability': 0.4,
            'model_probability_before_promotion_adjustment': 0.4,
            'features': {
                'horse_id': 'horse-1',
                'total_races': 0,
            },
        }]

        result = exclude_debut_predictions(predictions)

        self.assertIs(result, predictions)
        self.assertIsNone(result[0]['probability'])
        self.assertIsNone(
            result[0]['model_probability_before_promotion_adjustment']
        )
        self.assertTrue(result[0]['excluded'])
        self.assertIn('検証不可', result[0]['error'])

    def test_excluded_prediction_can_be_formatted_without_probability(self):
        prediction = {
            'horse_id': 'horse-1',
            'probability': None,
            'excluded': True,
            'error': '初出走で過去データがないため、検証不可です。',
            'actual_finish': 1,
        }

        formatted = format_backtest_prediction(prediction)

        self.assertIn('horse-1: excluded', formatted)
        self.assertIn('初出走', formatted)


if __name__ == '__main__':
    unittest.main()
