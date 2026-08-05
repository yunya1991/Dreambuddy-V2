"""
跨资产特征引擎 — ETH跟随BTC特性的算法落地

理论映射 (BCRM 八卦力学 → 跨资产维度):
  当ETH作为BTC的"矛盾次要方面"时，其走势受BTC这个"矛盾主要方面"主导。
  本模块将BTC作为"参照系"(reference frame)，量化ETH相对BTC的:
    - 趋势跟随强度 (beta)
    - 波动率传导 (volatility spillover)
    - 联动一致性 (correlation)
    - 相对强弱 (relative strength)
    - 市值差异代理 (market cap proxy via price ratio)

核心思想: ETH的矛盾运动不是孤立的，而是在BTC的"力场"中展开的。
"""

import numpy as np
import pandas as pd
from typing import Optional, Dict, List


def compute_cross_asset_features(
    df: pd.DataFrame,
    ref_df: pd.DataFrame,
    symbol: str = "ETH",
    ref_symbol: str = "BTC",
    correlation_window: int = 48,
    beta_window: int = 120,
    vol_window: int = 24,
) -> pd.DataFrame:
    """
    计算跨资产特征

    Args:
        df: 目标资产OHLCV (如ETH)
        ref_df: 参考资产OHLCV (如BTC)
        symbol: 目标资产名称
        ref_symbol: 参考资产名称
        correlation_window: 相关性计算窗口
        beta_window: Beta系数计算窗口
        vol_window: 波动率计算窗口

    Returns:
        DataFrame of cross-asset features, aligned with df.index
    """
    feats = pd.DataFrame(index=df.index)

    # 对齐时间索引
    aligned = df[["close"]].join(
        ref_df[["close"]].rename(columns={"close": "ref_close"}),
        how="left",
    )
    aligned = aligned.ffill().dropna()

    if len(aligned) < max(correlation_window, beta_window, vol_window) + 10:
        # 数据不足，返回空特征
        for col in _feature_names():
            feats[col] = 0.0
        return feats

    target_returns = aligned["close"].pct_change()
    ref_returns = aligned["ref_close"].pct_change()

    # ============================================================
    # 1. BTC联动特征 (Correlation & Co-movement)
    # ============================================================

    # 滚动相关性
    rolling_corr = target_returns.rolling(correlation_window).corr(ref_returns)
    feats["ca_corr"] = rolling_corr.fillna(0).clip(-1, 1)

    # 相关性稳定性 (过去N个周期的相关性标准差越小=越稳定跟随)
    feats["ca_corr_stability"] = rolling_corr.rolling(correlation_window).std().fillna(1).clip(0, 2)

    # 联动方向一致率 (同涨同跌的比例)
    same_dir = (np.sign(target_returns) == np.sign(ref_returns)).astype(float)
    feats["ca_same_dir_ratio"] = same_dir.rolling(correlation_window).mean().fillna(0.5)

    # ============================================================
    # 2. Beta系数 (趋势跟随强度)
    # ============================================================

    # 滚动Beta = Cov(ETH, BTC) / Var(BTC)
    cov = target_returns.rolling(beta_window).cov(ref_returns)
    var_ref = ref_returns.rolling(beta_window).var()
    beta = cov / (var_ref + 1e-10)
    feats["ca_beta"] = beta.fillna(1.0).clip(-3, 5)

    # Beta变化率 (Beta增大=ETH对BTC更敏感)
    feats["ca_beta_change"] = beta.pct_change(12).replace([np.inf, -np.inf], 0).fillna(0).clip(-2, 2)

    # Beta稳定性
    feats["ca_beta_stability"] = beta.rolling(beta_window).std().fillna(1).clip(0, 3)

    # ============================================================
    # 3. 波动率传导 (Volatility Spillover)
    # ============================================================

    target_vol = target_returns.rolling(vol_window).std()
    ref_vol = ref_returns.rolling(vol_window).std()

    # 相对波动率 (ETH vol / BTC vol, >1=ETH波动更大)
    feats["ca_vol_ratio"] = (target_vol / (ref_vol + 1e-10)).fillna(1).clip(0, 5)

    # 波动率差 (绝对)
    feats["ca_vol_spread"] = (target_vol - ref_vol).fillna(0).clip(-0.1, 0.1) * 100

    # BTC波动率变化方向 (BTC波动率上升时，ETH通常会跟)
    ref_vol_change = ref_vol.pct_change(6).replace([np.inf, -np.inf], 0).fillna(0)
    feats["ca_ref_vol_rising"] = (ref_vol_change > 0.1).astype(float)

    # 波动率传导滞后: BTC前N期波动率 vs ETH当期波动率
    ref_vol_lagged = ref_vol.shift(6)
    feats["ca_vol_spillover"] = (ref_vol_lagged / (target_vol + 1e-10)).fillna(1).clip(0, 5)

    # ============================================================
    # 4. 相对强弱 (Relative Strength)
    # ============================================================

    # 相对价格变化 (ETH涨幅 - BTC涨幅, 不同周期)
    for period in [6, 12, 24, 48]:
        target_ret = aligned["close"].pct_change(period)
        ref_ret = aligned["ref_close"].pct_change(period)
        feats[f"ca_rel_return_{period}"] = (target_ret - ref_ret).fillna(0).clip(-0.3, 0.3)

    # 相对动量 (ETH动量 vs BTC动量)
    target_mom = target_returns.rolling(24).sum()
    ref_mom = ref_returns.rolling(24).sum()
    feats["ca_rel_momentum"] = (target_mom - ref_mom).fillna(0).clip(-0.5, 0.5)

    # 相对强弱RSI差 (ETH RSI - BTC RSI)
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
    feats["ca_rsi_spread"] = ((target_rsi - ref_rsi) / 100).fillna(0).clip(-1, 1)

    # ============================================================
    # 5. BTC趋势方向 (Trend Following Signal)
    # ============================================================

    # BTC均线趋势 (多周期)
    for period in [20, 50, 200]:
        ref_ma = aligned["ref_close"].rolling(period).mean()
        feats[f"ca_ref_above_ma{period}"] = (
            (aligned["ref_close"] > ref_ma).astype(float)
        )

    # BTC均线排列 (多头=1, 空头=-1)
    ref_ma5 = aligned["ref_close"].rolling(5).mean()
    ref_ma20 = aligned["ref_close"].rolling(20).mean()
    ref_ma50 = aligned["ref_close"].rolling(50).mean()
    ref_bull = (ref_ma5 > ref_ma20) & (ref_ma20 > ref_ma50)
    ref_bear = (ref_ma5 < ref_ma20) & (ref_ma20 < ref_ma50)
    feats["ca_ref_trend_alignment"] = np.where(ref_bull, 1.0, np.where(ref_bear, -1.0, 0.0))

    # BTC MACD方向
    ref_ema12 = aligned["ref_close"].ewm(span=12, adjust=False).mean()
    ref_ema26 = aligned["ref_close"].ewm(span=26, adjust=False).mean()
    ref_dif = ref_ema12 - ref_ema26
    ref_dea = ref_dif.ewm(span=9, adjust=False).mean()
    feats["ca_ref_macd_signal"] = (ref_dif > ref_dea).astype(float)

    # BTC短期动量方向
    for period in [6, 12, 24]:
        ref_mom_val = ref_returns.rolling(period).sum()
        feats[f"ca_ref_momentum_{period}"] = np.sign(ref_mom_val).fillna(0)

    # ============================================================
    # 6. 背离检测 (Divergence Detection)
    # ============================================================

    # 价格背离: ETH新高但BTC未新高 (顶背离信号)
    eth_high20 = aligned["close"].rolling(20).max()
    btc_high20 = aligned["ref_close"].rolling(20).max()
    eth_new_high = aligned["close"] >= eth_high20 * 0.98
    btc_new_high = aligned["ref_close"] >= btc_high20 * 0.98
    feats["ca_bear_divergence"] = (eth_new_high & ~btc_new_high).astype(float)

    # 价格背离: ETH新低但BTC未新低 (底背离信号)
    eth_low20 = aligned["close"].rolling(20).min()
    btc_low20 = aligned["ref_close"].rolling(20).min()
    eth_new_low = aligned["close"] <= eth_low20 * 1.02
    btc_new_low = aligned["ref_close"] <= btc_low20 * 1.02
    feats["ca_bull_divergence"] = (eth_new_low & ~btc_new_low).astype(float)

    # ============================================================
    # 7. 市值/价格比代理 (Market Cap Proxy)
    # ============================================================

    # ETH/BTC价格比 (反映相对估值)
    price_ratio = aligned["close"] / aligned["ref_close"]
    feats["ca_price_ratio"] = price_ratio

    # 价格比变化率 (ETH相对BTC走强/走弱)
    feats["ca_price_ratio_change"] = price_ratio.pct_change(24).fillna(0).clip(-0.2, 0.2)

    # 价格比位置 (相对于近期均值)
    ratio_ma = price_ratio.rolling(120).mean()
    ratio_std = price_ratio.rolling(120).std()
    feats["ca_price_ratio_zscore"] = (
        (price_ratio - ratio_ma) / (ratio_std + 1e-10)
    ).fillna(0).clip(-3, 3)

    # ============================================================
    # 8. BTC引导信号 (BTC Leading Signal)
    # ============================================================

    # BTC前1-3小时收益率 (BTC可能领先ETH)
    for lag in [1, 2, 3]:
        feats[f"ca_ref_ret_lag{lag}"] = ref_returns.shift(lag).fillna(0).clip(-0.1, 0.1)

    # BTC前1小时是否大涨/大跌 (>0.5%)
    ref_lag1_big = np.abs(ref_returns.shift(1)) > 0.005
    feats["ca_ref_big_move"] = ref_lag1_big.astype(float)
    feats["ca_ref_big_move_dir"] = np.where(
        ref_returns.shift(1) > 0.005, 1.0,
        np.where(ref_returns.shift(1) < -0.005, -1.0, 0.0)
    )

    # 填充NaN和inf
    feats = feats.ffill().fillna(0)
    feats = feats.replace([np.inf, -np.inf], 0)

    return feats


