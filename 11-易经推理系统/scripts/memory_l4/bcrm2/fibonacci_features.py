"""
斐波那契技术特征 — 数学确定性的比例分割

理论映射:
  "金融市场变化无序，但斐波那契比例是数学确定性的分割"
  不同市值的币种波动率不同，但斐波那契比例是统一的度量衡:
    - BTC (大市值低波动): 回撤通常止于浅层 (0.236/0.382)
    - ETH (中市值中波动): 回撤通常到中层 (0.5/0.618)
    - 小市值高波动: 回撤可能到深层 (0.786/1.0)

核心思想: 用斐波那契比例作为"归一化标尺"，
  将不同币种的价格波动映射到统一的比例空间，
  让模型能够跨币种比较"回撤深度"和"反弹强度"。

包含特征:
  1. 斐波那契回撤位 (Fibonacci Retracement)
  2. 斐波那契扩展位 (Fibonacci Extension)
  3. 斐波那契扇形 (Fibonacci Fan)
  4. 斐波那契时间周期 (Fibonacci Time Zones)
  5. 波动率归一化的回撤深度
"""

import numpy as np
import pandas as pd
from typing import List, Optional, Tuple, Dict


# 斐波那契关键比例
FIB_RATIOS = {
    "0236": 0.236,
    "0382": 0.382,
    "05": 0.5,
    "0618": 0.618,
    "0786": 0.786,
    "10": 1.0,
    "1272": 1.272,
    "1618": 1.618,
    "20": 2.0,
    "2618": 2.618,
}

# 回撤常用比例
RETRACE_RATIOS = [0.236, 0.382, 0.5, 0.618, 0.786]
# 扩展常用比例
EXTENSION_RATIOS = [0.618, 1.0, 1.272, 1.618, 2.0, 2.618]


# ============================================================
# 1. 斐波那契回撤特征
# ============================================================

def fibonacci_retracement_features(
    df: pd.DataFrame,
    swing_lookback: int = 60,
    ratios: Optional[List[float]] = None,
) -> pd.DataFrame:
    """
    斐波那契回撤特征

    计算逻辑:
      1. 找到过去N根K线的最高点和最低点 (摆动高低点)
      2. 计算斐波那契回撤位: 从高点到低点的反弹/回调比例
      3. 当前价格处于哪个回撤位 = 归一化的回撤深度

    用法:
      - 上升趋势中: 回调到0.382/0.5/0.618是潜在支撑位
      - 下降趋势中: 反弹到0.382/0.5/0.618是潜在阻力位
      - 回撤深度归一化: 不同币种用同一比例标尺比较

    Args:
        df: OHLCV数据
        swing_lookback: 摆动高低点的回看周期
        ratios: 回撤比例列表

    Returns:
        DataFrame of Fibonacci retracement features
    """
    if ratios is None:
        ratios = RETRACE_RATIOS

    feats = pd.DataFrame(index=df.index)

    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    n = len(df)

    # 滚动最高点和最低点
    roll_high = pd.Series(high).rolling(swing_lookback).max().values
    roll_low = pd.Series(low).rolling(swing_lookback).min().values

    # 摆动幅度 (高-低)
    swing_range = roll_high - roll_low
    swing_range_safe = np.where(swing_range > 1e-10, swing_range, 1e-10)

    # 当前价格在摆动区间内的位置 (0=最低点, 1=最高点)
    position_in_range = (close - roll_low) / swing_range_safe
    position_in_range = np.clip(position_in_range, -0.5, 1.5)
    feats["fib_retrace_position"] = position_in_range

    # 回撤深度: 从最高点回落的比例 (0=在最高点, 1=在最低点)
    retrace_depth = (roll_high - close) / swing_range_safe
    retrace_depth = np.clip(retrace_depth, -0.5, 1.5)
    feats["fib_retrace_depth"] = retrace_depth

    # 距离各回撤位的距离 (当前价 - 回撤位) / 摆动幅度
    for i, ratio in enumerate(ratios):
        ratio_name = f"{int(ratio*1000)}"
        # 上升回撤位 (从高点往下 = roll_high - ratio*range)
        retrace_level_bull = roll_high - ratio * swing_range_safe
        # 距离该位的远近 (正=在上方, 负=在下方, 接近0=正好在该位)
        dist_to_level = (close - retrace_level_bull) / swing_range_safe
        feats[f"fib_bull_{ratio_name}_dist"] = dist_to_level
        # 是否接近该位 (±5%摆动范围)
        feats[f"fib_bull_{ratio_name}_touch"] = (np.abs(dist_to_level) < 0.05).astype(float)

    # 最近的回撤位是哪个 (编码为比例值)
    closest_ratio = np.zeros(n)
    for i in range(n):
        if np.isnan(swing_range[i]) or swing_range[i] < 1e-10:
            closest_ratio[i] = 0.5
            continue
        pos = position_in_range[i]
        # 找最接近的回撤比例
        dists = [abs(pos - r) for r in ratios]
        min_idx = np.argmin(dists)
        closest_ratio[i] = ratios[min_idx]
    feats["fib_closest_retrace"] = closest_ratio

    # 回撤强度: 当前回撤速度 (5根K线回撤了多少比例)
    retrace_5d_ago = (roll_high - pd.Series(close).shift(5).values) / swing_range_safe
    retrace_velocity = retrace_depth - retrace_5d_ago
    feats["fib_retrace_velocity"] = np.nan_to_num(retrace_velocity, 0)

    # 摆动区间的波动率归一化 (摆动幅度 / 平均波动率)
    atr_proxy = pd.Series(high - low).rolling(14).mean().values
    feats["fib_swing_atr_ratio"] = np.where(
        atr_proxy > 1e-10, swing_range / (atr_proxy * 10), 1.0
    )
    feats["fib_swing_atr_ratio"] = np.nan_to_num(feats["fib_swing_atr_ratio"], 1)

    return feats


