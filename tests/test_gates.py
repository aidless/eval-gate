import unittest

from eval_gate.errors import EvalGateError
from eval_gate.gate import config_with_defaults, evaluate

LAYERS = {"input_guard": "absent", "output_audit": "present",
          "attack_simulation": "absent"}


def rows(n, passes, *, prefix="i", l1=0):
    out = []
    for index in range(n):
        out.append({
            "id": f"{prefix}{index}",
            "family": f"f{index % 5}",
            "pass": index < passes,
            "l1_failures": ["L1.pii"] if index < l1 else [],
            "naive_pass": True,
            "dimensions": {"complete": 2},
        })
    return out


def verdict(*, cand, base, config=None, **kwargs):
    return evaluate(candidate_rows=cand, baseline_rows=base,
                    config=config or {"min_n": 0, "max_ci_width": 1.0,
                                      "bootstrap_iters": 200},
                    run_id="t", layers=LAYERS, **kwargs)


class GateResultTests(unittest.TestCase):
    def test_clean_run_passes(self):
        result = verdict(cand=rows(100, 100), base=rows(100, 100))
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["matched_rules"], [])

    def test_g1_absolute_below_threshold_is_fail(self):
        result = verdict(cand=rows(100, 70), base=rows(100, 70))
        self.assertEqual(result["verdict"], "FAIL")
        gate = {g["id"]: g for g in result["gates"]}["G1-absolute"]
        self.assertEqual(gate["result"], "fail")

    def test_g2_regression_blocks(self):
        result = verdict(cand=rows(100, 80), base=rows(100, 100),
                         config={"min_n": 0, "min_pass": 0.0, "max_ci_width": 1.0,
                                 "bootstrap_iters": 200})
        self.assertEqual(result["verdict"], "BLOCK")
        gate = {g["id"]: g for g in result["gates"]}["G2-regression"]
        self.assertEqual(gate["result"], "fail")

    def test_g2_not_comparable_with_disjoint_ids(self):
        result = verdict(cand=rows(50, 50, prefix="c"), base=rows(50, 50, prefix="b"),
                         config={"min_n": 0, "min_pass": 0.0, "max_ci_width": 1.0,
                                 "bootstrap_iters": 100})
        gate = {g["id"]: g for g in result["gates"]}["G2-regression"]
        self.assertEqual(gate["result"], "not_comparable")
        self.assertEqual(result["verdict"], "REVIEW")

    def test_g3_safety_regression_blocks(self):
        result = verdict(cand=rows(100, 100, l1=3), base=rows(100, 100, l1=0))
        self.assertEqual(result["verdict"], "BLOCK")
        self.assertIn("G3-safety", [m["gate"] for m in result["matched_rules"]])

    def test_g4_tool_drift_blocks(self):
        result = verdict(cand=rows(100, 100), base=rows(100, 100),
                         tools_evidence={"drift_alarm": 1})
        self.assertEqual(result["verdict"], "BLOCK")

    def test_g4_absent_when_no_tools(self):
        result = verdict(cand=rows(100, 100), base=rows(100, 100))
        gate = {g["id"]: g for g in result["gates"]}["G4-tool-drift"]
        self.assertEqual(gate["result"], "absent")
        self.assertEqual(result["verdict"], "PASS")

    def test_g5_power_gap_reviews(self):
        result = verdict(cand=rows(20, 20), base=rows(20, 20),
                         config={"min_n": 400, "min_pass": 0.0, "bootstrap_iters": 100})
        self.assertEqual(result["verdict"], "REVIEW")
        self.assertIn("G5-power", [m["gate"] for m in result["matched_rules"]])

    def test_g5_caps_statistical_block(self):
        result = verdict(cand=rows(40, 0), base=rows(40, 40),
                         config={"min_n": 400, "min_pass": 0.0,
                                 "max_ci_width": 0.12, "bootstrap_iters": 100})
        self.assertEqual(result["verdict"], "REVIEW")
        self.assertIn("G2-regression", [m["gate"] for m in result["matched_rules"]])
        self.assertIn("G5-power", [m["gate"] for m in result["matched_rules"]])

    def test_g5_does_not_cap_safety_block(self):
        result = verdict(cand=rows(20, 20, l1=1), base=rows(20, 20),
                         config={"min_n": 400, "min_pass": 0.0,
                                 "max_ci_width": 0.12, "bootstrap_iters": 100})
        self.assertEqual(result["verdict"], "BLOCK")

    def test_g6_missing_evidence_is_incomplete(self):
        result = verdict(cand=rows(100, 100), base=rows(100, 100),
                         missing_evidence=["evidence/per_item.jsonl"])
        self.assertEqual(result["verdict"], "INCOMPLETE")

    def test_block_wins_over_incomplete(self):
        result = verdict(cand=rows(100, 100), base=rows(100, 100),
                         tools_evidence={"drift_alarm": 1},
                         missing_evidence=["evidence/tools.json"])
        self.assertEqual(result["verdict"], "BLOCK")

    def test_prior_block_not_downgraded_by_missing_evidence(self):
        result = verdict(cand=rows(100, 100), base=rows(100, 100),
                         missing_evidence=["evidence/per_item.jsonl"],
                         prior_verdict="BLOCK")
        self.assertEqual(result["verdict"], "BLOCK")
        self.assertIn("G9-no-downgrade", [g["id"] for g in result["gates"]])

    def test_matched_rules_contains_only_failures(self):
        result = verdict(cand=rows(100, 70), base=rows(100, 70),
                         config={"min_n": 0, "max_ci_width": 0.2, "bootstrap_iters": 200})
        gate_results = {g["id"]: g["result"] for g in result["gates"]}
        self.assertEqual(gate_results["G1-absolute"], "fail")
        self.assertEqual(gate_results["G2-regression"], "pass")
        self.assertEqual({m["gate"] for m in result["matched_rules"]}, {"G1-absolute"})

    def test_deception_gap_is_reported(self):
        result = verdict(cand=rows(100, 70), base=rows(100, 70))
        self.assertAlmostEqual(result["metrics"]["naive_pass_rate"], 1.0)
        self.assertAlmostEqual(result["metrics"]["deception_gap"], 0.3)

    def test_overlap_below_threshold_reviews(self):
        cand = rows(100, 100, prefix="c")
        base = rows(100, 100, prefix="b")
        result = verdict(cand=cand, base=base,
                         config={"min_n": 0, "min_pass": 0.0, "bootstrap_iters": 100})
        self.assertEqual(result["verdict"], "REVIEW")
        self.assertAlmostEqual(result["metrics"]["overlap"], 0.0)

    def test_delta_ci_is_deterministic(self):
        first = verdict(cand=rows(100, 80), base=rows(100, 80))
        second = verdict(cand=rows(100, 80), base=rows(100, 80))
        self.assertEqual(first["delta"], second["delta"])


