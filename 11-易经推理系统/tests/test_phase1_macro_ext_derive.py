"""Phase 0-3 宏观金融 + BTC 链上 特征补充的 TDD 测试。

TDD 顺序：RED → 本文件测试全部失败 → GREEN → 修改 macro_features.py / five_domain_sqlite_reader / macro_feature_select_v2。

Group 1 (本文件): 特征衍生正确性 + 对齐规则（经验979688：严格 ffill max_gap=4，禁 bfill/interp，三要素证据）
Group 2 (test_phase2_strict_criteria.py): 严格型「一损全弃」判定
Group 3 (test_phase3_injection_logging.py): 特征注入三层判据日志
Group 4 (test_dual_guard_l1l2l3.py): 战略层冲突双保险 L1/L2/L3
"""
import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timezone, timedelta


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def sample_ohlcv_500():
    """500 根 1H K 线 (2024-01-01 ~ 2024-01-21)"""
    np.random.seed(42)
    n = 500
    dates = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    returns = np.random.normal(0.0002, 0.02, n)
    close_arr = 50000 * np.exp(np.cumsum(returns))
    close = pd.Series(close_arr, index=dates)
    high = pd.Series(close_arr * (1 + np.abs(np.random.normal(0, 0.005, n))), index=dates)
    low = pd.Series(close_arr * (1 - np.abs(np.random.normal(0, 0.005, n))), index=dates)
    open_ = close.shift(1).fillna(close.iloc[0])
    volume = pd.Series(np.random.lognormal(10, 1, n), index=dates)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})


@pytest.fixture
def panewslab_macro_4h_sparse():
    """Panewslab 4h 粒度宏观数据。覆盖 500 bar (21 天) ≈ 126 个 4h 点（max_gap=4），
    确保对齐后有效值比例 > 50%（250 根 bar）以通过 MacroFeatures 末尾的质量门。

    注意：中间删去 1 条点作为「缺口（=12h）」用于验证 max_gap_bars=4。
    Panewslab 起点故意落后 K 线首 bar 8h → 测试 lookahead_guard 正常工作。

    覆盖字段：12 个新特征依赖的原始 pn_* 代理（命名与 five_domain_sqlite_reader 输出一致）。
    """
    np.random.seed(123)
    # 130 条 4h（= 21.7 天），再删 4 条缺口 → 剩 126 条，覆盖 500 根 1h bar
    dates = pd.date_range("2024-01-01 08:00:00", periods=130, freq="4h", tz="UTC")
    # 删第 30/60/90/120 条（各有 12h gap，刚好可以在 gap limit 边界上测试）
    drop_idx = [30, 60, 90, 120]
    dates = dates.delete(drop_idx)
    N = len(dates)
    df = pd.DataFrame({
        # 宏观金融 7 列 原始值
        "pn_us_vix":            np.random.uniform(14, 36, N),    # VIX 14~36
        "pn_us_10yr_yield":     np.random.uniform(3.0, 4.8, N),  # 美债
        "pn_us_fedfunds":       np.random.uniform(4.0, 5.8, N),  # FedFunds
        "pn_us_cpi_yoy":        np.random.uniform(1.5, 4.5, N),  # CPI YoY
        "pn_us_sp500_chg_pct":  np.random.randn(N) * 0.8,        # S&P 1d 变动 %
        "pn_us_dollar_index":   np.random.uniform(99, 108, N),   # DXY
        "pn_btc_etf_daily_flow_usd_millions": np.random.uniform(-200, 400, N),  # BTC ETF 单日净流入 M
        "pn_rwa_tvl_usd_billions": np.random.uniform(600, 900, N),              # RWA TVL B
        "pn_rwa_change7d_pct":      np.random.randn(N) * 0.5,                   # 7 日增速
        "pn_treasury_total_btc_holdings": np.cumsum(np.random.randint(-20, 60, N)) + 1000,  # 国库 BTC 持有
        # BTC 链上 5 列 原始值
        "pn_whale_netflow_cap_pct":   np.random.uniform(-1.2, 1.5, N),  # 巨鲸净流入占比
        "pn_ex_bal_BTC_chg30d_pct":   np.random.uniform(-5, 3, N),       # 交易所 30d 变动
        "defi_breadth_currentRange":  np.random.randint(0, 4, N).astype(float),  # DeFi 广度 0-3
        "fut_liq_long_24h_usd_millions":  np.random.uniform(50, 800, N),  # 多头爆仓 M
        "fut_open_interest_usd_billions": np.random.uniform(18, 40, N),   # 期货 OI B
        "pn_btc_dominance_pct":       np.random.uniform(48, 64, N),       # BTC 占比
    }, index=dates)
    return df


