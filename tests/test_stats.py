import unittest

from eval_gate.stats import (ci_width, overlap_rate, paired_bootstrap_delta,
                             wilson_interval)


class WilsonTests(unittest.TestCase):
    def test_empty_sample_is_conservative(self):
        self.assertEqual(wilson_interval(0, 0), (0.0, 1.0))

    def test_interval_contains_point(self):
        low, high = wilson_interval(387, 480)
        self.assertLess(low, 387 / 480)
        self.assertGreater(high, 387 / 480)

    def test_interval_stays_in_unit_range(self):
        self.assertEqual(wilson_interval(0, 10)[0], 0.0)
        self.assertLessEqual(wilson_interval(10, 10)[1], 1.0)

    def test_more_passes_shifts_interval_up(self):
        self.assertLess(wilson_interval(380, 480)[0],
                        wilson_interval(387, 480)[0])

    def test_width_shrinks_with_more_samples(self):
        self.assertLess(ci_width(wilson_interval(800, 1000)),
                        ci_width(wilson_interval(80, 100)))

    def test_known_bounds_for_regression_case(self):
        low, high = wilson_interval(387, 480)
        self.assertAlmostEqual(low, 0.7685, places=3)
        self.assertAlmostEqual(high, 0.8391, places=3)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.candidate = {f"i{i}": 1.0 if i < 90 else 0.0 for i in range(100)}
        self.baseline = {f"i{i}": 1.0 if i < 80 else 0.0 for i in range(100)}
        self.families = {f"i{i}": f"f{i % 10}" for i in range(100)}

    def test_same_seed_is_identical(self):
        first = paired_bootstrap_delta(self.candidate, self.baseline, self.families,
                                       iterations=200, seed=7)
        second = paired_bootstrap_delta(self.candidate, self.baseline, self.families,
                                        iterations=200, seed=7)
        self.assertEqual(first, second)

    def test_different_seed_changes_interval(self):
        first = paired_bootstrap_delta(self.candidate, self.baseline, self.families,
                                       iterations=200, seed=7)
        second = paired_bootstrap_delta(self.candidate, self.baseline, self.families,
                                        iterations=200, seed=8)
        self.assertNotEqual(first["ci95"], second["ci95"])

    def test_delta_direction(self):
        stats = paired_bootstrap_delta(self.candidate, self.baseline, self.families,
                                       iterations=200, seed=20261103)
        self.assertAlmostEqual(stats["delta"], 0.10)
        self.assertGreater(stats["ci95"][0], 0.0)

    def test_unpaired_ids_are_ignored(self):
        candidate = {"a": 1.0, "b": 0.0}
        baseline = {"a": 0.0, "c": 0.0}
        stats = paired_bootstrap_delta(candidate, baseline, {"a": "f", "b": "f"}, iterations=50)
        self.assertEqual(stats["n"], 1)
        self.assertAlmostEqual(stats["delta"], 1.0)

    def test_strata_count(self):
        stats = paired_bootstrap_delta(self.candidate, self.baseline, self.families,
                                       iterations=50)
        self.assertEqual(stats["families"], 10)

    def test_empty_overlap(self):
        stats = paired_bootstrap_delta({"a": 1.0}, {"b": 1.0}, {}, iterations=50)
        self.assertEqual(stats["n"], 0)
        self.assertEqual(stats["delta"], 0.0)


class OverlapTests(unittest.TestCase):
    def test_overlap_rate(self):
        self.assertAlmostEqual(overlap_rate(["a", "b", "c"], ["a", "b"]), 2 / 3)

    def test_empty_candidate(self):
        self.assertEqual(overlap_rate([], ["a"]), 0.0)


if __name__ == "__main__":
    unittest.main()
