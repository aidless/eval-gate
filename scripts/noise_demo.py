"""同一批预测，换样本量，观察判决会不会“横跳”。

用途：给 docs/why.md 与文章提供可复跑的数字。不是新功能，只是把
`eval_gate.runner.run_gate` 在一个固定数据源上反复调用。

跑法：python3 scripts/noise_demo.py
"""
from __future__ import annotations

import json
import pathlib
import random
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval_gate.contract import read_jsonl, write_jsonl
from eval_gate.runner import run_gate

DEMO = ROOT / "eval_gate" / "demo_data"
SCENARIO = DEMO / "scenarios" / "p2_regression"
SEEDS = 20
SAMPLE_N = 40


def _by_id(path: pathlib.Path) -> dict[str, dict]:
    return {row["id"]: row for row in read_jsonl(path)}


def main() -> int:
    dataset = _by_id(DEMO / "dataset.jsonl")
    candidate = _by_id(SCENARIO / "predictions.jsonl")
    baseline = _by_id(SCENARIO / "baseline_predictions.jsonl")
    ids = sorted(set(dataset) & set(candidate) & set(baseline))

    def run_subset(subset_ids: list[str], out: pathlib.Path, min_n: int,
                   max_ci_width: float) -> dict:
        write_jsonl(out / "dataset.jsonl", [dataset[i] for i in subset_ids])
        write_jsonl(out / "candidate.jsonl", [candidate[i] for i in subset_ids])
        write_jsonl(out / "baseline.jsonl", [baseline[i] for i in subset_ids])
        return run_gate(
            dataset_path=out / "dataset.jsonl",
            predictions_path=out / "candidate.jsonl",
            baseline_predictions_path=out / "baseline.jsonl",
            out_dir=out / "run",
            config={"bootstrap_iters": 2000, "min_n": min_n, "max_ci_width": max_ci_width},
            run_id="noise-demo",
        )["verdict"]

    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        full = run_subset(ids, root / "full", 400, 0.12)
        print(f"full n={len(ids)}: verdict={full['verdict']} "
              f"delta={full['delta']['value']:+.4f} "
              f"delta_ci=[{full['delta']['ci95'][0]:+.4f}, {full['delta']['ci95'][1]:+.4f}]")

        for label, min_n, width in (("gate-default", 400, 0.12), ("forced-decide", 40, 1.0)):
            verdicts, deltas = [], []
            for seed in range(SEEDS):
                rng = random.Random(20261103 + seed)
                subset = sorted(rng.sample(ids, SAMPLE_N))
                verdict = run_subset(subset, root / f"{label}-{seed}", min_n, width)
                verdicts.append(verdict["verdict"])
                deltas.append(verdict["delta"]["value"])
            flipped = len(set(verdicts))
            print(f"{label} n={SAMPLE_N} x{SEEDS}: verdicts={sorted(set(verdicts))} "
                  f"flipped={flipped > 1} delta_range=[{min(deltas):+.4f}, {max(deltas):+.4f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
