"""趋势速度 + 变化点检测：从 quadrant(x,y) 时间序列计算。"""

import statistics
from typing import Dict, List

from .types import CleanedEvent


def compute_trend_velocity(events: List[CleanedEvent]) -> Dict:
    """三维速度 + 加速度 + 变化点检测。

    返回:
    {
        "velocity": {"price": float, "confidence": float},
        "acceleration": {"price": float},
        "change_point": str,
    }
    """
    if len(events) < 2:
        return {
            "velocity": {"price": 0, "confidence": 0},
            "acceleration": {"price": 0},
            "change_point": "STABLE",
        }

    # 速度 = d(x)/dt (按事件顺序，dt=1 step)
    velocities: List[float] = []
    for i in range(1, len(events)):
        velocities.append(events[i].quadrant_x - events[i - 1].quadrant_x)

    # 加速度 = d(v)/dt
    accelerations: List[float] = []
    for i in range(1, len(velocities)):
        accelerations.append(velocities[i] - velocities[i - 1])

    v_latest = velocities[-1] if velocities else 0
    a_latest = accelerations[-1] if accelerations else 0

    # 速度稳定性（最近 3 个速度的 stdev 倒数）
    recent_v = velocities[-3:] if len(velocities) >= 3 else velocities
    v_confidence = (
        1.0 / (1.0 + statistics.stdev(recent_v))
        if len(recent_v) >= 2
        else 0.5
    )

    # 变化点检测
    eps = 0.001
    change_point = _detect_change_point(v_latest, a_latest, velocities, eps)

    return {
        "velocity": {
            "price": round(v_latest, 4),
            "confidence": round(v_confidence, 4),
        },
        "acceleration": {"price": round(a_latest, 4)},
        "change_point": change_point,
    }


def _detect_change_point(
    v: float, a: float, velocities: List[float], eps: float
) -> str:
    """检测趋势变化点。"""
    if abs(v) < eps and abs(a) < eps:
        return "STABLE"
    if v * a > 0 and abs(a) > eps:
        return "ACCELERATING"
    if v * a < 0 and abs(a) > eps:
        return "DECELERATING"
    if len(velocities) >= 3 and _sign(velocities[-1]) != _sign(velocities[-3]):
        return "REVERSING"
    return "STABLE"


def _sign(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)
