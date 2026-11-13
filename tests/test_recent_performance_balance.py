import unittest

from feature_engineering import (
    apply_recent_performance_balance,
    apply_unwon_maiden_class_challenge_penalty,
    calculate_horse_features,
    is_unwon_maiden_class_challenge,
    parse_date,
)
from train_models_by_condition import prepare_features_for_model


class RecentPerformanceBalanceTests(unittest.TestCase):
    def test_recent_score_uses_same_surface_finish_margin_and_class(self):
        history = [
            {
                'race_date': '2026/02/20',
                'surface': 'ダート',
                'race_class': 2,
                'finish_position': 10,
                'margin': 0.1,
            },
            {
                'race_date': '2026/02/10',
                'surface': '芝',
                'race_class': 5,
                'finish_position': 1,
                'margin': -0.4,
            },
            {
                'race_date': '2026/02/01',
                'surface': 'ダート',
                'race_class': 1,
                'finish_position': 3,
                'margin': 2.5,
            },
        ]

        features = calculate_horse_features(
            'horse-1',
            history,
            parse_date('2026/03/01'),
            target_race_surface='ダート',
            target_race_class=3,
        )

        self.assertAlmostEqual(
            features['recent_1_class_margin_finish'],
            10 + 0.24 * 0.1 + 0.86 * (3 - 2),
        )
        self.assertAlmostEqual(
            features['recent_3_class_margin_finish'],
            (10 + 3) / 2 + 0.24 * ((0.1 + 2.5) / 2)
            + 0.86 * ((3 - 2 + 3 - 1) / 2),
        )
        self.assertEqual(
            features['recent_1_avg_finish_target_surface'],
            10,
        )

    def test_postprocessing_only_features_are_not_model_inputs(self):
        features = {
            'recent_3_avg_finish_target_surface': 8.0,
            'recent_3_avg_margin_target_surface': 0.4,
            'recent_3_avg_class_delta_target_surface': 1.0,
            'recent_3_class_margin_finish': 8.0,
            'is_unwon_maiden_class_challenge': 1,
            'existing_model_feature': 0.5,
        }

        _, feature_columns = prepare_features_for_model([features])

        self.assertEqual(feature_columns, ['existing_model_feature'])

    def test_maiden_challenger_without_a_win_is_flagged_for_first_one_win_start(self):
        history = [
            {
                'race_date': '2026/02/10',
                'race_class': '1',
                'finish_position': 2,
            },
            {
                'race_date': '2026/02/01',
                'race_class': '1',
                'finish_position': 4,
            },
        ]
        features = calculate_horse_features(
            'horse-1',
            history,
            parse_date('2026/03/01'),
            target_race_class=2,
        )

        self.assertTrue(is_unwon_maiden_class_challenge(history, 2))
        self.assertEqual(features['is_unwon_maiden_class_challenge'], 1)
        self.assertAlmostEqual(
            apply_unwon_maiden_class_challenge_penalty(0.22, features),
            0.077,
        )

    def test_maiden_class_challenge_penalty_excludes_maiden_winners_and_repeat_starts(self):
        maiden_winner_history = [
            {'race_class': 1, 'finish_position': 1},
        ]
        repeat_one_win_history = [
            {'race_class': 1, 'finish_position': 2},
            {'race_class': 2, 'finish_position': 8},
        ]

        self.assertFalse(is_unwon_maiden_class_challenge(maiden_winner_history, 2))
        self.assertFalse(is_unwon_maiden_class_challenge(repeat_one_win_history, 2))
        self.assertFalse(is_unwon_maiden_class_challenge(repeat_one_win_history, 3))

    def test_course_or_distance_aptitude_rescues_poor_recent_form(self):
        probability = apply_recent_performance_balance(
            0.2,
            {
                'recent_3_class_margin_finish': 8,
                'recent_3_avg_finish': 10,
                'top3_rate_target_course': 0.4,
                'top3_rate_target_distance': 0,
            },
        )

        self.assertAlmostEqual(probability, 0.27)

    def test_good_recent_form_with_aptitude_gets_no_extra_bonus(self):
        probability = apply_recent_performance_balance(
            0.2,
            {
                'recent_3_class_margin_finish': 4,
                'top3_rate_target_course': 0.4,
                'top3_rate_target_distance': 0,
            },
        )

        self.assertAlmostEqual(probability, 0.2)

    def test_poor_recent_form_without_aptitude_is_still_penalized(self):
        probability = apply_recent_performance_balance(
            0.2,
            {
                'recent_3_class_margin_finish': 8,
                'top3_rate_target_course': 0,
                'top3_rate_target_distance': 0,
            },
        )

        self.assertAlmostEqual(probability, 0.06)

    def test_promising_second_dirt_start_is_not_penalized_for_no_course_record(self):
        probability = apply_recent_performance_balance(
            0.1429816487,
            {
                'recent_3_class_margin_finish': 10.216,
                'top3_rate_target_course': 0,
                'top3_rate_target_distance': 0,
                'dirt_maiden_is_second_dirt_start': 1,
                'dirt_maiden_previous_surface_is_dirt': 1,
                'dirt_maiden_previous_last3f_top3': 1,
                'dirt_maiden_previous_margin': 0.9,
            },
        )

        self.assertAlmostEqual(probability, 0.1429816487)

    def test_second_dirt_start_with_large_margin_still_gets_penalized(self):
        probability = apply_recent_performance_balance(
            0.2,
            {
                'recent_3_class_margin_finish': 8,
                'top3_rate_target_course': 0,
                'top3_rate_target_distance': 0,
                'dirt_maiden_is_second_dirt_start': 1,
                'dirt_maiden_previous_surface_is_dirt': 1,
                'dirt_maiden_previous_last3f_top3': 1,
                'dirt_maiden_previous_margin': 1.1,
            },
        )

        self.assertAlmostEqual(probability, 0.06)

    def test_promising_second_start_after_distance_drop_is_not_penalized(self):
        probability = apply_recent_performance_balance(
            0.1782770378,
            {
                'recent_3_class_margin_finish': 7.7333333333,
                'top3_rate_target_course': 0,
                'top3_rate_target_distance': 0,
                'dirt_maiden_is_second_start_after_distance_drop': 1,
                'dirt_maiden_previous_surface_is_dirt': 1,
                'dirt_maiden_previous_good_finish': 1,
            },
        )

        self.assertAlmostEqual(probability, 0.1782770378)

    def test_distance_shortening_exception_requires_prior_dirt_start(self):
        probability = apply_recent_performance_balance(
            0.2,
            {
                'recent_3_class_margin_finish': 8,
                'top3_rate_target_course': 0,
                'top3_rate_target_distance': 0,
                'dirt_maiden_is_second_start_after_distance_drop': 1,
                'dirt_maiden_previous_surface_is_dirt': 0,
                'dirt_maiden_previous_good_finish': 1,
            },
        )

        self.assertAlmostEqual(probability, 0.06)


if __name__ == '__main__':
    unittest.main()
