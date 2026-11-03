import unittest

from eval_gate.gate import evaluate

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
                    config=config or {"min_n": 0, "bootstrap_iters": 200},
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
                         config={"min_n": 0, "min_pass": 0.0, "bootstrap_iters": 200})
        self.assertEqual(result["verdict"], "BLOCK")
        gate = {g["id"]: g for g in result["gates"]}["G2-regression"]
        self.assertEqual(gate["result"], "fail")

    def test_g2_not_comparable_with_disjoint_ids(self):
        result = verdict(cand=rows(50, 50, prefix="c"), base=rows(50, 50, prefix="b"),
                         config={"min_n": 0, "min_pass": 0.0, "bootstrap_iters": 100})
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


if __name__ == "__main__":
    unittest.main()