# ============================================================
# 2. 斐波那契扩展特征
# ============================================================

def fibonacci_extension_features(
    df: pd.DataFrame,
    swing_lookback: int = 60,
    ratios: Optional[List[float]] = None,
) -> pd.DataFrame:
    """
    斐波那契扩展特征

    计算逻辑:
      找到一段趋势(A→B)，然后预测C浪的目标位 = B + (A→B幅度) × 比例
      用于: 突破后的目标位预测、止盈位计算

    简化实现: 用近期高低点估算扩展目标位
    """
    if ratios is None:
        ratios = EXTENSION_RATIOS

    feats = pd.DataFrame(index=df.index)

    high = df["high"].values
    low = df["low"].values
    close = df["close"].values

    # 近期高低点
    roll_high = pd.Series(high).rolling(swing_lookback).max().values
    roll_low = pd.Series(low).rolling(swing_lookback).min().values
    swing_range = roll_high - roll_low
    swing_range_safe = np.where(swing_range > 1e-10, swing_range, 1e-10)

    # 向上扩展目标位 (从低点向上扩展)
    for ratio in ratios:
        ratio_name = f"{int(ratio*1000)}" if ratio < 10 else f"r{int(ratio*100)}"
        ext_up = roll_low + ratio * swing_range_safe
        # 当前价距离该扩展位的距离
        dist_up = (ext_up - close) / swing_range_safe
        feats[f"fib_ext_up_{ratio_name}"] = dist_up
        # 是否突破该位
        feats[f"fib_ext_up_{ratio_name}_break"] = (close > ext_up).astype(float)

    # 向下扩展目标位 (从高点向下扩展)
    for ratio in ratios:
        ratio_name = f"{int(ratio*1000)}" if ratio < 10 else f"r{int(ratio*100)}"
        ext_down = roll_high - ratio * swing_range_safe
        dist_down = (close - ext_down) / swing_range_safe
        feats[f"fib_ext_down_{ratio_name}"] = dist_down
        feats[f"fib_ext_down_{ratio_name}_break"] = (close < ext_down).astype(float)

    # 最近的扩展目标位
    feats["fib_next_resistance"] = 0.0  # 最近的上方扩展位比例
    feats["fib_next_support"] = 0.0     # 最近的下方扩展位比例

    return feats


# ============================================================
# 3. 波动率归一化的回撤深度
# ============================================================

