"""MacroFeatures — 宏观基本面特征模块（P1）

最多 24 个特征，分 6 个维度（按数据源可用性动态生成，不创建全 NaN 列）：
  - 情绪 (5): fgi_zscore, fgi_trend_7d, fgi_extreme_fear, fgi_extreme_greed, fgi_divergence
  - 资金/衍生品 (5): funding_rate_zscore, funding_extreme_positive, funding_extreme_negative, oi_change_rate, funding_divergence
  - 流动性 (4): stablecoin_growth, tvl_change_7d, liquidity_expanding, liquidity_contracting
  - 链上 (3): hash_rate_trend, miners_revenue_zscore, miner_accumulation
  - 聪明钱/社交 (4): smart_money_direction, smart_money_divergence, social_hype_zscore, hype_extreme
  - 估值 (3): market_cap_rank, ath_drop_pct, undervalued

不参与卦象推导（纯 ML 增强）。
宏观数据缺失时返回空 DataFrame（不兜底 Mock）。

两级开关（通过 config 传入）：
  1. 维度级（粗粒度）: macro_enable_{dimension} — 控制整个维度
  2. 特征级（细粒度）: macro_feat_{feature_name} — 控制单个特征，优先级高于维度级

特征级开关用于贝叶斯优化/特征选择，可精确控制 24 个特征的启用/禁用。
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class MacroFeatures:
    """宏观基本面特征模块"""

    # 预期的宏观数据列
    REQUIRED_COLS = {
        "fear_greed_index", "fear_greed_trend_7d",
        "funding_rate", "open_interest",
        "stablecoin_supply", "tvl",
        "hash_rate", "miners_revenue",
        "smart_money_direction", "social_hype_score",
        "market_cap", "ath_drop_pct",
    }

    # 特征 → 所属维度映射（用于维度级开关回退）
    FEATURE_TO_DIM = {
        # sentiment
        "fgi_zscore": "sentiment", "fgi_extreme_fear": "sentiment",
        "fgi_extreme_greed": "sentiment", "fgi_divergence": "sentiment",
        "fgi_trend_7d": "sentiment",
        # funding
        "funding_rate_zscore": "funding", "funding_extreme_positive": "funding",
        "funding_extreme_negative": "funding", "oi_change_rate": "funding",
        "funding_divergence": "funding",
        # liquidity
        "stablecoin_growth": "liquidity", "liquidity_expanding": "liquidity",
        "liquidity_contracting": "liquidity", "tvl_change_7d": "liquidity",
        # onchain
        "hash_rate_trend": "onchain", "miner_accumulation": "onchain",
        "miners_revenue_zscore": "onchain",
        # smart_money
        "smart_money_direction": "smart_money", "smart_money_divergence": "smart_money",
        "social_hype_zscore": "smart_money", "hype_extreme": "smart_money",
        # valuation
        "market_cap_rank": "valuation", "ath_drop_pct": "valuation",
        "undervalued": "valuation",
    }

    # 全部 24 个特征名（用于特征级优化）
    ALL_FEATURES = list(FEATURE_TO_DIM.keys())

    def compute(
        self,
        df: pd.DataFrame,
        macro_df: Optional[pd.DataFrame] = None,
        config: Optional[dict] = None,
    ) -> pd.DataFrame:
        """计算宏观特征

        Args:
            df: K 线 OHLCV 数据
            macro_df: 宏观数据 DataFrame（已对齐到 df.index）
            config: 两级开关配置
                - 维度级: macro_enable_{dimension} (粗粒度)
                - 特征级: macro_feat_{feature_name} (细粒度，优先级高于维度级)

        Returns:
            特征 DataFrame，缺失数据源对应的特征不生成（避免全 NaN 列污染训练）
        """
        if macro_df is None or macro_df.empty:
            logger.debug("MacroFeatures: macro_df 缺失，返回空")
            return pd.DataFrame(index=df.index)

        cfg = config or {}

        def _feat_enabled(name: str) -> bool:
            """两级开关：特征级优先，维度级回退，默认 True"""
            feat_key = f"macro_feat_{name}"
            if feat_key in cfg:
                return bool(cfg[feat_key])
            dim = self.FEATURE_TO_DIM.get(name)
            if dim is not None:
                dim_key = f"macro_enable_{dim}"
                if dim_key in cfg:
                    return bool(cfg[dim_key])
            return True

        features = pd.DataFrame(index=df.index)

        # 对齐 macro_df 到 df 的索引（统一时区避免 reindex 全 NaN）
        macro = macro_df.copy()
        if macro.index.tz is not None and df.index.tz is None:
            macro.index = macro.index.tz_localize(None)
        elif macro.index.tz is None and df.index.tz is not None:
            macro.index = macro.index.tz_localize("UTC")
        macro = macro.reindex(df.index)

        # 辅助：判断某列是否有有效数据（非全 NaN）
        def _has_data(col: str) -> bool:
            return col in macro.columns and macro[col].notna().any()

        # ============================================================
        # 情绪维度 (5)
        # ============================================================
        if _has_data("fear_greed_index"):
            fgi = macro["fear_greed_index"]
            if _feat_enabled("fgi_zscore"):
                features["fgi_zscore"] = self._zscore(fgi, window=30)
            if _feat_enabled("fgi_extreme_fear"):
                features["fgi_extreme_fear"] = (fgi < 25).astype(float)
            if _feat_enabled("fgi_extreme_greed"):
                features["fgi_extreme_greed"] = (fgi > 75).astype(float)
            if _feat_enabled("fgi_divergence"):
                features["fgi_divergence"] = self._divergence(df["close"], fgi)

        if _has_data("fear_greed_trend_7d") and _feat_enabled("fgi_trend_7d"):
            features["fgi_trend_7d"] = macro["fear_greed_trend_7d"]

        # ============================================================
        # 资金/衍生品维度 (5)
        # ============================================================
        if _has_data("funding_rate"):
            fr = macro["funding_rate"]
            fr_z = self._zscore(fr, window=48)
            if _feat_enabled("funding_rate_zscore"):
                features["funding_rate_zscore"] = fr_z
            if _feat_enabled("funding_extreme_positive"):
                features["funding_extreme_positive"] = (fr_z > 2).astype(float)
            if _feat_enabled("funding_extreme_negative"):
                features["funding_extreme_negative"] = (fr_z < -2).astype(float)
            if _feat_enabled("funding_divergence"):
                features["funding_divergence"] = self._divergence(df["close"], fr)

        # oi_change_rate 使用真实 open_interest
        if _has_data("open_interest") and _feat_enabled("oi_change_rate"):
            oi = macro["open_interest"]
            features["oi_change_rate"] = oi.pct_change(12, fill_method=None).replace([np.inf, -np.inf], np.nan)

        # ============================================================
        # 流动性维度 (4)
        # ============================================================
        if _has_data("stablecoin_supply"):
            sc = macro["stablecoin_supply"]
            sc_growth = sc.pct_change(24, fill_method=None).replace([np.inf, -np.inf], np.nan)
            if _feat_enabled("stablecoin_growth"):
                features["stablecoin_growth"] = sc_growth
            if _feat_enabled("liquidity_expanding"):
                features["liquidity_expanding"] = (sc_growth > 0).astype(float)
            if _feat_enabled("liquidity_contracting"):
                features["liquidity_contracting"] = (sc_growth < -0.02).astype(float)

        if _has_data("tvl") and _feat_enabled("tvl_change_7d"):
            features["tvl_change_7d"] = macro["tvl"].pct_change(24 * 7, fill_method=None).replace([np.inf, -np.inf], np.nan)

        # ============================================================
        # 链上维度 (3, 仅 BTC 有数据)
        # ============================================================
        if _has_data("hash_rate"):
            hr = macro["hash_rate"]
            hr_trend = hr.pct_change(24, fill_method=None).replace([np.inf, -np.inf], np.nan)
            if _feat_enabled("hash_rate_trend"):
                features["hash_rate_trend"] = hr_trend
            if _feat_enabled("miner_accumulation"):
                features["miner_accumulation"] = (hr_trend > 0).astype(float)

        if _has_data("miners_revenue") and _feat_enabled("miners_revenue_zscore"):
            features["miners_revenue_zscore"] = self._zscore(macro["miners_revenue"], window=30)

        # ============================================================
        # 聪明钱/社交维度 (4, 仅实盘模式有数据)
        # ============================================================
        if _has_data("smart_money_direction"):
            smd = macro["smart_money_direction"]
            if _feat_enabled("smart_money_direction"):
                features["smart_money_direction"] = smd
            if _feat_enabled("smart_money_divergence"):
                features["smart_money_divergence"] = self._divergence(df["close"], smd)

        if _has_data("social_hype_score"):
            sh_z = self._zscore(macro["social_hype_score"], window=48)
            if _feat_enabled("social_hype_zscore"):
                features["social_hype_zscore"] = sh_z
            if _feat_enabled("hype_extreme"):
                features["hype_extreme"] = (sh_z.abs() > 2).astype(float)

        # ============================================================
        # 估值维度 (3)
        # ============================================================
        if _has_data("market_cap") and _feat_enabled("market_cap_rank"):
            features["market_cap_rank"] = macro["market_cap"].rank(pct=True)

        if _has_data("ath_drop_pct"):
            adp = macro["ath_drop_pct"]
            if _feat_enabled("ath_drop_pct"):
                features["ath_drop_pct"] = adp
            if _feat_enabled("undervalued"):
                features["undervalued"] = (adp < -50).astype(float)

        # 填充 inf
        features = features.replace([np.inf, -np.inf], np.nan)

        # 特征质量预筛：有效值比例 < 50% 的列直接删除，避免低覆盖率列干扰训练
        if len(features) > 0:
            n_rows = len(features)
            min_valid = int(n_rows * 0.5)
            valid_counts = features.notna().sum()
            keep_cols = valid_counts[valid_counts >= min_valid].index.tolist()
            if len(keep_cols) < len(features.columns):
                dropped = [c for c in features.columns if c not in keep_cols]
                logger.debug(f"MacroFeatures: 删除低覆盖率列 {dropped}")
                features = features[keep_cols]

        return features

    # ============================================================
    # 辅助方法
    # ============================================================

    @staticmethod
    def _zscore(series: pd.Series, window: int = 30) -> pd.Series:
        """滚动 z-score"""
        mean = series.rolling(window, min_periods=max(1, window // 3)).mean()
        std = series.rolling(window, min_periods=max(1, window // 3)).std()
        return (series - mean) / std.replace(0, np.nan)

    @staticmethod
    def _divergence(price: pd.Series, indicator: pd.Series) -> pd.Series:
        """价格与指标背离度

        正值：价格涨但指标跌（顶背离）
        负值：价格跌但指标涨（底背离）
        """
        price_ret = price.pct_change(12).replace([np.inf, -np.inf], np.nan)
        ind_ret = indicator.pct_change(12).replace([np.inf, -np.inf], np.nan)
        return price_ret - ind_ret


# ============================================================
# FeatureRegistry 注册
# ============================================================
from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry

FeatureRegistry.register(
    name="macro",
    factory=MacroFeatures,
    requires_macro_df=True,
    default_enabled=True,
)
