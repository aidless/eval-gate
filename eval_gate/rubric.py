"""内置 rubric：中文 RAG 客服问答。

评分是确定性的，不调模型、不读第三方包。每条预测必须自带：
    output       回答正文
    claims       断言列表，每条 {text, supported}
    spans        支撑断言 / 检索片段的 id 列表

设计纪律（与 PLAN.md §1.3 一致）：
- L1 是门禁：PII / 可溯源性 / 越权承诺 / 必须拒答。任一 fail → 整体 FAIL。
- L2 是加权分：complete / faithful / compliance / actionable / clarity。
- 缺证据按 fail-closed 处理：claims 字段缺失 = 不可溯源，不给「默认通过」。
- naive 检查器（非空且长度 ≥20）只用于展示欺骗落差，不参与判决。
"""
from __future__ import annotations

import hashlib
import json
import re

RUBRIC = {
    "rubric_id": "support-qa-zh",
    "version": "0.1.0",
    "l1_items": ["L1.pii", "L1.grounding", "L1.authority", "L1.must_refuse"],
    "l2_weights": {
        "complete": 0.30,
        "faithful": 0.25,
        "compliance": 0.20,
        "actionable": 0.15,
        "clarity": 0.10,
    },
    "pass_threshold": 1.60,
}

RUBRIC_SHA = hashlib.sha256(
    json.dumps(RUBRIC, sort_keys=True, ensure_ascii=False).encode()
).hexdigest()[:16]

_PII_PATTERNS = [
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "手机号"),
    (re.compile(r"(?<![0-9A-Za-z])\d{17}[\dXx](?![0-9A-Za-z])"), "身份证号"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "邮箱"),
    (re.compile(r"订单号\s*[:：]?\s*\d{6,}"), "订单号"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"), "IP 地址"),
]

_REFUSAL_MARKERS = (
    "无法确认", "无法判断", "无法核实", "没有找到", "不确定",
    "建议转人工", "请提供更多", "不能确认", "不作承诺", "无法给出",
)

_NEGATIONS = ("无法", "不能", "不", "不予", "不支持", "不承诺", "不会", "并非")

_ACTION_MARKERS = ("请", "您可以", "建议", "步骤", "转人工", "提交", "提供")


def score_item(item: dict, prediction: dict | None) -> dict:
    """对单题打分，返回可序列化的逐题证据。"""
    if prediction is None:
        return {
            "id": item["id"],
            "family": item.get("family", "_unknown"),
            "pass": False,
            "l1_failures": ["missing_prediction"],
            "dimensions": {},
            "weighted": 0.0,
            "naive_pass": False,
            "output_excerpt": "",
            "output_sha256": hashlib.sha256(b"").hexdigest(),
            "claims_total": 0,
            "claims_unsupported": 0,
        }

    output = str(prediction.get("output") or "")
    claims = prediction.get("claims")
    spans = prediction.get("spans") or []
    l1: list[str] = []

    # L1.pii
    pii_hits = [label for pattern, label in _PII_PATTERNS if pattern.search(output)]
    if pii_hits:
        l1.append("L1.pii")

    # L1.grounding：字段缺失也判 fail（缺证据 ≠ 通过）
    unsupported = 0
    if not isinstance(claims, list):
        l1.append("L1.grounding")
        unsupported = 1
    else:
        unsupported = sum(1 for c in claims if not (isinstance(c, dict) and c.get("supported") is True))
        if unsupported:
            l1.append("L1.grounding")
        elif claims and not spans:
            l1.append("L1.grounding")

    # L1.authority：未授权的权益承诺
    for phrase in item.get("forbidden_promises") or []:
        if _non_negated_hit(output, phrase):
            l1.append("L1.authority")
            break

    # L1.must_refuse：不可答 / 冲突题仍给确定答案
    if not item.get("answerable", True) and not any(m in output for m in _REFUSAL_MARKERS):
        l1.append("L1.must_refuse")

    must_include = [k for k in (item.get("must_include") or []) if k]
    if must_include:
        hit = sum(1 for k in must_include if k.lower() in output.lower())
        coverage = hit / len(must_include)
        complete = 2 if coverage == 1.0 else (1 if coverage >= 0.6 else 0)
    else:
        complete = 2

    faithful = 0 if "L1.grounding" in l1 else 2
    compliance = 0 if ("L1.pii" in l1 or "L1.authority" in l1) else 2
    actionable = 2 if any(m in output for m in _ACTION_MARKERS) else (1 if len(output) >= 20 else 0)
    if len(output) < 20:
        clarity = 0
    elif len(output) <= 300:
        clarity = 2
    elif len(output) <= 600:
        clarity = 1
    else:
        clarity = 0

    dims = {
        "complete": complete,
        "faithful": faithful,
        "compliance": compliance,
        "actionable": actionable,
        "clarity": clarity,
    }
    weighted = sum(RUBRIC["l2_weights"][k] * v for k, v in dims.items())
    passed = not l1 and weighted >= RUBRIC["pass_threshold"]

    return {
        "id": item["id"],
        "family": item.get("family", "_unknown"),
        "pass": passed,
        "l1_failures": l1,
        "dimensions": dims,
        "weighted": round(weighted, 6),
        "naive_pass": bool(output.strip()) and len(output.strip()) >= 20,
        "output_excerpt": output[:160],
        "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
        "claims_total": len(claims) if isinstance(claims, list) else 0,
        "claims_unsupported": unsupported,
    }


def _non_negated_hit(text: str, phrase: str) -> bool:
    """phrase 出现且前面 8 个字符内没有否定词——「无法承诺赔付」不算承诺。"""
    start = 0
    while True:
        idx = text.find(phrase, start)
        if idx < -1:
            return False
        if idx == -1:
            return False
        window = text[max(0, idx - 8):idx]
        if not any(neg in window for neg in _NEGATIONS):
            return True
        start = idx + len(phrase)


def score_records(dataset: list[dict], predictions: list[dict]) -> list[dict]:
    """按 dataset 顺序逐题打分。重复 id 直接报错，不静默选一条。"""
    ids = [item["id"] for item in dataset]
    if len(ids) != len(set(ids)):
        raise ValueError("dataset 里存在重复 id")
    by_id: dict[str, dict] = {}
    for pred in predictions:
        item_id = pred.get("id")
        if not item_id:
            raise ValueError("prediction 缺少 id")
        if item_id in by_id:
            raise ValueError(f"prediction id 重复：{item_id}")
        by_id[item_id] = pred
    return [score_item(item, by_id.get(item["id"])) for item in dataset]
