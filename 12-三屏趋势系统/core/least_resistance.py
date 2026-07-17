"""三屏趋势系统 — 最小阻力方向引擎

第一性原理：市场总是沿着阻力最小方向运动。

从5个维度分别计算"多方阻力"和"空方阻力"：
- 价格阻力：上方压力位 vs 下方支撑位
- 量能阻力：上涨/下跌放量程度，OBV资金流向
- 动量阻力：RSI超买超卖，MACD动能，背离
- 趋势阻力：均线斜率，Elder-ray多空力量，加速度
- 基本面阻力：矿工抛压，链上活跃度，宏观环境

阻力小的方向 = 市场最可能运动的方向

三维度模型：
- Direction（方向）：最小阻力方向
- Velocity（速度）：阻力差变化率
- Acceleration（加速度）：速度变化率
"""

import math
from typing import Dict, Any, Optional, List
import numpy as np
import pandas as pd

try:
    from .config import (
        LEAST_RESISTANCE_WEIGHTS,
        LEAST_RESISTANCE_PRICE_LOOKBACK,
    )
except ImportError:
    LEAST_RESISTANCE_WEIGHTS = {
        "price": 0.30,
        "volume": 0.20,
        "momentum": 0.20,
        "trend": 0.20,
        "fundamental": 0.10,
    }
    LEAST_RESISTANCE_PRICE_LOOKBACK = 60


def calc_price_resistance(df, lookback: int = 60) -> Dict[str, float]:
    """
    计算价格阻力（上方压力 vs 下方支撑）

    返回:
        {
            "bull_resistance": 0-1,  # 上涨阻力（多方需要克服的阻力）
            "bear_resistance": 0-1,  # 下跌阻力（空方需要克服的阻力）
            "nearest_resistance": float,  # 最近压力位距离（%）
            "nearest_support": float,     # 最近支撑位距离（%）
            "resistance_levels": [...],   # 压力位列表
            "support_levels": [...],      # 支撑位列表
        }
    """
    if len(df) < 20:
        return {"bull_resistance": 0.5, "bear_resistance": 0.5,
                "nearest_resistance": 0.05, "nearest_support": 0.05,
                "resistance_levels": [], "support_levels": []}

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    current_price = close[-1]

    lookback = min(lookback, len(df))
    recent_high = high[-lookback:]
    recent_low = low[-lookback:]

    resistance_levels = []
    support_levels = []

    for i in range(2, len(recent_high) - 2):
        if recent_high[i] > recent_high[i-1] and recent_high[i] > recent_high[i-2] \
           and recent_high[i] > recent_high[i+1] and recent_high[i] > recent_high[i+2]:
            resistance_levels.append(recent_high[i])

    for i in range(2, len(recent_low) - 2):
        if recent_low[i] < recent_low[i-1] and recent_low[i] < recent_low[i-2] \
           and recent_low[i] < recent_low[i+1] and recent_low[i] < recent_low[i+2]:
            support_levels.append(recent_low[i])

    ma_periods = [20, 50, 128, 200]
    for period in ma_periods:
        if len(close) >= period:
            ma = np.mean(close[-period:])
            if ma > current_price:
                resistance_levels.append(ma)
            else:
                support_levels.append(ma)

    resistance_above = [r for r in resistance_levels if r > current_price]
    support_below = [s for s in support_levels if s < current_price]

    if resistance_above:
        nearest_resistance_pct = (min(resistance_above) - current_price) / current_price
    else:
        nearest_resistance_pct = 0.10

    if support_below:
        nearest_support_pct = (current_price - max(support_below)) / current_price
    else:
        nearest_support_pct = 0.10

    nearest_resistance_pct = max(0.01, min(0.20, nearest_resistance_pct))
    nearest_support_pct = max(0.01, min(0.20, nearest_support_pct))

    bull_resistance = 1.0 - (nearest_resistance_pct / 0.20)
    bear_resistance = 1.0 - (nearest_support_pct / 0.20)

    bull_resistance = max(0.1, min(0.9, bull_resistance))
    bear_resistance = max(0.1, min(0.9, bear_resistance))

    return {
        "bull_resistance": round(bull_resistance, 4),
        "bear_resistance": round(bear_resistance, 4),
        "nearest_resistance_pct": round(nearest_resistance_pct, 4),
        "nearest_support_pct": round(nearest_support_pct, 4),
        "resistance_count": len(resistance_above),
        "support_count": len(support_below),
    }


