"""FundamentalFeatures — 基本面时序衍生特征（12列）

输入：DataFrame，列为基本面指标（如 funding_rate, long_short_ratio, whale_netflow,
      hash_rate, exchange_reserve 等），index 为时间戳。
输出：12 个衍生特征，用于 signal_engine 增强信号置信度。

特征清单：
  momentum_1d          — 1日动量（最近值 vs 1日前）
  momentum_7d          — 7日动量
  zscore_20d           — 20日 Z-score（偏离均值的标准差倍数）
  volatility_20d       — 20日波动率（收益率标准差）
  trend_strength       — 趋势强度（|20日斜率| / 波动率）
  mean_reversion       — 均值回归压力（当前值 vs 20日均值的偏离）
  rate_of_change_3d    — 3日变化率
  acceleration         — 加速度（动量的动量）
  range_ratio          — 振幅比（20日振幅 / 当前值）
  distribution_skew    — 分布偏度（20日收益率偏度）
  position_in_range    — 区间位置（当前值在20日高低点中的位置 0-1）
  stability_score      — 稳定性评分（1 - 变异系数，clamp 0-1）

设计原则：
  - 对单指标 DataFrame 也能工作（每列独立计算）
  - 缺列时跳过，不抛异常（fail-open）
  - 所有特征归一化到合理范围，便于 signal_engine 加权
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
    """基本面时序衍生特征计算。

    Args:
        df: 基本面指标时序 DataFrame，每列一个指标，index 为时间戳
        ref_df: 未使用（兼容 FeaturePipeline 接口）
        macro_df: 未使用
        symbol: 未使用

    Returns:
        DataFrame，12 列衍生特征（按列计算后取横截面平均，输出单行特征向量）
    """
    if df is None or df.empty:
        return pd.DataFrame()

    # 只保留数值列
    num_df = df.select_dtypes(include=[np.number]).copy()
    if num_df.empty:
        return pd.DataFrame()

    # 对每列做滚动 Z-score 标准化，消除量级差异后取横截面均值
    col_mean = num_df.rolling(20, min_periods=5).mean()
    col_std = num_df.rolling(20, min_periods=5).std().replace(0, np.nan)
    normalized = (num_df - col_mean) / col_std
    normalized = normalized.fillna(0.0)
    close_proxy = normalized.mean(axis=1)

    result = pd.DataFrame(index=df.index)

    # 1. momentum_1d：1日动量（用 diff 因为 proxy 可能为负）
    result["momentum_1d"] = close_proxy.diff(1).fillna(0.0)

    # 2. momentum_7d：7日动量
    result["momentum_7d"] = close_proxy.diff(7).fillna(0.0)

    # 3. zscore_20d：20日 Z-score
    roll_mean = close_proxy.rolling(20, min_periods=1).mean()
    roll_std = close_proxy.rolling(20, min_periods=1).std().replace(0, np.nan)
    result["zscore_20d"] = ((close_proxy - roll_mean) / roll_std).fillna(0.0)

    # 4. volatility_20d：20日波动率（用 diff 的标准差）
    daily_ret = close_proxy.diff().fillna(0.0)
    result["volatility_20d"] = daily_ret.rolling(20, min_periods=1).std().fillna(0.0)

    # 5. trend_strength：趋势强度 = |20日斜率| / 波动率
    slope = close_proxy.diff(20) / 20.0
    result["trend_strength"] = (
        slope.abs() / (result["volatility_20d"] + 1e-10)
    ).clip(-10, 10).fillna(0.0)

    # 6. mean_reversion：均值回归压力 = (当前值 - 20日均值) / 20日标准差
    result["mean_reversion"] = (
        (close_proxy - roll_mean) / (roll_std + 1e-10)
    ).clip(-5, 5).fillna(0.0)

    # 7. rate_of_change_3d：3日变化率
    result["rate_of_change_3d"] = close_proxy.diff(3).fillna(0.0)

    # 8. acceleration：加速度 = momentum_1d 的动量
    result["acceleration"] = result["momentum_1d"].diff().fillna(0.0)

    # 9. range_ratio：振幅比
    roll_high = close_proxy.rolling(20, min_periods=1).max()
    roll_low = close_proxy.rolling(20, min_periods=1).min()
    amplitude = (roll_high - roll_low) / (close_proxy.abs() + 1e-10)
    result["range_ratio"] = amplitude.clip(0, 10).fillna(0.0)

    # 10. distribution_skew：20日收益率偏度
    result["distribution_skew"] = daily_ret.rolling(20, min_periods=5).skew().fillna(0.0)

    # 11. position_in_range：区间位置 0-1
    pos = (close_proxy - roll_low) / (roll_high - roll_low + 1e-10)
    result["position_in_range"] = pos.clip(0, 1).fillna(0.5)

    # 12. stability_score：稳定性评分 = 1 - 变异系数
    cv = (roll_std / (roll_mean.abs() + 1e-10)).clip(0, 5)
    result["stability_score"] = (1.0 - cv / 5.0).clip(0, 1).fillna(0.5)

    return result
