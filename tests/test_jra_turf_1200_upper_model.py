import unittest

from jra_turf_1200_upper_model import (
    JRA_COURSES,
    add_jra_course_features,
    is_jra_turf_1200_upper,
)


class JraTurf1200UpperModelTests(unittest.TestCase):
    def test_scope_includes_jra_turf_1200_open_and_grade_races(self):
        self.assertTrue(
            is_jra_turf_1200_upper('中山', '芝', 1200, 9)
        )
        self.assertTrue(
            is_jra_turf_1200_upper('4中山9', '芝', '1200', '7')
        )
        self.assertFalse(
            is_jra_turf_1200_upper('中山', '芝', 1200, 4)
        )
        self.assertFalse(
            is_jra_turf_1200_upper('中山', 'ダート', 1200, 9)
        )
        self.assertFalse(
            is_jra_turf_1200_upper('中山', '芝', 2000, 9)
        )
        self.assertFalse(
            is_jra_turf_1200_upper('大井', '芝', 1200, 9)
        )

    def test_course_features_have_stable_columns(self):
        features = add_jra_course_features({}, '4中山9')

        self.assertEqual(
            [features[f'target_jra_course_{course}'] for course in JRA_COURSES],
            [0, 1] + [0] * (len(JRA_COURSES) - 2),
        )


if __name__ == '__main__':
    unittest.main()
