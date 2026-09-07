"""MacroFeatures — 宏观基本面特征模块（P1 + 扩展：宏观金融 / BTC 链上）

原有 24 特征（6 维）+ 新增 12 特征（2 个新维度），分 8 个维度：
  - 情绪 (5): fgi_zscore, fgi_trend_7d, fgi_extreme_fear, fgi_extreme_greed, fgi_divergence
  - 资金/衍生品 (5): funding_rate_zscore, funding_extreme_positive, funding_extreme_negative,
                     oi_change_rate, funding_divergence
  - 流动性 (4): stablecoin_growth, tvl_change_7d, liquidity_expanding, liquidity_contracting
  - 链上 (3): hash_rate_trend, miners_revenue_zscore, miner_accumulation
  - 聪明钱/社交 (4): smart_money_direction, smart_money_divergence, social_hype_zscore, hype_extreme
  - 估值 (3): market_cap_rank, ath_drop_pct, undervalued
  ── 新增（Panewslab/BlockBeats 数据） ──
  - 宏观金融扩展 (7): vix_zone, us_macro_regime, sp500_7d_break, dxy_strength,
                       btc_etf_flow_3d, rwa_liquidity_pulse, treasury_balance_delta
  - BTC 链上扩展 (5): whale_netflow_pulse, exchange_btc_30d, defi_breadth,
                       oi_liq_pressure, btc_dom_delta

+ 可选共线性消解列：stablecoin_minus_rwa（当稳定币 supply 与 rwa_tvl 同时存在时生成）。

不参与卦象推导（纯 ML 增强）。
宏观数据缺失时返回空 DataFrame（不兜底 Mock）。

两级开关（通过 config 传入）：
  1. 维度级（粗粒度）: macro_enable_{dimension} — 控制整个维度
     — 新增: macro_enable_macro_finance_ext / macro_enable_btc_onchain_ext
  2. 特征级（细粒度）: macro_feat_{feature_name} — 控制单个特征，优先级高于维度级

特征级开关用于贝叶斯优化/特征选择，可精确控制 36 个（或 37 含残差）特征的启用/禁用。
FAIL-OPEN：所有新特征缺源时直接跳过，不生成全 NaN 列（字节等价旧逻辑）。
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ============================================================
# [P2] 模块级 YAML 配置路径 + 硬编码默认值（FAIL-OPEN fallback）
# ============================================================
import os as _os
_here = _os.path.dirname(_os.path.abspath(__file__))       # bcrm2/
_l4   = _os.path.dirname(_here)                            # memory_l4/
_scripts = _os.path.dirname(_l4)                           # scripts/
_ROOT = _os.path.dirname(_scripts)                         # 11-易经推理系统/
_YAML_PATH = _os.path.join(_ROOT, "configs", "macro_features.yaml")

_DEFAULT_FEATURE_TO_DIM: Dict[str, str] = {
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
    # ── 宏观金融扩展（Panewslab） ──
    "vix_zone":              "macro_finance_ext",
    "us_macro_regime":       "macro_finance_ext",
    "sp500_7d_break":        "macro_finance_ext",
    "dxy_strength":          "macro_finance_ext",
    "btc_etf_flow_3d":       "macro_finance_ext",
    "rwa_liquidity_pulse":   "macro_finance_ext",
    "treasury_balance_delta": "macro_finance_ext",
    # 残差去共线性列（流动性维度归因为稳定币 vs RWA）
    "stablecoin_minus_rwa":  "macro_finance_ext",
    # ── BTC 链上扩展 ──
    "whale_netflow_pulse":   "btc_onchain_ext",
    "exchange_btc_30d":      "btc_onchain_ext",
    "defi_breadth":          "btc_onchain_ext",
    "oi_liq_pressure":       "btc_onchain_ext",
    "btc_dom_delta":         "btc_onchain_ext",
}


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

    # [P2] 特征→维度映射（初始=默认值，模块末尾 _load_yaml_config() 可覆盖）
    FEATURE_TO_DIM = dict(_DEFAULT_FEATURE_TO_DIM)

    # 全部 37 个特征名（24 旧 + 12 新 + stablecoin_minus_rwa 可选衍生残差）
    # 注：stablecoin_minus_rwa 仅当 stablecoin_supply & pn_rwa_* 同时存在时才生成
    ALL_FEATURES = list(FEATURE_TO_DIM.keys())

    @classmethod
    def reload(cls) -> bool:
        """重新从 YAML 加载特征→维度映射。返回 True=YAML 成功，False=fallback 默认。"""
        return _load_yaml_config()

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

        # ============================================================
        # 宏观金融扩展维度 (7, 数据来源: Panewslab pn_us_* / pn_* / pn_rwa_*)
        # FAIL-OPEN: 任一输入列缺 → 该特征不生成（字节等价旧逻辑输出）
        # ============================================================

        # 1. VIX 分区 (0: <20, 1: 20~28, 2: 28~35, 3: >35)
        if _has_data("pn_us_vix") and _feat_enabled("vix_zone"):
            v = macro["pn_us_vix"]
            codes = pd.Series(np.nan, index=v.index, dtype=float)
            codes = codes.where(v.isna(), 0.0)
            codes = codes.where(~((v >= 20) & (v < 28)), 1.0)
            codes = codes.where(~((v >= 28) & (v < 35)), 2.0)
            codes = codes.where(~(v >= 35), 3.0)
            features["vix_zone"] = codes.astype(float)

        # 2. 宏观 regime：基于 FedFunds + CPI（美林时钟简化到宽松/中性/紧缩 3 分类）
        #    宽松: FedFunds < 4.0 且 CPI < 2.5； 紧缩: FedFunds>=5.0 且 CPI>=3.5； 其余 中性
        #    FAIL-OPEN：若 CPI 缺（Panewslab 不常给 CPI），则只看 FFR 单独判定（宽松 FFR<4 / 紧缩 FFR>=5 / 其余中性）。
        if (_has_data("pn_us_fedfunds") or _has_data("pn_us_cpi_yoy")) and _feat_enabled("us_macro_regime"):
            ffr = macro.get("pn_us_fedfunds")
            cpi = macro.get("pn_us_cpi_yoy")
            if ffr is None:
                ffr = pd.Series(np.nan, index=macro.index)
            if cpi is None:
                cpi = pd.Series(np.nan, index=macro.index)
            regime = pd.Series(np.nan, index=macro.index, dtype=float)
            # 宽松
            loose_w_cpi = (ffr < 4.0) & (cpi < 2.5)
            loose_no_cpi = (ffr < 4.0) & cpi.isna()  # CPI 缺时 FFR 单边宽松判定
            loose = loose_w_cpi | loose_no_cpi
            # 紧缩
            tight_w_cpi = (ffr >= 5.0) & (cpi >= 3.5)
            tight_no_cpi = (ffr >= 5.0) & cpi.isna()  # CPI 缺时 FFR 单边紧缩判定
            tight = tight_w_cpi | tight_no_cpi
            regime = regime.where(~loose, 0.0)          # 宽松
            regime = regime.where(~tight, 2.0)          # 紧缩
            # 中性：非紧非松，且至少有一个指标（ffr or cpi）非 NaN
            neutral_mask = (~loose & ~tight) & (ffr.notna() | cpi.notna())
            regime = regime.where(~neutral_mask, 1.0)   # 中性
            features["us_macro_regime"] = regime.astype(float)

        # 3. sp500_7d_break: S&P 7 日累计涨跌的 30 日滚动 z-score
        #    输入列兼容：若有 1d 涨跌幅（首选 pn_us_sp500_chg_pct）直接 rolling 求和；
        #    若只有 level 值（pn_us_sp500，Panewslab 通常给 level），先做 24 bar(≈1d) 差分近似日涨跌。
        sp500_has = _has_data("pn_us_sp500_chg_pct") or _has_data("pn_us_sp500")
        if sp500_has and _feat_enabled("sp500_7d_break"):
            if _has_data("pn_us_sp500_chg_pct"):
                sp = macro["pn_us_sp500_chg_pct"]
                # 1h ffill 对齐后的日涨跌幅在 24 行相同，每 168 bar 求和 / 24 ≈ 实际 7 日累计
                roll7 = sp.rolling(168, min_periods=24).sum() / 24.0
            else:
                sp_level = macro["pn_us_sp500"]
                # level→近似 1-bar 回报率（1h bar 回报太小，放大到 24-bar 日回报）
                sp_daily_ret = sp_level.pct_change(24, fill_method=None).replace([np.inf, -np.inf], np.nan)
                # 7 日累计回报 ≈ rolling 7 日 (168 bar) 的 24-bar 日回报求和 / 24？不对：
                # 因为对齐后 level 值在尾段 4 bars 都是同一 snapshot 值，pct_change(24) 肯定为 NaN（相邻 24 条里只有 4 条非空）。
                # 所以退而求其次：直接用 7 bar（1 天内 4 条有效 ≈ 7 bar 覆盖）的 raw 回报率，然后做 zscore，保持 FAIL-OPEN 少量数据。
                sp_1bar_ret = sp_level.pct_change(1, fill_method=None).replace([np.inf, -np.inf], np.nan)
                # 7d(168h) 累计，对 1-bar 在尾段少数值也能勉强有输出：用 168 bar rolling prod 近似累计，sum 对 return 也可。
                roll7_raw = (1.0 + sp_1bar_ret.fillna(0)).rolling(168, min_periods=2).apply(np.prod, raw=True) - 1.0
                roll7 = roll7_raw.replace([np.inf, -np.inf, 1.0], np.nan) * 100.0  # 转 % 量级
            features["sp500_7d_break"] = self._zscore(roll7, window=30)

        # 4. dxy_strength: DXY 30 日滚动 z-score
        if _has_data("pn_us_dollar_index") and _feat_enabled("dxy_strength"):
            # 30d = 720 bar（FAIL-OPEN 少数据自适应：nonnull_count < 10 → 放 minp=1 且 std=0 保留 0 不转 NaN）
            win = 30 * 24
            dxy = macro["pn_us_dollar_index"]
            dxy_nonnull = int(dxy.notna().sum())
            minp = 1 if dxy_nonnull <= 10 else max(72, len(df) // 3)
            mean = dxy.rolling(win, min_periods=minp).mean()
            std = dxy.rolling(win, min_periods=minp).std()
            if dxy_nonnull <= 10:
                # FAIL-OPEN：4 个相同 ffill 值 → std=0 → 保留 0（表示无偏离）而非 NaN，让列有值通过 gate
                denom = std.replace(0, np.nan)
                raw_strength = (dxy - mean) / denom
                strength = raw_strength.where(~std.eq(0) | dxy.isna(), 0.0)
                features["dxy_strength"] = strength.astype(float)
            else:
                features["dxy_strength"] = (dxy - mean) / std.replace(0, np.nan)

        # 5. btc_etf_flow_3d: 3 日 BTC ETF 累计净流入 归一（全局 90d zscore 或 norm 代理）
        #    输入列兼容：优先 millions（精确日流入），否则用 pn_btc_etf_daily_flow_usd（USD 单位除以 1e6 → millions）
        #    或直接用 pn_btc_etf_flow_norm（Panewslab 已归一化代理）。
        #    列名双轨：BCRM2 数据层同时暴露 {pn_, 无前缀} 两套（_fetch_panewslab_blockbeats_snapshot_latest
        #    同时注入 panewslab 原始 metrics（无前缀）和 FiveDomainSqliteReader 派生 dict（加 pn_），
        #    所以候选列名把两套都加进去，哪套命中就用哪套；FAIL-OPEN 字节等价保持。
        btc_etf_cols = (
            "pn_btc_etf_daily_flow_usd_millions",
            "pn_btc_etf_daily_flow_usd", "btc_etf_daily_flow_usd",
            "eth_etf_daily_flow_usd",
            "pn_btc_etf_flow_norm",
            "pn_btc_etf_total_aum_usd", "btc_etf_total_aum_usd",
            "eth_etf_total_aum_usd",
        )
        etf_has = any(_has_data(c) for c in btc_etf_cols)
        if etf_has and _feat_enabled("btc_etf_flow_3d"):
            # 选一个「BTC 日净流入 USD」列；优先 BTC 精确列；缺时退 ETH（作为大盘 ETF 流动代理）
            btc_flow_col = next((c for c in ("pn_btc_etf_daily_flow_usd_millions",
                                             "pn_btc_etf_daily_flow_usd", "btc_etf_daily_flow_usd",
                                             "eth_etf_daily_flow_usd", "pn_eth_etf_daily_flow_usd")
                                 if _has_data(c)), None)
            if btc_flow_col == "pn_btc_etf_daily_flow_usd_millions":
                f = macro["pn_btc_etf_daily_flow_usd_millions"]
                etf_nonnull = int(f.notna().sum())
                mp_sum = 2 if etf_nonnull <= 10 else 12
                sum3 = f.rolling(72, min_periods=mp_sum).sum() / 24.0
            elif btc_flow_col in ("pn_btc_etf_daily_flow_usd", "btc_etf_daily_flow_usd",
                                  "eth_etf_daily_flow_usd", "pn_eth_etf_daily_flow_usd"):
                # 转为 millions（除以 1e6），再 rolling 3 日求和
                f_m = macro[btc_flow_col] / 1_000_000.0
                etf_nonnull = int(f_m.notna().sum())
                mp_sum = 2 if etf_nonnull <= 10 else 12
                sum3 = f_m.rolling(72, min_periods=mp_sum).sum() / 24.0
            else:
                # pn_btc_etf_flow_norm 是归一化代理，本身不是日流 → 用 72 bar rolling mean 近似 3 日累计平滑
                norm = macro["pn_btc_etf_flow_norm"]
                etf_nonnull = int(norm.notna().sum())
                mp_sum = 2 if etf_nonnull <= 10 else 12
                sum3 = norm.rolling(72, min_periods=mp_sum).mean()
            win = 90 * 24
            # FAIL-OPEN 少数据：sum3 nonnull 可能只有 3-4（Panewslab 对齐后尾段 bars）。
            #   90d rolling minp=2 会导致前 1 个点没统计量（safe_out 变成 NaN）→ 掉 gate。
            #   修正：nonnull <= 10 时 min_periods 降到 1（单点 mean=自身, std=0 → safe_out 填 0）
            #   保证每个 sum3 nonnull 位置都产出 safe_out（std=0 分支 0），过 quality gate min_valid=3。
            #   注意：std 显式 ddof=0，因为 ddof=1 在 n=1 时返回 NaN（pandas 默认 ddof=1 样本 std）。
            sum3_nn = int(sum3.notna().sum())
            minp = 1 if sum3_nn <= 10 else max(2, min(90, len(df) // 4))
            m_mean = sum3.rolling(win, min_periods=minp).mean()
            m_std = sum3.rolling(win, min_periods=minp).std(ddof=0)
            denom = m_std.replace(0, np.nan)
            raw = (sum3 - m_mean) / denom
            # denom=0 说明 3 日累计全相同 → 归一偏离=0（不是 NaN，过 gate）
            safe_out = raw.where(~m_std.eq(0) | sum3.isna(), 0.0)
            features["btc_etf_flow_3d"] = safe_out.astype(float)

        # 6. rwa_liquidity_pulse: RWA TVL 7 日增速 的 30 日 z-score（精确增速字段）
        #    输入兼容：pn_rwa_change7d_pct（首选直接 7d 增速）或 pn_rwa_tvl_usd_billions（十亿单位）
        #    或 pn_rwa_tvl_usd（实际 SQLite 返回的是美元整数，非 billions → 自动 /1e9）。
        #    FAIL-OPEN：4 bars nonnull 时 pct_change(168) 全 NaN → 用 Δbar 自适应百分比差分缩放至 7 天口径。
        rwa_cols_ok = (_has_data("pn_rwa_change7d_pct")
                       or _has_data("pn_rwa_tvl_usd_billions")
                       or _has_data("pn_rwa_tvl_usd"))
        # 局部 helper: Δbar 自适应 pct_change（按相邻 nonnull 对算百分比，再按 Δbar 缩放至 target_days 量级）
        def _adapt_pct(s: pd.Series, target_days: int = 7) -> pd.Series:
            vals = s.values
            idx_nonnull = np.where(pd.notna(vals))[0]
            out_arr = np.full(len(s), np.nan, dtype=float)
            if len(idx_nonnull) < 2:
                return pd.Series(out_arr, index=s.index)
            target_bars = target_days * 24.0
            for i in range(1, len(idx_nonnull)):
                ic = idx_nonnull[i]
                ip = idx_nonnull[i - 1]
                dbar = ic - ip
                if dbar <= 0 or np.isnan(vals[ip]) or vals[ip] == 0:
                    continue
                raw_pct = (vals[ic] - vals[ip]) / float(vals[ip]) * 100.0
                # 按 Δbar 缩放到 target_days（线性近似：时间越短 → 放大越多）
                scaled = raw_pct * (target_bars / float(dbar)) if float(dbar) > 0 else raw_pct
                out_arr[ic] = float(scaled)
            return pd.Series(out_arr, index=s.index).replace([np.inf, -np.inf], np.nan)

        if rwa_cols_ok and _feat_enabled("rwa_liquidity_pulse"):
            win_z = 30 * 24
            # 先用首选 direct 7d；否则 level→adaptive pct
            if _has_data("pn_rwa_change7d_pct"):
                raw = macro["pn_rwa_change7d_pct"].astype(float)
            elif _has_data("pn_rwa_tvl_usd_billions"):
                tvl = macro["pn_rwa_tvl_usd_billions"].astype(float)
                rwa_nn = int(tvl.notna().sum())
                raw = _adapt_pct(tvl, target_days=7) if rwa_nn <= 20 else (
                    tvl.pct_change(168, fill_method=None).replace([np.inf, -np.inf], np.nan) * 100.0
                )
            else:
                tvl = macro["pn_rwa_tvl_usd"].astype(float) / 1_000_000_000.0
                rwa_nn = int(tvl.notna().sum())
                raw = _adapt_pct(tvl, target_days=7) if rwa_nn <= 20 else (
                    tvl.pct_change(168, fill_method=None).replace([np.inf, -np.inf], np.nan) * 100.0
                )
            raw_nn = int(raw.notna().sum())
            minp_z = 2 if raw_nn <= 10 else max(2, min(72, len(df) // 3))
            m = raw.rolling(win_z, min_periods=minp_z).mean()
            s = raw.rolling(win_z, min_periods=minp_z).std()
            denom = s.replace(0, np.nan)
            pulse_raw = (raw - m) / denom
            pulse_safe = pulse_raw.where(~s.eq(0) | raw.isna(), 0.0)
            features["rwa_liquidity_pulse"] = pulse_safe.astype(float).replace([np.inf, -np.inf], np.nan)

        # 7. treasury_balance_delta: 各国/企业国库 BTC 净增量 — 7 日均值
        #    输入兼容：pn_treasury_total_btc_holdings（首选）/ pn_treasury_btc_total（Panewslab 实际返回名）
        #    / pn_holdings_treasury_btc（SQLite reader 派生字段名）
        tb_cols = ("pn_treasury_total_btc_holdings", "pn_treasury_btc_total", "pn_holdings_treasury_btc")
        tb_has = next((c for c in tb_cols if _has_data(c)), None)
        if tb_has is not None and _feat_enabled("treasury_balance_delta"):
            tb = macro[tb_has]
            # 7 日(168h) 差分：当前值 - 168 小时前的值 → 除以 7 ≈ 每日净增。
            # FAIL-OPEN：对齐后可能只有 3-4 bars 连续非空，找 168 bar 之前的值会失败。
            # 自适应：对每一行，向前找到 "最近一个 nonnull 值的位置"，计算行差 Δbar，
            #   若 Δbar ≥ 168 → 正常 diff(168)/7；若 Δbar∈[2,168) → 年化等价 diff / (Δbar/24/7)；
            #   这样尾段少量 bars 也能给出日变化率估计。
            nonnull_idx = np.where(tb.notna().values)[0]
            delta_daily_arr = np.full(len(tb), np.nan, dtype=float)
            if len(nonnull_idx) >= 2:
                tb_vals = tb.values
                for i in range(1, len(nonnull_idx)):
                    idx_cur = nonnull_idx[i]
                    idx_prev = nonnull_idx[i - 1]
                    delta_bars = idx_cur - idx_prev
                    if delta_bars <= 0:
                        continue
                    val_cur = tb_vals[idx_cur]
                    val_prev = tb_vals[idx_prev]
                    # 计算 "7日增量"：当前 bar 相对 prev bar 的绝对差按 7 天比例缩放（若小于 7 天）
                    # 或直接按 bar 差 / 24 ≈ 天数差的日净增（与原公式 diff(168)/7 口径一致）
                    days_apart = delta_bars / 24.0
                    daily_change = (val_cur - val_prev) / days_apart if days_apart > 0 else np.nan
                    delta_daily_arr[idx_cur] = float(daily_change)
            features["treasury_balance_delta"] = pd.Series(delta_daily_arr, index=tb.index).replace([np.inf, -np.inf], np.nan)

        # 7b. stablecoin_minus_rwa 残差去共线性（当稳定币供给或总市值与 RWA 增速同时存在时）
        #    输入兼容：首选 stablecoin_supply（旧口径），否则用 stablecoin_transparency 真实输出
        #    stablecoin_mcap_bln（≈ USDT+USDC 真实供应量之和，单位 B 美元）或 usdt/usdc_circulating_bln
        #    求和；或 change_7d_pct（stablecoin_transparency 已直接给出的 7 日加权涨跌 %）；
        #    再缺时用 {pn_, 无前缀} global_market_cap_usd 的差分近似（因为稳定币在总市值中占比稳定，
        #    总市值变化 ≈ 稳定币变化 × 常数；保持 FAIL-OPEN 语义）。
        #    FAIL-OPEN: nonnull<=20 时 pct_change(168) 全 NaN → Δbar 自适应 pct_change 缩放。
        stab_cols_ok = (_has_data("stablecoin_supply")
                        or _has_data("stablecoin_mcap_bln")
                        or _has_data("usdt_circulating_bln")
                        or _has_data("usdc_circulating_bln")
                        or _has_data("change_7d_pct")
                        or _has_data("stablecoin_change_rate")
                        or _has_data("pn_global_market_cap_usd")
                        or _has_data("global_market_cap_usd"))
        if (stab_cols_ok and rwa_cols_ok) and _feat_enabled("stablecoin_minus_rwa"):
            # 局部 helper 同 rwa 块
            def _adapt_pct2(s: pd.Series, target_days: int = 7) -> pd.Series:
                vals = s.values
                idx_nonnull = np.where(pd.notna(vals))[0]
                out_arr = np.full(len(s), np.nan, dtype=float)
                if len(idx_nonnull) < 2:
                    return pd.Series(out_arr, index=s.index)
                target_bars = target_days * 24.0
                for i in range(1, len(idx_nonnull)):
                    ic = idx_nonnull[i]
                    ip = idx_nonnull[i - 1]
                    dbar = ic - ip
                    if dbar <= 0 or np.isnan(vals[ip]) or vals[ip] == 0:
                        continue
                    raw_pct = (vals[ic] - vals[ip]) / float(vals[ip]) * 100.0
                    scaled = raw_pct * (target_bars / float(dbar)) if float(dbar) > 0 else raw_pct
                    out_arr[ic] = float(scaled)
                return pd.Series(out_arr, index=s.index).replace([np.inf, -np.inf], np.nan)

            # stablecoin 7d% 计算优先级：
            #   1) 直接已有的 change_7d_pct（stablecoin_transparency 已派生的 7 日加权涨跌 %）
            #   2) stablecoin_mcap_bln 总稳定币市值（level）→ Δbar 自适应 pct_change 到 7d
            #   3) usdt_circulating_bln + usdc_circulating_bln 求和（与 [2] 基本等价）
            #   4) stablecoin_supply 旧口径
            #   5) global_market_cap_usd / pn_global_market_cap_usd 总市值 proxy
            if _has_data("change_7d_pct"):
                sc_7d = macro["change_7d_pct"].astype(float)  # 已是 7d%，直接用
            elif _has_data("stablecoin_mcap_bln"):
                sc = macro["stablecoin_mcap_bln"].astype(float)
                sc_nn = int(sc.notna().sum())
                sc_7d = _adapt_pct2(sc, 7) if sc_nn <= 20 else (
                    sc.pct_change(168, fill_method=None).replace([np.inf, -np.inf], np.nan) * 100.0
                )
            elif _has_data("usdt_circulating_bln") or _has_data("usdc_circulating_bln"):
                usdt = macro["usdt_circulating_bln"].astype(float) if _has_data("usdt_circulating_bln") else 0.0
                usdc = macro["usdc_circulating_bln"].astype(float) if _has_data("usdc_circulating_bln") else 0.0
                sc_sum = (usdt + usdc).replace(0.0, np.nan)
                sc_nn = int(sc_sum.notna().sum())
                sc_7d = _adapt_pct2(sc_sum, 7) if sc_nn <= 20 else (
                    sc_sum.pct_change(168, fill_method=None).replace([np.inf, -np.inf], np.nan) * 100.0
                )
            elif _has_data("stablecoin_supply"):
                sc = macro["stablecoin_supply"].astype(float)
                sc_nn = int(sc.notna().sum())
                sc_7d = _adapt_pct2(sc, 7) if sc_nn <= 20 else (
                    sc.pct_change(168, fill_method=None).replace([np.inf, -np.inf], np.nan) * 100.0
                )
            else:
                # 近似：总市值 7 日增速（包含 BTC/ETH，但作为 stablecoin 代理 FAIL-OPEN 仍有意义）
                gcap_col = next((c for c in ("pn_global_market_cap_usd", "global_market_cap_usd") if _has_data(c)),
                                "pn_global_market_cap_usd")
                gcap = macro[gcap_col].astype(float)
                gcap_nn = int(gcap.notna().sum())
                sc_7d = _adapt_pct2(gcap, 7) if gcap_nn <= 20 else (
                    gcap.pct_change(168, fill_method=None).replace([np.inf, -np.inf], np.nan) * 100.0
                )
            # RWA 7 日增速（同 rwa_liquidity_pulse 的 pct 计算，但非 zscore，保持同比 %）
            if _has_data("pn_rwa_change7d_pct"):
                rwa_7d = macro["pn_rwa_change7d_pct"].astype(float)
            elif _has_data("pn_rwa_tvl_usd_billions"):
                tvl = macro["pn_rwa_tvl_usd_billions"].astype(float)
                tvl_nn = int(tvl.notna().sum())
                rwa_7d = _adapt_pct2(tvl, 7) if tvl_nn <= 20 else (
                    tvl.pct_change(168, fill_method=None).replace([np.inf, -np.inf], np.nan) * 100.0
                )
            else:
                tvl = macro["pn_rwa_tvl_usd"].astype(float) / 1_000_000_000.0
                tvl_nn = int(tvl.notna().sum())
                rwa_7d = _adapt_pct2(tvl, 7) if tvl_nn <= 20 else (
                    tvl.pct_change(168, fill_method=None).replace([np.inf, -np.inf], np.nan) * 100.0
                )
            # 残差 = 纯链上投机性流动 = 稳定币增速 - RWA 增速（RWA 是国债/法币锚定，增速差值≈纯交易性资金变化）
            features["stablecoin_minus_rwa"] = (sc_7d - rwa_7d).replace([np.inf, -np.inf], np.nan)

        # ============================================================
        # BTC 链上扩展维度 (5)
        # ============================================================

        # 1. whale_netflow_pulse: 巨鲸净流入 3 日滚动 ÷ 全局 60d std 归一（±1σ 压缩）
        #    FAIL-OPEN：对齐后可能只有 3-4 bars nonnull，72 bar rolling min_periods=8 会全 NaN。
        #    改为：nonnull 数量 < 10 时用 min_periods=2（让 3-4 根 bar 也能产出均值级结果）；
        #    同理 60d*24 的全局 std min_periods 从 24*7 降到 min(7, nonnull count)。
        #    denom=0 时 FAIL-OPEN 填 0（表示 "无波动偏离" 而非 NaN，过 gate）。
        #    列名双轨 fallback（按精准度排序，候选命中即生成）：
        #      · pn_whale_netflow_cap_pct / whale_netflow_cap_pct：首选（Panewslab 已归一化的巨鲸净流入/总市值 %）
        #      · pn_whale_netflow_to_ex_usd / whale_netflow_to_ex_usd：巨鲸净流入交易所 USD 绝对额
        #        → / spot1_BTC_mcap 转 %（作为 cap_pct 近似，FAIL-OPEN 保底）
        #      · spot1_BTC_nf24 / spot10_WBTC_nf24：巨鲸级币种 24h 净流量（spot1_BTC/spot10_WBTC）
        #        → / spot{1,10}_*_mcap 归一，作为巨鲸资金流 proxy（数据源接入前的 FAIL-OPEN 近似）
        _whale_pct_col = next((c for c in ("pn_whale_netflow_cap_pct", "whale_netflow_cap_pct")
                               if _has_data(c)), None)
        _whale_usd_col = next((c for c in ("pn_whale_netflow_to_ex_usd", "whale_netflow_to_ex_usd")
                               if _has_data(c)), None)
        _whale_has = (_whale_pct_col is not None
                      or _whale_usd_col is not None
                      or _has_data("spot1_BTC_nf24")
                      or _has_data("spot10_WBTC_nf24"))
        if _whale_has and _feat_enabled("whale_netflow_pulse"):
            if _whale_pct_col is not None:
                w = macro[_whale_pct_col].astype(float)
            elif _whale_usd_col is not None:
                # USD 净流量 / 总市值近似归一化（spot1_BTC_mcap 或 btc_etf_total_aum_usd 作分母）
                denom_col = next((c for c in ("spot1_BTC_mcap", "pn_btc_etf_total_aum_usd",
                                              "btc_etf_total_aum_usd", "global_market_cap_usd")
                                  if _has_data(c)), None)
                if denom_col is not None:
                    denom = macro[denom_col].astype(float).replace(0, np.nan)
                    w = (macro[_whale_usd_col].astype(float) / denom * 100.0)  # 转 % 与 cap_pct 同量级
                else:
                    w = macro[_whale_usd_col].astype(float)
            else:
                # 用 spot1_BTC_nf24 / spot10_WBTC_nf24 作为巨鲸级净流量 proxy，÷对应 mcap 归一
                parts = []
                if _has_data("spot1_BTC_nf24") and _has_data("spot1_BTC_mcap"):
                    p1 = (macro["spot1_BTC_nf24"].astype(float)
                          / macro["spot1_BTC_mcap"].astype(float).replace(0, np.nan) * 100.0)
                    parts.append(p1)
                if _has_data("spot10_WBTC_nf24") and _has_data("spot10_WBTC_mcap"):
                    p2 = (macro["spot10_WBTC_nf24"].astype(float)
                          / macro["spot10_WBTC_mcap"].astype(float).replace(0, np.nan) * 100.0)
                    parts.append(p2)
                if parts:
                    import functools
                    w = functools.reduce(lambda a, b: a.add(b, fill_value=0), parts) / float(len(parts))
                else:
                    # 兜底：spot{1,10} nf24 原始归一 到 (0-1) 量级
                    col = "spot1_BTC_nf24" if _has_data("spot1_BTC_nf24") else "spot10_WBTC_nf24"
                    raw = macro[col].astype(float)
                    raw_abs_max = raw.abs().replace(0, np.nan).rolling(60 * 24, min_periods=2).max()
                    w = raw / raw_abs_max  # 归一 ±1
            # 3 日 = 72 小时 滚动 mean（FAIL-OPEN 自适应 min_periods）
            nonnull_count = int(w.notna().sum())
            mp_w3 = 2 if nonnull_count <= 10 else 8
            w3 = w.rolling(72, min_periods=mp_w3).mean()
            # FAIL-OPEN 同 btc_etf 尾段问题：w3 nonnull 只有 3 时 mp_std=2 会让首 1 个位置没 normed。
            #   nonnull_count <= 10 → mp_std 降为 1（w3 有值的位置必产出归一值，std=0 填 0 过 gate）
            #   注意：std 显式 ddof=0，因为 ddof=1 在 n=1 时返回 NaN（pandas 默认 ddof=1 样本 std）。
            w3_nn = int(w3.notna().sum())
            mp_std = 1 if w3_nn <= 10 else 24 * 7
            w3_std = w3.rolling(60 * 24, min_periods=mp_std).std(ddof=0)
            denom = w3_std.replace(0, np.nan)
            normed_raw = (w3 / denom).replace([np.inf, -np.inf], np.nan)
            normed = normed_raw.where(~w3_std.eq(0) | w3.isna(), 0.0)
            features["whale_netflow_pulse"] = normed

        # 2. exchange_btc_30d: 交易所 BTC 余额 30 日变动百分比
        #    兼容大小写：pn_ex_bal_BTC_chg30d_pct（旧名，B 大写）与 pn_ex_bal_btc_chg30d_pct（新名，小写）
        exch_cols = ("pn_ex_bal_BTC_chg30d_pct", "pn_ex_bal_btc_chg30d_pct")
        exch_has = next((c for c in exch_cols if _has_data(c)), None)
        if exch_has is not None and _feat_enabled("exchange_btc_30d"):
            features["exchange_btc_30d"] = macro[exch_has].astype(float)

        # 3. defi_breadth: DeFi 广度区间标签（0~3），直接透传
        #    兼容：首选 defi_breadth_currentRange（战略层 reader 精确名），退而用
        #    bb_*_range 或 pn_cycle_bottom_hit_ratio_pct（链上近似值，FAIL-OPEN 保底透传）。
        defi_col_options = ("defi_breadth_currentRange", "bb_defi_range_tag",
                            "blockbeats_signal_overall", "pn_cycle_sentiment_norm")
        defi_has = next((c for c in defi_col_options if _has_data(c)), None)
        if defi_has is not None and _feat_enabled("defi_breadth"):
            features["defi_breadth"] = macro[defi_has].astype(float)

        # 4. oi_liq_pressure: 多头爆仓压力（爆仓金额 / OI 总量，归一化 ±1σ）
        #    兼容精确列名（M/B 拆分）或 Panewslab pn_* 统一列（原始 USD 整数）。
        #    优先：pn_liq_atr_percentile_proxy（SQLite 已归一化代理）；否则用 raw 列计算 M/B 比。
        liq_pressure_cols_ok = (
            (_has_data("fut_liq_long_24h_usd_millions") and _has_data("fut_open_interest_usd_billions"))
            or (_has_data("pn_fut_liquidation_24h_usd") and _has_data("pn_fut_open_interest_usd"))
            or _has_data("pn_liq_atr_percentile_proxy")
            or (_has_data("pn_fut_long_liq_ratio") and _has_data("pn_leverage_ratio_oi_cap"))
        )
        if liq_pressure_cols_ok and _feat_enabled("oi_liq_pressure"):
            if _has_data("fut_liq_long_24h_usd_millions") and _has_data("fut_open_interest_usd_billions"):
                liq_long_M = macro["fut_liq_long_24h_usd_millions"].astype(float)
                oi_B = macro["fut_open_interest_usd_billions"].astype(float)
                ratio = (liq_long_M / oi_B.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
            elif _has_data("pn_liq_atr_percentile_proxy"):
                # SQLite reader 已计算好的 爆仓-ATR 百分位 proxy（直接透传，0-1 量纲 ≈ 压力百分位）
                ratio = macro["pn_liq_atr_percentile_proxy"].astype(float) * 1000.0
            elif _has_data("pn_fut_liquidation_24h_usd") and _has_data("pn_fut_open_interest_usd"):
                # pn_* 原始美元单位：24h 爆仓 (USD) / OI (USD) → 无量纲比，×1000 便于数量级可读
                liq_usd = macro["pn_fut_liquidation_24h_usd"].astype(float)
                oi_usd = macro["pn_fut_open_interest_usd"].astype(float)
                ratio = (liq_usd / oi_usd.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan) * 1000.0
            else:
                # fallback: long_liq_ratio（多空爆仓比）× leverage 作为压力近似（高杠杆 + 多头爆仓比 = 压力）
                lr = macro["pn_fut_long_liq_ratio"].astype(float)
                lev = macro["pn_leverage_ratio_oi_cap"].astype(float)
                ratio = (lr * lev * 100.0).replace([np.inf, -np.inf], np.nan)
            features["oi_liq_pressure"] = ratio

        # 5. btc_dom_delta: BTC 占比 % 的 1 日差分（= 24 bar diff）
        #    FAIL-OPEN：对齐后 nonnull 只有尾段 3-4 bars，diff(24) 会全 NaN。
        #    降级：nonnull < 30 时用 diff(1) 相邻 bar 差分（4 bars → 3 nonnull 差分，= 0 也 OK 过 gate）
        if _has_data("pn_btc_dominance_pct") and _feat_enabled("btc_dom_delta"):
            bd = macro["pn_btc_dominance_pct"].astype(float)
            bd_nn = int(bd.notna().sum())
            diff_period = 1 if bd_nn < 30 else 24
            features["btc_dom_delta"] = bd.diff(diff_period)

        # 填充 inf
        features = features.replace([np.inf, -np.inf], np.nan)

        # 特征质量预筛：有效值太少的列直接删除，避免无信息量列进入训练
        # - 旧 24 特征依赖 FGI/FR 等历史长数据 → 覆盖率通常 >50%（数千 bars）
        # - FAIL-OPEN 场景：Panewslab/BlockBeats pn_* 慢变量只在尾段 3-4 bars 非空（对齐严格无泄漏）
        #   → 派生的 13 新特征也只有 3-4 nonnull，若按 50% 硬闸会全被误删
        # 放宽标准：至少 3 bars 有效值（≈ FAIL-OPEN 尾段最小非空阈值）即可保留，
        # LGBM 原生支持 NaN，少量有效值的特征若对标签有区分度仍会被 LGBM 切分利用。
        if len(features) > 0:
            n_rows = len(features)
            min_valid = max(3, int(n_rows * 0.001))  # 3000 rows → 3 bars 即保留
            valid_counts = features.notna().sum()
            keep_cols = valid_counts[valid_counts >= min_valid].index.tolist()
            if len(keep_cols) < len(features.columns):
                dropped = [c for c in features.columns if c not in keep_cols]
                logger.debug(f"MacroFeatures: 删除低覆盖率列 {dropped} (min_valid={min_valid})")
                features = features[keep_cols]

        return features

    # ============================================================
    # 辅助方法
    # ============================================================

    @staticmethod
    def _zscore(series: pd.Series, window: int = 30) -> pd.Series:
        """滚动 z-score（FAIL-OPEN 安全：当滚动 std=0 时保留 0 而非 NaN，
        因为恒值表示「无偏离」，避免少数据场景因 ffill 同值被强制转 NaN 后被 gate 删除。）"""
        mean = series.rolling(window, min_periods=max(1, window // 3)).mean()
        std = series.rolling(window, min_periods=max(1, window // 3)).std()
        zero_std_mask = std.eq(0) & series.notna()
        # 先正常除（std=0 → NaN），再把 zero_std 位置填 0
        out = (series - mean) / std.replace(0, np.nan)
        out = out.where(~zero_std_mask, 0.0)
        return out

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
# [P2] YAML 配置加载函数 + 模块初始化调用
# ============================================================
def _load_yaml_config() -> bool:
    """从 _YAML_PATH 加载特征→维度映射。

    FAIL-OPEN：文件缺失/解析失败 → 返回 False，使用 _DEFAULT_FEATURE_TO_DIM。
    TC 可 monkeypatch macro_features._YAML_PATH 指向临时文件。
    """
    try:
        import yaml
        with open(_YAML_PATH, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        if not isinstance(raw, dict):
            raise ValueError(f"YAML root is {type(raw).__name__}, expected dict")
        features = raw.get("features")
        if not isinstance(features, dict):
            raise ValueError(f"'features' key is {type(features).__name__}, expected dict")

        new_map: Dict[str, str] = {}
        for k, v in features.items():
            if not isinstance(k, str) or not isinstance(v, str):
                logger.warning("macro_features.yaml bad entry: %r=%r, skipped", k, v)
                continue
            new_map[k] = v

        if not new_map:
            raise ValueError("YAML loaded but features dict is empty")

        MacroFeatures.FEATURE_TO_DIM = new_map
        MacroFeatures.ALL_FEATURES = list(new_map.keys())
        logger.info("macro_features.yaml loaded %d features", len(new_map))
        return True

    except FileNotFoundError:
        logger.warning("macro_features.yaml not found at %s, using defaults", _YAML_PATH)
    except Exception as e:
        logger.warning("macro_features.yaml parse error: %s, using defaults", e)

    # Fallback：用硬编码默认值
    MacroFeatures.FEATURE_TO_DIM = dict(_DEFAULT_FEATURE_TO_DIM)
    MacroFeatures.ALL_FEATURES = list(_DEFAULT_FEATURE_TO_DIM.keys())
    return False


# 模块 import 时自动加载一次（类定义 + 函数定义后）
_load_yaml_config()


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
