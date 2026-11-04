"""CLI 契约测试：退出码、可行动报错、JSON 输出、demo 自校验。"""
import contextlib
import io
import json
import pathlib
import shutil
import tempfile
import unittest

from eval_gate.cli import main
from eval_gate.contract import write_jsonl

HERE = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = HERE / "eval_gate" / "demo_data"
SCENARIOS = FIXTURES / "scenarios"


def call(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def run_args(name: str, out_dir: pathlib.Path, *extra: str) -> list[str]:
    scenario = SCENARIOS / name
    return ["run",
            "--dataset", str(FIXTURES / "dataset.jsonl"),
            "--predictions", str(scenario / "predictions.jsonl"),
            "--baseline-predictions", str(scenario / "baseline_predictions.jsonl"),
            "--out", str(out_dir),
            "--iterations", "2000",
            *extra]


class ExitCodeTests(unittest.TestCase):
    def test_pass_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = call(run_args("p1_pass", pathlib.Path(tmp) / "run", "--json"))
        self.assertEqual(code, 0)
        self.assertIn("verdict=PASS", out)
        payload, _ = json.JSONDecoder().raw_decode(out[out.index("{"):])
        self.assertIn("alpha_adjust", payload["metrics"])

    def test_block_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, _ = call(run_args("p2_regression", pathlib.Path(tmp) / "run"))
        self.assertEqual(code, 1)

    def test_fail_on_review_blocks_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            # n=120 的代码题场景在默认配置下判 REVIEW
            scenario = SCENARIOS / "p7_code_hidden"
            code, out, _ = call([
                "run", "--dataset", str(scenario / "dataset.jsonl"),
                "--predictions", str(scenario / "predictions.jsonl"),
                "--baseline-predictions", str(scenario / "baseline_predictions.jsonl"),
                "--out", str(pathlib.Path(tmp) / "run"),
                "--iterations", "2000", "--fail-on", "review"])
        self.assertEqual(code, 1)
        self.assertIn("verdict=REVIEW", out)

    def test_fail_on_never_always_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, _ = call(run_args("p2_regression", pathlib.Path(tmp) / "run",
                                       "--fail-on", "never"))
        self.assertEqual(code, 0)

    def test_verify_tampered_evidence_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = pathlib.Path(tmp) / "run"
            call(run_args("p1_pass", out_dir))
            (out_dir / "evidence" / "per_item.jsonl").write_text("{}\n", encoding="utf-8")
            code, stdout, stderr = call(["verify", "--run-dir", str(out_dir)])
        self.assertEqual(code, 1)
        self.assertIn("problem", stderr)
        self.assertIn("INCOMPLETE", stdout)


class ActionableErrorTests(unittest.TestCase):
    def test_duplicate_input_returns_two_not_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            bad_ds = tmp_path / "bad.jsonl"
            write_jsonl(bad_ds, [
                {"id": "a", "family": "f", "input": "同一道题"},
                {"id": "b", "family": "f", "input": "同一道题"},
            ])
            preds = tmp_path / "p.jsonl"
            write_jsonl(preds, [])
            code, _, stderr = call([
                "run", "--dataset", str(bad_ds), "--predictions", str(preds),
                "--baseline-predictions", str(preds), "--out", str(tmp_path / "run")])
        self.assertEqual(code, 2)
        self.assertIn("error:", stderr)
        self.assertIn("next:", stderr)
        self.assertNotIn("Traceback", stderr)

    def test_bad_threshold_returns_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, stderr = call(run_args("p1_pass", pathlib.Path(tmp) / "run",
                                            "--max-regression", "3"))
        self.assertEqual(code, 2)
        self.assertIn("0.03", stderr)

    def test_missing_dataset_returns_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, stderr = call([
                "run", "--dataset", str(pathlib.Path(tmp) / "nope.jsonl"),
                "--predictions", str(SCENARIOS / "p1_pass" / "predictions.jsonl"),
                "--baseline-predictions",
                str(SCENARIOS / "p1_pass" / "baseline_predictions.jsonl"),
                "--out", str(pathlib.Path(tmp) / "run")])
        self.assertEqual(code, 2)
        self.assertIn("next:", stderr)


class DemoContractTests(unittest.TestCase):
    def test_quickstart_matches_expected(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = call(["quickstart", "--out", tmp, "--iterations", "2000"])
        self.assertEqual(code, 0)
        self.assertIn("4/4 符合预期", out)

    def test_each_scenario_has_expected_numbers(self):
        for folder in sorted((FIXTURES / "scenarios").iterdir()):
            scenario = json.loads((folder / "scenario.json").read_text(encoding="utf-8"))
            expected = scenario["expected"]
            self.assertTrue("verdict" in expected or "error_contains" in expected,
                            folder.name)

    def test_scenario_datasets_are_unique(self):
        for folder in sorted((FIXTURES / "scenarios").iterdir()):
            scenario = json.loads((folder / "scenario.json").read_text(encoding="utf-8"))
            dataset = FIXTURES / scenario.get("dataset", "dataset.jsonl")
            rows = [json.loads(line) for line in
                    dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
            inputs = [" ".join(row["input"].split()).lower() for row in rows]
            self.assertEqual(len(inputs), len(set(inputs)), folder.name)

    def test_demo_can_run_from_copied_fixtures(self):
        """示例数据不依赖源码树：复制到别处也能跑（证明 wheel 自带数据可用）。"""
        with tempfile.TemporaryDirectory() as tmp:
            copied = pathlib.Path(tmp) / "fixtures"
            shutil.copytree(FIXTURES, copied)
            code, out, _ = call(["demo", "--fixtures", str(copied),
                                 "--out", str(pathlib.Path(tmp) / "runs"),
                                 "--iterations", "1000"])
        self.assertEqual(code, 0)
        self.assertIn("10/10 符合预期", out)


if __name__ == "__main__":
    unittest.main()
