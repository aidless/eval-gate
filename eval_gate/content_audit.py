"""内容保真度审计：把 ai-club 逐篇核读踩出的判据固化为可失败的门。

来源：ai-club.cn 54 篇逐篇核读（2026-11-22/23）。三条判据各自带反证：
- detect_redirect：只认「指向外部全文的引流短语」，不用「结尾无标点」——后者会把
  脚注(↩︎)/License(MIT)/署名(CEO)/newsletter 误判为截断（批次03 初版 3 篇假阳）。
- detect_fidelity：SequenceMatcher 去空白后相似度 + 功能性差异落盘；0.999 也可能
  功能性失效——blog/65566 的 2 处 `**` 被吞让 glob 路径 `Classes/**/*` 变 `//*`。
- byte_contains：判断文件是否真含某字符串必须读字节，不信 grep/print 的文本层——
  工具呈现层会脱敏（disclaimer.md 邮箱误判的教训）。

本模块与 eval_gate 的回归门引擎并行，不改动现有 gate.py/cli.py。
"""
from __future__ import annotations

import base64
import difflib
import re
from pathlib import Path
from typing import Any

# 引流短语：带明确指向性，排除普通 "read more" 导航
_REDIRECT_RE = re.compile(
    "|".join([
        r"read\s+(?:the\s+)?full\s+(?:story|article|post)",
        r"read\s+the\s+(?:original|full\s+version)",
        r"full\s+story\s+at\b",
        r"continue\s+reading\s+(?:at|on|the\s+original)",
        r"阅读全文|查看原文|阅读原文|点击阅读原文",
    ]),
    re.I,
)
# 尾部无标点但正当的收尾——仅作提示，不单独判红
_NON_TRUNC = re.compile(
    r"\bLicense\b|\bLicence\b|MIT|CC BY|↩︎|Cited by|See our calculations"
    r"|\bCEO\b|Co-founder|thanks for reading|Sponsor me|newsletter|相关阅读|版权归",
    re.I,
)
# 功能性字符：在转载/转换中丢失会改变语义或破坏代码/路径
_FUNCTIONAL = re.compile(r"\*|\\|/|\||`|_|\{|\}|\[|\]")


def detect_redirect(body: str) -> dict[str, Any]:
    phrases = sorted({m.group(0) for m in _REDIRECT_RE.finditer(body or "")})
    tail = (body or "").strip()[-200:]
    tail_suspicious = bool(tail) and tail[-1] not in ".!?。！？」”』）)]" and not _NON_TRUNC.search(tail)
    return {
        "is_redirect": bool(phrases),
        "phrases": phrases,
        "tail_suspicious_not_conclusive": tail_suspicious,
    }


def detect_fidelity(src: str, dst: str) -> dict[str, Any]:
    """返回相似度与功能性差异。fidelity_ok=False 表示差异可能破坏功能。"""
    a = re.sub(r"\s+", "", src or "")
    b = re.sub(r"\s+", "", dst or "")
    ratio = difflib.SequenceMatcher(None, a, b).ratio() if (a or b) else 1.0
    sm = difflib.SequenceMatcher(None, a, b)
    functional_diffs: list[dict[str, str]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        removed, added = a[i1:i2], b[j1:j2]
        if _FUNCTIONAL.search(removed) or _FUNCTIONAL.search(added):
            functional_diffs.append({"op": tag, "removed": removed[:40], "added": added[:40]})
    return {
        "ratio": round(ratio, 4),
        "functional_diff_count": len(functional_diffs),
        "functional_diffs": functional_diffs[:10],
        # 关键：ratio 再高，只要有功能性差异就判不可信
        "fidelity_ok": len(functional_diffs) == 0,
    }


def byte_contains(path: str | Path, literal: str) -> bool:
    """字节级子串判定，绕过文本解码与呈现层脱敏。"""
    data = Path(path).read_bytes()
    return literal.encode("utf-8") in data


def cross_byline(ld_author: str, page_src: str, body_names: list[str]) -> dict[str, Any]:
    names = [n for n in body_names if n]
    conflict = bool(ld_author and names and ld_author not in names and page_src not in names)
    return {
        "ld_author": ld_author,
        "page_src": page_src,
        "body_bylines": names,
        "conflict": conflict,
        "note": "三者不一致仅标记，不自动裁决（机构名与真人常同时成立）",
    }


def selftest() -> int:
    """注入反例必须判红、已知正例必须判绿；门本身可失败。"""
    checks: list[tuple[str, bool]] = []

    def ck(name: str, cond: bool) -> None:
        checks.append((name, cond))

    # 引流：真阳
    ck("verge tail", detect_redirect("News. Read the full story at The Verge")["is_redirect"])
    ck("ars tail", detect_redirect("land.\n\nRead full article\n\nComments")["is_redirect"])
    ck("zh tail", detect_redirect("前半段……点击阅读原文")["is_redirect"])
    # 引流：批次03 的 3 篇假阳必须判绿
    ck("license not trunc", not detect_redirect("bridge. License MIT")["is_redirect"])
    ck("footnote not trunc", not detect_redirect("periods. ↩︎ See our calculations ↩︎")["is_redirect"])
    ck("byline not trunc", not detect_redirect("contact x. Vipul Ved Prakash CEO")["is_redirect"])
    ck("newsletter not trunc", not detect_redirect("thanks for reading, keep those hammers up")["is_redirect"])
    # 反证：删掉引流句必须翻绿
    ck("mutation flips green", not detect_redirect("News. 更多内容。")["is_redirect"])
    # 保真度：0.999 但 ** 被吞必须报红（blog/65566 原样）
    hi = detect_fidelity("s.source_files='Pod/Classes/**/*'", "s.source_files='Pod/Classes//*'")
    ck("0.999 functional diff red", (not hi["fidelity_ok"]) and hi["functional_diff_count"] >= 1)
    ck("identical green", detect_fidelity("same text here", "same text here")["fidelity_ok"])
    ck("pure whitespace green", detect_fidelity("a b c", "a  b   c")["fidelity_ok"])
    # 反证：把 ** 补回去必须翻绿
    ck("restore ** flips green", detect_fidelity("Classes/**/*", "Classes/**/*")["fidelity_ok"])
    # 署名冲突
    c = cross_byline("AI Club", "Hacker News", ["Vipul Ved Prakash"])
    ck("byline conflict marked", c["conflict"])
    ck("byline same green", not cross_byline("Vipul Ved Prakash", "Hacker News", ["Vipul Ved Prakash"])["conflict"])

    ok = sum(1 for _, cond in checks if cond)
    for name, cond in checks:
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    print(f"selftest {ok}/{len(checks)}")
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
