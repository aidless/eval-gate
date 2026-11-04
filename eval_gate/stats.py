"""统计核心：Wilson 区间 + 按 family 分层的 paired bootstrap / 大样本正态近似。

三个刻意的选择：
1. 绝对通过率用 Wilson，而不是正态近似。n=480、p=0.89 时两者差别不大，
   但 p 接近 0/1 或 n 变小时，正态近似会给出越界区间。
2. 回退用 paired bootstrap：同一道题在候选与基线上配对，按 family 分层重采样。
   不配对会把「题目变简单了」误当成「模型变好了」。
   重采样单位是**题**，不是预测条数；同一题的多条预测必须先在外部合并成一条。
3. n 很大（默认 iterations×n > 2×10^7）时改用同一分层的正态近似，避免纯 Python
   的 O(iterations×n) 变成几分钟。用了哪种方法写进 `method`，verify 用同一方法重算。

bootstrap 的 seed 固定，重跑必须逐字节一致（除时间戳）。跨 Python 版本的一致性
由 `tests/test_stats.py` 的 golden 用例守住；`random.Random` 的 Mersenne Twister
序列在 CPython 里稳定，但 `random.choices` 的实现细节不属于兼容性承诺，所以
CI 在 3.9–3.12 上都跑同一条 golden 断言。
"""
from __future__ import annotations

import math
import random
from collections.abc import Iterable, Mapping
from typing import Any

Z_95 = 1.959963984540054
Z_80 = 0.8416212335729143

# 纯 Python bootstrap 的默认工作量上限：iterations × n。
# 超过它就用分层正态近似（同一 estimand，同一方差公式）。
MAX_BOOTSTRAP_WORK = 20_000_000


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


def overlap_rate(candidate_ids: Iterable[str], baseline_ids: Iterable[str]) -> float:
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


def _strata(candidate: Mapping[str, float], baseline: Mapping[str, float],
            families: Mapping[str, str]) -> tuple[dict[str, list[float]], list[str]]:
    """只保留两边都有的 id，按 family 分组，存逐题差值（候选 − 基线）。"""
    ids = sorted(set(candidate) & set(baseline))
    strata: dict[str, list[float]] = {}
    for item_id in ids:
        family = families.get(item_id, "_unknown")
        strata.setdefault(family, []).append(
            float(candidate[item_id]) - float(baseline[item_id]))
    return strata, ids


def _stratified_variance(strata: Mapping[str, list[float]], n: int) -> float:
    """分层均值差的方差：Σ_h (n_h/n)^2 * var_h / n_h = Σ_h n_h*var_h / n^2。"""
    if n <= 0:
        return 0.0
    total = 0.0
    for values in strata.values():
        size = len(values)
        if size < 2:
            continue
        mean = sum(values) / size
        var = sum((value - mean) ** 2 for value in values) / (size - 1)
        total += size * var
    return total / (n * n)


def mde_from_variance(variance: float, *, alpha: float = 0.05,
                      power: float = 0.8) -> float:
    """给定 delta 的方差，返回双侧检验在指定功效下的最小可检测效应。

    MDE = (z_{alpha/2} + z_{power}) * sqrt(var)。以 480 题、discordant≈20% 为例，
    var≈8.3e-5，MDE≈5.7pp：这就是「容差 3pp、n=480」时漏掉真实回退的概率
    仍然偏高的原因（见 STATS_DESIGN.md §4）。
    """
    if variance <= 0:
        return 0.0
    z_alpha = alpha_to_z(alpha)
    z_power = _z_for_power(power)
    return (z_alpha + z_power) * math.sqrt(variance)


def alpha_to_z(alpha: float) -> float:
    """双侧 alpha 对应的正态临界值（零依赖）。"""
    return _z_for_alpha(alpha)


def _z_for_alpha(alpha: float) -> float:
    # 只做常用值的精确回退，避免引入 scipy。
    table = {0.10: 1.6448536269514722, 0.05: Z_95, 0.01: 2.5758293035489004}
    for key, value in table.items():
        if abs(alpha - key) < 1e-12:
            return value
    # 正态分位数的 Acklam 有理近似（相对误差 < 1.15e-9）
    p = 1.0 - alpha / 2.0
    return _norm_ppf(p)


def _z_for_power(power: float) -> float:
    table = {0.8: Z_80, 0.9: 1.2815515655446004, 0.95: 1.6448536269514722}
    for key, value in table.items():
        if abs(power - key) < 1e-12:
            return value
    return _norm_ppf(power)


def _norm_ppf(p: float) -> float:
    """Acklam 近似，零依赖。"""
    if not 0.0 < p < 1.0:
        raise ValueError("p 必须在 (0,1) 内")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
                ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def paired_bootstrap_delta(
    candidate: Mapping[str, float],
    baseline: Mapping[str, float],
    families: Mapping[str, str],
    *,
    iterations: int = 10_000,
    seed: int = 20261103,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """候选 − 基线的配对 bootstrap（强制 bootstrap，不做大样本切换）。

    - 只使用两边都存在的 id（未配对的题不能比较）。
    - 按 family 分层，每个 family 内等量重采样（单位是题，不是预测条数）。
    - 返回 point / ci95 / n / iterations / seed / families。
    """
    strata, ids = _strata(candidate, baseline, families)
    n = len(ids)
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
            for value in picked:
                total += value
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


def paired_delta_ci(
    candidate: Mapping[str, float],
    baseline: Mapping[str, float],
    families: Mapping[str, str],
    *,
    iterations: int = 10_000,
    seed: int = 20261103,
    alpha: float = 0.05,
    method: str = "auto",
    max_bootstrap_work: int = MAX_BOOTSTRAP_WORK,
) -> dict[str, Any]:
    """带方法标记的配对 delta 区间（gate 走这里）。

    method:
        auto       iterations×n <= max_bootstrap_work 时 bootstrap，否则 normal
        bootstrap  强制 bootstrap（n 很大时会很慢）
        normal     强制分层正态近似

    返回额外字段：method / variance / mde / discordant，用于 STATS_DESIGN 的披露。
    """
    strata, ids = _strata(candidate, baseline, families)
    n = len(ids)
    if n == 0:
        return {
            "delta": 0.0, "ci95": [0.0, 0.0], "n": 0, "iterations": 0,
            "seed": seed, "families": 0, "method": "empty", "variance": 0.0,
            "mde": 0.0, "discordant": 0,
        }

    if method not in {"auto", "bootstrap", "normal"}:
        raise ValueError(f"未知 method={method!r}；允许 auto/bootstrap/normal")
    resolved = method
    if method == "auto":
        resolved = "bootstrap" if iterations * n <= max_bootstrap_work else "normal"

    point = sum(candidate[i] - baseline[i] for i in ids) / n
    variance = _stratified_variance(strata, n)
    mde = mde_from_variance(variance, alpha=alpha)
    discordant = sum(1 for item_id in ids
                     if candidate[item_id] != baseline[item_id])

    if resolved == "bootstrap":
        stats = paired_bootstrap_delta(candidate, baseline, families,
                                       iterations=iterations, seed=seed, alpha=alpha)
        low, high = stats["ci95"]
    else:
        half = _z_for_alpha(alpha) * math.sqrt(variance)
        low, high = point - half, point + half
        iterations = 0

    return {
        "delta": point,
        "ci95": [max(-1.0, low), min(1.0, high)],
        "n": n,
        "iterations": iterations,
        "seed": seed,
        "families": len(strata),
        "method": resolved,
        "variance": variance,
        "mde": mde,
        "discordant": discordant,
    }