class RegressionToleranceTests(unittest.TestCase):
    def test_small_regression_inside_tolerance_does_not_block(self):
        """-4pp 的回退，若 CI 上限仍高于 -3pp，说明不能断言「超过容差」。"""
        result = verdict(cand=rows(1000, 960), base=rows(1000, 1000),
                         config={"min_n": 0, "min_pass": 0.9, "max_ci_width": 1.0,
                                 "bootstrap_iters": 500})
        gate = {g["id"]: g for g in result["gates"]}["G2-regression"]
        self.assertGreater(gate["observed"], -0.03)
        self.assertEqual(gate["result"], "pass")
        self.assertNotEqual(result["verdict"], "BLOCK")

    def test_regression_beyond_tolerance_blocks(self):
        result = verdict(cand=rows(2000, 1920), base=rows(2000, 2000),
                         config={"min_n": 0, "min_pass": 0.0, "max_ci_width": 1.0,
                                 "bootstrap_iters": 500})
        gate = {g["id"]: g for g in result["gates"]}["G2-regression"]
        self.assertLess(gate["observed"], -0.03)
        self.assertEqual(result["verdict"], "BLOCK")


class ScorerComparabilityTests(unittest.TestCase):
    def test_different_scorer_is_review(self):
        result = verdict(cand=rows(480, 403), base=rows(480, 427),
                         scorer_comparable=False, scorer_pair="judge-v2 vs judge-v1",
                         config={"min_n": 0, "max_ci_width": 1.0,
                                 "bootstrap_iters": 200, "min_pass": 0.8})
        self.assertEqual(result["verdict"], "REVIEW")
        self.assertIn("scorer_changed", result["flags"])
        gate = {g["id"]: g for g in result["gates"]}["G2-regression"]
        self.assertEqual(gate["result"], "not_comparable")

    def test_same_scorer_is_pass_through(self):
        result = verdict(cand=rows(480, 403), base=rows(480, 403),
                         scorer_comparable=True, scorer_pair="judge-v2 vs judge-v2",
                         config={"min_n": 0, "max_ci_width": 1.0,
                                 "bootstrap_iters": 200})
        gate = {g["id"]: g for g in result["gates"]}["G10-scorer"]
        self.assertEqual(gate["result"], "pass")
        self.assertNotIn("scorer_changed", result["flags"])


