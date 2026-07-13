"""三屏趋势系统 — 趋势一致性检测

核心算法：静态指标 + 三维动态融合，动态优先原则

- 静态投票：传统方法，基础判定
- 三维动态：方向 + 速度 + 加速度，捕捉趋势逆转
- 动态优先：逆转信号强时，动态方向覆盖静态方向
- 趋势一致性：周线 vs 日线方向对齐检测
"""

from typing import List, Dict
try:
    from .indicators import (
        calc_indicator_dynamics,
        calc_trend_direction_static,
    )
    from .config import (
        SCREEN1_INDICATORS,
        SCREEN2_INDICATORS,
        WEEKLY_WEIGHT,
        DAILY_WEIGHT,
        REVERSAL_THRESHOLD,
        REVERSAL_SPEED_LOW,
        REVERSAL_ACCEL_HIGH,
    )
except ImportError:
    from indicators import (
        calc_indicator_dynamics,
        calc_trend_direction_static,
    )
    from config import (
        SCREEN1_INDICATORS,
        SCREEN2_INDICATORS,
        WEEKLY_WEIGHT,
        DAILY_WEIGHT,
        REVERSAL_THRESHOLD,
        REVERSAL_SPEED_LOW,
        REVERSAL_ACCEL_HIGH,
    )


def calc_trend_direction_dynamic(df, indicators: List[str]) -> dict:
    """
    计算三维动态指标的趋势方向

    返回:
        {
            "direction": "BULL"/"BEAR"/"REVERSAL_BULL"/"REVERSAL_BEAR"/"NEUTRAL",
            "confidence": 0-100,
            "signals": [{indicator, direction, speed, acceleration}],
            "reversal_score": 0-100,
            "reversal_signals": [...],
            "bull_count": int,
            "bear_count": int,
            "avg_speed": float,
            "avg_acceleration": float,
        }
    """
    signals = []
    reversal_signals = []
    bull_count = 0
    bear_count = 0

    for ind in indicators:
        dyn = calc_indicator_dynamics(df, ind)
        signals.append({
            "indicator": ind,
            "direction": dyn["direction"],
            "speed": dyn["speed"],
            "acceleration": dyn["acceleration"],
        })
        if dyn["direction"] == "BULL":
            bull_count += 1
        elif dyn["direction"] == "BEAR":
            bear_count += 1

        # 逆转检测：仅在明确方向（BULL/BEAR）时检测，NEUTRAL 不参与
        if dyn["direction"] == "BULL":
            if dyn["speed"] < REVERSAL_SPEED_LOW and dyn["acceleration"] > REVERSAL_ACCEL_HIGH:
                reversal_signals.append({"indicator": ind, "type": "potential_reversal_bear"})
        elif dyn["direction"] == "BEAR":
            if dyn["speed"] < REVERSAL_SPEED_LOW and dyn["acceleration"] > REVERSAL_ACCEL_HIGH:
                reversal_signals.append({"indicator": ind, "type": "potential_reversal_bull"})

    reversal_score = min(100, len(reversal_signals) / len(indicators) * 100) if indicators else 0

    if bull_count > bear_count:
        base_direction = "BULL"
        count = bull_count
    elif bear_count > bull_count:
        base_direction = "BEAR"
        count = bear_count
    else:
        base_direction = "NEUTRAL"
        count = max(bull_count, bear_count)

    if reversal_score > 50:
        if base_direction == "BULL":
            final_direction = "REVERSAL_BEAR"
        elif base_direction == "BEAR":
            final_direction = "REVERSAL_BULL"
        else:
            final_direction = base_direction
    else:
        final_direction = base_direction

    avg_speed = sum(s["speed"] for s in signals) / len(signals) if signals else 0
    avg_accel = sum(s["acceleration"] for s in signals) / len(signals) if signals else 0
    confidence = min(100, 50 + count * 10 + (avg_speed + avg_accel) / 200 * 20)

    return {
        "direction": final_direction,
        "confidence": round(confidence, 1),
        "signals": signals,
        "reversal_score": round(reversal_score, 1),
        "reversal_signals": reversal_signals,
        "bull_count": bull_count,
        "bear_count": bear_count,
        "avg_speed": round(avg_speed, 1),
        "avg_acceleration": round(avg_accel, 1),
    }


def _core_direction(d: str) -> str:
    """提取核心方向（去除 REVERSAL_ 前缀）"""
    if d.startswith("REVERSAL_"):
        return "BULL" if d == "REVERSAL_BULL" else "BEAR"
    return d


