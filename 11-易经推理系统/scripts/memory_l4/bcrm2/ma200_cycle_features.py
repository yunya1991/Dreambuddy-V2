"""MA200 牛熊分界 + 比特币价格驱动周期特征

Spec 补充 — 两大经典经验法则的算法落地（v2：纯价格驱动，移除 halving 日期依赖）：
  1. MA200 牛熊分界线：日线站上 MA200 = 牛市，跌破 = 熊市（三日确认原则）
  2. 比特币周期特征：用 365 日高低点、180/365 日动量、长周期波动率等
     **纯价格驱动**特征替代静态 halving 日期，避免「phase=牛市」的硬映射
     导致跨周期泛化失败（v1 经验：halving-based 周期特征使 F1 从 0.247 降至 0.199）。

设计原则：
  - 所有周期特征必须基于「当前可观测的价格序列」计算
  - 不引入任何外部日期先验（halving/减半时间表）
  - 用滚动窗口的高/低/分位数代替「时间到了该涨/该跌」的硬规则
  - 与 MA200 特征正交：MA200 管「长期趋势方向」，周期特征管「周期内位置 + 长期动量」

特征列表（10 列）：
  MA200 组（3 列）:
    - ma200_distance_pct: 价格距 MA200 百分比（正=上方，负=下方）
    - ma200_above: 价格是否在 MA200 上方（1.0/0.0）
    - ma200_slope_20d: MA200 20日斜率（正=上升，负=下降）

  价格驱动周期组（7 列，纯价格计算，无外部日期）:
    - cycle_distance_from_365d_high: 距 365 日滚动高点的回撤百分比（0=新高，负值=回撤深度）
    - cycle_distance_from_365d_low: 距 365 日滚动低点的反弹百分比（0=新低，正值=反弹高度）
    - cycle_position_in_range: 当前价格在 [365d_low, 365d_high] 中的位置（0=低点，1=高点）
    - cycle_time_since_peak: 距 365 日高点经过的天数（0=今日创新高，365=高点在一年前）
    - cycle_momentum_180d: 180 日对数收益（半年动量，捕捉中期周期方向）
    - cycle_vol_regime_90d: 90 日已实现波动率（长期波动率环境，区分牛/熊市波动特征）
    - cycle_trend_365d: 365 日对数收益（年度趋势方向，捕捉长周期方向）
"""
from __future__ import annotations

import logging
import numpy as np
import pandas as pd
from typing import Dict, List

logger = logging.getLogger(__name__)

__all__ = ["MA200CycleFeatures"]


# ============================================================
# MA200 牛熊分界线特征（保持不变）
# ============================================================

def compute_ma200_features(close: pd.Series) -> pd.DataFrame:
    """计算 MA200 牛熊分界线特征。

    经典经验：
      - 日线 MA200 是最经典的牛熊分界线
      - 价格站上 MA200 = 牛市环境，跌破 = 熊市环境
      - MA200 斜率上升 = 长期趋势向上，下降 = 长期趋势向下
      - 三日确认原则：连续3日收在 MA200 上方/下方才确认

    Args:
        close: 收盘价 Series

    Returns:
        DataFrame with 3 columns
    """
    ma200 = close.rolling(200, min_periods=100).mean()

    # 距离百分比
    distance_pct = ((close - ma200) / ma200 * 100.0).replace([np.inf, -np.inf], 0.0)

    # 是否在上方（1.0/0.0）
    above = (close > ma200).astype(float)

    # MA200 斜率：20日变化率
    slope_20d = ma200.pct_change(20).replace([np.inf, -np.inf], 0.0)

    feats = pd.DataFrame({
        "ma200_distance_pct": distance_pct,
        "ma200_above": above,
        "ma200_slope_20d": slope_20d,
    }, index=close.index)

    feats = feats.ffill().fillna(0)
    return feats


# ============================================================
# 价格驱动周期特征（v2：移除 halving 日期，纯价格计算）
# ============================================================

