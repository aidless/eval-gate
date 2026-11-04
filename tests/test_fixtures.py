import json
import pathlib
import tempfile
import unittest

from eval_gate.cli import main

HERE = pathlib.Path(__file__).resolve().parent.parent
DEMO_DATA = HERE / "eval_gate" / "demo_data"


class FixtureTests(unittest.TestCase):
    def test_dataset_shape(self):
        rows = [json.loads(line) for line in
                (DEMO_DATA / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()]
        self.assertEqual(len(rows), 480)
        self.assertEqual(len({row["id"] for row in rows}), 480)
        self.assertEqual(len({row["family"] for row in rows}), 20)

    def test_demo_five_of_five(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = main(["demo", "--fixtures", str(DEMO_DATA),
                         "--out", tmp, "--iterations", "10000"])
            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
