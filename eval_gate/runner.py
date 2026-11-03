"""编排：run（产出证据 + 判决）与 verify（只读证据重算）。

关键不变量：
- run 必须在同一目录写 `evidence/`、`run.json`、`verdict.json`。
- verify 只读 `run.json` + `evidence/`，不重新读取 dataset/predictions。
- verify 发现文件缺失 / 哈希不符 / 存储判决与重算不符，一律不得 PASS。
- 上一次判决更严重时，删证据不得把结论降级（G9）。
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

from .attribution import render_attribution
from .contract import (read_json, read_jsonl, sha256_file, sha256_text, validate_instance,
                       write_json, write_jsonl)
from .gate import DEFAULT_CONFIG, GATE_RULES_SHA, VERDICT_ORDER, config_with_defaults, evaluate
from .rubric import RUBRIC, RUBRIC_SHA, score_records
from .tools import scan_tools

# 每一份 vendored 组件的上游位置，写进 run.json 便于追溯。
UPSTREAM = {
    "mcp-guard": {
        "path": "vendor:/home/liuzewen/mcp-guard/guard",
        "commit": "17ce95732b2e28af9e98e1ec7c3ddcbd099fb164",
    },
    "auditable-llm-eval": {
        "path": "vendor:/home/liuzewen/auditable-llm-eval",
        "commit": "d4fcdcd31de1945ef39ba0c5952f62cc3f559d8a",
    },
}


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _run_id(head_sha: str, dataset_sha: str, predictions_sha: str) -> str:
    head = (head_sha or "unknown")[:7]
    if not all(ch.isalnum() or ch in "._-" for ch in head):
        head = "local"
    return f"pr-{head}-{dataset_sha[:8]}-{predictions_sha[:8]}"


def _load_tools(path: pathlib.Path | str | None) -> tuple[list[dict] | None, dict | None]:
    if not path:
        return None, None
    data = read_json(path)
    tools = data.get("tools", data) if isinstance(data, dict) else data
    return tools, None


def run_gate(
    *,
    dataset_path: pathlib.Path | str,
    predictions_path: pathlib.Path | str,
    baseline_predictions_path: pathlib.Path | str,
    out_dir: pathlib.Path | str,
    tools_path: pathlib.Path | str | None = None,
    tool_snapshot_path: pathlib.Path | str | None = None,
    changed_files: list[str] | None = None,
    head_sha: str = "unknown",
    config: dict | None = None,
    run_id: str | None = None,
) -> dict:
    dataset_path = pathlib.Path(dataset_path)
    predictions_path = pathlib.Path(predictions_path)
    baseline_path = pathlib.Path(baseline_predictions_path)
    out_dir = pathlib.Path(out_dir)
    changed_files = changed_files or []
    cfg = config_with_defaults(config)

    dataset = read_jsonl(dataset_path)
    predictions = read_jsonl(predictions_path)
    baseline_predictions = read_jsonl(baseline_path)
    candidate_rows = score_records(dataset, predictions)
    baseline_rows = score_records(dataset, baseline_predictions)

    tools = snapshot = None
    if tools_path:
        tools, _ = _load_tools(tools_path)
        snapshot = read_json(tool_snapshot_path) if tool_snapshot_path else None
    tools_evidence = scan_tools(tools, snapshot) if tools is not None else None
    layers = {
        "input_guard": "present" if tools_evidence is not None else "absent",
        "output_audit": "present",
        "attack_simulation": "absent",
    }

    dataset_sha = sha256_file(dataset_path)
    predictions_sha = sha256_file(predictions_path)
    baseline_sha = sha256_file(baseline_path)
    rubric_sha = sha256_text(json.dumps(RUBRIC, sort_keys=True, ensure_ascii=False))
    head_sha = head_sha or "unknown"
    run_id = run_id or _run_id(head_sha, dataset_sha, predictions_sha)

    evidence_dir = out_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(evidence_dir / "per_item.jsonl", candidate_rows)
    write_jsonl(evidence_dir / "baseline_per_item.jsonl", baseline_rows)
    summary = {
        "candidate": {
            "n": len(candidate_rows),
            "passes": sum(1 for row in candidate_rows if row.get("pass")),
            "naive_passes": sum(1 for row in candidate_rows if row.get("naive_pass")),
        },
        "baseline": {
            "n": len(baseline_rows),
            "passes": sum(1 for row in baseline_rows if row.get("pass")),
            "naive_passes": sum(1 for row in baseline_rows if row.get("naive_pass")),
        },
        "extra_predictions": len({p.get("id") for p in predictions} - {row["id"] for row in candidate_rows}),
    }
    write_json(evidence_dir / "summary.json", summary)
    if tools_evidence is not None:
        write_json(evidence_dir / "tools.json", tools_evidence)

    manifest = {
        str(path.relative_to(out_dir)): sha256_file(path)
        for path in sorted(evidence_dir.glob("*.json*"))
    }
    run_meta = {
        "run_id": run_id,
        "created_utc": _utc_now(),
        "rules_version": GATE_RULES_SHA,
        "scorer_version": RUBRIC_SHA,
        "tool_digests": {t["name"]: t["digest"] for t in (tools_evidence or {}).get("tools", [])},
        "repos": UPSTREAM,
        "inputs": {
            "dataset_sha256": dataset_sha,
            "predictions_sha256": predictions_sha,
            "baseline_predictions_sha256": baseline_sha,
            "rubric_sha256": rubric_sha,
            "head_sha": head_sha,
            "changed_files": changed_files,
            "config": cfg,
        },
        "evidence_manifest": manifest,
        "layers": layers,
    }
    problems = validate_instance(run_meta, "run.schema.json")
    if problems:
        raise RuntimeError("run.json 契约校验失败：\n" + "\n".join(problems))
    write_json(out_dir / "run.json", run_meta)

    verdict = evaluate(
        candidate_rows=candidate_rows,
        baseline_rows=baseline_rows,
        config=cfg,
        run_id=run_id,
        layers=layers,
        tools_evidence=tools_evidence,
    )
    _check_verdict(verdict)
    write_json(out_dir / "verdict.json", verdict)

    attribution = render_attribution(
        candidate_rows=candidate_rows,
        baseline_rows=baseline_rows,
        verdict=verdict,
        changed_files=changed_files,
        tools_evidence=tools_evidence,
        candidate_models={p.get("model", "unknown") for p in predictions},
        baseline_models={p.get("model", "unknown") for p in baseline_predictions},
    )
    (out_dir / "attribution.md").write_text(attribution, encoding="utf-8")
    return {"run_dir": str(out_dir), "run_id": run_id, "verdict": verdict}


def _check_verdict(verdict: dict) -> None:
    problems = validate_instance(verdict, "verdict.schema.json")
    if problems:
        raise RuntimeError("verdict.json 契约校验失败：\n" + "\n".join(problems))


_REQUIRED_BY_LAYER = {
    "output_audit": ["evidence/per_item.jsonl", "evidence/baseline_per_item.jsonl"],
    "input_guard": ["evidence/tools.json"],
}


def verify_run(run_dir: pathlib.Path | str, *, prior_config: dict | None = None) -> dict:
    """只读证据重算。返回 {problems, verdict}。"""
    run_dir = pathlib.Path(run_dir)
    problems: list[str] = []
    run_path = run_dir / "run.json"
    stored_path = run_dir / "verdict.json"

    if not run_path.exists():
        verdict = evaluate(
            candidate_rows=[], baseline_rows=[], config=prior_config or DEFAULT_CONFIG,
            run_id="unknown", layers={"input_guard": "absent", "output_audit": "absent",
                                      "attack_simulation": "absent"},
            missing_evidence=["run.json"],
        )
        return {"problems": ["run.json 不存在"], "verdict": verdict}

    run = read_json(run_path)
    problems.extend(validate_instance(run, "run.schema.json"))
    layers = run.get("layers", {})
    manifest = run.get("evidence_manifest", {})

    required: list[str] = []
    for layer, paths in _REQUIRED_BY_LAYER.items():
        if layers.get(layer) == "present":
            required.extend(paths)
    if layers.get("output_audit") != "present":
        required.append("evidence/per_item.jsonl")

    missing: list[str] = []
    tampered: list[str] = []
    for rel in required:
        path = run_dir / rel
        if not path.exists():
            missing.append(rel)
            continue
        actual = sha256_file(path)
        if rel not in manifest:
            missing.append(rel)
        elif manifest[rel] != actual:
            tampered.append(rel)

    candidate_rows: list[dict] = []
    baseline_rows: list[dict] = []
    if (run_dir / "evidence/per_item.jsonl").exists():
        candidate_rows = read_jsonl(run_dir / "evidence/per_item.jsonl")
    if (run_dir / "evidence/baseline_per_item.jsonl").exists():
        baseline_rows = read_jsonl(run_dir / "evidence/baseline_per_item.jsonl")
    tools_evidence = None
    if (run_dir / "evidence/tools.json").exists():
        tools_evidence = read_json(run_dir / "evidence/tools.json")

    stored = read_json(stored_path) if stored_path.exists() else None
    prior_verdict = stored.get("verdict") if isinstance(stored, dict) else None
    missing_all = missing + [f"{rel} (sha256 不匹配)" for rel in tampered]

    verdict = evaluate(
        candidate_rows=candidate_rows,
        baseline_rows=baseline_rows,
        config=run["inputs"]["config"],
        run_id=run["run_id"],
        layers=layers,
        missing_evidence=missing_all,
        tools_evidence=tools_evidence,
        prior_verdict=prior_verdict,
    )

    # 存储判决与重算不符：手改 verdict.json 或产物不同步
    if stored and not missing_all:
        mismatch = []
        for key in ("verdict", "severity"):
            if stored.get(key) != verdict.get(key):
                mismatch.append(f"{key}: 存储 {stored.get(key)!r} vs 重算 {verdict.get(key)!r}")
        stored_value = (stored.get("primary_metric") or {}).get("value")
        if stored_value is None or abs(stored_value - verdict["primary_metric"]["value"]) > 1e-6:
            mismatch.append("primary_metric.value 与重算不一致")
        stored_delta = (stored.get("delta") or {}).get("value")
        if stored_delta is None or abs(stored_delta - verdict["delta"]["value"]) > 1e-6:
            mismatch.append("delta.value 与重算不一致")
        if mismatch:
            problems.extend(mismatch)
            verdict = _force_incomplete(
                verdict, "存储判决与重算不一致：" + "; ".join(mismatch))
    elif tampered:
        verdict = _force_incomplete(
            verdict, "证据哈希不匹配：" + ", ".join(tampered))
    elif missing:
        problems.extend(f"缺少必需证据 {rel}" for rel in missing)

    _check_verdict(verdict)
    return {"problems": problems, "verdict": verdict}


def _force_incomplete(verdict: dict, reason: str) -> dict:
    """把证据/一致性缺陷记为 INCOMPLETE；已有更重判决（BLOCK）不得被降级。"""
    verdict = dict(verdict)
    current = verdict.get("verdict", "PASS")
    target = current if VERDICT_ORDER.get(current, 0) > VERDICT_ORDER["INCOMPLETE"] else "INCOMPLETE"
    verdict["verdict"] = target
    verdict["severity"] = {"BLOCK": "block", "INCOMPLETE": "incomplete"}[target]
    verdict["why"] = reason
    verdict["gates"] = list(verdict["gates"]) + [{
        "id": "G6-evidence",
        "rule": "证据完整且与存储判决一致",
        "observed": "tampered",
        "result": "fail",
        "verdict": target,
        "detail": reason,
    }]
    verdict["matched_rules"] = [{"gate": g["id"], "verdict": g["verdict"]}
                                for g in verdict["gates"] if g.get("verdict")]
    return verdict
