"""命令行入口。

    python3 -m eval_gate.cli run --dataset ... --predictions ... \
        --baseline-predictions ... --out runs/pr-1
    python3 -m eval_gate.cli verify --run-dir runs/pr-1
    python3 -m eval_gate.cli quickstart
    python3 -m eval_gate.cli demo

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
import time
from collections.abc import Sequence
from importlib import resources
from typing import Any

from .errors import EvalGateError
from .gate import DEFAULT_CONFIG
from .runner import run_gate, verify_run

_NON_PASS = {"BLOCK", "FAIL", "INCOMPLETE"}


def _fmt_ci(ci: Sequence[float]) -> str:
    return f"[{ci[0]:.4f}, {ci[1]:.4f}]"


def _verdict_line(verdict: dict[str, Any]) -> str:
    m = verdict["primary_metric"]
    d = verdict["delta"]
    return (f"verdict={verdict['verdict']} pass_rate={m['value']:.4f} "
            f"ci={_fmt_ci(m['ci95'])} delta={d['value']:+.4f} "
            f"delta_ci={_fmt_ci(d['ci95'])} n={m['n']} "
            f"run_id={verdict['run_id']}")


def _emit_github_output(path: str | None, verdict: dict[str, Any]) -> None:
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


def _exit_code(verdict: dict[str, Any], fail_on: str) -> int:
    if fail_on == "never":
        return 0
    if fail_on == "review":
        return 1 if verdict["verdict"] in {"BLOCK", "FAIL", "INCOMPLETE", "REVIEW"} else 0
    return 1 if verdict["verdict"] in _NON_PASS else 0


def cmd_run(args: argparse.Namespace) -> int:
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
        "ci_method": args.ci_method,
        "alpha_adjust": args.alpha_adjust,
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


def cmd_verify(args: argparse.Namespace) -> int:
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


QUICKSTART_SCENARIOS = ("p1_pass", "p2_regression", "p3_false_green", "p4_tool_drift")


def _bundled_fixtures() -> pathlib.Path:
    """安装后也能找到随包分发的示例数据（wheel 里包含 demo_data/）。"""
    return pathlib.Path(str(resources.files("eval_gate").joinpath("demo_data")))


def _run_demo(fixtures: pathlib.Path, out_root: pathlib.Path, iterations: int,
              names: tuple[str, ...] | None = None,
              ) -> tuple[bool, list[dict[str, Any]]]:
    """跑场景并核对 scenario.json 里的 expected（判决/通过率/delta/预期报错）。

    expected.delta 的容差是 0.005：quickstart 用 2000 次 bootstrap、demo 用 10000 次，
    两者会有千分位差异；pass_rate 是确定值，容差 1e-4。
    """
    rows: list[dict[str, Any]] = []
    ok = True
    scenario_dirs = [fixtures / "scenarios" / name for name in names] if names else \
        sorted((fixtures / "scenarios").iterdir())
    for scenario_dir in scenario_dirs:
        scenario_path = scenario_dir / "scenario.json"
        if not scenario_path.exists():
            raise EvalGateError(
                f"找不到示例场景：{scenario_path}",
                hint="用 --fixtures 指向包含 scenarios/ 的目录；安装版自带 demo_data",
            )
        scenario_dir = scenario_path.parent
        scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
        name = scenario.get("name", scenario_dir.name)
        dataset = fixtures / scenario["dataset"] if scenario.get("dataset") \
            else fixtures / "dataset.jsonl"
        expected = scenario["expected"]
        run_dir = out_root / name
        if run_dir.exists():
            shutil.rmtree(run_dir)

        try:
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
                config={"bootstrap_iters": iterations,
                        "seed": DEFAULT_CONFIG["seed"],
                        "alpha_adjust": scenario.get("alpha_adjust", "none")},
                run_id=name,
            )
        except EvalGateError as exc:
            needle = expected.get("error_contains")
            if not needle:
                raise
            passed = needle in str(exc)
            ok = ok and passed
            rows.append({"name": name, "expected": f"error[{needle}]",
                         "actual": "ERROR", "result": "OK" if passed else "MISMATCH",
                         "pass_rate": None, "delta": None,
                         "note": scenario.get("note", "")})
            print(f"[{name}] expected=error contains={needle!r} "
                  f"actual=ERROR result={'OK' if passed else 'MISMATCH'}")
            print(f"  {exc.render().splitlines()[0]}")
            continue

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

        actual = verdict["verdict"]
        rate = verdict["primary_metric"]["value"]
        delta = verdict["delta"]["value"]
        checks = []
        if "verdict" in expected:
            checks.append(actual == expected["verdict"])
        if "pass_rate" in expected:
            checks.append(abs(rate - float(expected["pass_rate"])) <= 1e-4)
        if "delta" in expected:
            checks.append(abs(delta - float(expected["delta"])) <= 0.005)
        passed = all(checks)
        ok = ok and passed
        rows.append({
            "name": name,
            "expected": expected.get("verdict", "-"),
            "actual": actual,
            "result": "OK" if passed else "MISMATCH",
            "pass_rate": rate,
            "delta": delta,
            "note": scenario.get("note", ""),
        })
        print(f"[{name}] expected={expected.get('verdict', '-')} actual={actual} "
              f"pass_rate={rate:.4f} delta={delta:+.4f}")

    print("\n示例仓判决：")
    print("| 场景 | 预期 | 实际 | 结果 | 通过率 | delta |")
    print("|---|---|---|---|---|---|")
    for row in rows:
        rate = "-" if row["pass_rate"] is None else f"{row['pass_rate']:.4f}"
        delta = "-" if row["delta"] is None else f"{row['delta']:+.4f}"
        print(f"| {row['name']} | {row['expected']} | {row['actual']} | {row['result']} "
              f"| {rate} | {delta} |")
    print(f"\n{sum(1 for r in rows if r['result'] == 'OK')}/{len(rows)} 符合预期")
    return ok, rows


def cmd_demo(args: argparse.Namespace) -> int:
    fixtures = pathlib.Path(args.fixtures).resolve() if args.fixtures else _bundled_fixtures()
    ok, rows = _run_demo(fixtures, pathlib.Path(args.out).resolve(), args.iterations)
    print("\n每个场景的判决与证据都在 --out 目录：run.json / verdict.json / attribution.md")
    return 0 if ok else 1


def cmd_quickstart(args: argparse.Namespace) -> int:
    fixtures = _bundled_fixtures()
    out = pathlib.Path(args.out).resolve()
    started = time.perf_counter()
    ok, rows = _run_demo(fixtures, out, args.iterations, names=QUICKSTART_SCENARIOS)
    elapsed = time.perf_counter() - started
    print("\n这 4 个判决回答的是同一件事：")
    for row in rows:
        note = row["note"] or "见 attribution.md"
        print(f"  {row['actual']:<9} {row['name']:<18} {note}")
    print(f"\n{sum(1 for r in rows if r['result'] == 'OK')}/{len(rows)} 符合预期，"
          f"耗时 {elapsed:.2f}s（bootstrap={args.iterations}，seed="
          f"{DEFAULT_CONFIG['seed']}）")
    print(f"证据目录：{out}")
    print("下一步：eval-gate verify --run-dir "
          f"{out / rows[0]['name']}")
    return 0 if ok else 1


def _add_common(parser: argparse.ArgumentParser) -> None:
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
    run.add_argument("--ci-method", choices=["auto", "bootstrap", "normal"],
                     default="auto",
                     help="auto：iterations×n 太大时改用分层正态近似")
    run.add_argument("--alpha-adjust", choices=["none", "bonferroni"], default="none",
                     help="none：逐检验 95%%；bonferroni：两个统计 gate 分摊 alpha")
    run.set_defaults(func=cmd_run)
    _add_common(run)

    verify = sub.add_parser("verify", help="只读证据重算判决")
    verify.add_argument("--run-dir", required=True)
    verify.set_defaults(func=cmd_verify)
    _add_common(verify)

    demo = sub.add_parser("demo", help="跑全部示例场景并断言预期判决")
    demo.add_argument("--fixtures", default=None,
                      help="示例数据目录；默认使用随包分发的 eval_gate/demo_data")
    demo.add_argument("--out", default="eval-gate-runs/demo")
    demo.add_argument("--iterations", type=int, default=10_000)
    demo.set_defaults(func=cmd_demo)

    quickstart = sub.add_parser("quickstart", help="一条命令跑 4 个核心判决（无需仓库数据）")
    quickstart.add_argument("--out", default="eval-gate-runs/quickstart")
    quickstart.add_argument("--iterations", type=int, default=2_000)
    quickstart.set_defaults(func=cmd_quickstart)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except EvalGateError as exc:
        print(exc.render(), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
