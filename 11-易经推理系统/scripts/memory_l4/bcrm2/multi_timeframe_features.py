"""多时间框架特征 — 跨周期价格结构特征

设计目标：
  补充 MA200/周期特征之外的「跨周期结构」信息，提升模型区分相似 regime 的能力。
  现有 16 列特征对 TREND_UP_MILD vs RANGE_BOUND vs CONSOLIDATION 区分度不足，
  本模块新增 6 列跨周期特征，从「MA 对齐/多周期动量/波动率分位/成交量」四个维度
  增强形态判别信息量。

特征列表（6 列）:
  - ma_alignment_score: MA20/50/100/200 堆叠对齐评分
      +1 = 完美多头排列（MA20>MA50>MA100>MA200）
      -1 = 完美空头排列（MA20<MA50<MA100<MA200）
      0 = 均线纠缠（无明确趋势方向）
  - ma_cross_50_200_signal: MA50 vs MA200 金叉/死叉信号
      1 = 金叉（MA50 > MA200），-1 = 死叉，值大小按距离比例
  - log_ret_30d: 30 日对数收益（短期动量）
  - log_ret_90d: 90 日对数收益（中期动量，与 180d 互补）
  - vol_60d_percentile_252d: 60 日波动率在 252 日窗口的分位（波动率结构）
      高分位 = 当前波动率高于过去一年多数时间（极端市场）
  - volume_ma20_ratio: 当前成交量 / 20 日均量（成交量结构）
      >1 = 放量，<1 = 缩量，区分趋势确认 vs 假突破
"""
from __future__ import annotations

import logging
import numpy as np
import pandas as pd
from typing import Dict, List

logger = logging.getLogger(__name__)

__all__ = ["MultiTimeframeFeatures"]


def compute_ma_alignment_score(close: pd.Series) -> pd.Series:
    """计算 MA20/50/100/200 堆叠对齐评分。

    评分逻辑：
      - 4 条均线完美多头排列（MA20>MA50>MA100>MA200）= +1.0
      - 4 条均线完美空头排列（MA20<MA50<MA100<MA200）= -1.0
      - 部分对齐：每对相邻 MA 满足条件 +0.25，不满足 -0.25
      - 均线纠缠（混合）= 接近 0

    Args:
        close: 收盘价 Series

    Returns:
        Series: 对齐评分 [-1.0, 1.0]
    """
    ma20 = close.rolling(20, min_periods=10).mean()
    ma50 = close.rolling(50, min_periods=25).mean()
    ma100 = close.rolling(100, min_periods=50).mean()
    ma200 = close.rolling(200, min_periods=100).mean()

    # 4 对相邻 MA 的对齐情况（多头=+1, 空头=-1, 纠缠=0）
    pairs = [
        (ma20, ma50),
        (ma50, ma100),
        (ma100, ma200),
        (ma20, ma200),  # 长短期价差确认
    ]

    score = pd.Series(0.0, index=close.index)
    for fast, slow in pairs:
        # 多头排列
        bull = (fast > slow).astype(float)
        # 空头排列
        bear = (fast < slow).astype(float)
        # 每对贡献 ±0.25
        score += 0.25 * (bull - bear)

    score = score.clip(-1.0, 1.0).fillna(0.0)
    return score


def compute_ma_cross_signal(close: pd.Series) -> pd.Series:
    """计算 MA50 vs MA200 金叉/死叉信号。

    信号逻辑：
      - MA50 > MA200 = 金叉（多头环境），信号强度按 (MA50-MA200)/MA200 比例
      - MA50 < MA200 = 死叉（空头环境），信号强度按比例
      - 用 tanh 限幅到 [-1, 1] 避免极端值

    Args:
        close: 收盘价 Series

    Returns:
        Series: 信号值 [-1, 1]
    """
    ma50 = close.rolling(50, min_periods=25).mean()
    ma200 = close.rolling(200, min_periods=100).mean()

    # (MA50 - MA200) / MA200 比例
    diff_pct = ((ma50 - ma200) / ma200).replace([np.inf, -np.inf], 0.0).fillna(0.0)

    # tanh 限幅，5% 差距即饱和
    signal = np.tanh(diff_pct / 0.05)
    return pd.Series(signal, index=close.index).fillna(0.0)


