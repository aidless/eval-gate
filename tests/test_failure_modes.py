"""失效模式回归测试：每个用例对应 FAILURE_MODES.md 里的一行。

命名约定：`test_fmNN_*` 的 NN 与文档表格中的编号一一对应。
这些用例不是「功能测试」，而是「这个包在什么情况下会给出错判决」的复现脚本。
"""
import pathlib
import tempfile
import unittest

from eval_gate.contract import read_json, write_json, write_jsonl
from eval_gate.errors import EvalGateError
from eval_gate.gate import evaluate
from eval_gate.rubric import score_records
from eval_gate.runner import run_gate, verify_run

LAYERS = {"input_guard": "absent", "output_audit": "present",
          "attack_simulation": "absent"}
FAST = {"bootstrap_iters": 200, "min_n": 0, "max_ci_width": 1.0}


def rows(n=100, passes=None, *, prefix="q", families=4, l1=0,
         naive=None):
    passes = n if passes is None else passes
    out = []
    for index in range(n):
        out.append({
            "id": f"{prefix}{index:03d}",
            "family": f"f{index % families}",
            "pass": index < passes,
            "l1_failures": ["L1.pii"] if index < l1 else [],
            "naive_pass": (index < passes) if naive is None else naive,
            "dimensions": {"complete": 2},
        })
    return out


def dataset(n=40, *, prefix="q"):
    return [{"id": f"{prefix}{index:03d}", "family": f"f{index % 3}",
             "input": f"{prefix} 第 {index} 题", "reference": "参考",
             "answerable": True} for index in range(n)]


def _run_gate_in_tmp(tmp: pathlib.Path, *, ds, cand, base, config=None,
                     **kwargs) -> dict:
    ds_path = tmp / "dataset.jsonl"
    cand_path = tmp / "cand.jsonl"
    base_path = tmp / "base.jsonl"
    write_jsonl(ds_path, ds)
    write_jsonl(cand_path, cand)
    write_jsonl(base_path, base)
    out = tmp / "run"
    return run_gate(dataset_path=ds_path, predictions_path=cand_path,
                    baseline_predictions_path=base_path, out_dir=out,
                    config=config or dict(FAST), **kwargs)


class SmallSampleAndPowerTests(unittest.TestCase):
    def test_fm01_tiny_sample_reviews(self):
        """FM-01 样本量极小：n=5 不可能给出 PASS/BLOCK。"""
        result = evaluate(candidate_rows=rows(5, 5), baseline_rows=rows(5, 5),
                          config={"min_n": 400, "min_pass": 0.0,
                                  "bootstrap_iters": 100},
                          run_id="t", layers=LAYERS)
        self.assertEqual(result["verdict"], "REVIEW")
        gate = {g["id"]: g for g in result["gates"]}["G5-power"]
        self.assertEqual(gate["result"], "fail")

    def test_fm08_extreme_skew_still_has_interval(self):
        """FM-08 分布极端偏斜：479/480 通过时区间宽度不为 0。"""
        result = evaluate(candidate_rows=rows(480, 479), baseline_rows=rows(480, 479),
                          config=dict(FAST), run_id="t", layers=LAYERS)
        low, high = result["primary_metric"]["ci95"]
        self.assertGreater(high - low, 0.0)
        self.assertEqual(result["verdict"], "PASS")


class ZeroVarianceTests(unittest.TestCase):
    def test_fm09_identical_candidate_and_baseline(self):
        """FM-09 零方差：候选=基线时 delta 区间退化为 [0,0]，但不崩。"""
        result = evaluate(candidate_rows=rows(200, 200), baseline_rows=rows(200, 200),
                          config=dict(FAST), run_id="t", layers=LAYERS)
        self.assertEqual(result["delta"]["ci95"], [0.0, 0.0])
        self.assertEqual(result["delta"]["mde"], 0.0)
        self.assertEqual(result["verdict"], "PASS")


class ThresholdSemanticsTests(unittest.TestCase):
    def test_fm10_g1_uses_wilson_lower_bound(self):
        """FM-10 单侧 vs 双侧：G1 看的是 95% 区间下限，不是点估计。"""
        result = evaluate(candidate_rows=rows(100, 80), baseline_rows=rows(100, 80),
                          config={"min_n": 0, "max_ci_width": 1.0,
                                  "bootstrap_iters": 100, "min_pass": 0.80},
                          run_id="t", layers=LAYERS)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertLess(result["primary_metric"]["ci95"][0], 0.80)

    def test_fm11_threshold_edge_is_flagged(self):
        """FM-11 阈值贴边：结论成立但离边界 <0.2pp 时挂 flag。"""
        result = evaluate(candidate_rows=rows(480, 401), baseline_rows=rows(480, 401),
                          config={"min_n": 0, "max_ci_width": 1.0,
                                  "bootstrap_iters": 200},
                          run_id="t", layers=LAYERS)
        self.assertIn("threshold_edge:G1", result["flags"])


