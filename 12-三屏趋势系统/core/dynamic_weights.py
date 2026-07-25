"""三屏趋势系统 — 动态权重调整 + 贝叶斯置信度

核心算法：
- 动态权重：基于回测表现 vs MA200基线，指标优胜劣汰
- 贝叶斯置信度：似然概率 × 先验 → 后验概率
"""

from typing import Dict, List

import numpy as np

try:
    from .config import (
        DAILY_WEIGHT,
        SCREEN1_INDICATORS,
        SCREEN2_INDICATORS,
        WEEKLY_WEIGHT,
    )
    from .indicators import calc_indicator_dynamics
except ImportError:
    from config import (
        DAILY_WEIGHT,
        SCREEN1_INDICATORS,
        SCREEN2_INDICATORS,
        WEEKLY_WEIGHT,
    )
    from indicators import calc_indicator_dynamics


def calc_indicator_performance(df, indicator_name: str, baseline_return: float = 0.0) -> dict:
    """
    计算单个指标的历史表现（用于权重排名）

    返回: {"sharpe", "win_rate", "total_return", "weight_score", "excess_return"}
    """
    try:
        close = df["close"].values
        signals = []
        for i in range(1, len(close)):
            df_slice = df.iloc[: i + 1]
            dyn = calc_indicator_dynamics(df_slice, indicator_name)
            if dyn["direction"] == "BULL":
                signals.append(1)
            elif dyn["direction"] == "BEAR":
                signals.append(-1)
            else:
                signals.append(0)

        if not signals or sum(abs(s) for s in signals) == 0:
            return {
                "sharpe": 0.0,
                "win_rate": 0.5,
                "total_return": 0.0,
                "weight_score": 0.0,
                "excess_return": 0.0,
            }

        returns = []
        for i, sig in enumerate(signals[:-1]):
            if sig != 0:
                ret = (close[i + 1] - close[i]) / close[i] * sig
                returns.append(ret)

        if not returns:
            return {
                "sharpe": 0.0,
                "win_rate": 0.5,
                "total_return": 0.0,
                "weight_score": 0.0,
                "excess_return": 0.0,
            }

        total_return = sum(returns)
        win_rate = sum(1 for r in returns if r > 0) / len(returns)
        sharpe = total_return / (np.std(returns) + 1e-9) if len(returns) > 1 else 0.0

        excess_return = total_return - baseline_return
        weight_score = sharpe + (win_rate - 0.5) * 10 + excess_return * 100

        return {
            "sharpe": round(sharpe, 3),
            "win_rate": round(win_rate, 3),
            "total_return": round(total_return, 3),
            "weight_score": round(weight_score, 3),
            "excess_return": round(excess_return, 3),
        }
    except Exception:
        return {
            "sharpe": 0.0,
            "win_rate": 0.5,
            "total_return": 0.0,
            "weight_score": 0.0,
            "excess_return": 0.0,
        }


def calc_dynamic_weights(df, indicators: List[str], prev_weights: Dict = None) -> dict:
    """
    计算指标的动态权重（基于历史表现排名）

    Phase 2 过拟合防护：
    1. 滚动窗口：仅用最近 WEIGHT_LOOKBACK_WINDOW 天数据
    2. 指数平滑：新权重 = α×原始 + (1-α)×上一期权重
    3. 权重约束：单指标权重限制在 [WEIGHT_MIN, WEIGHT_MAX]

    基线：日线 SMA200 策略
    筛选：优于基线的指标才分配权重
    排名：按 weight_score 从高到低分配权重

    参数:
        df: OHLCV DataFrame
        indicators: 指标列表
        prev_weights: 上一期权重（用于指数平滑），None=不平滑

    返回:
        {
            "weights": {indicator_name: 0-1},
            "performances": {indicator_name: {...}},
            "sorted_indicators": [...],
            "baseline_return": float,
        }
    """
    try:
        from .config import (
            WEIGHT_LOOKBACK_WINDOW,
            WEIGHT_MAX,
            WEIGHT_MIN,
            WEIGHT_SMOOTHING_ALPHA,
        )
    except ImportError:
        from config import (
            WEIGHT_LOOKBACK_WINDOW,
            WEIGHT_MAX,
            WEIGHT_MIN,
            WEIGHT_SMOOTHING_ALPHA,
        )

    # Phase 2.1: 滚动窗口 — 只用最近的数据，避免后见之明偏差
    if len(df) > WEIGHT_LOOKBACK_WINDOW:
        df = df.iloc[-WEIGHT_LOOKBACK_WINDOW:].copy()

    sma200 = df["close"].rolling(200, min_periods=1).mean()
    baseline_signals = np.where(df["close"] > sma200, 1, -1)
    baseline_returns = []
    for i in range(1, len(df)):
        baseline_returns.append(
            (df["close"].iloc[i] - df["close"].iloc[i - 1])
            / df["close"].iloc[i - 1]
            * baseline_signals[i - 1]
        )
    baseline_return = sum(baseline_returns) / len(baseline_returns) if baseline_returns else 0.0

    performances = {}
    for ind in indicators:
        performances[ind] = calc_indicator_performance(df, ind, baseline_return)

    sorted_indicators = sorted(
        performances.keys(), key=lambda x: performances[x]["weight_score"], reverse=True
    )

    total_score = sum(
        performances[ind]["weight_score"]
        for ind in sorted_indicators
        if performances[ind]["weight_score"] > 0
    )
    if total_score <= 0:
        equal_weight = 1.0 / len(indicators)
        raw_weights = dict.fromkeys(indicators, equal_weight)
    else:
        raw_weights = {}
        for ind in indicators:
            perf = performances[ind]
            if perf["weight_score"] > 0:
                raw_weights[ind] = perf["weight_score"] / total_score
            else:
                raw_weights[ind] = 0.0
        weight_sum = sum(raw_weights.values())
        if weight_sum > 0:
            raw_weights = {ind: w / weight_sum for ind, w in raw_weights.items()}
        else:
            equal_weight = 1.0 / len(indicators)
            raw_weights = dict.fromkeys(indicators, equal_weight)

    # Phase 2.2: 指数平滑 — 降低权重波动，防止过拟合近期数据
    alpha = WEIGHT_SMOOTHING_ALPHA
    if prev_weights is not None:
        smoothed_weights = {}
        for ind in indicators:
            raw = raw_weights.get(ind, 0.0)
            prev = prev_weights.get(ind, raw)
            smoothed_weights[ind] = alpha * raw + (1 - alpha) * prev
        raw_weights = smoothed_weights

    # Phase 2.3: 权重约束 — 单指标权重限制在 [WEIGHT_MIN, WEIGHT_MAX]
    constrained = {}
    for ind in indicators:
        w = raw_weights.get(ind, 0.0)
        # 对有权重的指标施加下限，对全部指标施加上限
        if w > 0:
            w = max(w, WEIGHT_MIN)
        w = min(w, WEIGHT_MAX)
        constrained[ind] = w

    # 重新归一化
    total = sum(constrained.values())
    if total > 0:
        weights = {ind: w / total for ind, w in constrained.items()}
    else:
        equal_weight = 1.0 / len(indicators)
        weights = dict.fromkeys(indicators, equal_weight)

    return {
        "weights": weights,
        "performances": performances,
        "sorted_indicators": sorted_indicators,
        "baseline_return": round(baseline_return, 4),
        "lookback_window": WEIGHT_LOOKBACK_WINDOW,
        "smoothed": prev_weights is not None,
    }