def volatility_normalized_fib_features(
    df: pd.DataFrame,
    atr_period: int = 14,
    lookback_periods: Optional[List[int]] = None,
) -> pd.DataFrame:
    """
    波动率归一化的斐波那契特征

    核心思想:
      不同币种的绝对价格波动率不同，但用ATR归一化后可比:
        - BTC: 价格高但ATR/价格比小 (低波动)
        - ETH: 价格中但ATR/价格比中 (中波动)
        - 小币: 价格低但ATR/价格比大 (高波动)

      用ATR作为"单位波动率标尺"，计算:
        - 回撤了多少个ATR (= 归一化深度)
        - 反弹了多少个ATR (= 归一化强度)
        - 这些值映射到斐波那契比例空间

    这是解决"不同币种幅度不可比"的核心特征。
    """
    if lookback_periods is None:
        lookback_periods = [12, 24, 60, 120]

    feats = pd.DataFrame(index=df.index)

    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    n = len(df)

    # ATR计算
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i-1]),
            abs(low[i] - close[i-1])
        )
    atr = pd.Series(tr).rolling(atr_period).mean().values
    atr_safe = np.where(atr > 1e-10, atr, 1e-10)

    # 归一化波动率 (ATR/价格: 不同币种可比)
    feats["fib_atr_norm"] = atr / close  # 百分比波动率

    for period in lookback_periods:
        # 周期内最高/最低点
        period_high = pd.Series(high).rolling(period).max().values
        period_low = pd.Series(low).rolling(period).min().values

        # 从高点回撤的ATR数 (归一化回撤深度)
        drawdown_atr = (period_high - close) / atr_safe
        feats[f"fib_dd_atr_{period}"] = np.nan_to_num(drawdown_atr, 0)

        # 从低点反弹的ATR数 (归一化反弹强度)
        rally_atr = (close - period_low) / atr_safe
        feats[f"fib_rally_atr_{period}"] = np.nan_to_num(rally_atr, 0)

        # 周期振幅的ATR数 (归一化波动幅度)
        range_atr = (period_high - period_low) / atr_safe
        feats[f"fib_range_atr_{period}"] = np.nan_to_num(range_atr, 0)

        # 回撤深度映射到斐波那契比例 (用范围做分母)
        range_val = period_high - period_low
        range_safe = np.where(range_val > 1e-10, range_val, 1e-10)
        retrace_depth = (period_high - close) / range_safe
        feats[f"fib_dd_ratio_{period}"] = np.clip(np.nan_to_num(retrace_depth, 0), 0, 1.5)

    # 斐波那契回撤位的ATR距离 (价格到各Fib位 = 多少个ATR)
    # 这是"用ATR度量Fib位距离"的核心特征
    for period in [60, 120]:
        period_high = pd.Series(high).rolling(period).max().values
        period_low = pd.Series(low).rolling(period).min().values
        range_val = period_high - period_low
        range_safe = np.where(range_val > 1e-10, range_val, 1e-10)

        for ratio in [0.382, 0.5, 0.618]:
            ratio_name = f"{int(ratio*1000)}"
            # 上升趋势回撤位
            retrace_level = period_high - ratio * range_safe
            dist_atr = (close - retrace_level) / atr_safe
            feats[f"fib_dd{period}_{ratio_name}_atr"] = np.nan_to_num(dist_atr, 0)

    # ATR归一化的斐波那契扇形近似
    # 扇形用不同比例的趋势线斜率表示，简化为不同周期的回撤深度梯度
    feats["fib_fan_slope"] = 0.0
    if len(lookback_periods) >= 2:
        short_dd = feats[f"fib_dd_atr_{lookback_periods[0]}"]
        long_dd = feats[f"fib_dd_atr_{lookback_periods[-1]}"]
        feats["fib_fan_slope"] = np.nan_to_num(short_dd - long_dd, 0)

    return feats


# ============================================================
# 4. 斐波那契时间周期特征
# ============================================================

