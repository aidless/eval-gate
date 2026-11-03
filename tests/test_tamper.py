"""防篡改：删证据 / 改证据 / 改判决，都不能变成 PASS。"""
import json
import pathlib
import shutil
import tempfile
import unittest

from eval_gate.contract import write_json
from eval_gate.runner import run_gate, verify_run

HERE = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = HERE / "fixtures"


def run_scenario(out_dir: pathlib.Path, name: str, iterations: int = 500) -> dict:
    scenario_dir = FIXTURES / "scenarios" / name
    scenario = json.loads((scenario_dir / "scenario.json").read_text(encoding="utf-8"))
    return run_gate(
        dataset_path=FIXTURES / "dataset.jsonl",
        predictions_path=scenario_dir / scenario["predictions"],
        baseline_predictions_path=scenario_dir / scenario["baseline_predictions"],
        out_dir=out_dir,
        tools_path=scenario_dir / scenario["tools"] if scenario.get("tools") else None,
        tool_snapshot_path=(scenario_dir / scenario["tool_snapshot"]
                            if scenario.get("tool_snapshot") else None),
        changed_files=scenario.get("changed_files", []),
        config={"bootstrap_iters": iterations},
        run_id=name,
    )["verdict"]


class TamperTests(unittest.TestCase):
    def test_deleting_candidate_evidence_never_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "p1"
            self.assertEqual(run_scenario(out, "p1_pass")["verdict"], "PASS")
            (out / "evidence" / "per_item.jsonl").unlink()
            verified = verify_run(out)["verdict"]
            self.assertEqual(verified["verdict"], "INCOMPLETE")
            self.assertNotEqual(verified["verdict"], "PASS")

    def test_deleting_evidence_does_not_downgrade_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "p2"
            self.assertEqual(run_scenario(out, "p2_regression")["verdict"], "BLOCK")
            (out / "evidence" / "per_item.jsonl").unlink()
            verified = verify_run(out)["verdict"]
            self.assertEqual(verified["verdict"], "BLOCK")

    def test_tampered_evidence_hash_is_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "p1"
            run_scenario(out, "p1_pass")
            path = out / "evidence" / "per_item.jsonl"
            path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            verified = verify_run(out)["verdict"]
            self.assertEqual(verified["verdict"], "INCOMPLETE")

    def test_tampered_verdict_json_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "p2"
            run_scenario(out, "p2_regression")
            path = out / "verdict.json"
            verdict = json.loads(path.read_text(encoding="utf-8"))
            verdict["verdict"] = "PASS"
            verdict["severity"] = "info"
            write_json(path, verdict)
            verified = verify_run(out)["verdict"]
            self.assertNotEqual(verified["verdict"], "PASS")

    def test_deleting_whole_evidence_dir_is_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "p1"
            run_scenario(out, "p1_pass")
            shutil.rmtree(out / "evidence")
            verified = verify_run(out)["verdict"]
            self.assertEqual(verified["verdict"], "INCOMPLETE")

    def test_missing_run_meta_is_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = pathlib.Path(tmp)
            verified = verify_run(empty)["verdict"]
            self.assertEqual(verified["verdict"], "INCOMPLETE")
            self.assertEqual(verified["primary_metric"]["n"], 0)

    def test_deleting_baseline_evidence_is_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "p1"
            run_scenario(out, "p1_pass")
            (out / "evidence" / "baseline_per_item.jsonl").unlink()
            verified = verify_run(out)["verdict"]
            self.assertEqual(verified["verdict"], "INCOMPLETE")


if __name__ == "__main__":
    unittest.main()
