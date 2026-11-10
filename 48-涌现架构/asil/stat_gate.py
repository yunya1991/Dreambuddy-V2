"""统计门禁：配对 bootstrap 置信区间 + Holm 多重比较校正（零依赖、可复现）。

用途：D3 候选变体与基线在**独立 holdout** 上的 top1 差异必须显著，
且同一轮测试的多个候选共用同一 holdout，需做 family-wise 错误控制。
"""

from __future__ import annotations

import math
import random
from statistics import NormalDist
from typing import Dict, List, Sequence


def wilson_interval(successes: int, n: int, alpha: float = 0.05) -> Dict[str, float]:
    """Wilson 得分区间：小样本比例估计的 95% CI（D2 无 holdout，适用此口径）。"""
    if n <= 0:
        return {"p": 0.0, "ci_low": 0.0, "ci_high": 1.0, "n": 0}
    z = NormalDist().inv_cdf(1 - alpha / 2)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return {
        "p": round(p, 6),
        "ci_low": round(max(0.0, center - margin), 6),
        "ci_high": round(min(1.0, center + margin), 6),
        "n": n,
    }


def evidence_level(n: int) -> str:
    """样本量诚实标注：避免 n=1 的 pass_rate=1.0 被当成结论。"""
    if n < 3:
        return "insufficient"
    if n < 10:
        return "weak"
    return "adequate"


def paired_bootstrap(
    candidate: Sequence[int],
    baseline: Sequence[int],
    n_boot: int = 2000,
    alpha: float = 0.05,
    seed: int = 42,
) -> Dict[str, float]:
    """配对 bootstrap：返回 top1 均值差、双侧 CI 与单侧 p 值（H1: diff > 0）。"""
    n = len(candidate)
    if n == 0 or n != len(baseline):
        return {
            "mean_diff": 0.0,
            "ci_low": 0.0,
            "ci_high": 0.0,
            "p_value": 1.0,
            "n": n,
            "n_boot": 0,
        }

    c = [int(x) for x in candidate]
    b = [int(x) for x in baseline]
    rng = random.Random(seed)
    diffs: List[float] = []
    for _ in range(n_boot):
        total = 0
        for _ in range(n):
            i = rng.randrange(n)
            total += c[i] - b[i]
        diffs.append(total / n)
    diffs.sort()

    lo_idx = max(0, int((alpha / 2) * n_boot))
    hi_idx = min(n_boot - 1, int((1 - alpha / 2) * n_boot))
    # 单侧 p：bootstrap 分布中 <= 0 的比例（加一平滑，避免 p=0）
    p_value = (1 + sum(1 for d in diffs if d <= 0)) / (n_boot + 1)

    return {
        "mean_diff": round(sum(c) / n - sum(b) / n, 6),
        "ci_low": round(diffs[lo_idx], 6),
        "ci_high": round(diffs[hi_idx], 6),
        "p_value": round(p_value, 6),
        "n": n,
        "n_boot": n_boot,
    }


def holm_adjust(pvalues: Sequence[float]) -> List[float]:
    """Holm step-down 校正，返回与输入同序的调整后 p 值。"""
    m = len(pvalues)
    if m == 0:
        return []
    indexed = sorted(range(m), key=lambda i: pvalues[i])
    adjusted = [1.0] * m
    running = 0.0
    for rank, idx in enumerate(indexed):
        value = min(1.0, pvalues[idx] * (m - rank))
        running = max(running, value)
        adjusted[idx] = round(running, 6)
    return adjusted
