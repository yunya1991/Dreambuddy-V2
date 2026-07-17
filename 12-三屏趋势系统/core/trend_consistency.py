"""三屏趋势系统 — 趋势一致性检测

核心算法：静态指标 + 三维动态融合，动态优先原则

- 静态投票：传统方法，基础判定
- 三维动态：方向 + 速度 + 加速度，捕捉趋势逆转
- 动态优先：逆转信号强时，动态方向覆盖静态方向
- 趋势一致性：周线 vs 日线方向对齐检测
"""

from typing import List, Dict, Optional
from datetime import datetime
import pandas as pd
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
        FUNDAMENTAL_SCREEN1_ENABLED,
        FUNDAMENTAL_TECH_WEIGHT,
        FUNDAMENTAL_FUND_WEIGHT,
        LEAST_RESISTANCE_ENABLED,
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
        FUNDAMENTAL_SCREEN1_ENABLED,
        FUNDAMENTAL_TECH_WEIGHT,
        FUNDAMENTAL_FUND_WEIGHT,
        LEAST_RESISTANCE_ENABLED,
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


def calc_reversal_persistence(df, indicators: List[str], lookback: int = 10) -> dict:
    """计算逆转信号的连续累积强度（P1 新增）

    逆转检测原本是瞬时的，本函数遍历最近 N 个历史切片，
    统计连续出现逆转信号的天数，用于增强逆转可信度。

    设计原则：
    - 单日逆转可能是噪声，连续多日逆转增强可信度
    - 连续 3 日逆转 → 可信度 ×1.5
    - 连续 5 日逆转 → 可信度 ×2.0（上限）
    - 中断后重新计数

    参数:
        df: DataFrame（日线或周线）
        indicators: 指标列表
        lookback: 回看天数（默认10）

    返回:
        {
            "persistence_count": int,          # 当前连续逆转天数
            "persistence_boost": float,        # 可信度增强因子(1.0~2.0)
            "reversal_history": list[bool],    # 最近N日是否出现逆转信号
            "max_persistence": int,            # 回看窗口内最大连续逆转天数
        }
    """
    history = []
    max_persistence = 0
    current_persistence = 0

    # 限制回看窗口不超过数据长度
    n = len(df)
    lookback = min(lookback, n - 1)
    if lookback < 1:
        return {
            "persistence_count": 0,
            "persistence_boost": 1.0,
            "reversal_history": [],
            "max_persistence": 0,
        }

    # 遍历最近 lookback 天，每天计算逆转 score
    start_idx = max(1, n - lookback)
    for i in range(start_idx, n):
        try:
            slice_df = df.iloc[:i + 1]
            dyn = calc_trend_direction_dynamic(slice_df, indicators)
            is_reversal = dyn["reversal_score"] > 50
            history.append(is_reversal)

            if is_reversal:
                current_persistence += 1
                max_persistence = max(max_persistence, current_persistence)
            else:
                current_persistence = 0
        except Exception:
            history.append(False)
            current_persistence = 0

    # 当前连续逆转天数（最后一天是否在持续逆转中）
    persistence_count = current_persistence

    # 可信度增强因子：连续3日×1.5，连续5日×2.0（上限）
    if persistence_count >= 5:
        persistence_boost = 2.0
    elif persistence_count >= 3:
        persistence_boost = 1.5
    elif persistence_count >= 2:
        persistence_boost = 1.2
    else:
        persistence_boost = 1.0

    return {
        "persistence_count": persistence_count,
        "persistence_boost": round(persistence_boost, 2),
        "reversal_history": history,
        "max_persistence": max_persistence,
    }