def calc_trend_consistency(weekly_df, daily_df) -> dict:
    """
    趋势一致性计算（静态 + 三维动态融合）

    动态优先原则：
    - 逆转信号 > 60% → 以动态方向为准（覆盖静态）
    - 动态方向 = NEUTRAL → 以静态方向为准（回退）
    - 其他情况 → 以动态方向为准

    返回:
        {
            "weekly": {static_direction, dynamic_direction, final_direction, core_direction, confidence, ...},
            "daily": {static_direction, dynamic_direction, final_direction, core_direction, confidence, ...},
            "consistent": bool,
            "overall_direction": "BULL"/"BEAR"/"NEUTRAL",
            "consistency_confidence": 0-100,
        }
    """
    weekly_static = calc_trend_direction_static(weekly_df, SCREEN1_INDICATORS)
    weekly_dynamic = calc_trend_direction_dynamic(weekly_df, SCREEN1_INDICATORS)

    if weekly_dynamic["reversal_score"] > REVERSAL_THRESHOLD:
        weekly_final = weekly_dynamic["direction"]
    elif weekly_dynamic["direction"] == "NEUTRAL":
        weekly_final = weekly_static
    else:
        weekly_final = weekly_dynamic["direction"]

    daily_static = calc_trend_direction_static(daily_df, SCREEN2_INDICATORS)
    daily_dynamic = calc_trend_direction_dynamic(daily_df, SCREEN2_INDICATORS)

    if daily_dynamic["reversal_score"] > REVERSAL_THRESHOLD:
        daily_final = daily_dynamic["direction"]
    elif daily_dynamic["direction"] == "NEUTRAL":
        daily_final = daily_static
    else:
        daily_final = daily_dynamic["direction"]

    weekly_core = _core_direction(weekly_final)
    daily_core = _core_direction(daily_final)

    # 趋势一致性判断：
    # - 周线与日线同向 → 一致
    # - 周线 NEUTRAL → 不阻断日线，视为"弱一致"（周线无意见，日线主导）
    # - 周线与日线反向 → 不一致
    if weekly_core == daily_core and weekly_core != "NEUTRAL":
        consistent = True
    elif weekly_core == "NEUTRAL" and daily_core != "NEUTRAL":
        consistent = True  # 周线中性时不阻断日线信号
    else:
        consistent = False

    if consistent:
        if weekly_core == "NEUTRAL":
            # 周线中性时，置信度以日线为主（降权处理）
            consistency_confidence = round(
                daily_dynamic["confidence"] * DAILY_WEIGHT +
                weekly_dynamic["confidence"] * WEEKLY_WEIGHT * 0.3, 1
            )
        else:
            consistency_confidence = round(
                weekly_dynamic["confidence"] * WEEKLY_WEIGHT +
                daily_dynamic["confidence"] * DAILY_WEIGHT, 1
            )
    else:
        consistency_confidence = round(
            min(weekly_dynamic["confidence"], daily_dynamic["confidence"]) * 0.5, 1
        )

    return {
        "weekly": {
            "static_direction": weekly_static,
            "dynamic_direction": weekly_dynamic["direction"],
            "final_direction": weekly_final,
            "core_direction": weekly_core,
            "confidence": weekly_dynamic["confidence"],
            "reversal_score": weekly_dynamic["reversal_score"],
            "bull_count": weekly_dynamic["bull_count"],
            "bear_count": weekly_dynamic["bear_count"],
            "avg_speed": weekly_dynamic["avg_speed"],
            "avg_acceleration": weekly_dynamic["avg_acceleration"],
            "signals": weekly_dynamic["signals"],
        },
        "daily": {
            "static_direction": daily_static,
            "dynamic_direction": daily_dynamic["direction"],
            "final_direction": daily_final,
            "core_direction": daily_core,
            "confidence": daily_dynamic["confidence"],
            "reversal_score": daily_dynamic["reversal_score"],
            "bull_count": daily_dynamic["bull_count"],
            "bear_count": daily_dynamic["bear_count"],
            "avg_speed": daily_dynamic["avg_speed"],
            "avg_acceleration": daily_dynamic["avg_acceleration"],
            "signals": daily_dynamic["signals"],
        },
        "consistent": consistent,
        "overall_direction": daily_core if (consistent and weekly_core == "NEUTRAL") else (weekly_core if consistent else "NEUTRAL"),
        "consistency_confidence": consistency_confidence,
    }