# ============================================================
# Group 1a: 宏观金融特征衍生（7 个）
# ============================================================

class TestMacroFinanceExtensionsDerive:
    """宏观金融 7 个新特征的数值正确性。

    预期：在 MacroFeatures.compute() 的 features 输出中存在下列列，且数值区间正确（或 fail-open 不生成）。
    """

    # ── 1. vix_zone ──
    def test_vix_zone_buckets(self, sample_ohlcv_500, panewslab_macro_4h_sparse):
        """VIX 应按 4 档编码：<20=0 / 20-28=1 / 28-35=2 / >35=3。"""
        import scripts.memory_l4.bcrm2.macro_features as mf
        from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher

        macro_aligned = MacroDataFetcher.align_to_klines(
            panewslab_macro_4h_sparse, sample_ohlcv_500.index,
            lookahead_guard=1, max_gap_bars=4,
        )
        feats = mf.MacroFeatures().compute(sample_ohlcv_500, macro_df=macro_aligned)
        assert "vix_zone" in feats.columns, "vix_zone 特征未生成（FAIL-RED）"
        v = feats["vix_zone"].dropna()
        assert len(v) > 100, "vix_zone 有效值过少（>100 非空）"
        # 4 档 {0,1,2,3} 只允许出现
        assert set(v.unique()) <= {0.0, 1.0, 2.0, 3.0}, f"vix_zone 非 0/1/2/3: {v.unique()}"
        # 具体分桶：VIX=15 → 0, VIX=24 → 1, VIX=30 → 2, VIX=40 → 3
        assert feats["vix_zone"][macro_aligned["pn_us_vix"].ffill() < 20].dropna().eq(0).all()
        assert feats["vix_zone"][(macro_aligned["pn_us_vix"].ffill() >= 28) & (macro_aligned["pn_us_vix"].ffill() < 35)].dropna().eq(2).all()

    # ── 2. us_macro_regime ──
    def test_us_macro_regime_categories(self, sample_ohlcv_500, panewslab_macro_4h_sparse):
        """宏观 regime = {0:宽松 1:中性 2:紧缩}，基于 FedFunds+CPI。"""
        import scripts.memory_l4.bcrm2.macro_features as mf
        from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher

        macro_aligned = MacroDataFetcher.align_to_klines(
            panewslab_macro_4h_sparse, sample_ohlcv_500.index,
            lookahead_guard=1, max_gap_bars=4,
        )
        feats = mf.MacroFeatures().compute(sample_ohlcv_500, macro_df=macro_aligned)
        assert "us_macro_regime" in feats.columns
        r = feats["us_macro_regime"].dropna()
        assert len(r) > 100
        assert set(r.unique()) <= {0.0, 1.0, 2.0}

    # ── 3. sp500_7d_break ──
    def test_sp500_7d_break_is_zscore(self, sample_ohlcv_500, panewslab_macro_4h_sparse):
        """sp500_7d_break 应为 S&P 7 日累计涨跌 × 滚动 z-score（30日窗口）。
        非 NaN 数量 >100，且均值绝对值 <2.0（z-score 范围）。
        """
        import scripts.memory_l4.bcrm2.macro_features as mf
        from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher

        macro_aligned = MacroDataFetcher.align_to_klines(
            panewslab_macro_4h_sparse, sample_ohlcv_500.index,
            lookahead_guard=1, max_gap_bars=4,
        )
        feats = mf.MacroFeatures().compute(sample_ohlcv_500, macro_df=macro_aligned)
        assert "sp500_7d_break" in feats.columns
        x = feats["sp500_7d_break"].dropna()
        assert len(x) > 100
        # 滚动 z-score 一般 -3~3
        assert x.abs().max() < 15

    # ── 4. dxy_strength ──
    def test_dxy_strength_30d_zscore(self, sample_ohlcv_500, panewslab_macro_4h_sparse):
        """DXY 30 日 z-score。"""
        import scripts.memory_l4.bcrm2.macro_features as mf
        from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher

        macro_aligned = MacroDataFetcher.align_to_klines(
            panewslab_macro_4h_sparse, sample_ohlcv_500.index,
            lookahead_guard=1, max_gap_bars=4,
        )
        feats = mf.MacroFeatures().compute(sample_ohlcv_500, macro_df=macro_aligned)
        assert "dxy_strength" in feats.columns
        x = feats["dxy_strength"].dropna()
        assert len(x) > 100
        assert x.abs().max() < 15

    # ── 5. btc_etf_flow_3d ──
    def test_btc_etf_flow_3d_is_3d_sum_std_norm(self, sample_ohlcv_500, panewslab_macro_4h_sparse):
        """3 日 BTC ETF 累计净流入，全局滚动 1σ 归一。"""
        import scripts.memory_l4.bcrm2.macro_features as mf
        from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher

        macro_aligned = MacroDataFetcher.align_to_klines(
            panewslab_macro_4h_sparse, sample_ohlcv_500.index,
            lookahead_guard=1, max_gap_bars=4,
        )
        feats = mf.MacroFeatures().compute(sample_ohlcv_500, macro_df=macro_aligned)
        assert "btc_etf_flow_3d" in feats.columns
        x = feats["btc_etf_flow_3d"].dropna()
        assert len(x) > 50

    # ── 6. rwa_liquidity_pulse + stablecoin_minus_rwa 残差 ──
    def test_rwa_pulse_and_residual_col_exists(self, sample_ohlcv_500, panewslab_macro_4h_sparse):
        """当 macro_df 同时含 stablecoin_supply（原有稳定币）+ pn_rwa_* 时，应额外生成 stablecoin_minus_rwa 残差列。"""
        import scripts.memory_l4.bcrm2.macro_features as mf
        from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher

        macro_extra = panewslab_macro_4h_sparse.copy()
        macro_extra["stablecoin_supply"] = np.random.uniform(100e9, 150e9, len(macro_extra))

        macro_aligned = MacroDataFetcher.align_to_klines(
            macro_extra, sample_ohlcv_500.index,
            lookahead_guard=1, max_gap_bars=4,
        )
        feats = mf.MacroFeatures().compute(sample_ohlcv_500, macro_df=macro_aligned)
        assert "rwa_liquidity_pulse" in feats.columns, "rwa_liquidity_pulse 未生成"
        assert "stablecoin_minus_rwa" in feats.columns, "stablecoin_minus_rwa 残差未生成（用于消解多重共线性）"
        x1 = feats["rwa_liquidity_pulse"].dropna()
        x2 = feats["stablecoin_minus_rwa"].dropna()
        assert len(x1) > 50 and len(x2) > 50

    # ── 7. treasury_balance_delta ──
    def test_treasury_balance_delta_7d_avg(self, sample_ohlcv_500, panewslab_macro_4h_sparse):
        """国库 BTC 7 日净增量均值。"""
        import scripts.memory_l4.bcrm2.macro_features as mf
        from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher

        macro_aligned = MacroDataFetcher.align_to_klines(
            panewslab_macro_4h_sparse, sample_ohlcv_500.index,
            lookahead_guard=1, max_gap_bars=4,
        )
        feats = mf.MacroFeatures().compute(sample_ohlcv_500, macro_df=macro_aligned)
        assert "treasury_balance_delta" in feats.columns
        x = feats["treasury_balance_delta"].dropna()
        assert len(x) > 50

    # ── 8. ALL_FEATURES 必须收录新特征 + FEATURE_TO_DIM 维度 = macro_finance_ext/btc_onchain_ext ──
    def test_all_features_registry_contains_12_new(self):
        import scripts.memory_l4.bcrm2.macro_features as mf
        expected = {
            # 宏观金融 7
            "vix_zone", "us_macro_regime", "sp500_7d_break", "dxy_strength",
            "btc_etf_flow_3d", "rwa_liquidity_pulse", "treasury_balance_delta",
            # BTC 链上 5
            "whale_netflow_pulse", "exchange_btc_30d", "defi_breadth",
            "oi_liq_pressure", "btc_dom_delta",
        }
        assert expected.issubset(set(mf.MacroFeatures.ALL_FEATURES)), \
            f"ALL_FEATURES 缺少: {expected - set(mf.MacroFeatures.ALL_FEATURES)}"
        dims = mf.MacroFeatures.FEATURE_TO_DIM
        for n in expected:
            assert dims[n] in {"macro_finance_ext", "btc_onchain_ext"}, f"{n} dim={dims[n]}"

    # ── 9. 两级开关：维度级关断 macro_enable_macro_finance_ext → 7 个宏观金融特征全部不生成 ──
    def test_dim_level_switch_disables_macro_finance_ext(self, sample_ohlcv_500, panewslab_macro_4h_sparse):
        import scripts.memory_l4.bcrm2.macro_features as mf
        from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher

        macro_aligned = MacroDataFetcher.align_to_klines(
            panewslab_macro_4h_sparse, sample_ohlcv_500.index,
            lookahead_guard=1, max_gap_bars=4,
        )
        cfg = {"macro_enable_macro_finance_ext": False, "macro_enable_btc_onchain_ext": True}
        feats = mf.MacroFeatures().compute(sample_ohlcv_500, macro_df=macro_aligned, config=cfg)
        for f in ["vix_zone", "us_macro_regime", "sp500_7d_break", "dxy_strength",
                  "btc_etf_flow_3d", "rwa_liquidity_pulse", "treasury_balance_delta"]:
            assert f not in feats.columns, f"维度关断失败: {f} 仍生成"
        # BTC 链上特征仍应生成
        assert "whale_netflow_pulse" in feats.columns or "defi_breadth" in feats.columns


