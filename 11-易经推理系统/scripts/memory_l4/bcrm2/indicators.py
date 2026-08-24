"""IndicatorBank — Phase 0 Layer 0-1 指标银行

Spec §2.2-2.3 定义的 12 个原子指标，输入 BTC 1D OHLCV DataFrame，
输出 Dict[str, pd.Series]，12 主指标长度=len(df)，全部无 NaN。

映射表（指标名 → 取值映射 ± / 原始值）：
  L1  ma200_above_3d          ±1 {+1, 0, -1}      三日确认 MA200 牛熊分界
  L2  ma50_above              ±0.5                价格在 MA50 上/下
  L3  ma20_vs_ma50_order      ±0.5                MA20 > MA50 多头/空头
  L4  cycle_position_365d     ±0.5 或 0           365d 区间位置 [0.25, 0.75]=0
  L5  ma_alignment_score      加权，原始[-1,1]    MA 堆叠对齐
  L6  ma200_slope_signed      ±0.5                MA200 斜率 20d（≥0.01）

  T1  dow_hhhl_score          贡献 ±2/0           近 3 个 Swing HH/HL 连续评分
  T2  log_ret_90d             ±1.0                90d 对数收益（±0.15 阈值）
  T3  log_ret_30d             ±0.5                30d 对数收益（±0.08 阈值）
  T4  ma_slope_wavg           加权，tanh 限幅     MA20/50/200 斜率加权
  T5  volume_trend_conf       ±0.5 或 0           量能趋势确认（20 日统计）

  MISC vol_60d_pct            原始 [0,1]          波动率分位（点阵图用）
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from bcrm2.ma200_cycle_features import compute_ma200_features, compute_btc_cycle_features
from bcrm2.multi_timeframe_features import (
    compute_ma_alignment_score,
    compute_log_returns,
    compute_vol_percentile,
    compute_volume_ratio,
)

__all__ = ["IndicatorBank"]


# ================================================================
# Swing 检测（用于 dow_hhhl_score）
# ================================================================

def _detect_swings(high: pd.Series, low: pd.Series, lookback: int = 5
                   ) -> Tuple[pd.Series, pd.Series]:
    """检测 Swing High / Swing Low。

    - Swing High: price[i] == max(price[i-lookback : i+lookback])
    - Swing Low:  price[i] == min(price[i-lookback : i+lookback])

    Returns: (is_sh_padded, is_sl_padded) — 若 i 是 swing 点，为 1.0；否则 0.0。
              两侧长度不足时用 0 填充（避免 NaN）。
    """
    n = len(high)
    is_sh = np.zeros(n, dtype=float)
    is_sl = np.zeros(n, dtype=float)

    h = high.values.astype(float)
    l = low.values.astype(float)

    for i in range(n):
        lo = max(0, i - lookback)
        hi = min(n, i + lookback + 1)
        if h[i] == h[lo:hi].max():
            is_sh[i] = 1.0
        if l[i] == l[lo:hi].min():
            is_sl[i] = 1.0
    return (pd.Series(is_sh, index=high.index, name="sh"),
            pd.Series(is_sl, index=low.index, name="sl"))


def _dow_hhhl_score(high: pd.Series, low: pd.Series, lookback: int = 5,
                    n_recent: int = 3) -> pd.Series:
    """道氏理论 HH/HL 近 N 个 Swing 点评分。

    - 连续 Higher High + Higher Low（上升趋势）→ + (2 / n_recent) × k ，其中 k 为连续数
      （在 3 个 swing 全部连续 HH+HL 时 = +2.0）
    - 连续 Lower High + Lower Low → -2.0
    - 混合 → 0
    """
    is_sh, is_sl = _detect_swings(high, low, lookback)
    n = len(high)
    score_arr = np.zeros(n, dtype=float)

    sh_idx = np.where(is_sh.values == 1.0)[0]
    sl_idx = np.where(is_sl.values == 1.0)[0]

    h_arr = high.values.astype(float)
    l_arr = low.values.astype(float)

    # 为每一日 i 计算「到当前为止最近 n_recent 个 SH / SL」
    # 使用指针 p_sh / p_sl 单调递增，避免重复 searchsorted
    p_sh = 0
    p_sl = 0
    for i in range(n):
        # 推进指针到 <= i 的最后一个 swing
        while p_sh + 1 < len(sh_idx) and sh_idx[p_sh + 1] <= i:
            p_sh += 1
        while p_sl + 1 < len(sl_idx) and sl_idx[p_sl + 1] <= i:
            p_sl += 1

        # 截取最近 n_recent 个 SH/SL 的价格与索引
        if len(sh_idx) == 0 or sh_idx[0] > i:
            score_arr[i] = 0.0
            continue
        start_sh = max(0, p_sh + 1 - n_recent)
        start_sl = max(0, p_sl + 1 - n_recent)
        recent_sh = sh_idx[start_sh:p_sh + 1]  # 升序索引
        recent_sl = sl_idx[start_sl:p_sl + 1]

        if len(recent_sh) < 2 or len(recent_sl) < 2:
            score_arr[i] = 0.0
            continue

        sh_prices = h_arr[recent_sh]
        sl_prices = l_arr[recent_sl]

        # HH: 相邻 SH 递增；HL: 相邻 SL 递增
        hh_cont = int(np.sum(np.diff(sh_prices) > 1e-9))
        hl_cont = int(np.sum(np.diff(sl_prices) > 1e-9))
        lh_cont = int(np.sum(np.diff(sh_prices) < -1e-9))
        ll_cont = int(np.sum(np.diff(sl_prices) < -1e-9))

        steps_sh = max(1, len(sh_prices) - 1)
        steps_sl = max(1, len(sl_prices) - 1)

        if hh_cont == steps_sh and hl_cont == steps_sl:
            # 上升趋势：按「连续 3 对 swing = +2.0」比例
            score_arr[i] = +2.0 * min(1.0, (hh_cont + hl_cont) / (2 * n_recent - 2))
        elif lh_cont == steps_sh and ll_cont == steps_sl:
            score_arr[i] = -2.0 * min(1.0, (lh_cont + ll_cont) / (2 * n_recent - 2))
        else:
            score_arr[i] = 0.0
    return pd.Series(score_arr, index=high.index)


def _ma_slope_weighted_avg(close: pd.Series) -> pd.Series:
    """MA 斜率加权平均：MA20slope×2 + MA50×1 + MA200×0.5 / 3.5 → tanh 限幅到 [-1, 1]"""
    ma20 = close.rolling(20, min_periods=10).mean()
    ma50 = close.rolling(50, min_periods=25).mean()
    ma200 = close.rolling(200, min_periods=100).mean()

    # pct_change(5) 近似斜率（年化化无关紧要，因为后续会 tanh 限幅）
    s20 = ma20.pct_change(5)
    s50 = ma50.pct_change(10)
    s200 = ma200.pct_change(20)

    # 归一化到可比尺度：×20 近似「每单位尺度斜率」
    combined = (2.0 * s20 * 20.0 + 1.0 * s50 * 10.0 + 0.5 * s200 * 20.0) / 3.5
    combined = combined.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    # tanh 限幅，阈值 ~ 0.02 饱和
    return pd.Series(np.tanh(combined / 0.02), index=close.index)


def _volume_trend_confidence(close: pd.Series, volume: pd.Series, lookback: int = 20
                             ) -> pd.Series:
    """量能趋势确认评分 [-0.5, 0, +0.5]。

    规则：近 lookback 日中「涨日 vol > 1.5 × vol_ma20 且 跌日 vol < 0.8 × vol_ma20」
    占比 ≥ 60% → +0.5；相反 ≤ 40% → -0.5；否则 0。
    如果 volume 全 0 / 不可用 → 0。
    """
    if volume.std() < 1e-12 or (volume == 0).all():
        return pd.Series(0.0, index=close.index)

    vol_ma = volume.rolling(lookback, min_periods=lookback // 2).mean().replace(0, np.nan)
    ratio = (volume / vol_ma).replace([np.inf, -np.inf], np.nan).fillna(1.0)

    ret = close.pct_change().fillna(0.0)
    up_day = ret > 1e-9
    down_day = ret < -1e-9

    good_up = up_day & (ratio > 1.5)
    good_down = down_day & (ratio < 0.8)

    denom = up_day.rolling(lookback, min_periods=1).sum() + \
            down_day.rolling(lookback, min_periods=1).sum()
    numer = good_up.rolling(lookback, min_periods=1).sum() + \
            good_down.rolling(lookback, min_periods=1).sum()

    ratio_support = (numer / denom.replace(0, np.nan)).fillna(0.5)

    score = pd.Series(0.0, index=close.index)
    score[ratio_support >= 0.60] = +0.5
    score[ratio_support <= 0.40] = -0.5
    return score


# ================================================================
# 主类
# ================================================================

class IndicatorBank:
    """Layer 0-1 指标银行。输出 12 主指标 + 若干 __raw_* 辅助列。"""

    #: 主指标顺序（与 Spec 定义完全一致）
    MAIN_INDICATORS: List[str] = [
        "ma200_above_3d", "ma50_above", "ma20_vs_ma50_order",
        "cycle_position_365d", "ma_alignment_score", "ma200_slope_signed",
        "dow_hhhl_score", "log_ret_90d", "log_ret_30d",
        "ma_slope_wavg", "volume_trend_conf", "vol_60d_pct",
    ]

    def compute_all(self, df: pd.DataFrame) -> Dict[str, pd.Series]:
        """对 BTC 1D OHLCV 计算 12 指标 + 原始值列。

        Args:
            df: DataFrame，至少有 close 列。若有 high/low 道氏评分更准；
                若有 volume 则量能指标非零。
        Returns:
            Dict[str, pd.Series]，长度=len(df)，index=df.index。
        """
        close = df["close"] if "close" in df.columns else pd.Series(df.iloc[:, -1], index=df.index)
        close = close.astype(float)
        high = df["high"].astype(float) if "high" in df.columns else close * 1.001
        low = df["low"].astype(float) if "low" in df.columns else close * 0.999
        volume = df["volume"].astype(float) if "volume" in df.columns else pd.Series(1.0, index=close.index)

        # ===== 可复用模块计算 =====
        ma200_df = compute_ma200_features(close)
        cycle_df = compute_btc_cycle_features(close)
        ma_alignment = compute_ma_alignment_score(close)
        vol_pct = compute_vol_percentile(close)
        vol_ratio_raw = compute_volume_ratio(df if "volume" in df.columns else df.assign(volume=volume))

        ma50 = close.rolling(50, min_periods=25).mean()
        ma20 = close.rolling(20, min_periods=10).mean()

        # ===== L1: MA200 三日确认 =====
        above = ma200_df["ma200_above"]
        # 连续 3 日 1.0 → 1；连续 3 日 0 → -1；否则 0
        roll_above_max = above.rolling(3, min_periods=3).max()
        roll_above_min = above.rolling(3, min_periods=3).min()
        ma200_3d = pd.Series(0.0, index=close.index)
        ma200_3d[(roll_above_max == 1.0) & (roll_above_min == 1.0)] = 1.0
        ma200_3d[(roll_above_max == 0.0) & (roll_above_min == 0.0)] = -1.0
        ma200_3d = ma200_3d.fillna(0.0)

        # ===== L2: MA50 上下 =====
        ma50_above_raw = (close > ma50).astype(float)
        ma50_above = (ma50_above_raw - 0.5) * 2.0  # 1 → +1  / 0 → -1

        # ===== L3: MA20 vs MA50 顺序 =====
        ma20_above_ma50 = (ma20 > ma50).astype(float).fillna(0.5)
        ma20_vs_ma50_order = (ma20_above_ma50 - 0.5) * 2.0

        # ===== L4: 365d 区间位置 ±0.5 / 0 =====
        pos = cycle_df["cycle_position_in_range"]
        cycle365 = pd.Series(0.0, index=close.index)
        cycle365[pos >= 0.75] = +0.5
        cycle365[pos <= 0.25] = -0.5

        # ===== L5: MA 对齐（原始 [-1, 1] × 系数 → 后续合成时） =====
        # 这里直接返回原始值（已在 [-1, 1]），合成器再乘权重
        ma_alignment_score = ma_alignment.clip(-1.0, 1.0).fillna(0.0)

        # ===== L6: MA200 斜率符号 ±0.5 =====
        slope = ma200_df["ma200_slope_20d"]
        ma200_slope_signed = pd.Series(0.0, index=close.index)
        ma200_slope_signed[slope >= 0.01] = +0.5
        ma200_slope_signed[slope <= -0.01] = -0.5

        # ===== T1: 道氏 HH/HL =====
        dow_hhhl = _dow_hhhl_score(high, low, lookback=5, n_recent=3)

        # ===== T2/T3: 对数收益 ± =====
        lr = compute_log_returns(close, periods=[30, 90])
        lr90_raw = lr["log_ret_90d"]
        lr30_raw = lr["log_ret_30d"]
        lr90 = pd.Series(0.0, index=close.index)
        lr90[lr90_raw >= 0.15] = +1.0
        lr90[lr90_raw <= -0.15] = -1.0
        lr30 = pd.Series(0.0, index=close.index)
        lr30[lr30_raw >= 0.08] = +0.5
        lr30[lr30_raw <= -0.08] = -0.5

        # ===== T4: MA 斜率加权 =====
        ma_slope_wavg = _ma_slope_weighted_avg(close)  # tanh 限幅到 [-1,1]

        # ===== T5: 量能趋势确认 =====
        vol_conf = _volume_trend_confidence(close, volume, lookback=20)

        # ===== MISC: vol_60d_pct =====
        vol_60d_pct = vol_pct.fillna(0.5).clip(0.0, 1.0)

        # ===== 打包 12 主指标 =====
        out: Dict[str, pd.Series] = {
            "ma200_above_3d":     ma200_3d,
            "ma50_above":         ma50_above,
            "ma20_vs_ma50_order": ma20_vs_ma50_order,
            "cycle_position_365d":cycle365,
            "ma_alignment_score": ma_alignment_score,
            "ma200_slope_signed": ma200_slope_signed,
            "dow_hhhl_score":     dow_hhhl,
            "log_ret_90d":        lr90,
            "log_ret_30d":        lr30,
            "ma_slope_wavg":      ma_slope_wavg,
            "volume_trend_conf":  vol_conf,
            "vol_60d_pct":        vol_60d_pct,
        }

        # 再填 NaN → 0 保险（rolling 开头可能仍有 NaN）
        for k, s in list(out.items()):
            out[k] = s.ffill().fillna(0.0)

        # ===== 辅助原始值 =====
        out["__raw_ma200_distance_pct"] = ma200_df["ma200_distance_pct"].ffill().fillna(0.0)
        out["__raw_ma200_slope"] = ma200_df["ma200_slope_20d"].ffill().fillna(0.0)
        out["__raw_cycle_position_in_range"] = cycle_df["cycle_position_in_range"].ffill().fillna(0.5)
        out["__raw_log_ret_90d"] = lr90_raw.ffill().fillna(0.0)
        out["__raw_log_ret_30d"] = lr30_raw.ffill().fillna(0.0)
        out["__raw_volume_ma20_ratio"] = vol_ratio_raw.ffill().fillna(0.0)

        return out