def calc_bayesian_confidence(weekly_df, daily_df) -> dict:
    """
    贝叶斯置信度计算（动态权重 + 三维动态融合）

    算法:
      P(趋势|信号) ∝ P(信号|趋势) × P(趋势)
      - 似然概率 = 动态权重 × 动态因子（0.5 + speed/200 + acceleration/200）
      - 先验隐含在历史权重排名中
      - 周线 60%，日线 40%

    返回:
        {
            "direction": "BULL"/"BEAR"/"NEUTRAL",
            "confidence": 0-100,
            "bull_probability": 0-1,
            "bear_probability": 0-1,
            "weekly_weights": {...},
            "daily_weights": {...},
        }
    """
    weekly_weights = calc_dynamic_weights(weekly_df, SCREEN1_INDICATORS)
    daily_weights = calc_dynamic_weights(daily_df, SCREEN2_INDICATORS)

    weekly_bull_prob = 0.0
    weekly_bear_prob = 0.0
    weekly_total_weight = 0.0

    for ind in SCREEN1_INDICATORS:
        weight = weekly_weights["weights"].get(ind, 0.0)
        dyn = calc_indicator_dynamics(weekly_df, ind)
        weekly_total_weight += weight

        if dyn["direction"] == "BULL":
            weekly_bull_prob += weight * (0.5 + dyn["speed"] / 200 + dyn["acceleration"] / 200)
        elif dyn["direction"] == "BEAR":
            weekly_bear_prob += weight * (0.5 + dyn["speed"] / 200 + dyn["acceleration"] / 200)

    if weekly_total_weight > 0:
        weekly_bull_prob /= weekly_total_weight
        weekly_bear_prob /= weekly_total_weight

    daily_bull_prob = 0.0
    daily_bear_prob = 0.0
    daily_total_weight = 0.0

    for ind in SCREEN2_INDICATORS:
        weight = daily_weights["weights"].get(ind, 0.0)
        dyn = calc_indicator_dynamics(daily_df, ind)
        daily_total_weight += weight

        if dyn["direction"] == "BULL":
            daily_bull_prob += weight * (0.5 + dyn["speed"] / 200 + dyn["acceleration"] / 200)
        elif dyn["direction"] == "BEAR":
            daily_bear_prob += weight * (0.5 + dyn["speed"] / 200 + dyn["acceleration"] / 200)

    if daily_total_weight > 0:
        daily_bull_prob /= daily_total_weight
        daily_bear_prob /= daily_total_weight

    bull_prob = weekly_bull_prob * WEEKLY_WEIGHT + daily_bull_prob * DAILY_WEIGHT
    bear_prob = weekly_bear_prob * WEEKLY_WEIGHT + daily_bear_prob * DAILY_WEIGHT

    if bull_prob > bear_prob:
        direction = "BULL"
        confidence = round(bull_prob * 100, 1)
    elif bear_prob > bull_prob:
        direction = "BEAR"
        confidence = round(bear_prob * 100, 1)
    else:
        direction = "NEUTRAL"
        confidence = round(min(bull_prob, bear_prob) * 50, 1)

    return {
        "direction": direction,
        "confidence": confidence,
        "bull_probability": round(bull_prob, 4),
        "bear_probability": round(bear_prob, 4),
        "weekly_weights": weekly_weights,
        "daily_weights": daily_weights,
    }
