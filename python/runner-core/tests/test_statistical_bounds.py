import unittest

from infergrade.statistical_bounds import wilson_score_interval, wilson_score_upper_bound


class StatisticalBoundsTests(unittest.TestCase):
    def test_zero_ceiling_hits_need_sixteen_observations_for_twenty_percent_limit(self):
        self.assertAlmostEqual(
            wilson_score_upper_bound(0, 8, 0.95),
            0.3244075649,
        )
        self.assertAlmostEqual(
            wilson_score_upper_bound(0, 16, 0.95),
            0.1936076805,
        )

    def test_one_ceiling_hit_in_twenty_does_not_prove_rate_below_twenty_percent(self):
        self.assertAlmostEqual(
            wilson_score_upper_bound(1, 20, 0.95),
            0.2361311934,
        )

    def test_empty_sample_has_no_bound(self):
        self.assertIsNone(wilson_score_upper_bound(0, 0, 0.95))
        self.assertIsNone(wilson_score_interval(0, 0, 0.95))

    def test_two_sided_interval_exposes_small_sample_uncertainty(self):
        lower, upper = wilson_score_interval(1, 3, 0.95)

        self.assertAlmostEqual(lower, 0.0614919447)
        self.assertAlmostEqual(upper, 0.7923403992)
        self.assertEqual(upper, wilson_score_upper_bound(1, 3, 0.95))

    def test_invalid_counts_and_confidence_fail_closed(self):
        for args in ((2, 1, 0.95), (-1, 1, 0.95), (0, 1, 1.0), (True, 1, 0.95)):
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    wilson_score_upper_bound(*args)


if __name__ == "__main__":
    unittest.main()
