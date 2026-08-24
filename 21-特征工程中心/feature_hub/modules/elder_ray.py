"""Elder-ray Adapter — Elder-ray 力量指标 → 7 列标准化特征

基于 Alexander Elder 的 Elder-ray 指标：
  Bull Power = High - EMA(close, 13)
  Bear Power = Low - EMA(close, 13)

输出 7 列：
  one-hot 5 列：elder_bullish_strong / elder_bullish / elder_neutral / elder_bearish / elder_bearish_strong
  差分 2 列：elder_bull_power_diff / elder_bear_power_diff
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from feature_hub.adapters.base_adapter import BaseAdapter


class ElderRayAdapter(BaseAdapter):
    """Elder-ray 力量指标适配器"""

    def __init__(self, ema_period: int = 13) -> None:
        self.ema_period = ema_period

    def compute(
        self,
        df: pd.DataFrame,
        ref_df: Optional[pd.DataFrame] = None,
        macro_df: Optional[pd.DataFrame] = None,
        symbol: str = "",
    ) -> pd.DataFrame:
        close = df["close"]
        high = df["high"]
        low = df["low"]

        # EMA
        ema = close.ewm(span=self.ema_period, adjust=False).mean()

        # Bull Power / Bear Power
        bull_power = high - ema
        bear_power = low - ema

        # Rating
        rating = pd.Series("neutral", index=df.index)
        rating[(bull_power > 0) & (bear_power > 0)] = "bullish_strong"
        rating[(bull_power > 0) & (bear_power <= 0)] = "bullish"
        rating[(bull_power <= 0) & (bear_power < 0)] = "bearish_strong"
        rating[(bull_power <= 0) & (bear_power >= 0) & (bull_power < 0)] = "bearish"

        # One-hot 5 列
        categories = ["bullish_strong", "bullish", "neutral", "bearish", "bearish_strong"]
        result = pd.DataFrame(index=df.index)
        for cat in categories:
            result[f"elder_{cat}"] = (rating == cat).astype(float)

        # 差分 2 列
        result["elder_bull_power_diff"] = bull_power.diff()
        result["elder_bear_power_diff"] = bear_power.diff()

        return result


def compute(
    df: pd.DataFrame,
    ref_df: Optional[pd.DataFrame] = None,
    macro_df: Optional[pd.DataFrame] = None,
    symbol: str = "",
) -> pd.DataFrame:
    """模块级入口 — 供 FeaturePipeline.register_module 注册"""
    return ElderRayAdapter().compute(df, ref_df=ref_df, macro_df=macro_df, symbol=symbol)
