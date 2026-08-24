"""FiveDomainFc Adapter — 五域特征 → 5 列 RobustScaler 标准化

五域概念（简化版，从 OHLCV 直接计算）：
  dao  (道) : 趋势方向 — EMA 斜率归一化
  tian (天) : 市场环境 — 波动率分位
  di   (地) : 支撑阻力 — 价格位置（close vs high-low range）
  jiang(将) : 动量强弱 — RSI 风格
  fa   (法) : 量价纪律 — 成交量 zscore

每域输出 0-100 原始分 → RobustScaler 标准化 ≈ [-3, 3]
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from feature_hub.adapters.base_adapter import BaseAdapter


class FiveDomainFcAdapter(BaseAdapter):
    """五域特征适配器"""

    def __init__(self, asset_class: str = "crypto") -> None:
        self.asset_class = asset_class

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
        volume = df["volume"]

        # 道趋势方向：EMA 斜率归一化
        ema = close.ewm(span=20, adjust=False).mean()
        ema_slope = ema.diff(5)
        dao = ((ema_slope / (ema.abs() + 1e-10)) * 50 + 50).clip(0, 100)

        # 天市场环境：ATR 归一化分位
        tr = (high - low).rolling(14).mean()
        tr_pct = tr / (close + 1e-10)
        tian = (tr_pct.rolling(60).rank(pct=True) * 100).clip(0, 100)

        # 地支撑阻力：价格位置
        roll_high = high.rolling(20).max()
        roll_low = low.rolling(20).min()
        price_range = (roll_high - roll_low).replace(0, np.nan)
        di = ((close - roll_low) / price_range * 100).clip(0, 100)

        # 将动量：RSI 风格
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / (loss + 1e-10)
        jiang = (100 - 100 / (1 + rs)).clip(0, 100)

        # 法量价纪律：成交量 zscore → 0-100
        vol_ma = volume.rolling(20).mean()
        vol_std = volume.rolling(20).std()
        vol_z = (volume - vol_ma) / (vol_std + 1e-10)
        fa = ((vol_z + 3) / 6 * 100).clip(0, 100)

        raw = pd.DataFrame({
            "dao": dao, "tian": tian, "di": di,
            "jiang": jiang, "fa": fa,
        }, index=df.index)

        # RobustScaler：每列 (x - median) / IQR
        out = pd.DataFrame(index=df.index)
        for col in raw.columns:
            s = raw[col]
            med = s.median()
            q1 = s.quantile(0.25)
            q3 = s.quantile(0.75)
            iqr = q3 - q1
            if iqr == 0 or pd.isna(iqr):
                out[col] = s - med
            else:
                out[col] = (s - med) / iqr
        return out


def compute(
    df: pd.DataFrame,
    ref_df: Optional[pd.DataFrame] = None,
    macro_df: Optional[pd.DataFrame] = None,
    symbol: str = "",
) -> pd.DataFrame:
    """模块级入口 — 供 FeaturePipeline.register_module 注册"""
    return FiveDomainFcAdapter().compute(df, ref_df=ref_df, macro_df=macro_df, symbol=symbol)