def calc_volume_resistance(df) -> Dict[str, float]:
    """
    计算量能阻力

    逻辑：
    - 上涨时放量 = 上涨阻力小（多方力量强）
    - 下跌时放量 = 下跌阻力小（空方力量强）
    - OBV向上 = 资金流入，上涨阻力小
    - OBV向下 = 资金流出，下跌阻力小
    """
    if len(df) < 20:
        return {"bull_resistance": 0.5, "bear_resistance": 0.5,
                "obv_trend": "neutral", "vol_price_divergence": 0.0}

    close = df["close"].values
    volume = df["volume"].values

    returns = np.diff(close) / close[:-1]
    vol_changes = np.diff(volume) / (volume[:-1] + 1e-10)

    up_days = returns > 0
    down_days = returns < 0

    if up_days.sum() > 0 and down_days.sum() > 0:
        avg_up_vol = np.mean(vol_changes[up_days]) if up_days.sum() > 0 else 0
        avg_down_vol = np.mean(vol_changes[down_days]) if down_days.sum() > 0 else 0

        vol_strength = avg_up_vol - avg_down_vol
    else:
        vol_strength = 0.0

    obv = np.zeros(len(close))
    obv[0] = volume[0]
    for i in range(1, len(close)):
        if close[i] > close[i-1]:
            obv[i] = obv[i-1] + volume[i]
        elif close[i] < close[i-1]:
            obv[i] = obv[i-1] - volume[i]
        else:
            obv[i] = obv[i-1]

    obv_ma_short = np.mean(obv[-10:]) if len(obv) >= 10 else obv[-1]
    obv_ma_long = np.mean(obv[-30:]) if len(obv) >= 30 else obv[-1]
    obv_trend_strength = (obv_ma_short - obv_ma_long) / (abs(obv_ma_long) + 1e-10)

    vol_score = math.tanh(vol_strength * 2) * 0.5
    obv_score = math.tanh(obv_trend_strength * 5) * 0.5

    combined_score = vol_score + obv_score

    if combined_score > 0:
        bull_resistance = 0.5 - combined_score
        bear_resistance = 0.5 + combined_score * 0.5
    else:
        bull_resistance = 0.5 + abs(combined_score) * 0.5
        bear_resistance = 0.5 - abs(combined_score)

    bull_resistance = max(0.1, min(0.9, bull_resistance))
    bear_resistance = max(0.1, min(0.9, bear_resistance))

    obv_trend = "bullish" if obv_trend_strength > 0.02 else ("bearish" if obv_trend_strength < -0.02 else "neutral")

    return {
        "bull_resistance": round(bull_resistance, 4),
        "bear_resistance": round(bear_resistance, 4),
        "obv_trend": obv_trend,
        "vol_price_divergence": round(vol_strength, 4),
        "obv_trend_strength": round(obv_trend_strength, 4),
    }


def calc_momentum_resistance(df) -> Dict[str, float]:
    """
    计算动量阻力

    逻辑：
    - RSI超买（>70）= 上涨阻力大
    - RSI超卖（<30）= 下跌阻力大
    - MACD柱体扩大 = 当前趋势阻力小
    - 顶背离 = 上涨阻力大
    - 底背离 = 下跌阻力大
    """
    if len(df) < 30:
        return {"bull_resistance": 0.5, "bear_resistance": 0.5,
                "rsi": 50, "macd_trend": "neutral", "divergence": "none"}

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values

    delta = np.diff(close)
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)

    period = 14
    avg_gain = np.mean(gain[-period:]) if len(gain) >= period else np.mean(gain)
    avg_loss = np.mean(loss[-period:]) if len(loss) >= period else np.mean(loss)

    if avg_loss == 0:
        rsi = 100
    else:
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    macd_line = ema12 - ema26
    signal_line = _ema(macd_line, 9)
    macd_hist = macd_line - signal_line

    hist_trend = 0
    if len(macd_hist) >= 5:
        recent_hist = macd_hist[-5:]
        hist_trend = (recent_hist[-1] - recent_hist[0]) / (abs(recent_hist[0]) + 1e-10)

    divergence = _detect_macd_divergence(close, macd_line)

    rsi_resistance_bull = 0.0
    rsi_resistance_bear = 0.0

    if rsi > 70:
        rsi_resistance_bull = (rsi - 70) / 30 * 0.4
    elif rsi < 30:
        rsi_resistance_bear = (30 - rsi) / 30 * 0.4

    macd_bull_boost = 0.0
    macd_bear_boost = 0.0
    if macd_hist[-1] > 0:
        macd_bull_boost = min(0.2, abs(hist_trend) * 0.3)
    else:
        macd_bear_boost = min(0.2, abs(hist_trend) * 0.3)

    div_bull_extra = 0.0
    div_bear_extra = 0.0
    if divergence == "bearish":
        div_bull_extra = 0.2
    elif divergence == "bullish":
        div_bear_extra = 0.2

    bull_resistance = 0.5 + rsi_resistance_bull + div_bull_extra - macd_bull_boost
    bear_resistance = 0.5 + rsi_resistance_bear + div_bear_extra - macd_bear_boost

    bull_resistance = max(0.1, min(0.9, bull_resistance))
    bear_resistance = max(0.1, min(0.9, bear_resistance))

    macd_trend = "bullish" if macd_hist[-1] > 0 and hist_trend > 0 else \
                 ("bearish" if macd_hist[-1] < 0 and hist_trend < 0 else "neutral")

    return {
        "bull_resistance": round(bull_resistance, 4),
        "bear_resistance": round(bear_resistance, 4),
        "rsi": round(rsi, 2),
        "macd_trend": macd_trend,
        "divergence": divergence,
        "hist_trend": round(hist_trend, 4),
    }


