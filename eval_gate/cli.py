"""命令行入口。

    python3 -m eval_gate.cli run --dataset ... --predictions ... \
        --baseline-predictions ... --out runs/pr-1
    python3 -m eval_gate.cli verify --run-dir runs/pr-1
    python3 -m eval_gate.cli demo --fixtures fixtures --out runs/demo

退出码约定：
    --fail-on block  （默认）BLOCK / FAIL / INCOMPLETE -> 1
    --fail-on review BLOCK / FAIL / INCOMPLETE / REVIEW -> 1
    --fail-on never  总是 0
REVIEW 在默认模式下不阻断，但会打印警告；INCOMPLETE 默认非零——缺证据不是通过。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys

from .gate import DEFAULT_CONFIG
from .runner import run_gate, verify_run

_NON_PASS = {"BLOCK", "FAIL", "INCOMPLETE"}


def _fmt_ci(ci) -> str:
    return f"[{ci[0]:.4f}, {ci[1]:.4f}]"


def _verdict_line(verdict: dict) -> str:
    m = verdict["primary_metric"]
    d = verdict["delta"]
    return (f"verdict={verdict['verdict']} pass_rate={m['value']:.4f} "
            f"ci={_fmt_ci(m['ci95'])} delta={d['value']:+.4f} "
            f"delta_ci={_fmt_ci(d['ci95'])} n={m['n']} "
            f"run_id={verdict['run_id']}")


def _emit_github_output(path: str | None, verdict: dict) -> None:
    if not path:
        return
    m = verdict["primary_metric"]
    lines = [
        f"verdict={verdict['verdict']}",
        f"pass-rate={m['value']:.6f}",
        f"pass-rate-ci={_fmt_ci(m['ci95'])}",
        f"delta={verdict['delta']['value']:+.6f}",
        f"delta-ci={_fmt_ci(verdict['delta']['ci95'])}",
        f"n={m['n']}",
        f"run-id={verdict['run_id']}",
        "attribution-path=attribution.md",
    ]
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _exit_code(verdict: dict, fail_on: str) -> int:
    if fail_on == "never":
        return 0
    if fail_on == "review":
        return 1 if verdict["verdict"] in {"BLOCK", "FAIL", "INCOMPLETE", "REVIEW"} else 0
    return 1 if verdict["verdict"] in _NON_PASS else 0


def cmd_run(args) -> int:
    if args.rubric:
        print(f"[warn] MVP 只支持内置 rubric（support-qa-zh）；已忽略 {args.rubric}",
              file=sys.stderr)
    config = {
        "min_pass": args.min_pass,
        "max_regression": args.max_regression,
        "min_n": args.min_n,
        "alpha": args.alpha,
        "bootstrap_iters": args.iterations,
        "seed": args.seed,
        "max_ci_width": args.max_ci_width,
        "min_overlap": args.min_overlap,
    }
    result = run_gate(
        dataset_path=args.dataset,
        predictions_path=args.predictions,
        baseline_predictions_path=args.baseline_predictions,
        out_dir=args.out,
        tools_path=args.tools,
        tool_snapshot_path=args.tool_snapshot,
        changed_files=args.changed_files,
        head_sha=args.head_sha,
        config=config,
        run_id=args.run_id,
    )
    verdict = result["verdict"]
    print(_verdict_line(verdict))
    if args.json:
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
    for gate in verdict["gates"]:
        if gate["result"] == "fail":
            print(f"  - {gate['id']}: {gate.get('detail', gate['rule'])}", file=sys.stderr)
    print(f"attribution: {pathlib.Path(result['run_dir']) / 'attribution.md'}")
    _emit_github_output(args.github_output, verdict)
    return _exit_code(verdict, args.fail_on)


def cmd_verify(args) -> int:
    result = verify_run(args.run_dir)
    verdict = result["verdict"]
    print(_verdict_line(verdict))
    if args.json:
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
    for problem in result["problems"]:
        print(f"  - problem: {problem}", file=sys.stderr)
    print(f"verify: {len(result['problems'])} 个问题；verdict={verdict['verdict']}",
          file=sys.stderr)
    _emit_github_output(args.github_output, verdict)
    return _exit_code(verdict, args.fail_on)


def cmd_demo(args) -> int:
    fixtures = pathlib.Path(args.fixtures).resolve()
    out_root = pathlib.Path(args.out).resolve()
    dataset = fixtures / "dataset.jsonl"
    rows = []
    ok = True
    for scenario_path in sorted((fixtures / "scenarios").glob("*/scenario.json")):
        scenario_dir = scenario_path.parent
        scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
        name = scenario.get("name", scenario_dir.name)
        run_dir = out_root / name
        if run_dir.exists():
            shutil.rmtree(run_dir)
        result = run_gate(
            dataset_path=dataset,
            predictions_path=scenario_dir / scenario["predictions"],
            baseline_predictions_path=scenario_dir / scenario["baseline_predictions"],
            out_dir=run_dir,
            tools_path=scenario_dir / scenario["tools"] if scenario.get("tools") else None,
            tool_snapshot_path=(scenario_dir / scenario["tool_snapshot"]
                                if scenario.get("tool_snapshot") else None),
            changed_files=scenario.get("changed_files", []),
            head_sha=scenario.get("head_sha", "unknown"),
            config={"bootstrap_iters": args.iterations,
                    "seed": DEFAULT_CONFIG["seed"]},
            run_id=name,
        )
        verdict = result["verdict"]

        post = scenario.get("post")
        if post:
            if post.startswith("delete:"):
                target = run_dir / post.split(":", 1)[1]
                if target.exists():
                    target.unlink()
            verified = verify_run(run_dir)
            verdict = verified["verdict"]
            for problem in verified["problems"]:
                print(f"[{name}] verify problem: {problem}", file=sys.stderr)

        expected = scenario["expected"]["verdict"]
        passed = verdict["verdict"] == expected
        ok = ok and passed
        rows.append({
            "name": name,
            "expected": expected,
            "actual": verdict["verdict"],
            "result": "OK" if passed else "MISMATCH",
            "pass_rate": verdict["primary_metric"]["value"],
            "delta": verdict["delta"]["value"],
        })
        print(f"[{name}] expected={expected} actual={verdict['verdict']} "
              f"pass_rate={verdict['primary_metric']['value']:.4f} "
              f"delta={verdict['delta']['value']:+.4f}")

    print("\n示例仓判决：")
    print("| 场景 | 预期 | 实际 | 结果 | 通过率 | delta |")
    print("|---|---|---|---|---|---|")
    for row in rows:
        print(f"| {row['name']} | {row['expected']} | {row['actual']} | {row['result']} "
              f"| {row['pass_rate']:.4f} | {row['delta']:+.4f} |")
    print(f"\n{sum(1 for r in rows if r['result'] == 'OK')}/{len(rows)} 符合预期")
    return 0 if ok else 1


def _add_common(parser) -> None:
    parser.add_argument("--fail-on", choices=["block", "review", "never"], default="block")
    parser.add_argument("--github-output", default=None,
                        help="写入 GitHub Actions $GITHUB_OUTPUT 的路径")
    parser.add_argument("--json", action="store_true", help="额外打印完整 verdict JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eval-gate")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="跑一次门禁并写证据/判决")
    run.add_argument("--dataset", required=True)
    run.add_argument("--predictions", required=True)
    run.add_argument("--baseline-predictions", required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--tools", default=None)
    run.add_argument("--tool-snapshot", default=None)
    run.add_argument("--changed-files", nargs="*", default=[])
    run.add_argument("--head-sha", default="unknown")
    run.add_argument("--run-id", default=None)
    run.add_argument("--rubric", default=None,
                     help="MVP 只支持内置 rubric；自定义 rubric 预留到 v0.2")
    run.add_argument("--min-pass", type=float, default=0.80)
    run.add_argument("--max-regression", type=float, default=0.03)
    run.add_argument("--min-n", type=int, default=400)
    run.add_argument("--alpha", type=float, default=0.05)
    run.add_argument("--iterations", type=int, default=10_000)
    run.add_argument("--seed", type=int, default=20261103)
    run.add_argument("--max-ci-width", type=float, default=0.12)
    run.add_argument("--min-overlap", type=float, default=0.80)
    run.set_defaults(func=cmd_run)
    _add_common(run)

    verify = sub.add_parser("verify", help="只读证据重算判决")
    verify.add_argument("--run-dir", required=True)
    verify.set_defaults(func=cmd_verify)
    _add_common(verify)

    demo = sub.add_parser("demo", help="跑示例仓 5 个场景并断言预期判决")
    demo.add_argument("--fixtures", default="fixtures")
    demo.add_argument("--out", default="runs/demo")
    demo.add_argument("--iterations", type=int, default=10_000)
    demo.set_defaults(func=cmd_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