def compute_log_returns(close: pd.Series, periods: List[int]) -> pd.DataFrame:
    """计算多周期对数收益。

    Args:
        close: 收盘价 Series
        periods: 周期列表，如 [30, 90]

    Returns:
        DataFrame with columns log_ret_{period}d
    """
    feats = {}
    for p in periods:
        col = f"log_ret_{p}d"
        feats[col] = np.log(close / close.shift(p)).replace([np.inf, -np.inf], 0.0)
    return pd.DataFrame(feats, index=close.index).fillna(0.0)


def compute_vol_percentile(close: pd.Series, vol_window: int = 60, rank_window: int = 252) -> pd.Series:
    """计算短期波动率在长周期的分位。

    形态语义：
      - 高分位（>0.8）= 当前波动率高于过去一年多数时间 → 极端市场（FOMO/暴跌）
      - 低分位（<0.2）= 当前波动率低于过去一年多数时间 → 压缩期（CONSOLIDATION）
      - 中分位 = 正常波动环境

    Args:
        close: 收盘价 Series
        vol_window: 短期波动率窗口，默认 60 日
        rank_window: 分位数计算窗口，默认 252 日（一年）

    Returns:
        Series: 分位数 [0, 1]
    """
    daily_ret = close.pct_change()
    vol = daily_ret.rolling(vol_window, min_periods=vol_window // 2).std() * np.sqrt(365)

    # 滚动分位
    percentile = vol.rolling(rank_window, min_periods=rank_window // 2).rank(pct=True)
    return percentile.fillna(0.5)


def compute_volume_ratio(df: pd.DataFrame, ma_period: int = 20) -> pd.Series:
    """计算成交量相对均量的比例。

    Args:
        df: OHLCV DataFrame，需含 volume 列
        ma_period: 均量周期，默认 20 日

    Returns:
        Series: 成交量比例（>1=放量，<1=缩量）
    """
    if "volume" not in df.columns:
        return pd.Series(1.0, index=df.index)

    volume = df["volume"].astype(float)
    vol_ma = volume.rolling(ma_period, min_periods=ma_period // 2).mean()

    ratio = (volume / vol_ma.replace(0, np.nan)).clip(0, 10).fillna(1.0)
    # tanh 限幅避免极端值
    ratio = np.tanh((ratio - 1.0) / 2.0)  # 中心化到 0 附近
    return pd.Series(ratio, index=df.index).fillna(0.0)


class MultiTimeframeFeatures:
    """多时间框架特征模块

    输出 6 列跨周期结构特征：
      - ma_alignment_score: MA 堆叠对齐评分 [-1, 1]
      - ma_cross_50_200_signal: 金叉/死叉信号 [-1, 1]
      - log_ret_30d: 30 日对数收益
      - log_ret_90d: 90 日对数收益
      - vol_60d_percentile_252d: 60 日波动率分位 [0, 1]
      - volume_ma20_ratio: 成交量相对均量比例（tanh 限幅）
    """

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"] if "close" in df.columns else pd.Series(df.iloc[:, -1], index=df.index)
        close = close.astype(float)

        alignment = compute_ma_alignment_score(close)
        cross_signal = compute_ma_cross_signal(close)
        log_rets = compute_log_returns(close, periods=[30, 90])
        vol_pct = compute_vol_percentile(close)
        vol_ratio = compute_volume_ratio(df)

        feats = pd.DataFrame({
            "ma_alignment_score": alignment,
            "ma_cross_50_200_signal": cross_signal,
            "vol_60d_percentile_252d": vol_pct,
            "volume_ma20_ratio": vol_ratio,
        }, index=df.index)

        feats = pd.concat([feats, log_rets], axis=1)
        feats = feats.replace([np.inf, -np.inf], 0.0).fillna(0)
        return feats

    @property
    def feature_categories(self) -> Dict[str, List[str]]:
        return {"multi_timeframe": "多时间框架结构特征"}


# ============================================================
# FeatureRegistry 注册
# ============================================================
from bcrm2.feature_registry import FeatureRegistry  # noqa: E402

FeatureRegistry.register(name="multi_timeframe", factory=MultiTimeframeFeatures)
