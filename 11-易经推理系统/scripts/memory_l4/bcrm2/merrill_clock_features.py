"""
美林时钟周期特征模块 — 跨资产资金流动周期 (重构版)

理论映射 (传统美林时钟 → 加密市场):
  传统美林时钟核心: 通胀×增长两维 → 四阶段 → 资金跨资产流转
  加密市场映射: 
    - 增长代理 = 库存周期阶段 (被动去库存/主动补库存/被动补库存/主动去库存)
    - 通胀代理 = BTC.Dominance (资金在BTC和altcoin之间流转)
    - 四阶段 = 库存周期 × BTC.D → 资金流转方向

核心哲学:
  物质本身是发展变化的, 但能量守恒
  资金不会凭空消失, 只是从一个地方流入另一个地方
  美林时钟就是追踪这种资金流转的工具

与4年库存周期的互补关系:
  库存周期: 探讨周期内的自身趋势变化 (BTC自身牛熊)
  美林时钟: 探讨跨资产周期的资金流转 (BTC↔altcoin↔稳定币)
  两者正交, 可组合使用

跨资产轮动因子体系:
  1. 宏观-技术共振因子 (Resonance Factor): 库存周期阶段 × 技术信号
  2. 跨资产动量因子 (Cross-Asset Momentum): BTC vs altcoin相对强弱
  3. 流动性与信用因子 (Liquidity & Credit): 稳定币市值/成交量变化
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple


# 美林时钟四阶段 (基于库存周期 × BTC.D)
MERRILL_PHASES = {
    "RECOVERY": 0,    # 复苏期: 被动去库存 + BTC.D下降 → 资金流入altcoin
    "OVERHEAT": 1,    # 过热期: 主动补库存 + BTC.D下降 → altcoin疯狂
    "STAGFLATION": 2, # 滞胀期: 被动补库存 + BTC.D上升 → 资金回流BTC
    "REFLATION": 3,   # 衰退期: 主动去库存 + BTC.D上升 → 资金流出加密市场
}

PHASE_NAMES = {v: k for k, v in MERRILL_PHASES.items()}


def _rolling_zscore(series: pd.Series, window: int) -> pd.Series:
    """滚动z-score (事前可见)"""
    mean = series.rolling(window, min_periods=max(5, window//4)).mean()
    std = series.rolling(window, min_periods=max(5, window//4)).std()
    return (series - mean) / (std + 1e-10)


def _rolling_percentile(series: pd.Series, window: int) -> pd.Series:
    """滚动百分位 (事前可见, 0-1)"""
    def _pct(x):
        if len(x) < 5:
            return 0.5
        return np.sum(x[-1] >= x) / len(x)
    return series.rolling(window, min_periods=max(5, window//4)).apply(_pct, raw=True)


# ============================================================
# 1. BTC.Dominance 特征 (资金流转代理)
# ============================================================

def btc_dominance_features(df: pd.DataFrame, ref_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """
    BTC.Dominance特征 — 资金在BTC和altcoin之间流转的代理

    理论: 
      - BTC.D = BTC市值 / 加密市场总市值
      - BTC.D上升 = 资金从altcoin流入BTC (避险)
      - BTC.D下降 = 资金从BTC流入altcoin (风险偏好)

    特征:
      - mc_btcd_ratio: 目标资产/BTC价格比 (相对强弱)
      - mc_btcd_trend: BTC.D趋势方向
      - mc_btcd_pct: BTC.D滚动百分位
      - mc_btcd_zscore: BTC.D z-score
      - mc_capital_flow_dir: 资金流向方向 (+1=流入altcoin, -1=流入BTC)
    """
    result = pd.DataFrame(index=df.index)
    close = df["close"]

    if ref_df is not None and len(ref_df) > 100:
        aligned = df[["close"]].join(
            ref_df[["close"]].rename(columns={"close": "btc_close"}),
            how="left",
        ).ffill().dropna()

        if len(aligned) > 50:
            price_ratio = aligned["close"] / (aligned["btc_close"] + 1e-10)
            result["mc_btcd_ratio"] = price_ratio.reindex(df.index).ffill().fillna(price_ratio.mean() if len(price_ratio) > 0 else 0)

            ratio_ma20 = price_ratio.rolling(20, min_periods=5).mean()
            ratio_ma60 = price_ratio.rolling(60, min_periods=20).mean()
            result["mc_btcd_trend"] = (ratio_ma20 > ratio_ma60).astype(float).reindex(df.index).ffill().fillna(0.5)

            result["mc_btcd_pct"] = _rolling_percentile(price_ratio, 120).reindex(df.index).ffill().fillna(0.5)
            result["mc_btcd_zscore"] = _rolling_zscore(price_ratio, 120).reindex(df.index).ffill().fillna(0)

            ratio_change = price_ratio.pct_change(20)
            result["mc_capital_flow_dir"] = np.sign(ratio_change).reindex(df.index).ffill().fillna(0)
        else:
            result["mc_btcd_ratio"] = 0
            result["mc_btcd_trend"] = 0.5
            result["mc_btcd_pct"] = 0.5
            result["mc_btcd_zscore"] = 0
            result["mc_capital_flow_dir"] = 0
    else:
        result["mc_btcd_ratio"] = 0
        result["mc_btcd_trend"] = 0.5
        result["mc_btcd_pct"] = 0.5
        result["mc_btcd_zscore"] = 0
        result["mc_capital_flow_dir"] = 0

    return result


# ============================================================
# 2. 库存周期特征 (增长代理)
# ============================================================

def inventory_cycle_proxy(df: pd.DataFrame) -> pd.DataFrame:
    """
    库存周期四阶段代理特征

    四阶段映射:
      被动去库存(复苏): 价格上升 + 波动率下降 + 成交量温和
      主动补库存(繁荣): 价格快速上升 + 波动率上升 + 成交量放大
      被动补库存(滞胀): 价格见顶横盘 + 波动率高 + 成交量萎缩
      主动去库存(衰退): 价格下降 + 波动率高 + 成交量放大

    特征:
      - mc_inv_phase: 库存周期四阶段编码 (0-3)
      - mc_inv_recovery_score: 复苏强度
      - mc_inv_expansion_score: 繁荣强度
      - mc_inv_stagflation_score: 滞胀强度
      - mc_inv_contraction_score: 衰退强度
    """
    result = pd.DataFrame(index=df.index)

    close = df['close'].values
    volume = df['volume'].values if 'volume' in df.columns else np.ones(len(close))
    high = df['high'].values
    low = df['low'].values

    roc20 = pd.Series(close).pct_change(20).fillna(0).values * 100
    roc60 = pd.Series(close).pct_change(60).fillna(0).values * 100

    tr = np.maximum(high - low, np.maximum(
        np.abs(high - np.roll(close, 1)),
        np.abs(low - np.roll(close, 1))
    ))
    tr[0] = high[0] - low[0]
    atr20 = pd.Series(tr).rolling(20, min_periods=5).mean().values
    vol_ratio = atr20 / np.where(close > 0, close, 1) * 100

    vol_ma20 = pd.Series(volume).rolling(20, min_periods=5).mean().fillna(0).values
    vol_ma60 = pd.Series(volume).rolling(60, min_periods=10).mean().fillna(0).values
    vol_change = np.where(vol_ma60 > 1e-10, (vol_ma20 - vol_ma60) / (vol_ma60 + 1e-10) * 100, 0)

    ma20 = pd.Series(close).rolling(20, min_periods=5).mean().values
    ma60 = pd.Series(close).rolling(60, min_periods=10).mean().values
    trend = np.where(ma60 > 0, (ma20 - ma60) / ma60 * 100, 0)

    recovery = np.clip(roc20 * 0.3 + (10 - vol_ratio) * 0.4 + np.clip(vol_change, 0, 50) * 0.3, 0, 100)
    expansion = np.clip(roc60 * 0.4 + vol_ratio * 0.2 + np.clip(vol_change, 0, 100) * 0.4, 0, 100)
    stagflation = np.clip(
        (np.abs(roc20) < 5).astype(float) * 30
        + vol_ratio * 3
        + np.clip(-vol_change, 0, 50) * 0.8,
        0, 100
    )
    contraction = np.clip(-roc20 * 0.3 + vol_ratio * 0.3 + np.clip(vol_change, -50, 50) * 0.2, 0, 100)
    contraction = np.where(roc20 < 0, contraction, contraction * 0.3)

    result['mc_inv_recovery_score'] = recovery
    result['mc_inv_expansion_score'] = expansion
    result['mc_inv_stagflation_score'] = stagflation
    result['mc_inv_contraction_score'] = contraction

    scores = np.column_stack([recovery, expansion, stagflation, contraction])
    dominant_phase = np.argmax(scores, axis=1)
    result['mc_inv_phase'] = dominant_phase

    return result


# ============================================================
# 3. 宏观-技术共振因子 (Resonance Factor)
# ============================================================

def resonance_factor_features(df: pd.DataFrame, cycle_phase: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """
    宏观-技术共振因子 — 库存周期阶段 × 技术信号

    理论: 当宏观周期方向与技术信号方向一致时, 信号更可靠

    特征:
      - mc_resonance_trend: 周期趋势 × 技术趋势共振
      - mc_resonance_momentum: 周期动量 × 技术动量共振
      - mc_resonance_volatility: 周期波动率状态 × 技术波动率状态共振
      - mc_resonance_score: 综合共振评分 (-1到1)
      - mc_resonance_confidence: 共振置信度 (0-1)
    """
    result = pd.DataFrame(index=df.index)
    close = df["close"]

    if cycle_phase is not None and "ic_phase" in cycle_phase.columns:
        ic_phase = cycle_phase["ic_phase"].values
    else:
        proxy = inventory_cycle_proxy(df)
        ic_phase = proxy["mc_inv_phase"].values

    ema20 = close.rolling(20, min_periods=10).mean()
    ema60 = close.rolling(60, min_periods=30).mean()
    ema200 = close.rolling(200, min_periods=100).mean()

    tech_trend = np.sign((ema20 - ema60).fillna(0))
    long_trend = np.sign((ema60 - ema200).fillna(0))

    momentum = close.pct_change(20).fillna(0) * 100

    high = df["high"]
    low = df["low"]
    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    atr14 = tr.rolling(14, min_periods=5).mean()
    atr_pct = (atr14 / close).fillna(0)
    vol_pct = _rolling_percentile(atr_pct, 60).fillna(0.5)
    tech_vol_regime = np.where(vol_pct < 0.33, -1, np.where(vol_pct > 0.66, 1, 0))

    cycle_trend = np.where(ic_phase == 0, 1, np.where(ic_phase == 1, 1, np.where(ic_phase == 2, 0, -1)))
    cycle_momentum = np.where(ic_phase == 0, 0.5, np.where(ic_phase == 1, 1.0, np.where(ic_phase == 2, 0.0, -0.5)))
    cycle_vol_regime = np.where(ic_phase == 0, -1, np.where(ic_phase == 1, 1, np.where(ic_phase == 2, 1, 1)))

    result["mc_resonance_trend"] = pd.Series(cycle_trend * np.array(tech_trend), index=df.index).fillna(0)
    result["mc_resonance_momentum"] = pd.Series(cycle_momentum * np.sign(np.array(momentum)), index=df.index).fillna(0)
    result["mc_resonance_volatility"] = pd.Series(cycle_vol_regime * tech_vol_regime, index=df.index).fillna(0)

    resonance_score = (
        result["mc_resonance_trend"] * 0.4 +
        result["mc_resonance_momentum"] * 0.3 +
        result["mc_resonance_volatility"] * 0.3
    )
    result["mc_resonance_score"] = resonance_score.clip(-1, 1).fillna(0)

    confidence = (
        np.abs(result["mc_resonance_trend"]) * 0.4 +
        np.abs(result["mc_resonance_momentum"]) * 0.3 +
        np.abs(result["mc_resonance_volatility"]) * 0.3
    )
    result["mc_resonance_confidence"] = confidence.clip(0, 1).fillna(0)

    return result


# ============================================================
# 4. 跨资产动量因子 (Cross-Asset Momentum)
# ============================================================

def cross_asset_momentum_features(df: pd.DataFrame, ref_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """
    跨资产动量因子 — BTC vs altcoin相对强弱

    理论: 
      - 相对强弱持续 = 资金持续流入某类资产
      - 相对强弱反转 = 资金开始流出

    特征:
      - mc_cam_return_diff: 目标资产与BTC收益率差 (多周期)
      - mc_cam_momentum_ratio: 相对动量比值
      - mc_cam_trend_ratio: 相对趋势强度
      - mc_cam_rsi_spread: RSI差
      - mc_cam_strength: 综合跨资产强度评分 (-1到1)
      - mc_cam_strength_pct: 跨资产强度滚动百分位
    """
    result = pd.DataFrame(index=df.index)

    if ref_df is not None and len(ref_df) > 100:
        aligned = df[["close"]].join(
            ref_df[["close"]].rename(columns={"close": "ref_close"}),
            how="left",
        ).ffill().dropna()

        if len(aligned) > 50:
            for period in [6, 12, 24, 48, 168]:
                target_ret = aligned["close"].pct_change(period).fillna(0)
                ref_ret = aligned["ref_close"].pct_change(period).fillna(0)
                result[f"mc_cam_return_diff_{period}"] = (target_ret - ref_ret).reindex(df.index).ffill().fillna(0).clip(-0.3, 0.3)

            target_mom = aligned["close"].pct_change(24).fillna(0) * 100
            ref_mom = aligned["ref_close"].pct_change(24).fillna(0) * 100
            result["mc_cam_momentum_ratio"] = (target_mom / (ref_mom + 1e-10)).reindex(df.index).ffill().fillna(1).clip(-5, 5)

            target_ema20 = aligned["close"].rolling(20, min_periods=10).mean()
            target_ema60 = aligned["close"].rolling(60, min_periods=30).mean()
            ref_ema20 = aligned["ref_close"].rolling(20, min_periods=10).mean()
            ref_ema60 = aligned["ref_close"].rolling(60, min_periods=30).mean()

            target_trend = (target_ema20 - target_ema60) / (target_ema60 + 1e-10) * 100
            ref_trend = (ref_ema20 - ref_ema60) / (ref_ema60 + 1e-10) * 100
            result["mc_cam_trend_ratio"] = (target_trend / (ref_trend + 1e-10)).reindex(df.index).ffill().fillna(1).clip(-5, 5)

            def _rsi(series, period=14):
                delta = series.diff()
                gain = delta.where(delta > 0, 0)
                loss = -delta.where(delta < 0, 0)
                avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
                avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
                rs = avg_gain / (avg_loss + 1e-10)
                return 100 - (100 / (1 + rs))

            target_rsi = _rsi(aligned["close"])
            ref_rsi = _rsi(aligned["ref_close"])
            result["mc_cam_rsi_spread"] = ((target_rsi - ref_rsi) / 100).reindex(df.index).ffill().fillna(0).clip(-1, 1)

            strength = (
                result.get("mc_cam_return_diff_24", 0) * 0.3 +
                np.sign(target_mom - ref_mom) * 0.3 +
                result["mc_cam_rsi_spread"] * 0.4
            )
            result["mc_cam_strength"] = strength.clip(-1, 1).fillna(0)

            result["mc_cam_strength_pct"] = _rolling_percentile(result["mc_cam_strength"], 120).fillna(0.5)
        else:
            for period in [6, 12, 24, 48, 168]:
                result[f"mc_cam_return_diff_{period}"] = 0
            result["mc_cam_momentum_ratio"] = 1
            result["mc_cam_trend_ratio"] = 1
            result["mc_cam_rsi_spread"] = 0
            result["mc_cam_strength"] = 0
            result["mc_cam_strength_pct"] = 0.5
    else:
        for period in [6, 12, 24, 48, 168]:
            result[f"mc_cam_return_diff_{period}"] = 0
        result["mc_cam_momentum_ratio"] = 1
        result["mc_cam_trend_ratio"] = 1
        result["mc_cam_rsi_spread"] = 0
        result["mc_cam_strength"] = 0
        result["mc_cam_strength_pct"] = 0.5

    return result


# ============================================================
# 5. 流动性与信用因子 (Liquidity & Credit)
# ============================================================

def liquidity_credit_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    流动性与信用因子 — 成交量变化反映资金流入流出

    理论:
      - 成交量放大 = 资金流入 (买方或卖方力量增加)
      - 成交量萎缩 = 资金流出或观望
      - 量价关系 = 资金流入的质量

    特征:
      - mc_liq_volume_pct: 成交量滚动百分位
      - mc_liq_volume_trend: 成交量趋势
      - mc_liq_price_volume_divergence: 量价背离
      - mc_liq_turnover_rate: 换手率代理
      - mc_liq_credit_score: 综合流动性评分 (0-1)
      - mc_liq_smart_money: 大单方向代理
    """
    result = pd.DataFrame(index=df.index)
    close = df["close"]
    volume = df["volume"] if "volume" in df.columns else pd.Series(1, index=df.index)
    high = df["high"]
    low = df["low"]

    result["mc_liq_volume_pct"] = _rolling_percentile(volume, 60).fillna(0.5)

    vol_ma20 = volume.rolling(20, min_periods=5).mean()
    vol_ma60 = volume.rolling(60, min_periods=20).mean()
    result["mc_liq_volume_trend"] = (vol_ma20 / (vol_ma60 + 1e-10) - 1).fillna(0).clip(-0.5, 0.5)

    price_trend = np.sign(close.pct_change(10).fillna(0))
    vol_trend = np.sign(volume.rolling(10).mean().pct_change(5).fillna(0))
    result["mc_liq_price_volume_divergence"] = (price_trend * vol_trend).fillna(0)

    hl_range = (high - low) / (close + 1e-10)
    close_position = (close - low) / (high - low + 1e-10)
    result["mc_liq_smart_money"] = (close_position - 0.5).rolling(20, min_periods=5).mean().fillna(0).clip(-0.5, 0.5)

    turnover_rate = (volume * close).rolling(20).mean().pct_change(20).fillna(0)
    result["mc_liq_turnover_rate"] = turnover_rate.clip(-0.5, 0.5)

    credit_score = (
        result["mc_liq_volume_pct"] * 0.3 +
        np.clip(result["mc_liq_volume_trend"], 0, 1) * 0.3 +
        result["mc_liq_price_volume_divergence"] * 0.2 +
        result["mc_liq_smart_money"] * 0.2 + 0.5
    )
    result["mc_liq_credit_score"] = credit_score.clip(0, 1).fillna(0.5)

    return result


