"""三屏对齐：按时间窗口划分事件，计算各屏趋势与对齐度。"""

from dataclasses import dataclass
from typing import Dict, List

from .types import CleanedEvent, ScreenResult


@dataclass
class ScreenConfig:
    long_window: int = 20   # 类比周线
    mid_window: int = 10    # 类比日线
    short_window: int = 5   # 类比 1h


def compute_triple_screen(
    events: List[CleanedEvent],
    config: ScreenConfig = ScreenConfig(),
) -> Dict:
    """三屏对齐。

    返回:
    {
        "long": ScreenResult, "mid": ScreenResult, "short": ScreenResult,
        "alignment": float,  # -1 ~ 1
        "trend_state": str,
    }
    """
    long_screen = _compute_screen(events[-config.long_window:], "long")
    mid_screen = _compute_screen(events[-config.mid_window:], "mid")
    short_screen = _compute_screen(events[-config.short_window:], "short")

    dirs = [long_screen.direction, mid_screen.direction, short_screen.direction]

    # 对齐度
    if len(set(dirs)) == 1 and dirs[0] != "FLAT":
        alignment = 1.0
    elif dirs.count(dirs[0]) >= 2:
        alignment = 0.3
    else:
        alignment = -0.3

    # 趋势状态
    if alignment > 0.5:
        trend_state = long_screen.direction
    elif alignment > 0:
        trend_state = mid_screen.direction
    else:
        trend_state = "TRANSITIONING"

    return {
        "long": long_screen,
        "mid": mid_screen,
        "short": short_screen,
        "alignment": round(alignment, 4),
        "trend_state": trend_state,
    }


def _compute_screen(window: List[CleanedEvent], timeframe: str) -> ScreenResult:
    """计算单屏趋势。"""
    if not window:
        return ScreenResult(
            timeframe=timeframe, direction="FLAT", confidence=0,
            x_mean=0, y_mean=0, profit_rate=0, case_count=0,
        )

    x_mean = sum(e.quadrant_x for e in window) / len(window)
    y_mean = sum(e.quadrant_y for e in window) / len(window)
    profits = sum(1 for e in window if e.is_profit is True)
    profit_rate = profits / len(window)

    # 方向判断
    if x_mean > 0.1:
        direction = "UP"
    elif x_mean < -0.1:
        direction = "DOWN"
    else:
        direction = "FLAT"

    # 置信度 = y_mean * 覆盖率 * 盈利方向一致性
    profit_alignment = 1.0 if (
        (x_mean > 0 and profit_rate > 0.5) or
        (x_mean < 0 and profit_rate < 0.5)
    ) else 0.5
    confidence = y_mean * min(1.0, len(window) / 20) * profit_alignment

    return ScreenResult(
        timeframe=timeframe,
        direction=direction,
        confidence=round(max(0, min(1, confidence)), 4),
        x_mean=round(x_mean, 4),
        y_mean=round(y_mean, 4),
        profit_rate=round(profit_rate, 4),
        case_count=len(window),
    )