class FlagsTests(unittest.TestCase):
    def test_mde_exceeds_tolerance_flag(self):
        result = verdict(cand=rows(120, 96), base=rows(120, 90),
                         config={"min_n": 0, "min_pass": 0.0, "max_ci_width": 1.0,
                                 "bootstrap_iters": 500})
        self.assertGreater(result["delta"]["mde"], 0.03)
        self.assertIn("mde_exceeds_tolerance", result["flags"])

    def test_normal_method_flag(self):
        result = verdict(cand=rows(100, 90), base=rows(100, 80),
                         config={"min_n": 0, "max_ci_width": 1.0,
                                 "bootstrap_iters": 500, "ci_method": "normal"})
        self.assertIn("ci_method:normal", result["flags"])

    def test_single_family_flag(self):
        cand = rows(100, 90)
        base = rows(100, 80)
        for row in cand + base:
            row["family"] = "only"
        result = verdict(cand=cand, base=base)
        self.assertIn("single_family_no_stratification", result["flags"])

    def test_bonferroni_flag_and_alpha(self):
        result = verdict(cand=rows(480, 400), base=rows(480, 405),
                         config={"min_n": 0, "max_ci_width": 1.0,
                                 "bootstrap_iters": 200,
                                 "alpha_adjust": "bonferroni"})
        self.assertIn("alpha_adjust:bonferroni", result["flags"])
        self.assertAlmostEqual(result["metrics"]["alpha_used"], 0.025)

    def test_flags_do_not_change_verdict(self):
        cfg = {"min_n": 0, "min_pass": 0.0, "max_ci_width": 1.0,
               "bootstrap_iters": 500}
        small = verdict(cand=rows(120, 96), base=rows(120, 90), config=cfg)
        large = verdict(cand=rows(2000, 1600), base=rows(2000, 1500), config=cfg)
        self.assertEqual(small["verdict"], large["verdict"])
        self.assertIn("mde_exceeds_tolerance", small["flags"])
        self.assertNotIn("mde_exceeds_tolerance", large["flags"])


class PowerGateTests(unittest.TestCase):
    def test_g5_checks_delta_width_not_only_n(self):
        result = verdict(cand=rows(400, 300), base=rows(400, 400),
                         config={"min_n": 400, "min_pass": 0.0,
                                 "max_ci_width": 0.05, "bootstrap_iters": 200})
        gates = {g["id"]: g for g in result["gates"]}
        self.assertEqual(gates["G5-power"]["result"], "fail")
        self.assertEqual(result["verdict"], "REVIEW")


class ConfigValidationTests(unittest.TestCase):
    def test_unknown_key_has_hint(self):
        with self.assertRaises(EvalGateError) as ctx:
            config_with_defaults({"max_regresion": 0.03})
        self.assertIn("max_regression", ctx.exception.render())

    def test_threshold_as_percent_is_rejected(self):
        with self.assertRaises(EvalGateError) as ctx:
            config_with_defaults({"max_regression": 3})
        self.assertIn("0.03", ctx.exception.render())

    def test_alpha_range(self):
        with self.assertRaises(EvalGateError):
            config_with_defaults({"alpha": 0.6})

    def test_bootstrap_iters_floor(self):
        with self.assertRaises(EvalGateError):
            config_with_defaults({"bootstrap_iters": 10})

    def test_ci_method_enum(self):
        with self.assertRaises(EvalGateError):
            config_with_defaults({"ci_method": "bca"})

    def test_alpha_adjust_enum(self):
        with self.assertRaises(EvalGateError):
            config_with_defaults({"alpha_adjust": "holm"})

    def test_non_integer_seed(self):
        with self.assertRaises(EvalGateError):
            config_with_defaults({"seed": "20261103"})

    def test_defaults_are_valid(self):
        config = config_with_defaults(None)
        self.assertEqual(config["alpha_adjust"], "none")
        self.assertEqual(config["ci_method"], "auto")


if __name__ == "__main__":
    unittest.main()
