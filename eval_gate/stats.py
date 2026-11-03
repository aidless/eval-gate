"""统计核心：Wilson 区间 + 按 family 分层的 paired bootstrap。

两个刻意的选择：
1. 绝对通过率用 Wilson，而不是正态近似。n=480、p=0.89 时两者差别不大，
   但 p 接近 0/1 或 n 变小时，正态近似会给出越界区间。
2. 回退用 paired bootstrap：同一道题在候选与基线上配对，按 family 分层重采样。
   不配对会把「题目变简单了」误当成「模型变好了」。

bootstrap 的 seed 固定，重跑必须逐字节一致（除时间戳）。
"""
from __future__ import annotations

import math
import random
from collections.abc import Mapping

Z_95 = 1.959963984540054


def wilson_interval(passes: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """95% Wilson 区间。n<=0 时返回 (0, 1)：fail-closed，不假装有信息。"""
    if n <= 0:
        return (0.0, 1.0)
    p = passes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def ci_width(ci: tuple[float, float]) -> float:
    return ci[1] - ci[0]


def overlap_rate(candidate_ids, baseline_ids) -> float:
    """两个集合的交集 / 候选集合大小。候选为空时返回 0。"""
    cand = set(candidate_ids)
    if not cand:
        return 0.0
    return len(cand & set(baseline_ids)) / len(cand)


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        raise ValueError("空样本没有分位数")
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_values[lo]
    return sorted_values[lo] * (hi - pos) + sorted_values[hi] * (pos - lo)


def paired_bootstrap_delta(
    candidate: Mapping[str, float],
    baseline: Mapping[str, float],
    families: Mapping[str, str],
    *,
    iterations: int = 10_000,
    seed: int = 20261103,
    alpha: float = 0.05,
) -> dict:
    """候选 − 基线的配对 bootstrap。

    - 只使用两边都存在的 id（未配对的题不能比较）。
    - 按 family 分层，每个 family 内等量重采样。
    - 返回 point / ci95 / n / iterations / seed / families。
    """
    ids = sorted(set(candidate) & set(baseline))
    n = len(ids)
    strata: dict[str, list[tuple[float, float]]] = {}
    for item_id in ids:
        family = families.get(item_id, "_unknown")
        strata.setdefault(family, []).append(
            (float(candidate[item_id]), float(baseline[item_id])))

    if n == 0:
        return {
            "delta": 0.0,
            "ci95": [0.0, 0.0],
            "n": 0,
            "iterations": iterations,
            "seed": seed,
            "families": 0,
        }

    point = sum(candidate[i] - baseline[i] for i in ids) / n
    rng = random.Random(seed)
    keys = sorted(strata)
    samples: list[float] = []
    for _ in range(iterations):
        total = 0.0
        for key in keys:
            values = strata[key]
            picked = rng.choices(values, k=len(values))
            for cand, base in picked:
                total += cand - base
        samples.append(total / n)
    samples.sort()
    return {
        "delta": point,
        "ci95": [_percentile(samples, alpha / 2),
                 _percentile(samples, 1 - alpha / 2)],
        "n": n,
        "iterations": iterations,
        "seed": seed,
        "families": len(keys),
    }
