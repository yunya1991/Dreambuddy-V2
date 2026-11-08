# R2-02: 4 维裁决（50 SPEC §4.4，独立实现，沿用 23 架构设计口径）。
#
# 四维权重（预注册固定值）：力量对比 0.40 / 时间紧迫性 0.15 / 证据一致性 0.25 / 市场影响 0.20。
# 证据一致性直接消费内部 vs 42 的对账结果：一致 -> 置信度 x1.0~1.15；分歧 -> x0.85~0.95 + conflict_flag。
# 共振阈值 0.6；主导阈值 0.55。
# 纯函数：不读文件、不写状态。
from __future__ import annotations

from typing import Any, Iterable

from core.path_synthesis import Path

# 四维权重（SPEC §4.4 预注册固定值）
W_FORCE = 0.40
W_URGENCY = 0.15
W_CONSISTENCY = 0.25
W_IMPACT = 0.20

# 阈值（沿用 23 架构设计口径，独立实现）
RESONANCE_THRESHOLD = 0.6
DOMINANCE_THRESHOLD = 0.55


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def force_score(paths: list[Path]) -> float:
    # 力量对比：多空双方加权置信度对比（外部证据权重求和，方向归一）。
    if not paths:
        return 0.5
    long_force = 0.0
    short_force = 0.0
    for p in paths:
        w = float(p.metadata.get("weight") or 0.0)
        if p.direction == "long":
            long_force += w * p.confidence
        elif p.direction == "short":
            short_force += w * p.confidence
    total = long_force + short_force
    if total <= 0:
        return 0.5
    return _clamp(long_force / total)


def urgency_score(paths: list[Path]) -> float:
    # 时间紧迫性：短 horizon + 高 continuation 的路径更紧迫。
    if not paths:
        return 0.0
    horizon_urgency = {"minutes": 1.0, "hours": 0.6, "days": 0.3, "weeks": 0.1}
    best = 0.0
    for p in paths:
        u = horizon_urgency.get(p.horizon, 0.3)
        best = max(best, _clamp(u * p.continuation_score))
    return best


def consistency_score(paths: list[Path], reconciliation: dict[str, Any] | None) -> tuple[float, bool]:
    # 证据一致性：内部 vs 42 对账结果调制置信度（一致 x1.0~1.15；分歧 x0.85~0.95 + conflict_flag）。
    # 返回 (score, conflict_flag)。
    rec = reconciliation or {}
    agree = rec.get("agreement")
    ratio = rec.get("agreement_ratio")
    if agree is None and ratio is None:
        # 无对账数据：fail-open，中性 0.5，不打 conflict_flag
        return 0.5, False
    if ratio is not None:
        base = _clamp(float(ratio))
    else:
        base = 1.0 if agree else 0.0
    if base >= 0.5:
        # 一致区间：乘数从 x1.0（base=0.5）线性升至 x1.15（base=1.0）
        mult = 1.0 + 0.15 * (base - 0.5) / 0.5
        return _clamp(base * mult), False
    # 分歧区间：乘数从 x0.95（base=0.5）线性降至 x0.85（base=0.0），打 conflict_flag
    mult = 0.95 - 0.10 * (0.5 - base) / 0.5
    return _clamp(base * mult), True


def impact_score(paths: list[Path]) -> float:
    # 市场影响：高置信度路径的加权覆盖面（多少维度/源参与）。
    if not paths:
        return 0.0
    dimensions = {p.dimension for p in paths}
    sources = {p.source for p in paths}
    coverage = _clamp(len(dimensions) / 4.0) * 0.5 + _clamp(len(sources) / 5.0) * 0.5
    peak = max(p.confidence for p in paths)
    return _clamp(coverage * peak)


def adjudicate(
    paths: Iterable[Path],
    reconciliation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # 4 维裁决主入口：paths -> 四维分数 + 加权总分 + 共振/主导判定。
    items = [p for p in paths if isinstance(p, Path)]
    f = force_score(items)
    u = urgency_score(items)
    c, conflict = consistency_score(items, reconciliation)
    m = impact_score(items)
    total = W_FORCE * f + W_URGENCY * u + W_CONSISTENCY * c + W_IMPACT * m
    if f > 0.5:
        direction = "long"
    elif f < 0.5:
        direction = "short"
    else:
        direction = "neutral"
    return {
        "force": round(f, 6),
        "urgency": round(u, 6),
        "consistency": round(c, 6),
        "impact": round(m, 6),
        "total": round(total, 6),
        "direction": direction,
        "resonance": total >= RESONANCE_THRESHOLD,
        "dominant": total >= DOMINANCE_THRESHOLD,
        "conflict_flag": conflict,
        "weights": {"force": W_FORCE, "urgency": W_URGENCY, "consistency": W_CONSISTENCY, "impact": W_IMPACT},
        "thresholds": {"resonance": RESONANCE_THRESHOLD, "dominance": DOMINANCE_THRESHOLD},
        "path_count": len(items),
    }
