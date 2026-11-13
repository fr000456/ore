import unittest

from jra_turf_2000_upper_model import (
    JRA_COURSES,
    add_jra_course_features,
    is_jra_turf_2000_upper,
)


class JraTurf2000UpperModelTests(unittest.TestCase):
    def test_scope_includes_jra_turf_2000_open_and_grade_races(self):
        self.assertTrue(
            is_jra_turf_2000_upper('東京', '芝', 2000, 9)
        )
        self.assertTrue(
            is_jra_turf_2000_upper('2東京7', '芝', '2000', '7')
        )
        self.assertFalse(
            is_jra_turf_2000_upper('東京', '芝', 2000, 4)
        )
        self.assertFalse(
            is_jra_turf_2000_upper('東京', '芝', 2000, 1)
        )
        self.assertFalse(
            is_jra_turf_2000_upper('東京', 'ダート', 2000, 9)
        )
        self.assertFalse(
            is_jra_turf_2000_upper('東京', '芝', 2200, 9)
        )
        self.assertFalse(
            is_jra_turf_2000_upper('大井', '芝', 2000, 9)
        )

    def test_course_features_have_stable_columns(self):
        features = add_jra_course_features({}, '2東京7')

        self.assertEqual(
            [features[f'target_jra_course_{course}'] for course in JRA_COURSES],
            [1] + [0] * (len(JRA_COURSES) - 1),
        )


if __name__ == '__main__':
    unittest.main()