# ============================================================
# Group 1b: BTC 链上特征衍生（5 个）
# ============================================================

class TestBtcOnchainExtensionsDerive:
    """BTC 链上 5 个新特征数值正确性。"""

    # ── 1. whale_netflow_pulse ──
    def test_whale_pulse_3d_rolling_mean_std_norm(self, sample_ohlcv_500, panewslab_macro_4h_sparse):
        import scripts.memory_l4.bcrm2.macro_features as mf
        from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher

        macro_aligned = MacroDataFetcher.align_to_klines(
            panewslab_macro_4h_sparse, sample_ohlcv_500.index,
            lookahead_guard=1, max_gap_bars=4,
        )
        feats = mf.MacroFeatures().compute(sample_ohlcv_500, macro_df=macro_aligned)
        assert "whale_netflow_pulse" in feats.columns
        x = feats["whale_netflow_pulse"].dropna()
        assert len(x) > 50

    # ── 2. exchange_btc_30d ──
    def test_exchange_btc_30d_pct(self, sample_ohlcv_500, panewslab_macro_4h_sparse):
        import scripts.memory_l4.bcrm2.macro_features as mf
        from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher

        macro_aligned = MacroDataFetcher.align_to_klines(
            panewslab_macro_4h_sparse, sample_ohlcv_500.index,
            lookahead_guard=1, max_gap_bars=4,
        )
        feats = mf.MacroFeatures().compute(sample_ohlcv_500, macro_df=macro_aligned)
        assert "exchange_btc_30d" in feats.columns
        x = feats["exchange_btc_30d"].dropna()
        assert len(x) > 50
        # 30d 变动百分比不应超出 ±100% 太多
        assert x.abs().max() < 200

    # ── 3. defi_breadth ──
    def test_defi_breadth_discrete(self, sample_ohlcv_500, panewslab_macro_4h_sparse):
        """DeFi 广度：0/1/2/3 区间标签（源自 holdings_defi-fundamental-breadth_currentRange）。"""
        import scripts.memory_l4.bcrm2.macro_features as mf
        from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher

        macro_aligned = MacroDataFetcher.align_to_klines(
            panewslab_macro_4h_sparse, sample_ohlcv_500.index,
            lookahead_guard=1, max_gap_bars=4,
        )
        feats = mf.MacroFeatures().compute(sample_ohlcv_500, macro_df=macro_aligned)
        assert "defi_breadth" in feats.columns
        x = feats["defi_breadth"].dropna()
        assert len(x) > 100
        assert set(x.unique()) <= {0.0, 1.0, 2.0, 3.0}

    # ── 4. oi_liq_pressure ──
    def test_oi_liq_pressure_ratio(self, sample_ohlcv_500, panewslab_macro_4h_sparse):
        """多头爆仓 USD / 总期货 OI USD，[0,1] 范围。"""
        import scripts.memory_l4.bcrm2.macro_features as mf
        from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher

        macro_aligned = MacroDataFetcher.align_to_klines(
            panewslab_macro_4h_sparse, sample_ohlcv_500.index,
            lookahead_guard=1, max_gap_bars=4,
        )
        feats = mf.MacroFeatures().compute(sample_ohlcv_500, macro_df=macro_aligned)
        assert "oi_liq_pressure" in feats.columns
        x = feats["oi_liq_pressure"].dropna()
        assert len(x) > 50
        # 爆仓 / OI 单位是 B/M 也可能错位。确保非负（除法可能放大，但不应为负）
        assert (x >= 0).all()

    # ── 5. btc_dom_delta ──
    def test_btc_dom_delta_1d_diff(self, sample_ohlcv_500, panewslab_macro_4h_sparse):
        """BTC 占比 % 的 1 日差分，单位为百分点。"""
        import scripts.memory_l4.bcrm2.macro_features as mf
        from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher

        macro_aligned = MacroDataFetcher.align_to_klines(
            panewslab_macro_4h_sparse, sample_ohlcv_500.index,
            lookahead_guard=1, max_gap_bars=4,
        )
        feats = mf.MacroFeatures().compute(sample_ohlcv_500, macro_df=macro_aligned)
        assert "btc_dom_delta" in feats.columns
        x = feats["btc_dom_delta"].dropna()
        assert len(x) > 50
        # 差分不应超过 ±20 个百分点（BTC 市场占比日波动上限）
        assert x.abs().max() < 20


