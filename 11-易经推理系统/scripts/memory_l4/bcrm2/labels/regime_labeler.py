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
    use_rolling_quantile: bool = True,
    target_balance: bool = True,
) -> pd.Series:
    """数据驱动的 8 态自动标签（以「当前市场形态特征」为主，未来收益为辅）。

    设计要点：
      - 主判定基于「可观测的当前特征」(trend_60 / adx / vol_20 / bb_width_pct /
        bocpd_prob)，使 Phase 0 特征能稳定拟合（可预测性更高）。
      - 未来收益 (future_ret) 仅作为辅助：只在「FOMO / VOLATILE_DROP 的极端
        定性兜底」与「派发期弱确认」时使用，且条件从「分位阈值」改为「绝对
        正负/比例」，减少其占标签信息量的权重（从 ~30% 降到 ~10%）。
      - 所有「分位阈值」均基于当前形态特征，保证标签可通过当前特征学习得到。
      - **滚动分位数动态阈值**（use_rolling_quantile=True）：用近期分位
        代替全局阈值，使 8 态标签分布随市场环境自适应，避免单一时段
        （如熊市）主导某类标签。

    参数：
      df: 至少含 close；可选 adx_14, bb_width_percentile_252, volume。
      forward_days: 未来收益窗口，默认 20；仅用作辅助弱校验。
      lookback: 滚动历史分位数窗口，默认 252。
      bocpd_prob_col: Phase 4 提供时使用真实 BOCPD 概率；否则用「价格反转」代理。
      use_rolling_quantile: 是否使用滚动分位数动态阈值（默认 True）。
      target_balance: 是否在标签生成后做均衡化调整（默认 True）。

    返回：
      labels: 长度=len(df) 的 Series，元素为 REGIME_ORDER 中的字符串，前
              lookback 条和最后 forward_days 条为 NaN（无法判断未来收益 /
              没有足够回看历史）。
    """
    close = df["close"].astype(float)
    n = len(close)

    # ===== 当前可观测特征信号 =====
    # 趋势强度：60 日对数收益（当前可得）
    trend_60 = np.log(close / close.shift(60))

    # 已实现波动率：20 日日化波动率（当前可得）
    daily_ret = close.pct_change()
    vol_20 = daily_ret.rolling(20, min_periods=10).std() * math.sqrt(365)

    # ADX（当前可得）
    if "adx_14" in df.columns:
        adx = df["adx_14"].astype(float)
    else:
        trend_14 = close.pct_change(14).abs()
        vol_14 = daily_ret.rolling(14, min_periods=8).std() * math.sqrt(365)
        adx = 50 * (trend_14 / (vol_14.where(vol_14 > 1e-9) + 1e-9))
        adx = adx.clip(lower=0, upper=100).ffill()

    # BB 宽度百分位（当前可得）
    if "bb_width_percentile_252" in df.columns:
        bb_width_pct = df["bb_width_percentile_252"].astype(float)
    else:
        close_std20 = close.rolling(20, min_periods=10).std()
        bb_width = (close_std20 * 4.0) / close.rolling(20, min_periods=10).mean()
        bb_width_pct = bb_width.rolling(lookback, min_periods=lookback // 2).rank(pct=True)

    # BOCPD 转折点概率（当前可得，价格反转代理）
    if bocpd_prob_col is not None and bocpd_prob_col in df.columns:
        bocpd_prob = df[bocpd_prob_col].astype(float)
    else:
        z20 = _rolling_zscore(close, 20)
        z20_prev = z20.shift(10)
        reversal_proxy = (
            ((z20_prev > 1.8) & (z20 < 0.4)) |
            ((z20_prev < -1.8) & (z20 > -0.4))
        ).astype(float)
        ret_10 = close.pct_change(10)
        # 注意：去掉 fut_10 依赖，只用「已实现收益 + 价格 z-score 转折」构造
        # 10 日强正收益后，价格又从高点回撤 → 视为反转概率上升
        price_from_peak = (close - close.rolling(10, min_periods=3).max()) / close.rolling(10, min_periods=3).max()
        price_from_trough = (close - close.rolling(10, min_periods=3).min()) / close.rolling(10, min_periods=3).min()
        contrarian = (
            ((ret_10 > 0.06) & (price_from_peak < -0.04)) |
            ((ret_10 < -0.06) & (price_from_trough > 0.04))
        )
        bocpd_prob = 0.5 * reversal_proxy + 0.5 * contrarian.astype(float)

    # ===== MA200 牛熊分界线信号（当前可得） =====
    # 经典经验：日线站上 MA200 = 牛市环境，跌破 = 熊市环境
    # 注意：MA200/周期特征已作为模型输入特征，标签生成不硬编码周期阶段
    ma200 = close.rolling(200, min_periods=100).mean()
    ma200_above = (close > ma200).astype(float)
    ma200_distance_pct = ((close - ma200) / ma200 * 100.0).replace([np.inf, -np.inf], 0.0)
    ma200_slope_20d = ma200.pct_change(20).replace([np.inf, -np.inf], 0.0)

    # ===== 未来收益：仅作为辅助弱校验，不作为主判定 =====
    # 只用「绝对正负」或「极端幅度」，避免引入过度复杂的不可预测分位信息
    future_ret = close.pct_change(forward_days).shift(-forward_days)
    future_ret_simple = future_ret  # 仅用于：极端涨跌弱确认、派发弱确认

    # ===== 滚动历史阈值（全部基于当前可得特征，保证可预测性） =====
    # 滚动分位数动态阈值：用近期分位代替全局阈值
    if use_rolling_quantile:
        # 滚动分位数：随市场环境自适应
        trend_q80 = trend_60.rolling(lookback, min_periods=lookback // 2).quantile(0.80)
        trend_q60 = trend_60.rolling(lookback, min_periods=lookback // 2).quantile(0.60)
        trend_q40 = trend_60.rolling(lookback, min_periods=lookback // 2).quantile(0.40)
        trend_q20 = trend_60.rolling(lookback, min_periods=lookback // 2).quantile(0.20)

        vol_q25 = vol_20.rolling(lookback, min_periods=lookback // 2).quantile(0.25)
        vol_q50 = vol_20.rolling(lookback, min_periods=lookback // 2).quantile(0.50)
        vol_q75 = vol_20.rolling(lookback, min_periods=lookback // 2).quantile(0.75)
    else:
        # 全局分位数（原逻辑）
        trend_q80 = pd.Series(np.nanquantile(trend_60.values, 0.80), index=df.index)
        trend_q60 = pd.Series(np.nanquantile(trend_60.values, 0.60), index=df.index)
        trend_q40 = pd.Series(np.nanquantile(trend_60.values, 0.40), index=df.index)
        trend_q20 = pd.Series(np.nanquantile(trend_60.values, 0.20), index=df.index)
        vol_q25 = pd.Series(np.nanquantile(vol_20.values, 0.25), index=df.index)
        vol_q50 = pd.Series(np.nanquantile(vol_20.values, 0.50), index=df.index)
        vol_q75 = pd.Series(np.nanquantile(vol_20.values, 0.75), index=df.index)

    # ===== 向量化判定（按 Spec §4.1 优先级） =====
    # 规则重构：
    #   - 每类主判定完全基于「trend_60 / adx / vol_20 / bb_width / bocpd_prob」
    #   - future_ret 仅在「FOMO/暴跌的极端兜底」「派发弱确认」出现，且只看正负
    labels = np.full(n, "RANGE_BOUND", dtype=object)

    # ----- REVERSAL（转折点）：主靠 BOCPD 代理 -----
    # 要求：转折信号强 + 趋势绝对值已经不大（即真的"转"了，不是趋势中途的噪声）
    is_reversal = (
        (bocpd_prob > 0.30) &
        (trend_60.abs() < 0.15)
    )

    # ----- FOMO_RALLY（狂热上涨）：主靠「强趋势 + 高波动」当前特征 -----
    # MA200/周期作为特征输入让模型学习，不在标签中硬编码
    is_fomo = (
        # 主判定：强趋势（top20%分位）+ 高波动（top25%分位）+ ADX 走中强
        ((trend_60 > trend_q80) & (vol_20 > vol_q75) & (adx > 20))
        # 兜底：60 日收益 > 25% 且波动率 > 中位
        | ((trend_60 > 0.25) & (vol_20 > vol_q50))
        # 弱辅助：未来 20 日极端正收益 (≥+18%) 且当前已经强趋势
        | ((future_ret_simple > 0.18) & (trend_60 > trend_q60))
    )

    # ----- VOLATILE_DROP（暴跌）：主靠「极弱趋势 + 高波动」 -----
    is_volatile_drop = (
        # 主判定：弱趋势（bottom 20%） + 高波动
        ((trend_60 < trend_q20) & (vol_20 > vol_q75))
        # 兜底：60 日绝对收益 < -20%（明显的熊市）
        | (trend_60 < -0.20)
        # 弱辅助：未来 20 日极端负收益 (≤-15%) 且当前已现疲态
        | ((future_ret_simple < -0.15) & (trend_60 < trend_q40))
    )

    # ----- DISTRIBUTION（派发）：趋势略负 + ADX 疲弱 + BB 偏宽 -----
    is_distribution = (
        (trend_60 < trend_q40) &
        (adx < 28) &
        (bb_width_pct > 0.50) &
        # 弱校验：未来 20 日没有极端暴涨（避免把 FOMO 启动点错判为派发）
        (future_ret_simple < 0.05)
    )

    # ----- TREND_UP_STRONG：趋势 top20% 分位 + ADX 强势 -----
    is_strong_up = (
        # 主判定：top20% 强趋势 + ADX>25 强趋势强度
        ((trend_60 > trend_q80) & (adx > 25))
        # 兜底：60 日绝对收益 > +15% 且 ADX 不弱（防止漏掉明显的上涨）
        | ((trend_60 > 0.15) & (adx > 20))
    )

    # ----- TREND_UP_MILD：趋势中强 + ADX 中强 -----
    is_mild_up = (
        # 主判定：top40% 趋势 + ADX>14，且没有被「强多 / FOMO」捕获
        (
            (trend_60 > trend_q60) &
            (adx > 14) &
            (~is_strong_up) &
            (~is_fomo)
        )
        # 兜底：60 日收益 > +5% 的绝对弱上涨，防漏掉
        | (
            (trend_60 > 0.05) &
            (~is_strong_up) &
            (~is_fomo)
        )
    )

    # ----- CONSOLIDATION（横盘）：低波动 + 窄布林 + 小趋势绝对值 -----
    is_consolidation = (
        (vol_20 < vol_q50 * 0.9 + vol_q25 * 0.1) &
        (bb_width_pct < 0.55) &
        (trend_60.abs() < 0.10)
    )

    # 按优先级赋值：兜底 → 横盘/弱趋势 → 强趋势 → 派发 → 极端事件
    labels[is_consolidation.fillna(False).values] = "CONSOLIDATION"
    labels[is_mild_up.fillna(False).values] = "TREND_UP_MILD"
    labels[is_strong_up.fillna(False).values] = "TREND_UP_STRONG"
    labels[is_distribution.fillna(False).values] = "DISTRIBUTION"
    labels[is_volatile_drop.fillna(False).values] = "VOLATILE_DROP"
    labels[is_fomo.fillna(False).values] = "FOMO_RALLY"
    labels[is_reversal.fillna(False).values] = "REVERSAL"

    labels_series = pd.Series(labels, index=df.index, dtype=object)

    # ===== 均衡化调整：将占比过高的标签中的边界样本降级为 RANGE_BOUND =====
    if target_balance:
        labels_series = _balance_labels(labels_series, trend_60, vol_20, adx, REGIME_ORDER)

    # ===== NaN 范围 =====
    invalid_mask = np.zeros(n, dtype=bool)
    invalid_mask[:lookback] = True
    invalid_mask[-forward_days:] = True
    invalid_mask |= (
        trend_60.isna().values |
        vol_20.isna().values |
        adx.isna().values |
        bb_width_pct.isna().values |
        trend_q60.isna().values |
        vol_q50.isna().values |
        # 保留 future_ret 作为辅助时，仍然要求其非 NaN（最后 forward_days 已置）
        future_ret.isna().values
    )
    labels_series.iloc[invalid_mask] = np.nan
    return labels_series


def _balance_labels(
    labels: pd.Series,
    trend_60: pd.Series,
    vol_20: pd.Series,
    adx: pd.Series,
    regime_order: list,
    max_ratio: float = 0.35,
    min_count: int = 5,
) -> pd.Series:
    """标签均衡化：将占比超过 max_ratio 的标签中，特征最弱的样本降级为 RANGE_BOUND。

    策略：对每个超占比标签，按 trend_60 绝对值排序，将最弱的一部分降级。
    这保留了标签的语义（弱趋势的 VOLATILE_DROP 实际上更接近 RANGE_BOUND）。

    Args:
        labels: 原始标签 Series
        trend_60: 60 日对数收益
        vol_20: 20 日波动率
        adx: ADX 值
        regime_order: 标签顺序
        max_ratio: 单类标签最大允许占比（默认 0.35）
        min_count: 每类至少保留的样本数（默认 5）

    Returns:
        均衡化后的标签 Series
    """
    n = len(labels)
    max_per_class = int(n * max_ratio)
    result = labels.copy()

    for label in regime_order:
        mask = (result == label)
        count = mask.sum()
        if count > max_per_class and count > min_count:
            # 按 trend_60 绝对值排序，最弱的降级
            weak_indices = (
                trend_60[mask]
                .abs()
                .sort_values()
                .index[:count - max_per_class]
            )
            result.loc[weak_indices] = "RANGE_BOUND"

    return result


def label_to_code(series: pd.Series) -> pd.Series:
    """将标签字符串转为 0~7 的整数编码。"""
    mapper = {name: i for i, name in enumerate(REGIME_ORDER)}
    return series.map(mapper).astype("Int64")
