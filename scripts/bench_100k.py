"""实测 10 万样本做一次判决的耗时（不是估算）。

    python3 scripts/bench_100k.py [n]

默认 n=100000，使用默认配置（bootstrap_iters=10000）。
此时 iterations × n = 1e9 > MAX_BOOTSTRAP_WORK，auto 会切到分层正态近似。
"""
import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from eval_gate.gate import DEFAULT_CONFIG, evaluate  # noqa: E402


def make_rows(n: int, passes: int) -> list[dict]:
    return [
        {
            "id": f"q{index:06d}",
            "family": f"f{index % 50}",
            "pass": index < passes,
            "l1_failures": [],
            "naive_pass": index < passes,
            "dimensions": {"complete": 2},
        }
        for index in range(n)
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("n", nargs="?", type=int, default=100_000)
    args = parser.parse_args()

    candidate = make_rows(args.n, int(args.n * 0.90))
    baseline = make_rows(args.n, int(args.n * 0.88))

    start = time.perf_counter()
    verdict = evaluate(
        candidate_rows=candidate,
        baseline_rows=baseline,
        config=DEFAULT_CONFIG,
        run_id="bench",
        layers={"input_guard": "absent", "output_audit": "present",
                "attack_simulation": "absent"},
    )
    elapsed = time.perf_counter() - start

    print(f"n={args.n}")
    print(f"method={verdict['delta']['method']}")
    print(f"iterations={verdict['delta']['iterations']}")
    print(f"verdict={verdict['verdict']}")
    print(f"pass_rate={verdict['primary_metric']['value']:.6f} "
          f"delta={verdict['delta']['value']:+.6f}")
    print(f"delta_ci={verdict['delta']['ci95']}")
    print(f"mde={verdict['delta']['mde']:.6f}")
    print(f"elapsed={elapsed:.4f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