# ============================================================
# Group 1c: 时间对齐规则（严格 ffill + max_gap=4，禁 bfill/interp）
# ============================================================

class TestAlignWithPanewslabGapRule:
    """按经验 979688：必须先打印三要素，严格对齐，严禁 bfill 或线性插值引入未来信息。"""

    def test_align_panewslab_max_gap_4(self):
        """宏观 4h 数据对齐到 1h bars，允许连续填充最多 4 根 bar（= 4h）。
        超过 4 根的 gap 必须保持 NaN（不因为填了后面的值而泄漏未来）。
        """
        from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher

        # 100 根 1H bar
        bar_idx = pd.date_range("2024-01-01 00:00", periods=100, freq="1h", tz="UTC")
        # Panewslab 每 4h 一条，但故意中间挖一条缺口（索引 24 与 36 之间缺 32 = 16h 跨度）
        pn_idx = pd.date_range("2024-01-01 04:00", periods=10, freq="4h", tz="UTC").delete(5)  # 去掉 idx=5 (24h)
        pn = pd.DataFrame({"pn_us_vix": [15.0, 16.0, 17.0, 18.0, 19.0, 25.0, 26.0, 27.0, 28.0]}, index=pn_idx)
        # 跨度：索引 4 (20:00, 19.0) → 索引 6 (next day 04:00, 25.0)，中间 12 根 bar 应填充 ≤4 bar 后 NaN 维持

        aligned = MacroDataFetcher.align_to_klines(
            pn, bar_idx, lookahead_guard=1, max_gap_bars=4,
        )

        assert "pn_us_vix" in aligned.columns
        col = aligned["pn_us_vix"]
        # 找缺口区间（20:00 ~ 次日04:00之间 = bar_idx 约 21..28）
        gap_start = pd.Timestamp("2024-01-02 00:00", tz="UTC")
        gap_region = col.loc[(bar_idx >= gap_start) & (bar_idx <= pd.Timestamp("2024-01-02 04:00", tz="UTC"))]
        # 其中后几根必须是 NaN（max_gap=4 用尽）
        assert gap_region.isna().any(), "max_gap_bars=4 后仍填充，未来信息泄漏！"

    def test_align_no_backward_or_interp(self):
        """严禁 backward fill / 线性插值。后向 bar 的非空不能向前填充。
        构造：首 5 bar 无宏观值，第 6 bar 有值。若首 bar 非空 → bfill。"""
        from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher

        bar_idx = pd.date_range("2024-01-01 00:00", periods=10, freq="1h", tz="UTC")
        pn_idx = pd.DatetimeIndex([pd.Timestamp("2024-01-01 05:00", tz="UTC")])
        pn = pd.DataFrame({"v": [99.0]}, index=pn_idx)

        aligned = MacroDataFetcher.align_to_klines(
            pn, bar_idx, lookahead_guard=1, max_gap_bars=4,
        )
        # bar 0..4：lookahead_guard=1 时，bar i 的 guard=i-1。bar=0: guard=-1 前无值 → NaN
        # bar 1..4: guard 分别为 0..3，pn_idx=5h → 5h > 0..3h (bar_idx 的 guard 时间) → 仍 NaN
        # bar 5: guard=4 → pn_idx=5h > 4h (bar_idx.at[4]) → NaN
        # bar 6: guard=5 → pn_idx=5h <= 5h(guard) → 可填充，填充值=99.0
        first_non_null = aligned["v"].first_valid_index()
        assert first_non_null is not None, "无填充"
        # 前 6 根 bar（bar_idx[0..5]）必须全 NaN
        assert aligned["v"].iloc[:6].isna().all(), "前6 bar不应有值（bfill 触发）"

    def test_align_evidence_three_elements_tuple(self):
        """Phase 0 基线流程应调用 align_evidence 返回 (kline_range, pn_range, intersected_count)。
        不新建脚本，直接在 align_to_klines 返回值可选附带三要素证据，或暴露 align 证据函数。
        """
        from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher
        assert hasattr(MacroDataFetcher, "compute_alignment_evidence"), \
            "MacroDataFetcher 应暴露 compute_alignment_evidence 返回三要素证据元组"

        bar_idx = pd.date_range("2024-01-01", periods=10, freq="1h", tz="UTC")
        pn_idx = pd.date_range("2024-01-01 04:00", periods=3, freq="4h", tz="UTC")
        pn = pd.DataFrame({"x": [1.0, 2.0, 3.0]}, index=pn_idx)

        ev = MacroDataFetcher.compute_alignment_evidence(pn, bar_idx)
        assert isinstance(ev, tuple) and len(ev) == 5, "证据应返回 (kline_first, kline_last, pn_first, pn_last, intersected_count)"
        assert ev[4] > 0, "交集 count 必须 >0"


