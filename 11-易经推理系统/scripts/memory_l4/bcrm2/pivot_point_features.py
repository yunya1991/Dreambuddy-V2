"""
枢纽点指标特征 — 数学确定性的关键价格水平

理论映射:
  枢纽点(Pivot Points)是用前一日高/低/收盘价通过确定性公式计算出的
  支撑/阻力位，具有严格的数学定义，不带主观参数。

  核心公式 (Standard Pivot):
    Pivot = (High + Low + Close) / 3
    R1 = 2*Pivot - Low    S1 = 2*Pivot - High
    R2 = Pivot + (High - Low)  S2 = Pivot - (High - Low)
    R3 = High + 2*(Pivot - Low)  S3 = Low - 2*(High - Pivot)

  优势: 纯数学计算，跨市场通用，交易者广泛参考
  包含5种计算法: Standard / Fibonacci / Camarilla / Woodie / Demark
"""

import numpy as np
import pandas as pd
from typing import List, Optional, Dict


# ============================================================
# 工具: 日线重采样
# ============================================================

def _resample_daily(df: pd.DataFrame) -> pd.DataFrame:
    daily = df.resample("1D").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()
    return daily


def _align_to_hourly(daily_series: pd.Series, hourly_index: pd.Index) -> pd.Series:
    return daily_series.reindex(hourly_index, method="ffill")


# ============================================================
# 1. Standard 枢纽点
# ============================================================

def standard_pivot_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Standard Pivot Points — 经典枢纽点

    Pivot = (H + L + C) / 3
    R1/R2/R3 = 阻力位, S1/S2/S3 = 支撑位
    """
    feats = pd.DataFrame(index=df.index)
    daily = _resample_daily(df)

    if len(daily) < 5:
        for col in _pp_standard_names():
            feats[col] = 0.0
        return feats

    h = daily["high"]
    l = daily["low"]
    c = daily["close"]

    pivot = (h + l + c) / 3
    r1 = 2 * pivot - l
    s1 = 2 * pivot - h
    r2 = pivot + (h - l)
    s2 = pivot - (h - l)
    r3 = h + 2 * (pivot - l)
    s3 = l - 2 * (h - pivot)

    # 当前价格相对于各枢纽点的距离 (归一化到ATR)
    close_hourly = df["close"]
    # 用日波动幅度做归一化
    daily_range = (h - l).replace(0, np.nan).ffill()

    for name, level in [("pivot", pivot), ("r1", r1), ("r2", r2), ("r3", r3),
                         ("s1", s1), ("s2", s2), ("s3", s3)]:
        dist = (close_hourly - _align_to_hourly(level, df.index)) / _align_to_hourly(daily_range, df.index)
        feats[f"pp_std_{name}_dist"] = dist.replace([np.inf, -np.inf], 0).fillna(0)
        # 是否在该位附近 (±0.3个日波动幅度)
        feats[f"pp_std_{name}_touch"] = (np.abs(dist) < 0.3).astype(float)

    # 当前价格在枢纽点体系中的位置 (S3=0, R3=1)
    pp_pos = (close_hourly - _align_to_hourly(s3, df.index)) / (
        _align_to_hourly(r3, df.index) - _align_to_hourly(s3, df.index) + 1e-10
    )
    feats["pp_std_position"] = pp_pos.replace([np.inf, -np.inf], 0.5).fillna(0.5).clip(-0.5, 1.5)

    # 趋势方向: 在Pivot上方=多头, 下方=空头
    feats["pp_std_above_pivot"] = (close_hourly > _align_to_hourly(pivot, df.index)).astype(float)

    # 从支撑/阻力反弹的标记
    feats["pp_std_bounce_s1"] = (
        (close_hourly > _align_to_hourly(s1, df.index)) &
        (df["low"] < _align_to_hourly(s1, df.index))
    ).astype(float)
    feats["pp_std_reject_r1"] = (
        (close_hourly < _align_to_hourly(r1, df.index)) &
        (df["high"] > _align_to_hourly(r1, df.index))
    ).astype(float)

    return feats


def _pp_standard_names() -> List[str]:
    names = []
    for name in ["pivot", "r1", "r2", "r3", "s1", "s2", "s3"]:
        names.extend([f"pp_std_{name}_dist", f"pp_std_{name}_touch"])
    names.extend(["pp_std_position", "pp_std_above_pivot", "pp_std_bounce_s1", "pp_std_reject_r1"])
    return names


# ============================================================
# 2. Fibonacci 枢纽点
# ============================================================

def fibonacci_pivot_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Fibonacci Pivot Points — 用斐波那契比例计算枢纽点

    R1 = Pivot + 0.382*(H-L)
    R2 = Pivot + 0.618*(H-L)
    R3 = Pivot + 1.000*(H-L)
    S1 = Pivot - 0.382*(H-L)
    S2 = Pivot - 0.618*(H-L)
    S3 = Pivot - 1.000*(H-L)
    """
    feats = pd.DataFrame(index=df.index)
    daily = _resample_daily(df)

    if len(daily) < 5:
        for col in _pp_fib_names():
            feats[col] = 0.0
        return feats

    h = daily["high"]
    l = daily["low"]
    c = daily["close"]
    pivot = (h + l + c) / 3
    rng = h - l
    daily_range = rng.replace(0, np.nan).ffill()

    levels = {}
    for name, ratio in [("r1", 0.382), ("r2", 0.618), ("r3", 1.0),
                         ("s1", 0.382), ("s2", 0.618), ("s3", 1.0)]:
        if name.startswith("r"):
            levels[name] = pivot + ratio * rng
        else:
            levels[name] = pivot - ratio * rng

    close_hourly = df["close"]
    for name, level in levels.items():
        dist = (close_hourly - _align_to_hourly(level, df.index)) / _align_to_hourly(daily_range, df.index)
        feats[f"pp_fib_{name}_dist"] = dist.replace([np.inf, -np.inf], 0).fillna(0)
        feats[f"pp_fib_{name}_touch"] = (np.abs(dist) < 0.3).astype(float)

    feats["pp_fib_position"] = (
        (close_hourly - _align_to_hourly(levels["s3"], df.index)) /
        (_align_to_hourly(levels["r3"], df.index) - _align_to_hourly(levels["s3"], df.index) + 1e-10)
    ).replace([np.inf, -np.inf], 0.5).fillna(0.5).clip(-0.5, 1.5)

    return feats


