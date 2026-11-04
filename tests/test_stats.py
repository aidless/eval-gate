import unittest

from eval_gate.stats import (alpha_to_z, ci_width, mde_from_variance, overlap_rate,
                             paired_bootstrap_delta, paired_delta_ci,
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


def _fixture():
    cand = {f"i{i}": 1.0 if (i * 7) % 10 < 9 else 0.0 for i in range(120)}
    base = {f"i{i}": 1.0 if (i * 7) % 10 < 7 else 0.0 for i in range(120)}
    fam = {f"i{i}": f"f{i % 4}" for i in range(120)}
    return cand, base, fam


class GoldenReproducibilityTests(unittest.TestCase):
    """固定 seed 的数值必须逐位一致：跨机器/跨 3.9–3.12 也不能漂。"""

    def test_bootstrap_golden_values(self):
        cand, base, fam = _fixture()
        stats = paired_bootstrap_delta(cand, base, fam, iterations=500,
                                       seed=20261103)
        self.assertEqual(stats["delta"], 0.2)
        self.assertEqual(stats["ci95"],
                         [0.13333333333333333, 0.2710416666666665])
        self.assertEqual(stats["n"], 120)
        self.assertEqual(stats["families"], 4)

    def test_normal_approximation_golden_values(self):
        cand, base, fam = _fixture()
        stats = paired_delta_ci(cand, base, fam, iterations=500,
                                seed=20261103, method="normal")
        self.assertEqual(stats["delta"], 0.2)
        self.assertEqual(stats["ci95"],
                         [0.1272087650151985, 0.2727912349848015])
        self.assertEqual(stats["method"], "normal")


class NormalFallbackTests(unittest.TestCase):
    def test_auto_uses_normal_when_work_too_large(self):
        cand, base, fam = _fixture()
        stats = paired_delta_ci(cand, base, fam, iterations=10_000,
                                max_bootstrap_work=100_000)
        self.assertEqual(stats["method"], "normal")
        self.assertEqual(stats["iterations"], 0)

    def test_auto_uses_bootstrap_for_small_work(self):
        cand, base, fam = _fixture()
        stats = paired_delta_ci(cand, base, fam, iterations=500)
        self.assertEqual(stats["method"], "bootstrap")
        self.assertEqual(stats["iterations"], 500)

    def test_bootstrap_and_normal_are_close(self):
        cand, base, fam = _fixture()
        boot = paired_delta_ci(cand, base, fam, iterations=2_000, seed=7)
        norm = paired_delta_ci(cand, base, fam, iterations=2_000, seed=7,
                               method="normal")
        self.assertLess(abs(boot["ci95"][0] - norm["ci95"][0]), 0.02)
        self.assertLess(abs(boot["ci95"][1] - norm["ci95"][1]), 0.02)


class MdeTests(unittest.TestCase):
    def test_known_mde_value(self):
        # (1.959964 + 0.841621) * sqrt(1e-4) = 0.0280159
        self.assertAlmostEqual(mde_from_variance(0.0001), 0.0280159, places=6)

    def test_zero_variance_has_zero_mde(self):
        self.assertEqual(mde_from_variance(0.0), 0.0)

    def test_mde_available_from_interval(self):
        cand, base, fam = _fixture()
        stats = paired_delta_ci(cand, base, fam, iterations=500, seed=20261103)
        self.assertGreater(stats["mde"], 0.0)
        self.assertAlmostEqual(stats["discordant"], 24)

    def test_alpha_to_z_is_two_sided(self):
        self.assertAlmostEqual(alpha_to_z(0.05), 1.959963984540054, places=6)
        self.assertAlmostEqual(alpha_to_z(0.025), 2.2414027264652865, places=6)
        self.assertGreater(alpha_to_z(0.01), alpha_to_z(0.05))


if __name__ == "__main__":
    unittest.main()
