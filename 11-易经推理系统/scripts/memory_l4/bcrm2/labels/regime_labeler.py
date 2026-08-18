"""
§4.1 8 态自动标签生成器（数据驱动，基于「未来收益 + ADX + BB 宽度 + 波动率」）

与 Spec 语义一致，不依赖 Phase 4 的 BOCPD：在 BOCPD 缺失时，
用「价格 z-score 转折分」近似替代转折点（REVERSAL）。

标签顺序与 RegimePredictor REGIME_ORDER 保持一致：
TREND_UP_STRONG, TREND_UP_MILD, RANGE_BOUND, CONSOLIDATION,
REVERSAL, VOLATILE_DROP, FOMO_RALLY, DISTRIBUTION
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd


# 8 态顺序 / 枚举（与 MarketRegimeClassifier 不完全一致；Spec §4.1 定义新的 8 态）
REGIME_ORDER: list = [
    "TREND_UP_STRONG",
    "TREND_UP_MILD",
    "RANGE_BOUND",
    "CONSOLIDATION",
    "REVERSAL",
    "VOLATILE_DROP",
    "FOMO_RALLY",
    "DISTRIBUTION",
]

REGIME_CODE = {name: i for i, name in enumerate(REGIME_ORDER)}


def _rolling_zscore(series: pd.Series, window: int) -> pd.Series:
    roll_mean = series.rolling(window, min_periods=max(5, window // 4)).mean()
    roll_std = series.rolling(window, min_periods=max(5, window // 4)).std()
    roll_std = roll_std.where(roll_std > 1e-12, np.nan)
    return (series - roll_mean) / roll_std


def generate_8state_label(
    df: pd.DataFrame,
    forward_days: int = 20,
    lookback: int = 252,
    bocpd_prob_col: Optional[str] = None,
) -> pd.Series:
    """数据驱动的 8 态自动标签（基于未来 N 日收益 + 当前市态特征）。

    参数：
      df: 至少含 close；可选 adx_14, bb_width_percentile_252, volume。
      forward_days: 未来收益窗口，默认 20。
      lookback: 滚动历史分位数窗口，默认 252。
      bocpd_prob_col: Phase 4 提供时使用真实 BOCPD 概率；否则用「价格反转」代理。

    返回：
      labels: 长度=len(df) 的 Series，元素为 REGIME_ORDER 中的字符串，前
              lookback 条和最后 forward_days 条为 NaN（无法判断未来收益 /
              没有足够回看历史）。
    """
    close = df["close"].astype(float)
    n = len(close)

    # ===== 输入信号 =====
    # 未来收益（forward_days 日之后的收益率，对齐到当日）
    future_ret = close.pct_change(forward_days).shift(-forward_days)

    # 趋势强度：60 日对数收益
    trend_60 = np.log(close / close.shift(60))

    # 已实现波动率：20 日日化波动率
    daily_ret = close.pct_change()
    vol_20 = daily_ret.rolling(20, min_periods=10).std() * math.sqrt(365)

    # ADX：若 df 中已经提供（Phase 0 产物），直接用；否则按公式近似（简化版 ADX proxy）
    if "adx_14" in df.columns:
        adx = df["adx_14"].astype(float)
    else:
        # 用 14 日趋势绝对值 + 14 日波动率的组合近似 ADX
        trend_14 = close.pct_change(14).abs()
        vol_14 = daily_ret.rolling(14, min_periods=8).std() * math.sqrt(365)
        adx = 50 * (trend_14 / (vol_14.where(vol_14 > 1e-9) + 1e-9))
        adx = adx.clip(lower=0, upper=100).ffill()

    # BB 宽度百分位：若已有直接用；否则以 20 日 BB 宽度 + 252 日百分位近似
    if "bb_width_percentile_252" in df.columns:
        bb_width_pct = df["bb_width_percentile_252"].astype(float)
    else:
        close_std20 = close.rolling(20, min_periods=10).std()
        bb_width = (close_std20 * 4.0) / close.rolling(20, min_periods=10).mean()
        bb_width_pct = bb_width.rolling(lookback, min_periods=lookback // 2).rank(pct=True)

    # BOCPD 转折点概率
    if bocpd_prob_col is not None and bocpd_prob_col in df.columns:
        bocpd_prob = df[bocpd_prob_col].astype(float)
    else:
        # 代理：close 的 20 日 z-score 极端反转分
        z20 = _rolling_zscore(close, 20)
        z20_prev = z20.shift(10)
        # 从极端正 → 回落，或极端负 → 反弹
        reversal_proxy = (
            ((z20_prev > 1.8) & (z20 < 0.4)) |
            ((z20_prev < -1.8) & (z20 > -0.4))
        ).astype(float)
        # 与 10 日收益方向相反的强动量 → 转折概率高
        ret_10 = close.pct_change(10)
        fut_10 = close.shift(-10).pct_change()
        contrarian = ((ret_10 > 0.06) & (fut_10 < -0.03)) | ((ret_10 < -0.06) & (fut_10 > 0.03))
        bocpd_prob = 0.4 * reversal_proxy + 0.6 * contrarian.astype(float)

    # ===== 滚动历史阈值（防止未来泄露）=====
    # 使用滚动分位数（而非绝对均值/2σ），保证每类有合理的样本占比
    # —— 避免 RANGE_BOUND 吃掉 80% 样本。
    trend_q80 = trend_60.rolling(lookback, min_periods=lookback // 2).quantile(0.80)
    trend_q60 = trend_60.rolling(lookback, min_periods=lookback // 2).quantile(0.60)
    trend_q40 = trend_60.rolling(lookback, min_periods=lookback // 2).quantile(0.40)
    trend_q20 = trend_60.rolling(lookback, min_periods=lookback // 2).quantile(0.20)

    vol_q25 = vol_20.rolling(lookback, min_periods=lookback // 2).quantile(0.25)
    vol_q50 = vol_20.rolling(lookback, min_periods=lookback // 2).quantile(0.50)
    vol_q75 = vol_20.rolling(lookback, min_periods=lookback // 2).quantile(0.75)

    fr_q10 = future_ret.rolling(lookback, min_periods=lookback // 2).quantile(0.10)
    fr_q25 = future_ret.rolling(lookback, min_periods=lookback // 2).quantile(0.25)
    fr_q40 = future_ret.rolling(lookback, min_periods=lookback // 2).quantile(0.40)
    fr_q60 = future_ret.rolling(lookback, min_periods=lookback // 2).quantile(0.60)
    fr_q85 = future_ret.rolling(lookback, min_periods=lookback // 2).quantile(0.85)
    fr_q90 = future_ret.rolling(lookback, min_periods=lookback // 2).quantile(0.90)

    # ===== 向量化判定（按 Spec §4.1 优先级） =====
    # 用字符串存储，最后前向不可用位置赋 NaN
    labels = np.full(n, "RANGE_BOUND", dtype=object)

    # 先计算各条件向量（注意：每类阈值都用滚动分位数保证分布）
    # REVERSAL：BOCPD 代理高 + 未来收益不极端（反转后走平/回摆，非 FOMO/Drop 尾段）
    is_reversal = (
        (bocpd_prob > 0.25) &
        (future_ret > fr_q10) & (future_ret < fr_q90)
    )

    # FOMO_RALLY：强趋势（top 20%）+ 高波动（top 25%），或未来极端正收益，或「60日绝对收益>25%+高波动」
    is_fomo = (
        ((trend_60 > trend_q80) & (vol_20 > vol_q75))
        | (future_ret > fr_q90)
        | ((trend_60 > 0.25) & (vol_20 > vol_q50))
    )

    # VOLATILE_DROP：弱趋势（bottom 20%）+ 高波动，或未来极端负收益，或「60日绝对收益<-20%」
    is_volatile_drop = (
        ((trend_60 < trend_q20) & (vol_20 > vol_q75))
        | (future_ret < fr_q10)
        | (trend_60 < -0.20)
    )

    # DISTRIBUTION：派发期 = 趋势略负 + ADX 疲弱 + BB 宽度偏高 + 未来负收益偏多
    is_distribution = (
        (trend_60 < trend_q40) &
        (adx < 28) &
        (bb_width_pct > 0.50) &
        (future_ret < fr_q40)
    )

    # TREND_UP_STRONG：趋势 top 20% + ADX 强；或 60 日绝对收益 > 15% 且 ADX>20
    is_strong_up = (
        ((trend_60 > trend_q80) & (adx > 25) & (future_ret > fr_q60))
        | ((trend_60 > 0.15) & (adx > 20) & (future_ret > fr_q40))
    )

    # TREND_UP_MILD：趋势中强 + ADX 中强（或未来收益为正）；或 60 日收益 > +5% 兜底
    is_mild_up = (
        (
            (trend_60 > trend_q60) &
            (adx > 14) &
            (future_ret > fr_q40) &
            (~is_strong_up)
        ) | (
            (trend_60 > 0.05) & (~is_strong_up) & (~is_fomo)
        )
    )

    # CONSOLIDATION：横盘 = 低波动 + 窄布林，且趋势绝对值较小（不关心相对分位）
    # 条件放松保证 CONSOLIDATION 拿到足够样本
    is_consolidation = (
        (vol_20 < vol_q25) &
        (bb_width_pct < 0.45) &
        (trend_60.abs() < 0.06)
    )

    # 按优先级赋值（numpy 顺序 = 条件的优先级反序，最后赋值优先级最高）
    # 兜底：RANGE_BOUND（已默认）
    # 先覆盖较常见类：TREND_UP_MILD、TREND_UP_STRONG、DISTRIBUTION、CONSOLIDATION
    labels[is_consolidation.fillna(False).values] = "CONSOLIDATION"
    labels[is_mild_up.fillna(False).values] = "TREND_UP_MILD"
    labels[is_strong_up.fillna(False).values] = "TREND_UP_STRONG"
    labels[is_distribution.fillna(False).values] = "DISTRIBUTION"
    # 再覆盖事件类：VOLATILE_DROP / FOMO_RALLY / REVERSAL
    labels[is_volatile_drop.fillna(False).values] = "VOLATILE_DROP"
    labels[is_fomo.fillna(False).values] = "FOMO_RALLY"
    labels[is_reversal.fillna(False).values] = "REVERSAL"

    labels_series = pd.Series(labels, index=df.index, dtype=object)

    # 前 lookback 条没有足够历史；最后 forward_days 条没有未来收益 → 置 NaN
    invalid_mask = np.zeros(n, dtype=bool)
    invalid_mask[:lookback] = True
    invalid_mask[-forward_days:] = True
    # 任一关键信号为 NaN 的行也置 NaN
    invalid_mask |= (
        future_ret.isna().values |
        trend_60.isna().values |
        vol_20.isna().values |
        adx.isna().values |
        bb_width_pct.isna().values |
        trend_q60.isna().values |
        vol_q50.isna().values
    )
    labels_series.iloc[invalid_mask] = np.nan
    return labels_series


def label_to_code(series: pd.Series) -> pd.Series:
    """将标签字符串转为 0~7 的整数编码。"""
    mapper = {name: i for i, name in enumerate(REGIME_ORDER)}
    return series.map(mapper).astype("Int64")
