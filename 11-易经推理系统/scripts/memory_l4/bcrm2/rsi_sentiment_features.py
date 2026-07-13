"""
RSI市场情绪买卖压力特征 — 数学确定性的超买超卖标尺

理论映射:
  RSI是0-100的归一化动量指标，具有数学确定性。
  不同市值币种的RSI阈值不同:
    - 大市值(BTC): 波动小，30/70阈值合适
    - 中市值(ETH): 波动中，可以30/70或25/75
    - 小市值: 波动大，20/80阈值更合适

  本模块通过波动率自动判断币种类型，自适应选择阈值，
  并计算多种RSI衍生情绪指标。

核心特征:
  1. 多周期RSI + 自适应超买超卖阈值
  2. RSI背离检测 (价格新高/新低 vs RSI不新高/新低)
  3. 买卖压力量化 (RSI在50上方的时长/幅度 = 多方压力)
  4. RSI区间分析 (趋势模式 vs 震荡模式)
  5. RSI与价格的量价关系
"""

import numpy as np
import pandas as pd
from typing import List, Optional, Dict


# ============================================================
# RSI基础计算
# ============================================================

def _calc_rsi(close: pd.Series, period: int) -> pd.Series:
    """计算RSI"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    return 100 - (100 / (1 + rs))


# ============================================================
# 自适应阈值判断
# ============================================================

def _classify_volatility(df: pd.DataFrame, lookback: int = 120) -> tuple:
    """
    根据波动率自动分类币种类型

    Returns:
        (rsi_oversold, rsi_overbought): 自适应阈值
        - 大市值低波动: (30, 70)
        - 中市值中波动: (25, 75) 
        - 小市值高波动: (20, 80)
    """
    returns = df["close"].pct_change()
    vol = returns.rolling(lookback).std() * np.sqrt(24 * 365)  # 年化波动率

    # 用波动率中位数判断类型
    median_vol = vol.median()

    if median_vol < 0.6:  # 年化60%以下 = 低波动(BTC类)
        return 30.0, 70.0
    elif median_vol < 1.0:  # 年化100%以下 = 中波动(ETH类)
        return 25.0, 75.0
    else:  # 高波动(小币种)
        return 20.0, 80.0


# ============================================================
# 1. 多周期RSI + 自适应超买超卖
# ============================================================

def rsi_adaptive_features(
    df: pd.DataFrame,
    rsi_periods: Optional[List[int]] = None,
) -> pd.DataFrame:
    """
    多周期RSI + 自适应超买超卖阈值

    大币种(BTC)用30/70，小币种用20/80，自动判断
    """
    if rsi_periods is None:
        rsi_periods = [6, 14, 28]

    feats = pd.DataFrame(index=df.index)
    close = df["close"]

    # 自适应阈值
    oversold, overbought = _classify_volatility(df)
    feats["rsi_oversold_threshold"] = oversold
    feats["rsi_overbought_threshold"] = overbought

    for period in rsi_periods:
        rsi = _calc_rsi(close, period)
        rsi_norm = rsi / 100.0  # 归一化到0-1

        feats[f"rsi_{period}"] = rsi_norm
        feats[f"rsi_{period}_center"] = rsi_norm - 0.5  # 偏离中性的程度

        # 自适应超买超卖标记
        feats[f"rsi_{period}_oversold"] = (rsi < oversold).astype(float)
        feats[f"rsi_{period}_overbought"] = (rsi > overbought).astype(float)

        # 超买超卖强度 (离阈值有多远)
        feats[f"rsi_{period}_os_strength"] = np.where(
            rsi < oversold,
            (oversold - rsi) / oversold,  # 超卖强度 0-1
            0
        )
        feats[f"rsi_{period}_ob_strength"] = np.where(
            rsi > overbought,
            (rsi - overbought) / (100 - overbought),  # 超买强度 0-1
            0
        )

        # RSI变化方向
        rsi_diff = rsi.diff()
        feats[f"rsi_{period}_rising"] = (rsi_diff > 0).astype(float)
        feats[f"rsi_{period}_velocity"] = rsi_diff / 10  # RSI变化速度

    # 多周期RSI一致性
    rsi6 = _calc_rsi(close, 6)
    rsi14 = _calc_rsi(close, 14)
    rsi28 = _calc_rsi(close, 28)

    # 都在超卖区 = 强超卖信号
    feats["rsi_all_oversold"] = (
        (rsi6 < oversold) & (rsi14 < oversold) & (rsi28 < oversold)
    ).astype(float)
    # 都在超买区 = 强超买信号
    feats["rsi_all_overbought"] = (
        (rsi6 > overbought) & (rsi14 > overbought) & (rsi28 > overbought)
    ).astype(float)

    # RSI多周期趋势一致性 (同方向)
    rsi_direction = pd.DataFrame({
        "r6": np.sign(rsi6 - 50),
        "r14": np.sign(rsi14 - 50),
        "r28": np.sign(rsi28 - 50),
    })
    feats["rsi_consistency"] = rsi_direction.mean(axis=1)

    return feats


# ============================================================
# 2. RSI背离检测
# ============================================================

def rsi_divergence_features(
    df: pd.DataFrame,
    lookback: int = 30,
    rsi_period: int = 14,
) -> pd.DataFrame:
    """
    RSI背离检测 — 趋势衰竭的经典信号

    看涨背离: 价格创新低, RSI不创新低 (底背离)
    看跌背离: 价格创新高, RSI不创新高 (顶背离)
    """
    feats = pd.DataFrame(index=df.index)
    close = df["close"]
    high = df["high"]
    low = df["low"]
    rsi = _calc_rsi(close, rsi_period)

    # 滚动高低点
    roll_low = low.rolling(lookback).min()
    roll_high = high.rolling(lookback).max()
    rsi_at_low = rsi.rolling(lookback).min()
    rsi_at_high = rsi.rolling(lookback).max()

    # 接近新低/新高
    near_new_low = low <= roll_low * 1.005
    near_new_high = high >= roll_high * 0.995

    # 看涨背离: 价格新低, 但RSI没新低
    feats["rsi_bull_div"] = (
        near_new_low & (rsi > rsi_at_low * 0.95) & (rsi < 40)
    ).astype(float)

    # 看跌背离: 价格新高, 但RSI没新高
    feats["rsi_bear_div"] = (
        near_new_high & (rsi < rsi_at_high * 1.05) & (rsi > 60)
    ).astype(float)

    # 背离强度 (RSI与价格走势的差)
    price_slope = close.pct_change(lookback)
    rsi_slope = (rsi - rsi.shift(lookback)) / 100
    feats["rsi_price_divergence"] = (rsi_slope - price_slope).fillna(0).clip(-1, 1)

    # 连续背离计数 (强背离信号)
    div_signal = np.sign(rsi_slope - price_slope)
    div_streak = pd.Series(0, index=df.index, dtype=float)
    for i in range(1, len(df)):
        if div_signal.iloc[i] == div_signal.iloc[i-1] and div_signal.iloc[i] != 0:
            div_streak.iloc[i] = div_streak.iloc[i-1] + 1
        else:
            div_streak.iloc[i] = 1.0 if div_signal.iloc[i] != 0 else 0.0
    feats["rsi_div_streak"] = div_streak * div_signal

    return feats


# ============================================================
# 3. 买卖压力量化
# ============================================================

def rsi_pressure_features(
    df: pd.DataFrame,
    rsi_period: int = 14,
    lookback: int = 48,
) -> pd.DataFrame:
    """
    RSI买卖压力量化

    核心思想:
      RSI > 50 = 买方主导, RSI < 50 = 卖方主导
      压力强度 = RSI偏离50的程度 × 持续时间
    """
    feats = pd.DataFrame(index=df.index)
    rsi = _calc_rsi(df["close"], rsi_period)

    # 买方压力 (RSI > 50的部分)
    buy_pressure = (rsi - 50).clip(0, 50) / 50  # 0-1
    # 卖方压力 (RSI < 50的部分)
    sell_pressure = (50 - rsi).clip(0, 50) / 50  # 0-1

    feats["rsi_buy_pressure"] = buy_pressure
    feats["rsi_sell_pressure"] = sell_pressure
    feats["rsi_net_pressure"] = (buy_pressure - sell_pressure)  # -1到1

    # 压力累积 (过去N个周期的压力总和)
    feats["rsi_buy_cum"] = buy_pressure.rolling(lookback).sum().fillna(0) / lookback
    feats["rsi_sell_cum"] = sell_pressure.rolling(lookback).sum().fillna(0) / lookback
    feats["rsi_net_cum"] = feats["rsi_buy_cum"] - feats["rsi_sell_cum"]

    # 压力持续性 (RSI在50上方/下方的时间比例)
    above_50 = (rsi > 50).astype(float)
    below_50 = (rsi < 50).astype(float)
    feats["rsi_bull_duration"] = above_50.rolling(lookback).mean().fillna(0.5)
    feats["rsi_bear_duration"] = below_50.rolling(lookback).mean().fillna(0.5)

    # 压力变化速度 (压力是在增强还是减弱)
    feats["rsi_buy_velocity"] = buy_pressure.diff(5).fillna(0)
    feats["rsi_sell_velocity"] = sell_pressure.diff(5).fillna(0)

    # 压力极值反转信号
    buy_extreme = buy_pressure > 0.8  # RSI > 90
    sell_extreme = sell_pressure > 0.8  # RSI < 10
    feats["rsi_buy_extreme"] = buy_extreme.astype(float)
    feats["rsi_sell_extreme"] = sell_extreme.astype(float)

    # 极值后反转 (压力从极值回落)
    feats["rsi_buy_reversal"] = (buy_extreme.shift(1) & ~buy_extreme & (buy_pressure.diff() < 0)).astype(float)
    feats["rsi_sell_reversal"] = (sell_extreme.shift(1) & ~sell_extreme & (sell_pressure.diff() < 0)).astype(float)

    return feats


# ============================================================
# 4. RSI区间分析
# ============================================================

def rsi_regime_features(
    df: pd.DataFrame,
    rsi_period: int = 14,
    lookback: int = 60,
) -> pd.DataFrame:
    """
    RSI区间分析 — 判断趋势模式 vs 震荡模式

    趋势模式: RSI长期在50上方/下方
    震荡模式: RSI在40-60之间反复
    """
    feats = pd.DataFrame(index=df.index)
    rsi = _calc_rsi(df["close"], rsi_period)

    # RSI均值和标准差
    rsi_mean = rsi.rolling(lookback).mean()
    rsi_std = rsi.rolling(lookback).std()

    feats["rsi_mean"] = (rsi_mean / 100).fillna(0.5)
    feats["rsi_volatility"] = (rsi_std / 50).fillna(0.5).clip(0, 2)

    # 市场模式: RSI均值偏离50 + 低波动 = 趋势模式
    deviation = np.abs(rsi_mean - 50)
    feats["rsi_trending"] = ((deviation > 10) & (rsi_std < 15)).astype(float)
    feats["rsi_ranging"] = ((deviation < 5) & (rsi_std > 10)).astype(float)

    # RSI通道 (布林带式)
    rsi_upper = rsi_mean + 2 * rsi_std
    rsi_lower = rsi_mean - 2 * rsi_std
    feats["rsi_at_upper"] = (rsi > rsi_upper).astype(float)
    feats["rsi_at_lower"] = (rsi < rsi_lower).astype(float)
    feats["rsi_channel_pos"] = ((rsi - rsi_lower) / (rsi_upper - rsi_lower + 1e-10)).fillna(0.5).clip(-0.5, 1.5)

    # RSI动量加速度 (二阶导数)
    rsi_accel = rsi.diff().diff()
    feats["rsi_acceleration"] = (rsi_accel / 10).fillna(0).clip(-2, 2)

    return feats


# ============================================================
# 5. RSI情绪压力综合引擎
# ============================================================

class RSISentimentFeatures:
    """
    RSI市场情绪买卖压力特征引擎

    核心价值:
      1. 自适应阈值 — 大币种30/70, 小币种20/80, 数学确定性
      2. 买卖压力量化 — RSI偏离50的程度 = 压力强度
      3. 背离检测 — 趋势衰竭的经典信号
      4. 区间分析 — 趋势模式 vs 震荡模式

    四大类特征:
      1. 多周期RSI + 自适应超买超卖
      2. RSI背离 (看涨/看跌)
      3. 买卖压力 (累积/速度/极值)
      4. RSI区间 (趋势/震荡模式)
    """

    def __init__(self):
        pass

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        all_feats = []
        all_feats.append(rsi_adaptive_features(df))
        all_feats.append(rsi_divergence_features(df))
        all_feats.append(rsi_pressure_features(df))
        all_feats.append(rsi_regime_features(df))
        result = pd.concat(all_feats, axis=1)
        result = result.ffill().fillna(0)
        result = result.replace([np.inf, -np.inf], 0)
        return result

    @property
    def feature_groups(self) -> Dict[str, str]:
        return {
            "rsi_adaptive": "多周期RSI + 自适应超买超卖",
            "rsi_divergence": "RSI背离检测 (趋势衰竭)",
            "rsi_pressure": "买卖压力量化 (累积/速度/极值)",
            "rsi_regime": "RSI区间分析 (趋势/震荡模式)",
        }