class MultipleComparisonTests(unittest.TestCase):
    def test_fm12_bonferroni_widens_interval(self):
        """FM-12 多处同时检验：bonferroni 把 alpha 分摊，区间更宽。"""
        base_config = {"bootstrap_iters": 200, "min_n": 0, "max_ci_width": 1.0}
        plain = evaluate(candidate_rows=rows(480, 400), baseline_rows=rows(480, 405),
                         config=base_config, run_id="t", layers=LAYERS)
        strict = evaluate(candidate_rows=rows(480, 400), baseline_rows=rows(480, 405),
                          config={**base_config, "alpha_adjust": "bonferroni"},
                          run_id="t", layers=LAYERS)
        self.assertGreater(strict["metrics"]["alpha_used"],
                           0.0)
        self.assertEqual(strict["metrics"]["alpha_used"],
                         plain["metrics"]["alpha_used"] / 2)
        self.assertGreater(strict["delta"]["ci95"][1] - strict["delta"]["ci95"][0],
                           plain["delta"]["ci95"][1] - plain["delta"]["ci95"][0])
        self.assertIn("alpha_adjust:bonferroni", strict["flags"])


class DuplicateAndContractTests(unittest.TestCase):
    def test_fm03_duplicate_input_rejected(self):
        """FM-03 精确重复题面（换 id 的泄漏）被拒绝。"""
        ds = dataset(10)
        ds[1]["input"] = ds[0]["input"]
        with self.assertRaises(EvalGateError) as ctx:
            score_records(ds, [])
        self.assertIn("完全相同", str(ctx.exception))
        self.assertIn("next:", ctx.exception.render())

    def test_fm06_duplicate_id_rejected(self):
        """FM-06 重复 id（同一题被算两次）被拒绝。"""
        ds = dataset(5)
        ds[1]["id"] = ds[0]["id"]
        with self.assertRaises(EvalGateError):
            score_records(ds, [])

    def test_fm14_missing_dataset_id_is_actionable(self):
        """FM-14 缺字段：报错要告诉下一步怎么做，而不是 KeyError。"""
        with self.assertRaises(EvalGateError) as ctx:
            score_records([{"family": "f", "input": "x"}], [])
        message = ctx.exception.render()
        self.assertIn("id", message)
        self.assertIn("next:", message)

    def test_fm17_empty_dataset_is_actionable(self):
        with self.assertRaises(EvalGateError) as ctx:
            score_records([], [])
        self.assertIn("空", str(ctx.exception))

    def test_fm19_external_pass_must_be_bool(self):
        """FM-19 外部判分器把 pass 写成字符串"false"时不能当真。"""
        with self.assertRaises(EvalGateError) as ctx:
            score_records(dataset(1), [{"id": "q000", "pass": "false"}])
        self.assertIn("布尔", ctx.exception.render())


