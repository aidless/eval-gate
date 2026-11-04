"""工具面：扫描 MCP 工具定义 + 检测漂移。

来源（vendor，MIT）：
    mcp-guard/guard/rules.py  @ 17ce95732b2e28af9e98e1ec7c3ddcbd099fb164
    mcp-guard/guard/drift.py  @ 同上
    mcp-guard/guard/scan.py   @ 同上（上游仓见 VENDOR.md）

改动：只保留 eval-gate 用到的函数；漂移比较仍然比 (规则 id, anchor)，
而不是整段命中文本——否则「read the id_rsa」→「read your id_rsa」这种
纯措辞改动会被误判成载荷替换。上游原文件更完整，追溯请看 VENDOR.md。
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

RULES = [
    {
        "id": "imperative-tag",
        "severity": "high",
        "patterns": [r"<\s*(?P<anchor>IMPORTANT|INSTRUCTION|SYSTEM|URGENT)[^>]*>"],
        "why": "伪装成系统指令的标签劫持",
    },
    {
        "id": "secret-read",
        "severity": "high",
        "patterns": [
            r"~\s*/\s*\.(?P<anchor>ssh|aws|gnupg|kube|docker|azure)",
            r"read\s+.*(?P<anchor>id_rsa|id_ed25519|\.pem)",
            r"(?:include|attach|send).{0,40}(?P<anchor>chat\s*history|conversation\s*history)",
            r"(?P<anchor>mcp).*\.json",
            r"~\s*/\s*\.config\s*/\s*(?P<anchor>gcloud)",
            r"(?P<anchor>\.netrc)\b",
            r"\b(?P<anchor>aws|gcloud|azure|kube)[\s_-]?credentials\b",
        ],
        "why": "读取密钥/配置/聊天记录并外带",
    },
    {
        "id": "exfil-param",
        "severity": "medium",
        "patterns": [
            r"fill\s+\w*(?P<anchor>context|session_id|metadata)\w*\s+with",
            r"use\s+(?P<anchor>system\s*prompt|previous\s*tool\s*result|conversation)"
            r".{0,30}param",
            r"populate\s+(the\s+)?\w*(?P<anchor>context|session_id|metadata)\w*\b.{0,40}?\s+with\b",
            r"copy\b.{0,80}?into\s+(the\s+)?(?P<anchor>context|session_id|metadata)\b",
            r"(?P<anchor>fill|populate|copy)\s+(the\s+)?\w*(context|session_id|metadata)\w*\b.{0,20}?\s+param",
        ],
        "why": "诱导模型把敏感数据填进无害名参数",
    },
    {
        "id": "recipient-rewrite",
        "severity": "high",
        "patterns": [
            r"\b(?P<anchor>bcc)\b",
            r"append\s+.{0,20}(?P<anchor>recipient|address|copy)",
            r"redirect\s+.{0,20}(?P<anchor>email|message)",
            r"hidden\s+(?P<anchor>copy|recipient|address|bcc)",
        ],
        "why": "改写收件人/静默抄送",
    },
    {
        "id": "auth-url-exec",
        "severity": "high",
        "patterns": [
            r"(?P<anchor>shell\s*=\s*True)",
            r"(?P<anchor>os\.system)\s*\(",
            r"(?:subprocess).*(?P<anchor>shell\s*=\s*True)",
        ],
        "why": "工具参数直达 shell",
    },
    {
        "id": "encoded-exfil",
        "severity": "high",
        "patterns": [
            r"(?P<anchor>ssh|\.ssh|id_rsa|id_ed25519|private[\s_-]*key|secret|token|password|credential)"
            r"[\s\S]{0,80}?(base64|b64|rot13|hex)[\s_-]?encod\w*"
            r"[\s\S]{0,160}?(include|attach|send|upload|post|place|put|exfiltrat|param)",
        ],
        "why": "敏感材料先编码再外带",
    },
]

_COMPILED = [
    (rule["id"], rule["severity"],
     [re.compile(p, re.I) for p in rule["patterns"]], rule["why"])
    for rule in RULES
]


def _norm(text: str) -> str:
    return " ".join((text or "").split()).lower()


def tool_text(tool: dict[str, Any]) -> str:
    parts = [tool.get("name", ""), tool.get("description", "")]
    schema = tool.get("inputSchema") or tool.get("parameters") or {}
    parts.append(json.dumps(schema, ensure_ascii=False))
    return "\n".join(parts)


def scan_text(text: str) -> list[dict[str, Any]]:
    hits = []
    for rid, severity, patterns, why in _COMPILED:
        for pattern in patterns:
            match = pattern.search(text or "")
            if match:
                anchor = match.groupdict().get("anchor")
                anchor = _norm(anchor) if anchor else (
                    "sha256:" + hashlib.sha256(_norm(match.group(0)).encode()).hexdigest()[:16])
                hits.append({
                    "rule": rid,
                    "severity": severity,
                    "match": match.group(0)[:80],
                    "anchor": anchor,
                    "why": why,
                })
                break
    return hits


def digest_tool(tool: dict[str, Any]) -> str:
    canon = json.dumps(tool, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canon.encode()).hexdigest()


def _changed_fields(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    fields = ("description", "title", "annotations", "name", "inputSchema", "parameters")
    return [f for f in fields
            if json.dumps(old.get(f, "<absent>"), sort_keys=True, ensure_ascii=False)
            != json.dumps(new.get(f, "<absent>"), sort_keys=True, ensure_ascii=False)]


def _hit_map(tool: dict[str, Any]) -> dict[tuple[str, str], str]:
    return {(h["rule"], h["anchor"]): h.get("match", "")
            for h in scan_text(tool_text(tool))}


def diff_tool(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """返回 status / fields / new_hits / changed_hits / alarm。"""
    if not old:
        return {"status": "new", "fields": _changed_fields({}, new),
                "new_hits": [], "changed_hits": [], "alarm": False}
    fields = _changed_fields(old, new)
    if not fields:
        return {"status": "ok", "fields": [], "new_hits": [],
                "changed_hits": [], "alarm": False}
    before = _hit_map(old)
    after = _hit_map(new)
    added = set(after) - set(before)
    rules_before = {r for r, _ in before}
    rules_after = {r for r, _ in after}
    new_hits = sorted(rules_after - rules_before)
    changed_hits = sorted({r for r, _ in added} & rules_before)
    return {
        "status": "changed",
        "fields": fields,
        "new_hits": new_hits,
        "changed_hits": changed_hits,
        "alarm": bool(new_hits or changed_hits),
    }


def scan_tools(tools: list[dict[str, Any]], snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """扫描当前工具清单，并与 pin 快照（digests + tools）比对漂移。"""
    pin_digests = (snapshot or {}).get("digests", {})
    pin_tools = (snapshot or {}).get("tools", {})
    results = []
    flagged = drift_alerts = drift_alarm = 0
    for tool in tools:
        hits = scan_text(tool_text(tool))
        is_flagged = bool(hits)
        flagged += int(is_flagged)
        drift = None
        if snapshot is not None:
            name = tool.get("name", "?")
            old_digest = pin_digests.get(name)
            now_digest = digest_tool(tool)
            if old_digest is None:
                drift = {"name": name, "status": "new", "alarm": None,
                         "new_hits": [], "changed_hits": [], "fields": []}
            elif old_digest == now_digest:
                drift = {"name": name, "status": "ok", "alarm": False,
                         "new_hits": [], "changed_hits": [], "fields": []}
            else:
                old = pin_tools.get(name)
                if old is None:
                    drift = {"name": name, "status": "DRIFT", "alarm": None,
                             "new_hits": [], "changed_hits": [],
                             "fields": ["<unknown: no snapshot stored>"]}
                else:
                    detail = diff_tool(old, tool)
                    drift = {"name": name,
                             "status": "DRIFT" if detail["fields"] else "changed",
                             "alarm": detail["alarm"],
                             "new_hits": detail["new_hits"],
                             "changed_hits": detail["changed_hits"],
                             "fields": detail["fields"]}
            if drift["status"] in ("DRIFT", "changed"):
                drift_alerts += 1
            if drift.get("alarm"):
                drift_alarm += 1
        results.append({
            "name": tool.get("name", "?"),
            "digest": digest_tool(tool),
            "flagged": is_flagged,
            "hits": hits,
            "drift": drift,
        })
    return {
        "scanned": len(tools),
        "flagged": flagged,
        "drift_alerts": drift_alerts,
        "drift_alarm": drift_alarm,
        "tools": results,
    }


def build_snapshot(tools: list[dict[str, Any]]) -> dict[str, Any]:
    """等价于 `mcp-guard-scan tools.json --pin` 写出的快照格式。"""
    return {
        "digests": {t.get("name", "?"): digest_tool(t) for t in tools},
        "tools": {t.get("name", "?"): t for t in tools},
    }
