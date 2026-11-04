import json
import pathlib
import tempfile
import unittest

from eval_gate.contract import (read_jsonl, sha256_file, sha256_text,
                                validate_instance, write_jsonl)
from eval_gate.errors import EvalGateError

HERE = pathlib.Path(__file__).resolve().parent.parent


def valid_run() -> dict:
    return {
        "schema_version": "1.0.0",
        "run_id": "pr-abc-12345678",
        "created_utc": "2026-11-03T00:00:00+00:00",
        "rules_version": "a" * 16,
        "scorer_version": "b" * 16,
        "tool_digests": {},
        "repos": {
            "mcp-guard": {"path": "vendor:/x", "commit": "unknown"},
            "auditable-llm-eval": {"path": "vendor:/y", "commit": "unknown"},
        },
        "inputs": {
            "dataset_sha256": "c" * 64,
            "predictions_sha256": "d" * 64,
            "baseline_predictions_sha256": "e" * 64,
            "rubric_sha256": "f" * 64,
            "head_sha": "unknown",
            "changed_files": [],
            "config": {"min_pass": 0.8, "max_regression": 0.03, "min_n": 400,
                       "alpha": 0.05, "bootstrap_iters": 10000, "seed": 20261103},
        },
        "evidence_manifest": {"evidence/per_item.jsonl": "1" * 64},
        "layers": {"input_guard": "absent", "output_audit": "present",
                   "attack_simulation": "absent"},
    }


def valid_verdict() -> dict:
    return {
        "schema_version": "1.0.0",
        "run_id": "pr-abc-12345678",
        "verdict": "PASS",
        "severity": "info",
        "primary_metric": {"name": "rubric_pass_rate", "value": 0.9,
                           "ci95": [0.87, 0.92], "n": 480},
        "baseline": {"name": "rubric_pass_rate", "value": 0.88,
                     "ci95": [0.85, 0.90], "n": 480},
        "delta": {"value": 0.02, "ci95": [0.001, 0.04], "n": 480, "comparable": True},
        "gates": [{"id": "G1-absolute", "rule": "r", "observed": 0.87, "result": "pass"}],
        "layers": {"input_guard": "absent", "output_audit": "present"},
        "attribution": "attribution.md",
        "why": "ok",
        "flags": [],
    }


class RunSchemaTests(unittest.TestCase):
    def test_valid_run_has_no_errors(self):
        self.assertEqual(validate_instance(valid_run(), "run.schema.json"), [])

    def test_missing_required_field(self):
        broken = valid_run()
        del broken["run_id"]
        errors = validate_instance(broken, "run.schema.json")
        self.assertTrue(any("run_id" in error for error in errors))

    def test_bad_sha_pattern(self):
        broken = valid_run()
        broken["inputs"]["dataset_sha256"] = "not-a-sha"
        errors = validate_instance(broken, "run.schema.json")
        self.assertTrue(any("dataset_sha256" in error for error in errors))

    def test_unknown_layer_rejected(self):
        broken = valid_run()
        broken["layers"]["input_guard"] = "maybe"
        self.assertNotEqual(validate_instance(broken, "run.schema.json"), [])

    def test_real_fixture_run_meta_validates(self):
        self.assertTrue((HERE / "eval_gate" / "demo_data" / "dataset.jsonl").exists())
        self.assertEqual(validate_instance(valid_run(), "run.schema.json"), [])


class VerdictSchemaTests(unittest.TestCase):
    def test_valid_verdict_has_no_errors(self):
        self.assertEqual(validate_instance(valid_verdict(), "verdict.schema.json"), [])

    def test_invalid_verdict_enum(self):
        broken = valid_verdict()
        broken["verdict"] = "OK"
        errors = validate_instance(broken, "verdict.schema.json")
        self.assertTrue(any("枚举" in error or "OK" in error for error in errors))

    def test_gate_result_enum(self):
        broken = valid_verdict()
        broken["gates"][0]["result"] = "maybe"
        self.assertNotEqual(validate_instance(broken, "verdict.schema.json"), [])


class IOTests(unittest.TestCase):
    def test_read_jsonl_skips_blank_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "x.jsonl"
            path.write_text('{"a": 1}\n\n{"a": 2}\n', encoding="utf-8")
            self.assertEqual(read_jsonl(path), [{"a": 1}, {"a": 2}])

    def test_read_jsonl_reports_line_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "bad.jsonl"
            path.write_text('{"a": 1}\nnope\n', encoding="utf-8")
            with self.assertRaises(EvalGateError) as ctx:
                read_jsonl(path)
            self.assertIn("第 2 行", str(ctx.exception))
            self.assertIn("next:", ctx.exception.render())

    def test_sha256_is_stable(self):
        self.assertEqual(sha256_text("中文"), sha256_text("中文"))
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "a.txt"
            path.write_text("中文", encoding="utf-8")
            self.assertEqual(sha256_file(path), sha256_text("中文"))

    def test_write_jsonl_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "x.jsonl"
            write_jsonl(path, [{"b": 2, "a": 1}])
            first = path.read_text(encoding="utf-8")
            write_jsonl(path, [{"a": 1, "b": 2}])
            self.assertEqual(first, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