def fibonacci_time_features(
    df: pd.DataFrame,
    swing_lookback: int = 120,
) -> pd.DataFrame:
    """
    斐波那契时间周期特征

    斐波那契时间序列: 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144...

    用法:
      从重要高低点开始数，第N个斐波那契时间单位可能是变盘点
      用于时间维度的归一化，补充价格维度的Fib特征

    简化实现:
      - 距离最近高点/低点的K线数
      - 这些时间点与斐波那契数列的接近程度
    """
    feats = pd.DataFrame(index=df.index)

    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    n = len(df)

    # 斐波那契时间序列 (K线根数)
    fib_time_periods = [3, 5, 8, 13, 21, 34, 55, 89]

    # 滚动查找最近的高点和低点位置
    bars_since_high = np.zeros(n)
    bars_since_low = np.zeros(n)

    # 简化: 用滚动最大值/最小值的位置
    lookback = swing_lookback
    for i in range(n):
        start = max(0, i - lookback + 1)
        window_high = high[start:i+1]
        window_low = low[start:i+1]
        if len(window_high) > 0:
            bars_since_high[i] = len(window_high) - 1 - np.argmax(window_high)
            bars_since_low[i] = len(window_low) - 1 - np.argmin(window_low)

    feats["fib_time_since_high"] = bars_since_high
    feats["fib_time_since_low"] = bars_since_low

    # 距离最近斐波那契时间点的远近 (高点后)
    for period in fib_time_periods:
        dist_to_fib = np.abs(bars_since_high - period) / period
        feats[f"fib_time_high_{period}"] = np.clip(dist_to_fib, 0, 2)
        # 是否在斐波那契时间窗口 (±20%)
        feats[f"fib_time_high_{period}_win"] = (dist_to_fib < 0.2).astype(float)

    for period in fib_time_periods:
        dist_to_fib = np.abs(bars_since_low - period) / period
        feats[f"fib_time_low_{period}"] = np.clip(dist_to_fib, 0, 2)
        feats[f"fib_time_low_{period}_win"] = (dist_to_fib < 0.2).astype(float)

    # 高低点时间差是否是斐波那契数
    high_low_diff = np.abs(bars_since_high - bars_since_low)
    feats["fib_time_hl_diff"] = high_low_diff

    # 时间周期合成: 当前在时间窗口中的位置 (0=刚到变盘点, 1=远离)
    min_time_dist = np.minimum(
        np.minimum.reduce([
            np.abs(bars_since_high - p) / p
            for p in fib_time_periods
        ]),
        np.minimum.reduce([
            np.abs(bars_since_low - p) / p
            for p in fib_time_periods
        ])
    )
    feats["fib_time_nearest"] = np.clip(min_time_dist, 0, 1)

    return feats


# ============================================================
# 5. 综合: 斐波那契特征引擎
# ============================================================

class FibonacciFeatures:
    """
    斐波那契技术特征引擎

    核心价值: 用数学确定性的比例作为"统一标尺"，
    解决不同市值币种的波动幅度不可比问题。

    四大类特征:
      1. 回撤特征: 价格在摆动区间中的归一化位置
      2. 扩展特征: 突破后的目标位预测
      3. 波动率归一化: 用ATR作为单位度量Fib深度 (跨币种可比)
      4. 时间周期: 斐波那契时间窗口的变盘概率
    """

    def __init__(
        self,
        swing_lookback: int = 60,
        atr_period: int = 14,
    ):
        self.swing_lookback = swing_lookback
        self.atr_period = atr_period

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算全部斐波那契特征"""
        all_feats = []

        # 1. 回撤特征
        ret_feats = fibonacci_retracement_features(df, self.swing_lookback)
        all_feats.append(ret_feats)

        # 2. 扩展特征 (精简版本，避免特征过多)
        ext_feats = fibonacci_extension_features(df, self.swing_lookback, ratios=[1.0, 1.618, 2.618])
        all_feats.append(ext_feats)

        # 3. 波动率归一化特征 (核心)
        vol_feats = volatility_normalized_fib_features(df, self.atr_period)
        all_feats.append(vol_feats)

        # 4. 时间周期特征
        time_feats = fibonacci_time_features(df, self.swing_lookback * 2)
        all_feats.append(time_feats)

        result = pd.concat(all_feats, axis=1)
        result = result.ffill().fillna(0)
        result = result.replace([np.inf, -np.inf], 0)

        return result

    @property
    def feature_groups(self) -> Dict[str, str]:
        """特征分组说明"""
        return {
            "fib_retrace": "斐波那契回撤 - 摆动区间归一化位置",
            "fib_extension": "斐波那契扩展 - 突破目标位",
            "fib_vol_norm": "波动率归一化 - ATR标尺 (跨币种可比)",
            "fib_time": "斐波那契时间 - 变盘时间窗口",
        }
