"""归因表：把 PASS→FAIL 的回退项变成可执行的排查线索。

原因映射是硬规则，不允许瞎猜（与 PLAN.md §2.3 一致）：
    prompts/** 变更           -> prompt
    tools/** 或工具 digest 变化 -> tool-definition
    model id 变化             -> model
    evals/dataset 变更        -> dataset
    其余                      -> unknown
"""
from __future__ import annotations

from .rubric import RUBRIC


def _cause(changed_files: list[str], tool_drift: bool,
           cand_models: set[str], base_models: set[str]) -> tuple[str, str]:
    evidence_parts = []
    if any(path.startswith("prompts/") for path in changed_files):
        evidence_parts.append("prompts 变更: " + ", ".join(
            p for p in changed_files if p.startswith("prompts/")))
        return "prompt", "; ".join(evidence_parts)
    if tool_drift or any(path.startswith("tools/") for path in changed_files):
        evidence_parts.append("工具定义变更")
        return "tool-definition", "; ".join(evidence_parts)
    if cand_models != base_models:
        evidence_parts.append(f"model: {sorted(base_models)} -> {sorted(cand_models)}")
        return "model", "; ".join(evidence_parts)
    if any(path.startswith("evals/dataset") for path in changed_files):
        return "dataset", "数据集文件变更"
    return "unknown", "无足够证据，不猜测"


_ACTIONS = {
    "prompt": "回滚该条 prompt 指令，或在新分支单独复测这条改动",
    "tool-definition": "恢复被改动的工具定义，并复核 drift 的命中内容",
    "model": "确认模型版本是否预期升级；若是，重跑基线",
    "dataset": "先对齐数据集版本，再比较（当前可能需要 G8 不可比）",
    "unknown": "保留样本，人工复核失败原因后再改",
}


def render_attribution(
    *,
    candidate_rows: list[dict],
    baseline_rows: list[dict],
    verdict: dict,
    changed_files: list[str] | None = None,
    tools_evidence: dict | None = None,
    candidate_models: set[str] | None = None,
    baseline_models: set[str] | None = None,
) -> str:
    changed_files = changed_files or []
    candidate_models = candidate_models or set()
    baseline_models = baseline_models or set()
    base_by_id = {row["id"]: row for row in baseline_rows}
    tool_drift = bool(tools_evidence and tools_evidence.get("drift_alarm"))

    regressions = []
    for row in candidate_rows:
        base = base_by_id.get(row["id"])
        if base and base.get("pass") and not row.get("pass"):
            regressions.append(row)

    cause, cause_evidence = _cause(changed_files, tool_drift,
                                   candidate_models, baseline_models)

    lines = [
        "# eval-gate 归因表",
        "",
        f"- run_id: `{verdict['run_id']}`",
        f"- 判定: **{verdict['verdict']}**（{verdict['severity']}）",
        f"- 主指标: {verdict['primary_metric']['value']:.4f} "
        f"(95% CI {verdict['primary_metric']['ci95'][0]:.4f}–"
        f"{verdict['primary_metric']['ci95'][1]:.4f}, n={verdict['primary_metric']['n']})",
        f"- 基线: {verdict['baseline']['value']:.4f}；"
        f"delta {verdict['delta']['value']:+.4f} "
        f"(95% CI {verdict['delta']['ci95'][0]:+.4f}–{verdict['delta']['ci95'][1]:+.4f})",
        f"- naive 检查器: {verdict['metrics']['naive_pass_rate']:.2%} 全绿，"
        f"与权威评分落差 {verdict['metrics']['deception_gap']:+.2%}",
        "",
        "## Gate 结果",
        "",
        "| Gate | 规则 | 观测 | 结果 |",
        "|---|---|---|---|",
    ]
    for gate in verdict["gates"]:
        result = gate["result"]
        if gate.get("verdict"):
            result += f" → {gate['verdict']}"
        lines.append(f"| {gate['id']} | {gate['rule']} | `{gate['observed']}` | {result} |")

    lines += ["", "## Top 回退项（PASS → FAIL）", ""]
    if not regressions:
        lines.append("无 PASS→FAIL 回退项。")
    else:
        lines += [
            "| item_id | family | 失败层 | 维度/原因 | 证据片段 | 疑似原因 | 建议动作 |",
            "|---|---|---|---|---|---|---|",
        ]
        for row in regressions[:10]:
            if row.get("l1_failures"):
                layer = "L1"
                dimension = row["l1_failures"][0]
            else:
                layer = "L2"
                dims = row.get("dimensions") or {}
                dimension = min(dims, key=lambda k: (dims[k], -RUBRIC["l2_weights"].get(k, 0)))
            span = (row.get("output_excerpt") or "").replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| `{row['id']}` | {row.get('family')} | {layer} | {dimension} | "
                f"{span[:80]} | {cause} | {_ACTIONS[cause]} |"
            )
        lines += ["", f"原因证据：{cause_evidence}"]

    lines += [
        "",
        "## 说明",
        "",
        "- 本表只列 PASS→FAIL；FAIL→PASS 与双方都 FAIL 的项不进 Top 列表。",
        "- `unknown` 不是「没问题」，是「证据不足」；不允许在这类项上编原因。",
        "",
    ]
    return "\n".join(lines)