def _pp_fib_names() -> List[str]:
    names = []
    for name in ["r1", "r2", "r3", "s1", "s2", "s3"]:
        names.extend([f"pp_fib_{name}_dist", f"pp_fib_{name}_touch"])
    names.append("pp_fib_position")
    return names


# ============================================================
# 3. Camarilla 枢纽点
# ============================================================

def camarilla_pivot_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Camarilla Pivot Points — 强调日内回归均值

    H4 = Close + Range * 1.1/2
    H3 = Close + Range * 1.1/4
    H2 = Close + Range * 1.1/6
    H1 = Close + Range * 1.1/12
    L1 = Close - Range * 1.1/12
    L2 = Close - Range * 1.1/6
    L3 = Close - Range * 1.1/4
    L4 = Close - Range * 1.1/2

    H3/L3是关键反转位, H4/L4是突破位
    """
    feats = pd.DataFrame(index=df.index)
    daily = _resample_daily(df)

    if len(daily) < 5:
        for col in _pp_camarilla_names():
            feats[col] = 0.0
        return feats

    h = daily["high"]
    l = daily["low"]
    c = daily["close"]
    rng = h - l
    daily_range = rng.replace(0, np.nan).ffill()

    levels = {}
    for name, mult in [("h4", 1.1/2), ("h3", 1.1/4), ("h2", 1.1/6), ("h1", 1.1/12),
                       ("l1", 1.1/12), ("l2", 1.1/6), ("l3", 1.1/4), ("l4", 1.1/2)]:
        if name.startswith("h"):
            levels[name] = c + mult * rng
        else:
            levels[name] = c - mult * rng

    close_hourly = df["close"]
    for name, level in levels.items():
        dist = (close_hourly - _align_to_hourly(level, df.index)) / _align_to_hourly(daily_range, df.index)
        feats[f"pp_cam_{name}_dist"] = dist.replace([np.inf, -np.inf], 0).fillna(0)
        feats[f"pp_cam_{name}_touch"] = (np.abs(dist) < 0.2).astype(float)

    # H3/L3 反转信号
    feats["pp_cam_reject_h3"] = (
        (close_hourly < _align_to_hourly(levels["h3"], df.index)) &
        (df["high"] > _align_to_hourly(levels["h3"], df.index))
    ).astype(float)
    feats["pp_cam_bounce_l3"] = (
        (close_hourly > _align_to_hourly(levels["l3"], df.index)) &
        (df["low"] < _align_to_hourly(levels["l3"], df.index))
    ).astype(float)

    # H4/L4 突破信号
    feats["pp_cam_break_h4"] = (close_hourly > _align_to_hourly(levels["h4"], df.index)).astype(float)
    feats["pp_cam_break_l4"] = (close_hourly < _align_to_hourly(levels["l4"], df.index)).astype(float)

    return feats


def _pp_camarilla_names() -> List[str]:
    names = []
    for name in ["h4", "h3", "h2", "h1", "l1", "l2", "l3", "l4"]:
        names.extend([f"pp_cam_{name}_dist", f"pp_cam_{name}_touch"])
    names.extend(["pp_cam_reject_h3", "pp_cam_bounce_l3", "pp_cam_break_h4", "pp_cam_break_l4"])
    return names


# ============================================================
# 4. 枢纽点综合引擎
# ============================================================

class PivotPointFeatures:
    """
    枢纽点特征引擎 — 多种计算法的综合

    三种计算法:
      Standard: 经典公式，最常用
      Fibonacci: 用0.382/0.618比例，与斐波那契特征呼应
      Camarilla: 强调日内回归，H3/L3是关键反转位
    """

    def __init__(self):
        pass

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        all_feats = []
        all_feats.append(standard_pivot_features(df))
        all_feats.append(fibonacci_pivot_features(df))
        all_feats.append(camarilla_pivot_features(df))
        result = pd.concat(all_feats, axis=1)
        result = result.ffill().fillna(0)
        result = result.replace([np.inf, -np.inf], 0)
        return result