def compute_btc_cycle_features(
    close: pd.Series,
    window: int = 365,
) -> pd.DataFrame:
    """计算比特币价格驱动周期特征（v2）。

    v2 设计原则：
      - 完全弃用 halving 日期等外部先验
      - 用 365 日滚动窗口的高/低点定位「周期内位置」
      - 用 180/365 日对数收益捕捉长周期动量
      - 用 90 日已实现波动率区分牛/熊市波动环境

    4 年周期论在 v2 中的体现：
      - cycle_position_in_range: 接近 0 = 周期底部区域，接近 1 = 周期顶部区域
      - cycle_distance_from_365d_high: 深度负值 = 处于周期下行段
      - cycle_momentum_180d / cycle_trend_365d: 长期动量方向，正=上升周期，负=下行周期
      - cycle_time_since_peak: 距上次高点的天数，>180 表示可能进入下行周期

    Args:
        close: 收盘价 Series（DatetimeIndex）
        window: 滚动窗口大小，默认 365（一年）

    Returns:
        DataFrame with 7 columns
    """
    n = len(close)
    close_arr = close.values.astype(float)

    # 365 日滚动高/低点
    rolling_high = close.rolling(window, min_periods=window // 2).max()
    rolling_low = close.rolling(window, min_periods=window // 2).min()

    # 距 365 日高点的回撤百分比（0=新高，负值=回撤深度）
    distance_from_high = ((close - rolling_high) / rolling_high * 100.0).replace([np.inf, -np.inf], 0.0)

    # 距 365 日低点的反弹百分比（0=新低，正值=反弹高度）
    distance_from_low = ((close - rolling_low) / rolling_low * 100.0).replace([np.inf, -np.inf], 0.0)

    # 当前价格在 [365d_low, 365d_high] 中的位置（0=低点，1=高点）
    range_width = (rolling_high - rolling_low).replace(0, np.nan)
    position_in_range = ((close - rolling_low) / range_width).clip(0.0, 1.0).fillna(0.5)

    # 距 365 日高点经过的天数（0=今日创新高，window=高点在一年前）
    # 用 argmax 找到滚动窗口内最高点的相对位置，然后转换为「距今天数」
    time_since_peak = _days_since_rolling_extreme(close, window, find_max=True)
    # 距 365 日低点经过的天数（对称特征，辅助判断周期阶段）
    # 此处省略，避免特征冗余（time_since_peak 已足够定位周期阶段）

    # 180 日对数收益（半年动量）
    momentum_180d = np.log(close / close.shift(180)).replace([np.inf, -np.inf], 0.0)

    # 90 日已实现波动率（年化）
    daily_ret = close.pct_change()
    vol_90d = daily_ret.rolling(90, min_periods=45).std() * np.sqrt(365)
    vol_90d = vol_90d.replace([np.inf, -np.inf], 0.0)

    # 365 日对数收益（年度趋势方向）
    trend_365d = np.log(close / close.shift(365)).replace([np.inf, -np.inf], 0.0)

    feats = pd.DataFrame({
        "cycle_distance_from_365d_high": distance_from_high,
        "cycle_distance_from_365d_low": distance_from_low,
        "cycle_position_in_range": position_in_range,
        "cycle_time_since_peak": time_since_peak,
        "cycle_momentum_180d": momentum_180d,
        "cycle_vol_regime_90d": vol_90d,
        "cycle_trend_365d": trend_365d,
    }, index=close.index)

    feats = feats.replace([np.inf, -np.inf], 0.0).fillna(0)
    return feats


def _days_since_rolling_extreme(close: pd.Series, window: int, find_max: bool = True) -> pd.Series:
    """计算当前价格距滚动窗口内极值点经过的天数。

    Args:
        close: 收盘价 Series
        window: 滚动窗口大小
        find_max: True=找最高点，False=找最低点

    Returns:
        Series: 距极值点的天数（0=今日即极值，window=极值在 window 天前）
    """
    n = len(close)
    arr = close.values.astype(float)
    result = np.zeros(n)

    # 向量化：对每个位置 i，找 [max(0, i-window+1), i] 窗口内的极值位置
    for i in range(n):
        start = max(0, i - window + 1)
        if start >= i:
            result[i] = 0.0
            continue
        sub = arr[start:i + 1]
        if find_max:
            ext_idx = np.argmax(sub)
        else:
            ext_idx = np.argmin(sub)
        # 距今天数 = 窗口末尾到极值位置的距离
        result[i] = float(len(sub) - 1 - ext_idx)

    return pd.Series(result, index=close.index)


# ============================================================
# 组合模块：MA200 + 价格驱动周期
# ============================================================

class MA200CycleFeatures:
    """MA200 牛熊分界 + 比特币价格驱动周期特征组合模块

    v2：移除 halving 日期依赖，全部特征基于价格序列计算。

    默认输出 10 列（MA200 3列 + 周期 7列）。
    可通过 enable_cycle=False 关闭周期特征，只输出 MA200 3列。

    10 列特征：
      MA200 组（3 列）:
        - ma200_distance_pct, ma200_above, ma200_slope_20d
      周期组（7 列，纯价格驱动）:
        - cycle_distance_from_365d_high, cycle_distance_from_365d_low,
          cycle_position_in_range, cycle_time_since_peak,
          cycle_momentum_180d, cycle_vol_regime_90d, cycle_trend_365d
    """

    def __init__(self, enable_cycle: bool = True):
        self.enable_cycle = enable_cycle

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"] if "close" in df.columns else pd.Series(df.iloc[:, -1], index=df.index)

        # MA200 特征（始终输出）
        ma200_feats = compute_ma200_features(close)

        if not self.enable_cycle:
            return ma200_feats

        # 价格驱动周期特征
        cycle_feats = compute_btc_cycle_features(close)

        result = pd.concat([ma200_feats, cycle_feats], axis=1)
        result = result.ffill().fillna(0)
        result = result.replace([np.inf, -np.inf], 0)
        return result

    @property
    def feature_categories(self) -> Dict[str, List[str]]:
        cats = {"ma200": "MA200 牛熊分界线特征"}
        if self.enable_cycle:
            cats["cycle"] = "比特币价格驱动周期特征（v2）"
        return cats


# ============================================================
# FeatureRegistry 注册
# ============================================================
from bcrm2.feature_registry import FeatureRegistry  # noqa: E402

FeatureRegistry.register(name="ma200_cycle", factory=MA200CycleFeatures)