def calc_trend_resistance(df) -> Dict[str, float]:
    """
    计算趋势阻力

    逻辑：
    - 均线斜率向上 = 上涨阻力小
    - 均线斜率向下 = 下跌阻力小
    - Elder-ray Bull Power > Bear Power = 多方力量强，上涨阻力小
    - 趋势加速度 = 速度变化率
    """
    if len(df) < 50:
        return {"bull_resistance": 0.5, "bear_resistance": 0.5,
                "trend_strength": 50, "ma_slope": 0.0, "elder_ray_balance": 0.0}

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values

    ma20 = _sma(close, 20)
    ma50 = _sma(close, 50)

    if len(ma20) >= 10:
        ma20_slope = (ma20[-1] - ma20[-10]) / ma20[-10] * 100
    else:
        ma20_slope = 0.0

    if len(ma50) >= 10:
        ma50_slope = (ma50[-1] - ma50[-10]) / ma50[-10] * 100
    else:
        ma50_slope = 0.0

    combined_slope = ma20_slope * 0.6 + ma50_slope * 0.4

    ema13 = _ema(close, 13)
    bull_power = high - ema13
    bear_power = low - ema13

    avg_bull = np.mean(bull_power[-10:]) if len(bull_power) >= 10 else np.mean(bull_power)
    avg_bear = np.mean(bear_power[-10:]) if len(bear_power) >= 10 else np.mean(bear_power)

    price_range = np.max(close[-30:]) - np.min(close[-30:]) + 1e-10
    elder_balance = (avg_bull - abs(avg_bear)) / price_range

    slope_score = math.tanh(combined_slope * 10)
    elder_score = math.tanh(elder_balance * 5)

    trend_score = slope_score * 0.6 + elder_score * 0.4

    if trend_score > 0:
        bull_resistance = 0.5 - trend_score * 0.4
        bear_resistance = 0.5 + trend_score * 0.3
    else:
        bull_resistance = 0.5 + abs(trend_score) * 0.3
        bear_resistance = 0.5 - abs(trend_score) * 0.4

    bull_resistance = max(0.1, min(0.9, bull_resistance))
    bear_resistance = max(0.1, min(0.9, bear_resistance))

    trend_strength = 50 + trend_score * 50

    return {
        "bull_resistance": round(bull_resistance, 4),
        "bear_resistance": round(bear_resistance, 4),
        "trend_strength": round(trend_strength, 2),
        "ma20_slope": round(ma20_slope, 4),
        "ma50_slope": round(ma50_slope, 4),
        "elder_balance": round(elder_balance, 4),
        "avg_bull_power": round(float(avg_bull), 4),
        "avg_bear_power": round(float(avg_bear), 4),
    }


def calc_fundamental_resistance(fundamental_data: Optional[Dict] = None) -> Dict[str, float]:
    """
    计算基本面阻力

    逻辑：
    - 基本面利多 = 上涨阻力小
    - 基本面利空 = 下跌阻力小
    - 基本面速度/加速度也影响阻力变化
    """
    if not fundamental_data:
        return {"bull_resistance": 0.5, "bear_resistance": 0.5,
                "available": False, "fund_score": 0.0}

    fund_score = 0.0
    score_sources = []

    if "score" in fundamental_data:
        fund_score += (float(fundamental_data["score"]) - 50) / 50 * 0.5
        score_sources.append("overall_score")

    if "direction" in fundamental_data:
        dir_map = {"BULL": 0.3, "BEAR": -0.3, "NEUTRAL": 0.0}
        fund_score += dir_map.get(fundamental_data["direction"], 0)
        score_sources.append("direction")

    if "dimensions" in fundamental_data:
        dims = fundamental_data["dimensions"]
        dim_count = 0
        dim_total = 0
        for dim_name, dim_data in dims.items():
            if dim_data.get("available", False):
                dim_score = (float(dim_data.get("score", 50)) - 50) / 50
                dim_total += dim_score
                dim_count += 1
        if dim_count > 0:
            fund_score += dim_total / dim_count * 0.2
            score_sources.append(f"{dim_count}_dimensions")

    fund_score = max(-1.0, min(1.0, fund_score))

    if fund_score > 0:
        bull_resistance = 0.5 - fund_score * 0.3
        bear_resistance = 0.5 + fund_score * 0.2
    else:
        bull_resistance = 0.5 + abs(fund_score) * 0.2
        bear_resistance = 0.5 - abs(fund_score) * 0.3

    bull_resistance = max(0.2, min(0.8, bull_resistance))
    bear_resistance = max(0.2, min(0.8, bear_resistance))

    return {
        "bull_resistance": round(bull_resistance, 4),
        "bear_resistance": round(bear_resistance, 4),
        "available": True,
        "fund_score": round(fund_score, 4),
        "score_sources": score_sources,
    }