def detect_trend_phase(df, indicators: List[str], lookback: int = 10) -> dict:
    """趋势生命周期阶段检测（P2-v2：基于Elder-ray理论）

    使用 Elder-ray 高级分析替代原 speed/accel 方式，检测趋势处于哪个生命周期阶段。

    理论基础（Alexander Elder 三重滤网第二屏）：
    - EMA(13) 斜率 = 趋势方向（共识价值的移动）
    - Bull Power / Bear Power = 多空力量对比
    - 背离信号 = 趋势衰竭预警
    - 失控信号 = 趋势末端确认

    四阶段模型：
    - EARLY（启动阶段）: EMA斜率较缓但开始转向，力量开始积累
    - ACCELERATING（加速阶段）: EMA趋势明确，主导力量增强，对手失控
    - MATURING（成熟/衰竭阶段）: EMA趋势仍在但背离出现，双方力量均减弱
    - REVERSING（逆转阶段）: EMA走平，背离+失控信号确认反转

    参数:
        df: DataFrame（日线或周线）
        indicators: 指标列表（保留接口兼容，实际使用Elder-ray）
        lookback: 背离检测回看窗口（默认10）

    返回:
        {
            "phase": str,              # EARLY / ACCELERATING / MATURING / REVERSING / UNKNOWN
            "phase_confidence": float, # 0-100，阶段判定置信度
            "ema_trend": str,          # EMA斜率方向 BULL/BEAR/NEUTRAL
            "bull_power": float,       # 当前多头力量
            "bear_power": float,       # 当前空头力量
            "bull_divergence": bool,   # 看跌背离
            "bear_divergence": bool,   # 看涨背离
            "bull_losing_control": bool,  # 多头失控
            "bear_losing_control": bool,  # 空头失控
            "both_weakening": bool,    # 多空力量均减弱
            "setup_score": float,      # 综合入场setup评分 0-100
        }
    """
    try:
        from .indicators import calc_elder_ray_advanced
    except ImportError:
        from indicators import calc_elder_ray_advanced

    er = calc_elder_ray_advanced(df, period=13, lookback=max(lookback, 10))

    return {
        "phase": er["phase"],
        "phase_confidence": er["phase_confidence"],
        "ema_trend": er["ema_trend"],
        "bull_power": er["bull_power"],
        "bear_power": er["bear_power"],
        "bull_divergence": er["bull_divergence"]["detected"],
        "bear_divergence": er["bear_divergence"]["detected"],
        "bull_divergence_strength": er["bull_divergence"]["strength"],
        "bear_divergence_strength": er["bear_divergence"]["strength"],
        "bull_losing_control": er["bull_losing_control"],
        "bear_losing_control": er["bear_losing_control"],
        "both_weakening": er["both_weakening"],
        "setup_score": er["setup_score"],
        # 保留原接口字段（向后兼容）
        "speed_trend": "RISING" if er["ema_trend"] == "BULL" else ("FALLING" if er["ema_trend"] == "BEAR" else "FLAT"),
        "accel_trend": "RISING" if er["both_weakening"] else "FLAT",
        "current_speed": abs(er["bull_power"]) + abs(er["bear_power"]),
        "current_accel": er["setup_score"] / 10,
        "speed_change": 0.0,
        "accel_change": 0.0,
    }


