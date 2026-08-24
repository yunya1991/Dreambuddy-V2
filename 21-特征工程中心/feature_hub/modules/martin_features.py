"""MartinFeatures — 马丁策略网格特征（5列）

从 OHLCV 模拟马丁网格持仓状态，输出：
  drawdown_depth  — 当前回撤深度（价格距近高百分比）
  martin_level     — 模拟马丁加仓层级（基于回撤分档）
  grid_profit      — 网格累计利润代理（基于波动幅度）
  atr_ratio        — ATR/价格 比率（波动率归一化）
  volatility_regime — 波动率分位（低/中/高 0/0.5/1）
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def compute(
    df: pd.DataFrame,
    ref_df: Optional[pd.DataFrame] = None,
    macro_df: Optional[pd.DataFrame] = None,
    symbol: str = "",
) -> pd.DataFrame:
    """马丁策略网格特征计算（5列）"""
    close = df["close"]
    high = df["high"]
    low = df["low"]
    result = pd.DataFrame(index=df.index)

    # drawdown_depth：价格距近60日高的回撤百分比
    roll_high = high.rolling(60, min_periods=1).max()
    result["drawdown_depth"] = (close - roll_high) / (roll_high + 1e-10)

    # martin_level：基于回撤深度分档（0~4级）
    dd = result["drawdown_depth"]
    level = pd.Series(0, index=df.index)
    level[dd < -0.05] = 1
    level[dd < -0.10] = 2
    level[dd < -0.15] = 3
    level[dd < -0.20] = 4
    result["martin_level"] = level

    # grid_profit：网格累计利润代理（基于日内波动幅度累加）
    daily_range = (high - low) / (close + 1e-10)
    result["grid_profit"] = daily_range.rolling(20, min_periods=1).sum() / 2

    # atr_ratio：ATR/价格 比率
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(14, min_periods=1).mean()
    result["atr_ratio"] = atr / (close + 1e-10)

    # volatility_regime：波动率分位（低0/中0.5/高1）
    vol_pct = result["atr_ratio"].rolling(60, min_periods=1).rank(pct=True)
    regime = pd.Series(0.5, index=df.index)
    regime[vol_pct < 0.33] = 0.0
    regime[vol_pct > 0.67] = 1.0
    result["volatility_regime"] = regime

    return result