def _feature_names() -> List[str]:
    """返回所有跨资产特征名（用于空数据时占位）"""
    return [
        "ca_corr", "ca_corr_stability", "ca_same_dir_ratio",
        "ca_beta", "ca_beta_change", "ca_beta_stability",
        "ca_vol_ratio", "ca_vol_spread", "ca_ref_vol_rising", "ca_vol_spillover",
        "ca_rel_return_6", "ca_rel_return_12", "ca_rel_return_24", "ca_rel_return_48",
        "ca_rel_momentum", "ca_rsi_spread",
        "ca_ref_above_ma20", "ca_ref_above_ma50", "ca_ref_above_ma200",
        "ca_ref_trend_alignment", "ca_ref_macd_signal",
        "ca_ref_momentum_6", "ca_ref_momentum_12", "ca_ref_momentum_24",
        "ca_bear_divergence", "ca_bull_divergence",
        "ca_price_ratio", "ca_price_ratio_change", "ca_price_ratio_zscore",
        "ca_ref_ret_lag1", "ca_ref_ret_lag2", "ca_ref_ret_lag3",
        "ca_ref_big_move", "ca_ref_big_move_dir",
    ]


# ===== FeatureRegistry 注册 =====
class CrossAssetFeatureWrapper:
    """将 compute_cross_asset_features 函数包装为类，适配 FeatureRegistry"""

    def __init__(self):
        pass

    def compute(self, df: pd.DataFrame, ref_df: pd.DataFrame,
                symbol: str = "ETH", ref_symbol: str = "BTC") -> pd.DataFrame:
        return compute_cross_asset_features(df, ref_df, symbol=symbol, ref_symbol=ref_symbol)


from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry

FeatureRegistry.register(
    name="cross_asset",
    factory=CrossAssetFeatureWrapper,
    requires_ref_df=True,
)