def calc_trend_consistency(weekly_df, daily_df, use_fundamental: Optional[bool] = None) -> dict:
    """
    趋势一致性计算（静态 + 三维动态融合 + 基本面融合）

    动态优先原则：
    - 逆转信号 > 60% → 以动态方向为准（覆盖静态）
    - 动态方向 = NEUTRAL → 以静态方向为准（回退）
    - 其他情况 → 以动态方向为准

    P0 改进：一致性分级（保持 consistent: bool 向后兼容）
    - STRONG_CONSISTENT: 周线与日线同向且非逆转（常规趋势跟随）
    - REVERSAL_CONSISTENT: 周线或日线处于动态逆转中（允许轻仓试探反向）
    - NEUTRAL_CONSISTENT: 周线中性，日线主导（弱一致）
    - INCONSISTENT: 周线与日线反向且无逆转信号

    基本面融合（可回退）：
    - use_fundamental=True 时，周线方向融合基本面 7 维分析
    - 基本面数据不可用时自动回退到纯技术分析
    - use_fundamental=False 时，完全使用纯技术分析（基线策略）

    返回:
        {
            "weekly": {static_direction, dynamic_direction, final_direction, core_direction, confidence, ...},
            "daily": {static_direction, dynamic_direction, final_direction, core_direction, confidence, ...},
            "consistent": bool,
            "consistency_level": str,
            "reversal_alignment": str,
            "overall_direction": "BULL"/"BEAR"/"NEUTRAL",
            "consistency_confidence": 0-100,
            "reversal_confidence": 0-100,
            "fundamental_fusion": {...},   # 基本面融合结果
        }
    """
    # 基本面开关：默认从 config 读取
    if use_fundamental is None:
        use_fundamental = FUNDAMENTAL_SCREEN1_ENABLED

    weekly_static = calc_trend_direction_static(weekly_df, SCREEN1_INDICATORS)
    weekly_dynamic = calc_trend_direction_dynamic(weekly_df, SCREEN1_INDICATORS)

    if weekly_dynamic["reversal_score"] > REVERSAL_THRESHOLD:
        weekly_final = weekly_dynamic["direction"]
    elif weekly_dynamic["direction"] == "NEUTRAL":
        weekly_final = weekly_static
    else:
        weekly_final = weekly_dynamic["direction"]

    # ── 基本面融合层（可回退）──
    fundamental_fusion = None
    if use_fundamental:
        try:
            from .fundamental_screen1 import calc_fundamental_screen1, fuse_tech_fundamental
        except ImportError:
            try:
                from fundamental_screen1 import calc_fundamental_screen1, fuse_tech_fundamental
            except ImportError:
                calc_fundamental_screen1 = None
                fuse_tech_fundamental = None

        if calc_fundamental_screen1 and fuse_tech_fundamental:
            # 从周线数据推断当前日期
            current_date = None
            if "date" in weekly_df.columns and len(weekly_df) > 0:
                try:
                    current_date = pd.to_datetime(weekly_df["date"].iloc[-1]).to_pydatetime()
                except Exception:
                    pass

            fundamental = calc_fundamental_screen1(current_date)

            # 提取技术方向和置信度
            tech_core = _core_direction(weekly_final)
            tech_conf = weekly_dynamic.get("confidence", 50.0)

            # 融合
            fundamental_fusion = fuse_tech_fundamental(
                tech_direction=tech_core,
                tech_confidence=tech_conf,
                fundamental=fundamental,
                tech_weight=FUNDAMENTAL_TECH_WEIGHT,
                fundamental_weight=FUNDAMENTAL_FUND_WEIGHT,
            )

            # 如果基本面融合成功且方向变化，更新周线方向
            if fundamental_fusion.get("fused", False) and fundamental_fusion.get("fundamental_available", False):
                fused_dir = fundamental_fusion["direction"]
                if fused_dir != tech_core and fused_dir != "NEUTRAL":
                    # 基本面改变了方向（仅在基本面更明确时）
                    if fundamental_fusion.get("conflict", False):
                        # 技术与基本面冲突 → 降低置信度但不改变方向
                        pass
                    else:
                        # 同向增强 → 保持方向，提升置信度
                        pass
                # 更新周线置信度
                weekly_dynamic["confidence"] = fundamental_fusion["confidence"]

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

    # ── P0 改进：逆转检测 ──
    weekly_is_reversal = weekly_final.startswith("REVERSAL_")
    daily_is_reversal = daily_final.startswith("REVERSAL_")

    if weekly_is_reversal and daily_is_reversal:
        reversal_alignment = "BOTH_REVERSAL"
    elif weekly_is_reversal:
        reversal_alignment = "WEEKLY_REVERSAL"
    elif daily_is_reversal:
        reversal_alignment = "DAILY_REVERSAL"
    else:
        reversal_alignment = "NONE"

    # ── P2-v3: Elder-ray 背离作为动态趋势一致性判定的核心依据 ──
    # 核心思想：Elder-ray 背离本身就代表一种趋势到另一种趋势的切换，就是动态趋势
    # 因此背离信号可以直接作为一致性判定的依据，而不仅仅是 INCONSISTENT 时的补充
    #
    # 判定逻辑：
    # 1. 周线BULL + 日线看涨背离 → 日线正从跌转涨（动态趋势向上切换）→ 与周线一致
    # 2. 周线BEAR + 日线看跌背离 → 日线正从涨转跌（动态趋势向下切换）→ 与周线一致
    # 3. 周线BEAR + 日线看涨背离 → 日线正在筑底（动态趋势向上切换）→ 与周线反向（逆转信号）
    # 4. 周线BULL + 日线看跌背离 → 日线正在筑顶（动态趋势向下切换）→ 与周线反向（逆转信号）
    elder_divergence_confirm = False
    er_daily = None
    try:
        from .indicators import calc_elder_ray_advanced
    except ImportError:
        from indicators import calc_elder_ray_advanced

    if weekly_core != "NEUTRAL":
        try:
            er_daily = calc_elder_ray_advanced(daily_df, period=13, lookback=20)
            er_bull_div = er_daily.get("bull_divergence", {}).get("detected", False)
            er_bear_div = er_daily.get("bear_divergence", {}).get("detected", False)

            # 背离方向与周线方向一致 → 动态趋势正在向周线方向切换 → 逆转一致
            if weekly_core == "BULL" and er_bear_div:
                # 周线看多 + 日线看涨背离 → 日线筑底 → 趋势向上切换中
                elder_divergence_confirm = True
                daily_is_reversal = True
            elif weekly_core == "BEAR" and er_bull_div:
                # 周线看空 + 日线看跌背离 → 日线筑顶 → 趋势向下切换中
                elder_divergence_confirm = True
                daily_is_reversal = True
        except Exception:
            elder_divergence_confirm = False
            er_daily = None

    # ── P0 改进：一致性分级（融入 Elder-ray 动态趋势判定）──
    if weekly_core == daily_core and weekly_core != "NEUTRAL":
        # 周线与日线同向
        if reversal_alignment == "NONE" and not elder_divergence_confirm:
            consistency_level = "STRONG_CONSISTENT"
            consistent = True
        else:
            # 同向但有逆转信号（动态逆转或 Elder-ray 背离）→ 逆转一致
            consistency_level = "REVERSAL_CONSISTENT"
            consistent = True
    elif weekly_core == "NEUTRAL" and daily_core != "NEUTRAL":
        consistency_level = "NEUTRAL_CONSISTENT"
        consistent = True
    elif reversal_alignment != "NONE" or elder_divergence_confirm:
        # 周线与日线反向，但存在动态逆转信号或 Elder-ray 背离 → 逆转一致
        # 核心：Elder-ray 背离本身就是动态趋势切换的判定依据
        consistency_level = "REVERSAL_CONSISTENT"
        consistent = True
    else:
        consistency_level = "INCONSISTENT"
        consistent = False

    # ── 置信度计算 ──
    if consistent:
        if weekly_core == "NEUTRAL":
            # 周线中性时，置信度以日线为主（降权处理）
            consistency_confidence = round(
                daily_dynamic["confidence"] * DAILY_WEIGHT +
                weekly_dynamic["confidence"] * WEEKLY_WEIGHT * 0.3, 1
            )
        elif consistency_level == "REVERSAL_CONSISTENT":
            # 逆转一致：使用动态置信度加权，整体降权（不确定性高）
            # P2-v3 改进：Elder-ray 背离确认时，降权幅度更小（0.85 vs 0.7）
            # 因为背离是趋势切换的可靠信号，置信度不应过度降权
            rev_weight = 0.85 if elder_divergence_confirm else 0.7
            consistency_confidence = round(
                (weekly_dynamic["confidence"] * WEEKLY_WEIGHT +
                 daily_dynamic["confidence"] * DAILY_WEIGHT) * rev_weight, 1
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

    # ── P0 改进：逆转置信度（仅 REVERSAL_CONSISTENT 时有意义）──
    # ── P1 改进：逆转信号累积增强（连续N日逆转增强可信度）──
    # ── P2-v3 改进：Elder-ray 背离作为动态趋势切换的核心判据，大幅提升逆转置信度 ──
    if consistency_level == "REVERSAL_CONSISTENT":
        # 逆转置信度 = 逆转 score 加权平均
        w_rev_score = weekly_dynamic["reversal_score"]
        d_rev_score = daily_dynamic["reversal_score"]

        # P2-v3: Elder-ray 背离确认时，用背离强度大幅提升逆转置信度
        # 背离本身就是趋势切换信号，应给予更高权重（×1.5 增强因子）
        if elder_divergence_confirm and er_daily is not None:
            if weekly_core == "BULL":
                er_div_strength = er_daily.get("bear_divergence", {}).get("strength", 0.0)
            else:
                er_div_strength = er_daily.get("bull_divergence", {}).get("strength", 0.0)
            # 背离强度直接作为逆转分数，并额外加成 50%
            d_rev_score = max(d_rev_score, er_div_strength) * 1.5
            w_rev_score = max(w_rev_score, er_div_strength * 0.5)

        # 动态速度+加速度增强逆转可信度
        w_dyn_factor = min(1.0, (weekly_dynamic["avg_speed"] + weekly_dynamic["avg_acceleration"]) / 200)
        d_dyn_factor = min(1.0, (daily_dynamic["avg_speed"] + daily_dynamic["avg_acceleration"]) / 200)

        reversal_confidence = round(
            (w_rev_score * WEEKLY_WEIGHT * (0.5 + w_dyn_factor * 0.5) +
             d_rev_score * DAILY_WEIGHT * (0.5 + d_dyn_factor * 0.5)), 1
        )

        # P1: 逆转信号累积增强
        # 连续逆转可显著增强可信度，单日逆转可能是噪声
        w_persistence = calc_reversal_persistence(weekly_df, SCREEN1_INDICATORS, lookback=8)
        d_persistence = calc_reversal_persistence(daily_df, SCREEN2_INDICATORS, lookback=10)

        # 取周线/日线累积增强的较大值作为整体增强因子
        w_boost = w_persistence["persistence_boost"]
        d_boost = d_persistence["persistence_boost"]
        combined_boost = max(w_boost, d_boost)

        if combined_boost > 1.0:
            reversal_confidence = round(min(100.0, reversal_confidence * combined_boost), 1)

        # 存储累积信息到返回结果
        weekly_persistence = w_persistence
        daily_persistence = d_persistence
    else:
        reversal_confidence = 0.0
        weekly_persistence = None
        daily_persistence = None

    # ── overall_direction：逆转状态下使用逆转方向 ──
    if consistency_level == "REVERSAL_CONSISTENT":
        # P2-v3: Elder-ray 背离确认时，方向指向周线方向
        # 因为背离确认的是"日线正从反向切换到周线方向" → 最终方向 = 周线方向
        if elder_divergence_confirm:
            overall_direction = weekly_core
        elif weekly_is_reversal and daily_is_reversal:
            overall_direction = weekly_core if weekly_dynamic["reversal_score"] >= daily_dynamic["reversal_score"] else daily_core
        elif weekly_is_reversal:
            overall_direction = weekly_core
        else:
            overall_direction = daily_core
    elif consistency_level == "NEUTRAL_CONSISTENT":
        overall_direction = daily_core
    elif consistency_level == "STRONG_CONSISTENT":
        overall_direction = weekly_core
    else:
        overall_direction = "NEUTRAL"

    # ── P2: 趋势生命周期阶段检测 ──
    weekly_phase = detect_trend_phase(weekly_df, SCREEN1_INDICATORS, lookback=8)
    daily_phase = detect_trend_phase(daily_df, SCREEN2_INDICATORS, lookback=10)

    # 综合阶段：日线阶段为主，周线阶段确认（日线更灵敏，周线更可靠）
    if daily_phase["phase"] == weekly_phase["phase"] and daily_phase["phase"] != "UNKNOWN":
        combined_phase = daily_phase["phase"]
        combined_phase_conf = max(daily_phase["phase_confidence"], weekly_phase["phase_confidence"])
    elif daily_phase["phase"] != "UNKNOWN":
        combined_phase = daily_phase["phase"]
        combined_phase_conf = daily_phase["phase_confidence"]
    elif weekly_phase["phase"] != "UNKNOWN":
        combined_phase = weekly_phase["phase"]
        combined_phase_conf = weekly_phase["phase_confidence"]
    else:
        combined_phase = "UNKNOWN"
        combined_phase_conf = 0.0

    # ── Phase 3.5: 最小阻力方向引擎 — 纯算法驱动（第一性原理）──
    # 静态指标投票已被移除，最小阻力三维模型（时间三维×五维阻力）为唯一驱动
    least_resistance = None
    if LEAST_RESISTANCE_ENABLED:
        try:
            from .least_resistance import compute_least_resistance_3d
        except ImportError:
            try:
                from least_resistance import compute_least_resistance_3d
            except ImportError:
                compute_least_resistance_3d = None

        if compute_least_resistance_3d:
            try:
                lr_fundamental = None
                if fundamental_fusion and fundamental_fusion.get("fundamental_available"):
                    lr_fundamental = fundamental_fusion.get("fundamental_data", None)

                lr_3d = compute_least_resistance_3d(
                    weekly_df, daily_df, fundamental_data=lr_fundamental,
                )

                lr_dir = lr_3d["direction"]
                lr_conf = lr_3d["confidence"]
                lr_velocity = lr_3d["velocity"]
                lr_acceleration = lr_3d["acceleration"]
                lr_entry = lr_3d["entry_signal"]
                lr_dir_diff = lr_3d["direction_diff"]

                least_resistance = {
                    "overall_direction": lr_dir,
                    "consistency_confidence": lr_conf,
                    "consistent": lr_dir != "NEUTRAL" and lr_dir_diff > 0,
                    "velocity": lr_velocity,
                    "acceleration": lr_acceleration,
                    "entry_signal": lr_entry,
                    "direction_diff": lr_dir_diff,
                    "trend_strength": lr_3d.get("trend_strength", 0),
                    "trend_duration": lr_3d.get("trend_duration", 0),
                    "drive_mode": lr_3d.get("drive_mode"),
                    "weekly": lr_3d["weekly"],
                    "daily": lr_3d["daily"],
                    "accumulation": lr_3d.get("accumulation"),
                    "early_inference": lr_3d.get("early_inference"),
                    "summary": lr_3d["summary"],
                }

                # 纯LR驱动：直接覆盖方向和置信度
                if lr_dir != "NEUTRAL":
                    overall_direction = lr_dir
                    if lr_dir_diff > 0:
                        # 周线日线同向 → 强一致
                        consistency_level = "STRONG_CONSISTENT"
                        consistent = True
                        consistency_confidence = lr_conf
                    else:
                        # 日线与周线不一致
                        consistent = False
                        consistency_level = "INCONSISTENT"
                        consistency_confidence = round(lr_conf * 0.5, 1)
                else:
                    overall_direction = "NEUTRAL"
                    consistent = False
                    consistency_level = "INCONSISTENT"
                    consistency_confidence = 0.0
            except Exception:
                least_resistance = None

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
            "is_reversal": weekly_is_reversal,
            "persistence": weekly_persistence,
            "phase": weekly_phase,  # P2 新增
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
            "is_reversal": daily_is_reversal,
            "persistence": daily_persistence,
            "phase": daily_phase,  # P2 新增
        },
        "consistent": consistent,
        "consistency_level": consistency_level,
        "reversal_alignment": reversal_alignment,
        "overall_direction": overall_direction,
        "consistency_confidence": consistency_confidence,
        "reversal_confidence": reversal_confidence,
        "elder_divergence_confirm": elder_divergence_confirm,  # P2-v3 新增
        "trend_phase": combined_phase,            # P2 新增
        "trend_phase_confidence": combined_phase_conf,  # P2 新增
        "fundamental_fusion": fundamental_fusion,  # 基本面融合结果（None=未启用/回退）
        "least_resistance": least_resistance,  # Phase 3.5 最小阻力方向引擎结果
    }