# ============================================================
# 6. 美林时钟四阶段分类 (库存周期 × BTC.D)
# ============================================================

def merrill_clock_phase(
    df: pd.DataFrame,
    ref_df: Optional[pd.DataFrame] = None,
    cycle_phase: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    美林时钟四阶段分类 — 基于库存周期 × BTC.Dominance

    分类逻辑:
      库存周期阶段 × BTC.D趋势 → 四阶段

      复苏期 (被动去库存 + BTC.D下降): 资金从BTC流入altcoin, 风险偏好回升
      过热期 (主动补库存 + BTC.D下降): altcoin疯狂上涨, FOMO情绪
      滞胀期 (被动补库存 + BTC.D上升): 资金从altcoin回流BTC, 避险开始
      衰退期 (主动去库存 + BTC.D上升): 资金流出加密市场, 恐慌

    特征:
      - mc_phase: 阶段编码 (0-3)
      - mc_phase_onehot_*: 四阶段one-hot
      - mc_phase_name: 阶段名称
      - mc_phase_confidence: 阶段置信度 (距决策边界的距离)
    """
    result = pd.DataFrame(index=df.index)

    if cycle_phase is not None and "ic_phase" in cycle_phase.columns:
        ic_phase = cycle_phase["ic_phase"].values
    else:
        proxy = inventory_cycle_proxy(df)
        ic_phase = proxy["mc_inv_phase"].values

    btc_d_feats = btc_dominance_features(df, ref_df)
    btc_d_trend = btc_d_feats["mc_btcd_trend"].values
    btc_d_ratio = btc_d_feats["mc_btcd_ratio"].values

    n = len(df)
    phases = np.zeros(n)
    confidence = np.zeros(n)

    for i in range(n):
        inv_p = ic_phase[i]
        d_trend = btc_d_trend[i]

        if np.isnan(inv_p) or np.isnan(d_trend):
            phases[i] = 0
            confidence[i] = 0
            continue

        inv_p = int(inv_p)

        if inv_p == 0 and d_trend < 0.5:
            phases[i] = MERRILL_PHASES["RECOVERY"]
            confidence[i] = min((0.5 - d_trend) * 2, 1.0)
        elif inv_p == 1 and d_trend < 0.5:
            phases[i] = MERRILL_PHASES["OVERHEAT"]
            confidence[i] = min((0.5 - d_trend) * 2, 1.0)
        elif inv_p == 2 and d_trend >= 0.5:
            phases[i] = MERRILL_PHASES["STAGFLATION"]
            confidence[i] = min((d_trend - 0.5) * 2, 1.0)
        elif inv_p == 3 and d_trend >= 0.5:
            phases[i] = MERRILL_PHASES["REFLATION"]
            confidence[i] = min((d_trend - 0.5) * 2, 1.0)
        else:
            if d_trend < 0.5:
                phases[i] = MERRILL_PHASES["RECOVERY"] if inv_p == 0 else MERRILL_PHASES["OVERHEAT"]
            else:
                phases[i] = MERRILL_PHASES["STAGFLATION"] if inv_p == 2 else MERRILL_PHASES["REFLATION"]
            confidence[i] = 0.3

    result["mc_phase"] = phases
    result["mc_phase_confidence"] = confidence

    for phase_name, phase_code in MERRILL_PHASES.items():
        result[f"mc_phase_{phase_name.lower()}"] = (phases == phase_code).astype(float)

    return result


# ============================================================
# 7. 交叉周期特征 (美林时钟 × 库存周期)
# ============================================================

def cross_cycle_features(
    df: pd.DataFrame,
    ref_df: Optional[pd.DataFrame] = None,
    cycle_phase: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    美林时钟 × 库存周期 交叉特征

    理论: 两个周期正交互补
      库存周期: 自身趋势变化 (时间锚点)
      美林时钟: 资金流转方向 (跨资产)

    交叉特征:
      - 美林阶段 × 库存阶段 → 16种组合
      - 资金流向 × 周期相位 → 捕捉周期共振
      - 共振因子 × 阶段特征
    """
    result = pd.DataFrame(index=df.index)

    merrill = merrill_clock_phase(df, ref_df, cycle_phase)
    flow = btc_dominance_features(df, ref_df)
    resonance = resonance_factor_features(df, cycle_phase)

    result["mc_recovery_flow"] = merrill["mc_phase_recovery"] * flow["mc_capital_flow_dir"]
    result["mc_overheat_flow"] = merrill["mc_phase_overheat"] * flow["mc_capital_flow_dir"]
    result["mc_stagflation_flow"] = merrill["mc_phase_stagflation"] * flow["mc_capital_flow_dir"]
    result["mc_reflation_flow"] = merrill["mc_phase_reflation"] * flow["mc_capital_flow_dir"]

    result["mc_resonance_recovery"] = merrill["mc_phase_recovery"] * resonance["mc_resonance_score"]
    result["mc_resonance_overheat"] = merrill["mc_phase_overheat"] * resonance["mc_resonance_score"]
    result["mc_resonance_stagflation"] = merrill["mc_phase_stagflation"] * resonance["mc_resonance_score"]
    result["mc_resonance_reflation"] = merrill["mc_phase_reflation"] * resonance["mc_resonance_score"]

    result["mc_liquidity_recovery"] = merrill["mc_phase_recovery"] * flow["mc_btcd_pct"]
    result["mc_liquidity_overheat"] = merrill["mc_phase_overheat"] * flow["mc_btcd_pct"]
    result["mc_liquidity_stagflation"] = merrill["mc_phase_stagflation"] * flow["mc_btcd_pct"]
    result["mc_liquidity_reflation"] = merrill["mc_phase_reflation"] * flow["mc_btcd_pct"]

    phase = merrill["mc_phase"].values
    phase_change = np.zeros(len(phase))
    for i in range(1, len(phase)):
        if phase[i] != phase[i-1]:
            phase_change[i] = 1
    result["mc_phase_change"] = phase_change

    if cycle_phase is not None and "ic_phase" in cycle_phase.columns:
        inv_phase = cycle_phase["ic_phase"].values
        for mp_name, mp_code in MERRILL_PHASES.items():
            for ip in range(4):
                col_name = f"mc_cross_{mp_name.lower()}_inv{int(ip)}"
                result[col_name] = ((phase == mp_code) & (inv_phase == ip)).astype(float)

    return result


# ============================================================
# 主类
# ============================================================

class MerrillClockFeatures:
    """
    美林时钟周期特征总入口 (重构版)

    五大类特征:
      1. BTC.Dominance特征 (资金流转代理) - 5个
      2. 库存周期代理特征 (增长代理) - 5个
      3. 宏观-技术共振因子 - 5个
      4. 跨资产动量因子 - 8个
      5. 流动性与信用因子 - 6个
      6. 美林时钟四阶段分类 - 6个
      7. 交叉周期特征 - ~20个

    总计: ~55个特征

    核心逻辑:
      - 将加密市场视为风险资产
      - 库存周期四阶段作为增长维度
      - BTC.Dominance作为通胀/资金流转维度
      - 四阶段 = 库存周期 × BTC.D → 资金流转方向
      - 三个跨资产轮动因子用于二层校准
    """

    def __init__(self, symbol: str = "BTC"):
        self.symbol = symbol

    def compute(
        self,
        df: pd.DataFrame,
        ref_df: Optional[pd.DataFrame] = None,
        enable_btcd: bool = True,
        enable_inventory: bool = True,
        enable_resonance: bool = True,
        enable_cross_asset_momentum: bool = True,
        enable_liquidity: bool = True,
        enable_phase: bool = True,
        enable_cross: bool = True,
        cycle_phase: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """计算美林时钟特征 (子模块可开关)

        Args:
            df: OHLCV数据
            ref_df: 参考资产OHLCV (如BTC数据，用于BTC.D计算)
            enable_btcd: BTC.Dominance特征
            enable_inventory: 库存周期代理特征
            enable_resonance: 宏观-技术共振因子
            enable_cross_asset_momentum: 跨资产动量因子
            enable_liquidity: 流动性与信用因子
            enable_phase: 美林时钟四阶段分类
            enable_cross: 交叉周期特征
            cycle_phase: 库存周期阶段数据 (用于交叉特征)
        """
        feats_list = []

        if enable_btcd:
            feats_list.append(btc_dominance_features(df, ref_df))
        if enable_inventory:
            feats_list.append(inventory_cycle_proxy(df))
        if enable_resonance:
            feats_list.append(resonance_factor_features(df, cycle_phase))
        if enable_cross_asset_momentum:
            feats_list.append(cross_asset_momentum_features(df, ref_df))
        if enable_liquidity:
            feats_list.append(liquidity_credit_features(df))
        if enable_phase:
            feats_list.append(merrill_clock_phase(df, ref_df, cycle_phase))
        if enable_cross:
            feats_list.append(cross_cycle_features(df, ref_df, cycle_phase))

        if not feats_list:
            return pd.DataFrame(index=df.index)

        result = pd.concat(feats_list, axis=1)
        result = result.ffill().fillna(0)
        result = result.replace([np.inf, -np.inf], 0)
        return result

    @property
    def n_features(self) -> int:
        return 55