class PassAtKTests(unittest.TestCase):
    def test_fm05_k_mismatch_rejected(self):
        """FM-05 候选 pass@1 vs 基线 pass@5：必须拒绝比较。"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            ds = dataset(40)
            cand = [{"id": item["id"], "pass": True, "k": 1} for item in ds]
            base = [{"id": item["id"], "pass": True, "k": 5} for item in ds]
            with self.assertRaises(EvalGateError) as ctx:
                _run_gate_in_tmp(tmp_path, ds=ds, cand=cand, base=base)
            self.assertIn("pass@1", str(ctx.exception))

    def test_fm05_same_k_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            ds = dataset(40)
            cand = [{"id": item["id"], "pass": True, "k": 3} for item in ds]
            base = [{"id": item["id"], "pass": True, "k": 3} for item in ds]
            result = _run_gate_in_tmp(tmp_path, ds=ds, cand=cand, base=base)
            self.assertEqual(result["verdict"]["verdict"], "PASS")


class ScorerTests(unittest.TestCase):
    def test_fm20_scorer_change_is_review(self):
        """FM-20 换了判分器版本：delta 不可归因给模型。"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            ds = [{"id": f"j{index:03d}", "family": f"f{index % 3}",
                   "input": f"题 {index}", "reference": "参考"} for index in range(480)]
            cand = [{"id": item["id"], "pass": index < 403,
                     "scorer_version": "judge-v2"} for index, item in enumerate(ds)]
            base = [{"id": item["id"], "pass": index < 427,
                     "scorer_version": "judge-v1"} for index, item in enumerate(ds)]
            result = _run_gate_in_tmp(tmp_path, ds=ds, cand=cand, base=base)
            verdict = result["verdict"]
            self.assertEqual(verdict["verdict"], "REVIEW")
            self.assertIn("scorer_changed", verdict["flags"])
            gate = {g["id"]: g for g in verdict["gates"]}["G2-regression"]
            self.assertEqual(gate["result"], "not_comparable")

    def test_fm07_external_scorer_instability_is_not_detected(self):
        """FM-07 判分器不稳定：G7 只标记 skipped，无法发现抖动（已知未防护）。"""
        result = evaluate(candidate_rows=rows(480, 470), baseline_rows=rows(480, 470),
                          config=dict(FAST), run_id="t", layers=LAYERS)
        gate = {g["id"]: g for g in result["gates"]}["G7-stability"]
        self.assertEqual(gate["result"], "skipped")
        self.assertEqual(result["verdict"], "PASS")


class InvisibleRiskTests(unittest.TestCase):
    def test_fm02_label_noise_is_invisible(self):
        """FM-02 标签噪声：对称翻转 10% 的标签，判决仍 PASS（已知未防护）。"""
        clean = rows(480, 480)
        noisy = rows(480, 432)  # 48 条样本标签被翻错
        result = evaluate(candidate_rows=noisy, baseline_rows=noisy,
                          config=dict(FAST), run_id="t", layers=LAYERS)
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["delta"]["ci95"], [0.0, 0.0])
        self.assertEqual(clean[0]["pass"], True)

    def test_fm04_difficulty_drift_is_invisible(self):
        """FM-04 基线来自旧版更容易的数据集：id 相同即可配对（已知未防护）。"""
        cand = rows(480, 480, prefix="a", families=1)
        base = rows(480, 384, prefix="a", families=1)
        result = evaluate(candidate_rows=cand, baseline_rows=base,
                          config=dict(FAST), run_id="t", layers=LAYERS)
        self.assertEqual(result["metrics"]["overlap"], 1.0)
        self.assertEqual(result["verdict"], "PASS")


class VersionContractTests(unittest.TestCase):
    def _make_run(self, tmp_path: pathlib.Path) -> pathlib.Path:
        ds = [{"id": f"v{index:03d}", "family": "f", "input": f"题 {index}",
               "reference": "参考"} for index in range(480)]
        cand = [{"id": item["id"], "pass": index < 400} for index, item in enumerate(ds)]
        base = [{"id": item["id"], "pass": index < 400} for index, item in enumerate(ds)]
        result = _run_gate_in_tmp(tmp_path, ds=ds, cand=cand, base=base)
        return pathlib.Path(result["run_dir"])

    def test_fm13_rules_version_mismatch_is_incomplete(self):
        """FM-13 跨版本不可比：rules_version 变了，verify 不得 PASS。"""
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._make_run(pathlib.Path(tmp))
            meta = read_json(run_dir / "run.json")
            meta["rules_version"] = "0" * 16
            write_json(run_dir / "run.json", meta)
            verified = verify_run(run_dir)
            self.assertEqual(verified["verdict"]["verdict"], "INCOMPLETE")
            self.assertTrue(any("rules_version" in p for p in verified["problems"]))

    def test_fm15_schema_version_mismatch_is_incomplete(self):
        """FM-15 schema 版本不匹配：旧/未来版本 run.json 不能当本版本证据。"""
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._make_run(pathlib.Path(tmp))
            meta = read_json(run_dir / "run.json")
            meta["schema_version"] = "2.0.0"
            write_json(run_dir / "run.json", meta)
            verified = verify_run(run_dir)
            self.assertEqual(verified["verdict"]["verdict"], "INCOMPLETE")
            self.assertTrue(any("schema_version" in p for p in verified["problems"]))

    def test_fm14_missing_inputs_config_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._make_run(pathlib.Path(tmp))
            meta = read_json(run_dir / "run.json")
            del meta["inputs"]["config"]
            write_json(run_dir / "run.json", meta)
            verified = verify_run(run_dir)
            self.assertTrue(any("inputs.config" in p for p in verified["problems"]))


if __name__ == "__main__":
    unittest.main()
