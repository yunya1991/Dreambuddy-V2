"""N1 维度力量聚合（50 复刻 23 dimension_force_evaluator 设计口径）。

不 import 23，独立实现。输入是 synthesize_paths 产出的 Path 列表，
按 dimension 分组聚合 long/short 力量。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from core.path_synthesis import Path


@dataclass(frozen=True)
class DimensionForce:
    dimension: str
    direction: str  # "long" | "short" | "neutral"
    strength: float  # |net| clamped [0,1]
    long_force: float  # Σ(weight × confidence) for long
    short_force: float  # Σ(weight × confidence) for short
    path_count: int
    degraded: str | None  # 降级原因（预留）


def _path_weight(path: Path) -> float:
    w = path.metadata.get("weight")
    if w is None:
        return 0.0
    try:
        return float(w)
    except (TypeError, ValueError):
        return 0.0


def aggregate_dimension_forces(paths: Iterable[Path]) -> dict[str, DimensionForce]:
    """按 dimension 聚合 long/short 力量。

    - long_force = Σ(weight × confidence) for direction == "long"
    - short_force = Σ(weight × confidence) for direction == "short"
    - net = long_force - short_force
    - direction = sign(net)（net==0 → "neutral"）
    - strength = min(1.0, |net|)
    """
    buckets: dict[str, list[Path]] = {}
    for path in paths:
        buckets.setdefault(path.dimension, []).append(path)

    result: dict[str, DimensionForce] = {}
    for dim, dim_paths in buckets.items():
        long_force = 0.0
        short_force = 0.0
        for p in dim_paths:
            w = _path_weight(p)
            contribution = w * (p.confidence or 0.0)
            if p.direction == "long":
                long_force += contribution
            elif p.direction == "short":
                short_force += contribution
            # neutral / other → 不贡献力量

        net = long_force - short_force
        if net > 0:
            direction = "long"
        elif net < 0:
            direction = "short"
        else:
            direction = "neutral"

        strength = min(1.0, abs(net))
        result[dim] = DimensionForce(
            dimension=dim,
            direction=direction,
            strength=strength,
            long_force=long_force,
            short_force=short_force,
            path_count=len(dim_paths),
            degraded=None,
        )
    return result


def aggregate_micro_forces_by_symbol(
    paths: Iterable[Path],
) -> dict[str, dict[str, float]]:
    """逐标的 × 逐维度 聚合微观有符号力 ∈ [-1, 1]（M2 宏微观对撞用）。

    signed_force = Σ(weight × confidence) for long − Σ(...) for short
    返回 {symbol: {dimension: signed_force}}，各维度独立 clamp 到 [-1, 1]。
    """
    buckets: dict[str, dict[str, float]] = {}
    for p in paths:
        w = _path_weight(p)
        contrib = w * (p.confidence or 0.0)
        if p.direction == "long":
            signed = contrib
        elif p.direction == "short":
            signed = -contrib
        else:
            signed = 0.0
        buckets.setdefault(p.symbol, {}).setdefault(p.dimension, 0.0)
        buckets[p.symbol][p.dimension] += signed

    for sym in buckets:
        for dim in buckets[sym]:
            v = buckets[sym][dim]
            buckets[sym][dim] = max(-1.0, min(1.0, v))
    return buckets