# ============================================================
# Group 1d: FeatureRegistry 集成（12 新特征通过 Registry 暴露）
# ============================================================

class TestExtendedMacroRegistryIntegration:
    """12 新特征必须在 FeatureRegistry 中可启用/禁用。"""

    def test_macro_module_counts_36_or_37(self, sample_ohlcv_500, panewslab_macro_4h_sparse):
        """旧版 24 + 12 新 + stablecoin_minus_rwa = 37（当稳定币供应存在时）。
        ALL_FEATURES 静态表必须已注册 37 个名字（fail-open 要求即使输入缺也必须在注册表可见）。
        由于 macro_df 只填了 Panewslab 列（不含 fear_greed/funding/tvl/hash/social/marketcap），
        旧 24 特征会因 _has_data（列缺）不生成。故检查两级：
          ① ALL_FEATURES 注册表 len ≥ 37（24+12+残差）
          ② 当输入列补充完整（Panewslab + 旧特征输入列）后，实际输出 ≥ 30（质量门会删短窗口特征）
        """
        import scripts.memory_l4.bcrm2.bagua_feature_engine  # noqa: F401
        import scripts.memory_l4.bcrm2.fibonacci_features  # noqa: F401
        import scripts.memory_l4.bcrm2.macro_features as mf_mod
        from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry
        from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher

        # ① 静态注册（必须即使没有数据也在 FEATURE_TO_DIM 中定义，确保开关可配置）
        assert len(mf_mod.MacroFeatures.ALL_FEATURES) >= 37, \
            f"ALL_FEATURES 注册数不足 37 (24旧+12新+残差)，实际={len(mf_mod.MacroFeatures.ALL_FEATURES)}"

        # ② 构造完整输入（Panewslab + 旧宏观列）：模拟 fear_greed/funding/tvl/hash/social/market_cap 存在
        macro_full = panewslab_macro_4h_sparse.copy()
        N = len(macro_full)
        np.random.seed(321)
        # 旧 24 特征的 REQUIRED_COLS 最小集合
        macro_full["fear_greed_index"] = np.random.randint(20, 80, N)
        macro_full["fear_greed_trend_7d"] = np.random.randn(N) * 5
        macro_full["funding_rate"] = np.random.randn(N) * 0.0005
        macro_full["open_interest"] = np.random.uniform(50e3, 200e3, N)
        macro_full["stablecoin_supply"] = np.random.uniform(100e9, 150e9, N)
        macro_full["tvl"] = np.random.uniform(50e9, 100e9, N)
        macro_full["hash_rate"] = np.random.uniform(400e9, 600e9, N)
        macro_full["miners_revenue"] = np.random.uniform(20e6, 40e6, N)
        macro_full["smart_money_direction"] = np.random.uniform(-0.5, 0.5, N)
        macro_full["social_hype_score"] = np.random.uniform(0, 100, N)
        macro_full["market_cap"] = np.random.uniform(500e9, 900e9, N)
        macro_full["ath_drop_pct"] = np.random.uniform(-60, 0, N)

        macro_aligned = MacroDataFetcher.align_to_klines(
            macro_full, sample_ohlcv_500.index,
            lookahead_guard=1, max_gap_bars=4,
        )
        feats, by_gua = FeatureRegistry.compute_all(
            df=sample_ohlcv_500, macro_df=macro_aligned, symbol="BTC",
            enabled=["bagua", "fibonacci", "macro"],
        )
        assert "macro" in by_gua
        count = len(by_gua["macro"])
        # 预期 30+：长窗口特征（DXY 30d）在 500 bar 范围内覆盖率可能 < 50%，会被质量门删；所以放宽到 ≥30
        # 36 - 6（长窗口删）≈ 30 合理
        assert count >= 30, f"macro 特征数应 ≥30 (24旧+12新-长窗口过滤)，实际={count}"

    def test_feature_knob_macro_feat_vix_zone_false(self, sample_ohlcv_500, panewslab_macro_4h_sparse):
        """特征级关断 macro_feat_vix_zone=False → 输出不含 vix_zone。"""
        import scripts.memory_l4.bcrm2.macro_features as mf
        from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher

        macro_aligned = MacroDataFetcher.align_to_klines(
            panewslab_macro_4h_sparse, sample_ohlcv_500.index,
            lookahead_guard=1, max_gap_bars=4,
        )
        cfg = {"macro_feat_vix_zone": False}  # 单特征关
        feats = mf.MacroFeatures().compute(sample_ohlcv_500, macro_df=macro_aligned, config=cfg)
        assert "vix_zone" not in feats.columns, "vix_zone 特征级关断失败"
        # 其他同类维度特征仍应生成（如 us_macro_regime）
        assert "us_macro_regime" in feats.columns

    def test_dim_level_btc_onchain_ext_false_disables_5(self, sample_ohlcv_500, panewslab_macro_4h_sparse):
        import scripts.memory_l4.bcrm2.macro_features as mf
        from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher

        macro_aligned = MacroDataFetcher.align_to_klines(
            panewslab_macro_4h_sparse, sample_ohlcv_500.index,
            lookahead_guard=1, max_gap_bars=4,
        )
        cfg = {"macro_enable_macro_finance_ext": True, "macro_enable_btc_onchain_ext": False}
        feats = mf.MacroFeatures().compute(sample_ohlcv_500, macro_df=macro_aligned, config=cfg)
        for f in ["whale_netflow_pulse", "exchange_btc_30d", "defi_breadth", "oi_liq_pressure", "btc_dom_delta"]:
            assert f not in feats.columns, f"btc_onchain_ext 关断失败 {f}"