def compute_least_resistance(
    df,
    fundamental_data: Optional[Dict] = None,
    weights: Optional[Dict[str, float]] = None,
    historical_diffs: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """
    计算最小阻力方向（主入口）

    参数:
        df: K线DataFrame
        fundamental_data: 基本面数据（可选）
        weights: 各维度权重配置
        historical_diffs: 历史阻力差列表（用于速度/加速度计算）

    返回:
        {
            "direction": "BULL"/"BEAR"/"NEUTRAL",
            "confidence": 0-100,
            "bull_resistance": 0-1,   # 多方阻力（上涨需要克服的阻力）
            "bear_resistance": 0-1,   # 空方阻力（下跌需要克服的阻力）
            "resistance_diff": -1~1,  # 阻力差 = bear - bull（正=多方阻力小）
            "velocity": float,        # 速度：阻力差变化率
            "acceleration": float,    # 加速度：速度变化率
            "dimensions": {           # 各维度详情
                "price": {...},
                "volume": {...},
                "momentum": {...},
                "trend": {...},
                "fundamental": {...},
            },
            "weights": {...},
        }
    """
    w = weights or LEAST_RESISTANCE_WEIGHTS

    price_r = calc_price_resistance(df, LEAST_RESISTANCE_PRICE_LOOKBACK)
    volume_r = calc_volume_resistance(df)
    momentum_r = calc_momentum_resistance(df)
    trend_r = calc_trend_resistance(df)
    fundamental_r = calc_fundamental_resistance(fundamental_data)

    w_fund = w.get("fundamental", 0.1) if fundamental_r.get("available") else 0
    total_other = w.get("price", 0.3) + w.get("volume", 0.2) + w.get("momentum", 0.2) + w.get("trend", 0.2)
    scale_factor = (1.0 - w_fund) / total_other if total_other > 0 else 1.0

    bull_resistance = (
        price_r["bull_resistance"] * w.get("price", 0.3) * scale_factor
        + volume_r["bull_resistance"] * w.get("volume", 0.2) * scale_factor
        + momentum_r["bull_resistance"] * w.get("momentum", 0.2) * scale_factor
        + trend_r["bull_resistance"] * w.get("trend", 0.2) * scale_factor
        + fundamental_r["bull_resistance"] * w_fund
    )

    bear_resistance = (
        price_r["bear_resistance"] * w.get("price", 0.3) * scale_factor
        + volume_r["bear_resistance"] * w.get("volume", 0.2) * scale_factor
        + momentum_r["bear_resistance"] * w.get("momentum", 0.2) * scale_factor
        + trend_r["bear_resistance"] * w.get("trend", 0.2) * scale_factor
        + fundamental_r["bear_resistance"] * w_fund
    )

    resistance_diff = bear_resistance - bull_resistance

    if resistance_diff > 0.10:
        direction = "BULL"
    elif resistance_diff < -0.10:
        direction = "BEAR"
    else:
        direction = "NEUTRAL"

    confidence = min(100, abs(resistance_diff) * 500)

    velocity = 0.0
    acceleration = 0.0

    if historical_diffs and len(historical_diffs) > 0:
        hist_mean = sum(historical_diffs) / len(historical_diffs)
        hist_std = np.std(historical_diffs) if len(historical_diffs) > 1 else 0.1
        if hist_std > 0:
            velocity = math.tanh((resistance_diff - hist_mean) / hist_std)
        else:
            velocity = math.tanh(resistance_diff * 10)

        if len(historical_diffs) >= 3:
            prev_3 = historical_diffs[-3:]
            prev_mean = sum(prev_3) / len(prev_3)
            acceleration = math.tanh((resistance_diff - prev_mean) * 5)
    else:
        velocity = math.tanh(resistance_diff * 10)

    return {
        "direction": direction,
        "confidence": round(confidence, 2),
        "bull_resistance": round(bull_resistance, 4),
        "bear_resistance": round(bear_resistance, 4),
        "resistance_diff": round(resistance_diff, 4),
        "velocity": round(velocity, 4),
        "acceleration": round(acceleration, 4),
        "dimensions": {
            "price": price_r,
            "volume": volume_r,
            "momentum": momentum_r,
            "trend": trend_r,
            "fundamental": fundamental_r,
        },
        "weights": {
            "price": round(w.get("price", 0.3) * scale_factor, 4),
            "volume": round(w.get("volume", 0.2) * scale_factor, 4),
            "momentum": round(w.get("momentum", 0.2) * scale_factor, 4),
            "trend": round(w.get("trend", 0.2) * scale_factor, 4),
            "fundamental": round(w_fund, 4),
        },
        "summary": _summarize_least_resistance(direction, confidence, velocity, acceleration),
    }


def calc_trend_strength(
    resistance_diff: float,
    velocity: float,
    acceleration: float,
    direction: str,
) -> float:
    """计算趋势强度（0-100）

    趋势强度由三个因素决定：
    1. 阻力差的绝对值（越大=趋势越强）
    2. 速度方向与趋势方向是否一致（一致=增强）
    3. 加速度方向（同向=加速，反向=减速但仍强）

    强度分级：
    - >70: 极强趋势（延续性主导，大周期决定小周期）
    - 40-70: 中等趋势
    - 20-40: 弱趋势（量变积累可能开始）
    - <20: 趋势衰竭（小周期量变积累，可能催生大周期反转）
    """
    if direction == "NEUTRAL":
        return 0.0

    # 阻力差贡献（0-50分）
    diff_strength = min(50.0, abs(resistance_diff) * 250)

    # 速度贡献（0-30分）：速度与方向一致时加分
    dir_sign = 1.0 if direction == "BULL" else -1.0
    velocity_aligned = velocity * dir_sign  # 正=同向
    velocity_strength = max(0.0, velocity_aligned) * 30.0

    # 加速度贡献（-20~20分）：加速加分，减速扣分但不低于0
    accel_aligned = acceleration * dir_sign
    accel_strength = max(-20.0, accel_aligned * 20.0)

    strength = diff_strength + velocity_strength + accel_strength
    return round(max(0.0, min(100.0, strength)), 2)


def calc_trend_duration(history_3d: Optional[List[Dict]], current_direction: str) -> int:
    """计算趋势延续时间（当前方向连续持续的周期数）

    从历史序列末尾向前回溯，统计当前方向连续出现的次数。
    方向改变即停止计数。
    """
    if not history_3d or current_direction == "NEUTRAL":
        return 0

    count = 0
    for h in reversed(history_3d):
        if h.get("direction") == current_direction:
            count += 1
        else:
            break
    return count


def determine_drive_mode(
    trend_strength: float,
    trend_duration: int,
    acceleration: float,
    direction: str,
) -> Dict[str, Any]:
    """判定双向驱动模式：大周期→小周期（延续） vs 小周期→大周期（催生）

    核心逻辑：
    - 趋势强度高 + 延续时间不长 → CONTINUATION（大周期决定小周期）
    - 趋势强度高 + 延续时间很长 → LATE_CONTINUATION（延续后期，开始关注小周期信号）
    - 趋势强度弱 + 加速度反向 → ACCUMULATION（小周期量变积累，催生大周期反转）
    - 趋势强度弱 + 加速度同向 → WEAKENING（趋势衰竭，等待方向选择）

    参数:
        trend_strength: 趋势强度 0-100
        trend_duration: 趋势延续周期数
        acceleration: 当前加速度
        direction: 当前方向

    返回:
        {
            "mode": "CONTINUATION"/"LATE_CONTINUATION"/"ACCUMULATION"/"WEAKENING",
            "drive_direction": "LARGE_TO_SMALL"/"SMALL_TO_LARGE",
            "description": str,
            "reversal_sensitivity": float,  # 反转敏感度 0-1（越高越关注小周期信号）
        }
    """
    dir_sign = 1.0 if direction == "BULL" else -1.0
    accel_aligned = acceleration * dir_sign  # 正=同向加速，负=反向减速

    # 反转敏感度：强度越低、延续越久、加速度越反向 → 敏感度越高
    strength_factor = max(0.0, 1.0 - trend_strength / 70.0)
    duration_factor = min(1.0, trend_duration / 15.0)
    accel_factor = max(0.0, -accel_aligned) * 2.0
    reversal_sensitivity = min(1.0, strength_factor * 0.4 + duration_factor * 0.3 + accel_factor * 0.3)

    if trend_strength >= 60 and trend_duration < 10:
        mode = "CONTINUATION"
        drive = "LARGE_TO_SMALL"
        desc = "强趋势延续中：大周期决定小周期，趋势延续性主导"
    elif trend_strength >= 40 and reversal_sensitivity < 0.5:
        mode = "CONTINUATION"
        drive = "LARGE_TO_SMALL"
        desc = "趋势延续中：大周期主导，小周期跟随"
    elif trend_strength >= 40 and reversal_sensitivity >= 0.5:
        mode = "LATE_CONTINUATION"
        drive = "LARGE_TO_SMALL"
        desc = "趋势延续后期：大周期仍主导但开始减弱，关注小周期量变信号"
    elif trend_strength < 40 and accel_aligned < -0.1:
        mode = "ACCUMULATION"
        drive = "SMALL_TO_LARGE"
        desc = "趋势衰竭+加速度反向：小周期量变积累中，可能催生大周期反转"
    else:
        mode = "WEAKENING"
        drive = "SMALL_TO_LARGE"
        desc = "趋势减弱：等待方向选择，小周期信号优先"

    return {
        "mode": mode,
        "drive_direction": drive,
        "description": desc,
        "reversal_sensitivity": round(reversal_sensitivity, 3),
    }


def detect_accumulation_breakthrough(
    direction: str,
    velocity: float,
    acceleration: float,
    daily_dir: str,
    daily_velocity: float,
    daily_acceleration: float,
    small_dir: str = None,
    small_acceleration: float = None,
    history_3d: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    """量变积累 → 质变突破检测

    核心原理：短周期的量积累会引发中周期的质变，中周期的量积累会引发长周期的质变。

    典型场景（磨底反弹）：
    1. 价格跌到某位置后不立即反弹，反复磨底
    2. 短周期：D仍为BEAR，但A开始持续正向（阻力减小加速度>0）→ 量变积累
    3. 短周期：V穿越零轴 → 量变到质变拐点
    4. 中周期：V跟随转向 → 中周期质变确认
    5. 中周期：D改变 → 长周期方向即将反转

    对称场景（筑顶下跌）：
    1. D仍为BULL，但A持续负向 → 量变积累
    2. V穿越零轴 → 质变拐点
    3. 长周期D改变 → 方向反转

    参数:
        direction: 长周期（周线）方向
        velocity: 长周期速度
        acceleration: 长周期加速度
        daily_dir: 中周期（日线）方向
        daily_velocity: 中周期速度
        daily_acceleration: 中周期加速度
        small_dir: 短周期方向（可选）
        small_acceleration: 短周期加速度（可选）
        history_3d: 历史三维模型序列 [{direction, velocity, acceleration, ...}]

    返回:
        {
            "stage": "NONE"/"ACCUMULATION"/"BREAKTHROUGH_IMMINENT"/"BREAKTHROUGH_CONFIRMED",
            "type": "BOTTOM"/"TOP"/None,  # 磨底/筑顶
            "early_direction": "BULL"/"BEAR"/None,  # 早期推理方向
            "confidence_boost": float,  # 置信度加成 0~30
            "accumulation_count": int,  # 量变积累持续周期数
            "description": str,
        }
    """
    # ── 检测量变积累：D方向不变但A持续反向 ──
    # 磨底：D=BEAR 但 A>0（加速度正向，阻力在减小）
    # 筑顶：D=BULL 但 A<0（加速度负向，阻力在增大）

    accumulation_type = None
    if direction == "BEAR" and acceleration > 0.15:
        accumulation_type = "BOTTOM"
    elif direction == "BULL" and acceleration < -0.15:
        accumulation_type = "TOP"

    # 短周期积累更灵敏
    small_accumulation = False
    if small_dir is not None and small_acceleration is not None:
        if direction == "BEAR" and small_acceleration > 0.2:
            small_accumulation = True
            accumulation_type = "BOTTOM"
        elif direction == "BULL" and small_acceleration < -0.2:
            small_accumulation = True
            accumulation_type = "TOP"

    # ── 统计量变积累持续周期数 ──
    accumulation_count = 0
    if history_3d:
        for h in reversed(history_3d):
            h_dir = h.get("direction", "")
            h_accel = h.get("acceleration", 0.0)
            if accumulation_type == "BOTTOM" and h_dir in ("BEAR", "NEUTRAL") and h_accel > 0.1:
                accumulation_count += 1
            elif accumulation_type == "TOP" and h_dir in ("BULL", "NEUTRAL") and h_accel < -0.1:
                accumulation_count += 1
            else:
                break

    # ── 判断质变阶段 ──
    stage = "NONE"
    early_direction = None
    confidence_boost = 0.0
    description = ""

    if accumulation_type is None:
        stage = "NONE"
    else:
        expected_new_dir = "BULL" if accumulation_type == "BOTTOM" else "BEAR"

        # 检测中周期（日线）是否已质变
        daily_qualitative_change = False
        if accumulation_type == "BOTTOM":
            # 日线V从负转正，或日线D已转为BULL
            if daily_velocity > 0 or daily_dir == "BULL":
                daily_qualitative_change = True
        elif accumulation_type == "TOP":
            if daily_velocity < 0 or daily_dir == "BEAR":
                daily_qualitative_change = True

        # 检测短周期质变
        short_qualitative_change = False
        if small_dir is not None:
            if accumulation_type == "BOTTOM" and small_dir == "BULL":
                short_qualitative_change = True
            elif accumulation_type == "TOP" and small_dir == "BEAR":
                short_qualitative_change = True

        # 分阶段判定
        if daily_qualitative_change and daily_dir == expected_new_dir:
            # 中周期D已改变 → 质变确认，长周期方向即将反转
            stage = "BREAKTHROUGH_CONFIRMED"
            early_direction = expected_new_dir
            confidence_boost = 25.0
            description = f"质变确认: 中周期方向已转为{expected_new_dir}，长周期方向反转在即"

        elif daily_qualitative_change or short_qualitative_change:
            # 短周期或中周期V已穿越 → 质变即将发生
            stage = "BREAKTHROUGH_IMMINENT"
            early_direction = expected_new_dir
            confidence_boost = 15.0
            detail = "中周期速度转向" if daily_qualitative_change else "短周期方向已变"
            description = f"质变临近: {detail}，{accumulation_type}积累{accumulation_count}周期"

        elif accumulation_count >= 2 or small_accumulation:
            # 仍在量变积累阶段
            stage = "ACCUMULATION"
            early_direction = expected_new_dir
            confidence_boost = 5.0 + min(10.0, accumulation_count * 2.0)
            description = f"量变积累中: {accumulation_type}磨底/筑顶，A持续反向{accumulation_count}周期"

    return {
        "stage": stage,
        "type": accumulation_type,
        "early_direction": early_direction,
        "confidence_boost": round(confidence_boost, 1),
        "accumulation_count": accumulation_count,
        "description": description,
    }


def compute_least_resistance_3d(
    weekly_df,
    daily_df,
    small_df=None,
    fundamental_data=None,
    weights=None,
    daily_history_diffs=None,
    history_3d=None,
) -> Dict[str, Any]:
    """时间三维 × 五维阻力算法 → 最小阻力三维模型

    时间三维映射到 D/V/A：
    - 长周期（周线）→ Direction：定方向
    - 中周期（日线）→ Velocity：定入场时机
    - 小周期（4H/小时线/日线近期切片）→ Acceleration：精细入场

    核心逻辑：
    - Direction 来自周线五维阻力差，确定大方向
    - Velocity 来自日线阻力差变化率，判断入场时机
    - Acceleration 来自小周期阻力差加速度，精细入场
    - 日线方向与周线一致 → 必须入场（理论上必须入）
    - 日线方向与周线不一致 → 等待
    - 量变积累→质变突破：短周期A持续反向积累，引发中周期V穿越，最终传导到长周期D

    参数:
        weekly_df: 周线 DataFrame
        daily_df: 日线 DataFrame
        small_df: 小周期 DataFrame（4H/小时线，可选）
        fundamental_data: 基本面数据
        weights: 五维权重配置
        daily_history_diffs: 历史日线阻力差列表（用于速度/加速度计算）
        history_3d: 历史三维模型序列，用于量变积累检测

    返回:
        {
            "direction": "BULL"/"BEAR"/"NEUTRAL",  # 最小阻力方向
            "confidence": 0-100,
            "velocity": float,      # 速度（来自日线阻力差变化率）
            "acceleration": float,  # 加速度（来自小周期阻力差变化率）
            "entry_signal": "MUST_ENTER"/"TIMING"/"WAIT",
            "weekly": {...},
            "daily": {...},
            "small": {...},
            "direction_diff": float,
            "accumulation": {...},  # 量变积累→质变突破检测结果
            "early_inference": {...},  # 早期方向推理
        }
    """
    w = weights or LEAST_RESISTANCE_WEIGHTS

    # ── 1. 长周期（周线）五维阻力 → Direction ──
    weekly_lr = compute_least_resistance(weekly_df, fundamental_data, w)
    direction = weekly_lr["direction"]
    weekly_diff = weekly_lr["resistance_diff"]
    weekly_velocity = weekly_lr["velocity"]
    weekly_acceleration = weekly_lr["acceleration"]

    # ── 2. 中周期（日线）五维阻力 → Velocity ──
    daily_lr = compute_least_resistance(daily_df, fundamental_data, w)
    daily_diff = daily_lr["resistance_diff"]
    daily_dir = daily_lr["direction"]
    daily_velocity_raw = daily_lr["velocity"]
    daily_acceleration_raw = daily_lr["acceleration"]

    # 速度：日线阻力差相对历史的变化率
    if daily_history_diffs and len(daily_history_diffs) >= 2:
        hist_mean = sum(daily_history_diffs) / len(daily_history_diffs)
        hist_std = float(np.std(daily_history_diffs)) if len(daily_history_diffs) > 1 else 0.1
        if hist_std > 1e-6:
            velocity = math.tanh((daily_diff - hist_mean) / hist_std)
        else:
            velocity = math.tanh(daily_diff * 10)
    else:
        velocity = math.tanh(daily_diff * 10)

    # ── 3. 小周期五维阻力 → Acceleration ──
    small_lr = None
    small_dir = None
    small_acceleration_raw = None
    if small_df is not None and len(small_df) >= 30:
        small_lr = compute_least_resistance(small_df, fundamental_data, w)
        small_diff = small_lr["resistance_diff"]
        small_dir = small_lr["direction"]
        small_acceleration_raw = small_lr["acceleration"]

        if daily_history_diffs and len(daily_history_diffs) >= 3:
            recent_diffs = daily_history_diffs[-3:]
            recent_mean = sum(recent_diffs) / len(recent_diffs)
            acceleration = math.tanh((small_diff - recent_mean) * 5)
        else:
            acceleration = math.tanh((small_diff - daily_diff) * 5)
    else:
        if daily_history_diffs and len(daily_history_diffs) >= 3:
            recent_diffs = daily_history_diffs[-3:]
            recent_mean = sum(recent_diffs) / len(recent_diffs)
            acceleration = math.tanh((daily_diff - recent_mean) * 5)
        else:
            acceleration = 0.0

    # ── 4. 趋势强度 + 趋势延续时间 + 双向驱动模式判定 ──
    trend_strength = calc_trend_strength(weekly_diff, weekly_velocity, weekly_acceleration, direction)
    trend_duration = calc_trend_duration(history_3d, direction)
    drive_mode = determine_drive_mode(trend_strength, trend_duration, acceleration, direction)

    # ── 5. 量变积累→质变突破检测（仅在反转敏感度>0时启用）──
    accumulation = detect_accumulation_breakthrough(
        direction=direction,
        velocity=weekly_velocity,
        acceleration=acceleration,
        daily_dir=daily_dir,
        daily_velocity=daily_velocity_raw,
        daily_acceleration=daily_acceleration_raw,
        small_dir=small_dir,
        small_acceleration=small_acceleration_raw,
        history_3d=history_3d,
    )

    # ── 6. 双向驱动方向推理 ──
    # CONTINUATION模式：大周期决定小周期，周线方向为最终方向
    # ACCUMULATION/WEAKENING模式：小周期催生大周期，量变质变信号可提前切换方向
    direction_diff = 0.0
    if direction != "NEUTRAL" and daily_dir != "NEUTRAL":
        if direction == daily_dir:
            direction_diff = 1.0
        else:
            direction_diff = -1.0

    # 基础入场信号
    if direction == "NEUTRAL":
        entry_signal = "WAIT"
    elif daily_dir == direction:
        entry_signal = "MUST_ENTER"
    elif daily_dir == "NEUTRAL":
        entry_signal = "WAIT"
    else:
        entry_signal = "WAIT"

    # 量变质变增强入场信号（受双向驱动模式调节）
    acc_stage = accumulation["stage"]
    acc_early_dir = accumulation["early_direction"]
    acc_boost = accumulation["confidence_boost"]

    # 在CONTINUATION模式下降权量变质变信号（趋势延续性主导）
    if drive_mode["drive_direction"] == "LARGE_TO_SMALL" and drive_mode["mode"] == "CONTINUATION":
        acc_boost *= 0.3  # 强趋势延续时，量变信号降权
    # 在LATE_CONTINUATION模式下半信量变信号
    elif drive_mode["mode"] == "LATE_CONTINUATION":
        acc_boost *= 0.6
    # ACCUMULATION/WEAKENING模式下全信量变信号（小周期催生大周期）

    early_inference = None
    if acc_stage in ("BREAKTHROUGH_CONFIRMED", "BREAKTHROUGH_IMMINENT"):
        early_inference = {
            "inferred_direction": acc_early_dir,
            "stage": acc_stage,
            "description": accumulation["description"],
        }
        if acc_early_dir and acc_early_dir != direction:
            if acc_stage == "BREAKTHROUGH_CONFIRMED":
                entry_signal = "MUST_ENTER"
                direction = acc_early_dir
                direction_diff = 1.0
            elif acc_stage == "BREAKTHROUGH_IMMINENT":
                entry_signal = "TIMING"
    elif acc_stage == "ACCUMULATION":
        early_inference = {
            "inferred_direction": acc_early_dir,
            "stage": acc_stage,
            "description": accumulation["description"],
        }

    # 置信度
    weekly_conf = weekly_lr["confidence"]
    daily_conf = daily_lr["confidence"]

    if direction_diff > 0:
        confidence = min(100, weekly_conf * 0.6 + daily_conf * 0.4 + 10)
    elif direction_diff < 0:
        confidence = weekly_conf * 0.5
    else:
        confidence = weekly_conf * 0.7

    # 量变质变置信度加成
    confidence = min(100, confidence + acc_boost)

    # 双向驱动模式置信度调节
    if drive_mode["mode"] == "CONTINUATION":
        confidence = min(100, confidence * 1.1)  # 强趋势延续，置信度提升
    elif drive_mode["mode"] == "WEAKENING":
        confidence = confidence * 0.8  # 趋势减弱，置信度降低

    return {
        "direction": direction,
        "confidence": round(confidence, 2),
        "velocity": round(velocity, 4),
        "acceleration": round(acceleration, 4),
        "entry_signal": entry_signal,
        "direction_diff": direction_diff,
        "weekly": weekly_lr,
        "daily": daily_lr,
        "small": small_lr,
        "weekly_diff": round(weekly_diff, 4),
        "daily_diff": round(daily_diff, 4),
        "trend_strength": trend_strength,
        "trend_duration": trend_duration,
        "drive_mode": drive_mode,
        "accumulation": accumulation,
        "early_inference": early_inference,
        "summary": _summarize_3d(direction, confidence, velocity, acceleration, entry_signal, accumulation, drive_mode),
    }


def _summarize_3d(direction, confidence, velocity, acceleration, entry_signal, accumulation=None, drive_mode=None):
    """生成三维模型文字描述"""
    parts = []
    if direction == "BULL":
        parts.append("方向: 看多")
    elif direction == "BEAR":
        parts.append("方向: 看空")
    else:
        parts.append("方向: 中性")

    if velocity > 0.3:
        parts.append(f"速度: 加速({velocity:.2f})")
    elif velocity < -0.3:
        parts.append(f"速度: 减速({velocity:.2f})")
    else:
        parts.append(f"速度: 平稳({velocity:.2f})")

    if acceleration > 0.2:
        parts.append(f"加速度: 正向({acceleration:.2f})")
    elif acceleration < -0.2:
        parts.append(f"加速度: 负向({acceleration:.2f})")
    else:
        parts.append(f"加速度: 趋零({acceleration:.2f})")

    # 双向驱动模式
    if drive_mode:
        mode_map = {
            "CONTINUATION": "趋势延续(大→小)",
            "LATE_CONTINUATION": "延续后期(大→小,关注小周期)",
            "ACCUMULATION": "量变积累(小→大)",
            "WEAKENING": "趋势减弱(小→大)",
        }
        mode_text = mode_map.get(drive_mode["mode"], drive_mode["mode"])
        parts.append(f"驱动: {mode_text}")
        if drive_mode.get("reversal_sensitivity", 0) > 0.5:
            parts.append(f"反转敏感度: {drive_mode['reversal_sensitivity']:.2f}")

    if entry_signal == "MUST_ENTER":
        parts.append("入场: 必须")
    elif entry_signal == "TIMING":
        parts.append("入场: 择机")
    else:
        parts.append("入场: 等待")

    # 量变质变信息
    if accumulation and accumulation.get("stage", "NONE") != "NONE":
        stage_map = {
            "ACCUMULATION": "量变积累",
            "BREAKTHROUGH_IMMINENT": "质变临近",
            "BREAKTHROUGH_CONFIRMED": "质变确认",
        }
        stage_text = stage_map.get(accumulation["stage"], accumulation["stage"])
        type_text = "磨底" if accumulation.get("type") == "BOTTOM" else "筑顶"
        parts.append(f"质变: {stage_text}({type_text},{accumulation['accumulation_count']}周期)")

    return " | ".join(parts)


def _summarize_least_resistance(direction: str, confidence: float, velocity: float, acceleration: float) -> str:
    """生成最小阻力方向的文字描述"""
    if direction == "BULL":
        if velocity > 0.5 and acceleration > 0:
            return "多方阻力持续减小，上涨趋势加速中"
        elif velocity > 0.3:
            return "多方阻力较小，上涨趋势明确"
        elif velocity > 0.1:
            return "多方阻力略小，震荡偏多"
        else:
            return "多空阻力接近，略偏向多方"
    elif direction == "BEAR":
        if velocity < -0.5 and acceleration < 0:
            return "空方阻力持续减小，下跌趋势加速中"
        elif velocity < -0.3:
            return "空方阻力较小，下跌趋势明确"
        elif velocity < -0.1:
            return "空方阻力略小，震荡偏空"
        else:
            return "多空阻力接近，略偏向空方"
    else:
        return "多空阻力相当，方向不明"


def _ema(data, period: int) -> np.ndarray:
    """计算EMA（返回与输入等长数组）"""
    n = len(data)
    if n < period:
        return np.zeros(n)
    multiplier = 2 / (period + 1)
    ema = np.zeros(n)
    ema[period-1] = np.mean(data[:period])
    for i in range(period, n):
        ema[i] = (data[i] - ema[i-1]) * multiplier + ema[i-1]
    ema[:period-1] = ema[period-1]
    return ema


def _sma(data, period: int) -> np.ndarray:
    """计算SMA"""
    if len(data) < period:
        return np.array(data)
    sma = np.convolve(data, np.ones(period)/period, mode='valid')
    return sma


def _detect_macd_divergence(close, macd_line) -> str:
    """检测MACD背离"""
    if len(close) < 30 or len(macd_line) < 30:
        return "none"

    lookback = min(30, len(close) - 1)
    price_high_idx = np.argmax(close[-lookback:])
    macd_high_idx = np.argmax(macd_line[-lookback:])

    price_low_idx = np.argmin(close[-lookback:])
    macd_low_idx = np.argmin(macd_line[-lookback:])

    if price_high_idx > macd_high_idx + 3:
        return "bearish"
    elif price_low_idx > macd_low_idx + 3:
        return "bullish"

    return "none"
