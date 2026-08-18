"""MacroFeatures + MacroDataFetcher 单元测试

测试覆盖:
1. align_to_klines 时间对齐 + 未来函数防护
2. MacroFeatures 完整宏观数据计算
3. MacroFeatures 缺失数据处理
4. MacroFeatures 部分缺失数据处理
5. FeatureRegistry 集成（macro 模块注册）
"""
import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timezone, timedelta


# ============================================================
# 测试数据 fixtures
# ============================================================

@pytest.fixture
def sample_ohlcv():
    """500根1H K线"""
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
def sample_macro_df():
    """模拟宏观数据（每日频率，覆盖K线时间范围）"""
    np.random.seed(123)
    dates = pd.date_range("2024-01-01", periods=25, freq="1D", tz="UTC")
    return pd.DataFrame({
        "fear_greed_index": np.random.randint(20, 80, 25),
        "fear_greed_trend_7d": np.random.randn(25) * 5,
        "funding_rate": np.random.randn(25) * 0.0005,
        "stablecoin_supply": np.random.uniform(100e9, 150e9, 25),
        "tvl": np.random.uniform(50e9, 100e9, 25),
        "hash_rate": np.random.uniform(400e9, 600e9, 25),
        "miners_revenue": np.random.uniform(20e6, 40e6, 25),
        "smart_money_direction": np.random.uniform(-0.5, 0.5, 25),
        "social_hype_score": np.random.uniform(0, 100, 25),
        "market_cap": np.random.uniform(500e9, 900e9, 25),
        "ath_drop_pct": np.random.uniform(-60, 0, 25),
    }, index=dates)


# ============================================================
# 测试 align_to_klines 时间对齐
# ============================================================

class TestAlignToKlines:
    """测试宏观数据对齐到K线时间戳"""

    def test_basic_alignment(self, sample_ohlcv, sample_macro_df):
        """基本对齐：宏观数据应被 forward-fill 到K线时间戳"""
        from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher

        aligned = MacroDataFetcher.align_to_klines(
            sample_macro_df, sample_ohlcv.index, lookahead_guard=1
        )
        assert len(aligned) == len(sample_ohlcv)
        # 应该有宏观数据列
        assert "fear_greed_index" in aligned.columns

    def test_lookahead_guard_prevents_future_data(self):
        """未来函数防护：宏观数据时间戳等于K线时间戳时不应被使用"""
        from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher

        # 创建K线时间戳（1H频率）
        kline_idx = pd.date_range("2024-01-01 00:00", periods=10, freq="1h", tz="UTC")
        # 创建宏观数据：时间戳与K线完全对齐
        macro_data = pd.DataFrame(
            {"value": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]},
            index=kline_idx.copy()
        )

        aligned = MacroDataFetcher.align_to_klines(
            macro_data, kline_idx, lookahead_guard=1
        )

        # 第0根K线：宏观数据时间戳等于K线时间戳，减去guard后为前1h，无数据 → NaN
        assert pd.isna(aligned["value"].iloc[0])
        # 第1根K线：guard后为第0根K线时间，对应宏观数据 value=10
        assert aligned["value"].iloc[1] == 10.0
        # 第2根K线：guard后为第1根K线时间，对应宏观数据 value=20
        assert aligned["value"].iloc[2] == 20.0

    def test_daily_macro_to_hourly_klines(self):
        """日级宏观数据对齐到小时级K线"""
        from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher

        # 3天的K线（72根1H）
        kline_idx = pd.date_range("2024-01-01 00:00", periods=72, freq="1h", tz="UTC")
        # 日级宏观数据（3天）
        macro_idx = pd.date_range("2024-01-01 00:00", periods=3, freq="1D", tz="UTC")
        macro_data = pd.DataFrame(
            {"fgi": [50.0, 60.0, 70.0]},
            index=macro_idx
        )

        aligned = MacroDataFetcher.align_to_klines(
            macro_data, kline_idx, lookahead_guard=1
        )

        # 第0根K线（1/1 00:00）：guard后为12/31 23:00，无宏观数据 → NaN
        assert pd.isna(aligned["fgi"].iloc[0])
        # 第1根K线（1/1 01:00）：guard后为1/1 00:00 → FGI=50
        assert aligned["fgi"].iloc[1] == 50.0
        # 第24根K线（1/2 00:00）：guard后为1/1 23:00 → FGI=50（forward-fill）
        assert aligned["fgi"].iloc[24] == 50.0
        # 第25根K线（1/2 01:00）：guard后为1/2 00:00 → FGI=60
        assert aligned["fgi"].iloc[25] == 60.0

    def test_empty_macro_returns_empty(self, sample_ohlcv):
        """空宏观数据应返回空DataFrame"""
        from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher

        empty_macro = pd.DataFrame()
        aligned = MacroDataFetcher.align_to_klines(
            empty_macro, sample_ohlcv.index, lookahead_guard=1
        )
        assert len(aligned) == len(sample_ohlcv)
        assert len(aligned.columns) == 0


# ============================================================
# 测试 MacroFeatures 特征计算
# ============================================================

class TestMacroFeatures:
    """测试宏观特征模块"""

    def test_full_macro_data(self, sample_ohlcv, sample_macro_df):
        """完整宏观数据应生成25个特征"""
        from scripts.memory_l4.bcrm2.macro_features import MacroFeatures
        from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher

        # 对齐宏观数据到K线
        macro_aligned = MacroDataFetcher.align_to_klines(
            sample_macro_df, sample_ohlcv.index, lookahead_guard=1
        )

        mf = MacroFeatures()
        features = mf.compute(sample_ohlcv, macro_df=macro_aligned)

        # 应有25个特征
        assert len(features.columns) == 25
        # 索引应与K线一致
        assert len(features) == len(sample_ohlcv)

        # 检查关键特征存在
        expected_cols = [
            "fgi_zscore", "fgi_extreme_fear", "fgi_extreme_greed", "fgi_divergence",
            "funding_rate_zscore", "funding_extreme_positive", "funding_extreme_negative",
            "stablecoin_growth", "liquidity_expanding", "tvl_change_7d",
            "hash_rate_trend", "miners_revenue_zscore", "miner_accumulation",
            "smart_money_direction", "social_hype_zscore", "hype_extreme",
            "market_cap_rank", "ath_drop_pct", "undervalued", "supply_ratio",
        ]
        for col in expected_cols:
            assert col in features.columns, f"缺少特征: {col}"

    def test_missing_macro_returns_empty(self, sample_ohlcv):
        """宏观数据缺失时应返回空DataFrame"""
        from scripts.memory_l4.bcrm2.macro_features import MacroFeatures

        mf = MacroFeatures()
        features = mf.compute(sample_ohlcv, macro_df=None)
        assert len(features.columns) == 0
        assert len(features) == len(sample_ohlcv)

        features_empty = mf.compute(sample_ohlcv, macro_df=pd.DataFrame())
        assert len(features_empty.columns) == 0

    def test_partial_macro_data(self, sample_ohlcv):
        """部分宏观数据缺失时，已有部分应正常计算，缺失部分为NaN"""
        from scripts.memory_l4.bcrm2.macro_features import MacroFeatures

        # 只有 FGI 和 funding_rate，没有其他
        partial_macro = pd.DataFrame(
            {
                "fear_greed_index": np.random.randint(20, 80, len(sample_ohlcv)),
                "funding_rate": np.random.randn(len(sample_ohlcv)) * 0.0005,
            },
            index=sample_ohlcv.index
        )

        mf = MacroFeatures()
        features = mf.compute(sample_ohlcv, macro_df=partial_macro)

        # 仍有25列
        assert len(features.columns) == 25
        # FGI 相关特征有值
        assert not features["fgi_extreme_fear"].isna().all()
        # hash_rate 相关特征全 NaN
        assert features["hash_rate_trend"].isna().all()
        assert features["miners_revenue_zscore"].isna().all()

    def test_no_inf_values(self, sample_ohlcv, sample_macro_df):
        """特征中不应有 inf 值"""
        from scripts.memory_l4.bcrm2.macro_features import MacroFeatures
        from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher

        macro_aligned = MacroDataFetcher.align_to_klines(
            sample_macro_df, sample_ohlcv.index, lookahead_guard=1
        )
        mf = MacroFeatures()
        features = mf.compute(sample_ohlcv, macro_df=macro_aligned)

        # 不应有 inf
        inf_count = np.isinf(features.select_dtypes(include=[np.number]).values).sum()
        assert inf_count == 0, f"发现 {inf_count} 个 inf 值"

    def test_extreme_fear_greed_binary(self, sample_ohlcv):
        """fgi_extreme_fear 和 fgi_extreme_greed 应为 0/1"""
        from scripts.memory_l4.bcrm2.macro_features import MacroFeatures

        macro = pd.DataFrame(
            {"fear_greed_index": [10, 80, 50, 20, 90, 30, 70, 25, 75, 15] * 50},
            index=sample_ohlcv.index
        )
        mf = MacroFeatures()
        features = mf.compute(sample_ohlcv, macro_df=macro)

        # extreme_fear 应在 FGI < 25 时为 1
        fear_mask = macro["fear_greed_index"] < 25
        if fear_mask.any():
            fear_vals = features.loc[fear_mask, "fgi_extreme_fear"]
            assert (fear_vals == 1.0).all()

        # extreme_greed 应在 FGI > 75 时为 1
        greed_mask = macro["fear_greed_index"] > 75
        if greed_mask.any():
            greed_vals = features.loc[greed_mask, "fgi_extreme_greed"]
            assert (greed_vals == 1.0).all()


# ============================================================
# 测试 FeatureRegistry 集成
# ============================================================

class TestMacroRegistryIntegration:
    """测试 macro 模块在 FeatureRegistry 中的注册和调用"""

    def test_macro_module_registered(self):
        """macro 模块应已注册"""
        import scripts.memory_l4.bcrm2.macro_features  # noqa: F401
        from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry

        modules = FeatureRegistry.list_modules()
        assert "macro" in modules

    def test_macro_requires_macro_df(self):
        """macro 模块的 spec 应设置 requires_macro_df=True"""
        import scripts.memory_l4.bcrm2.macro_features  # noqa: F401
        from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry

        spec = FeatureRegistry.get_spec("macro")
        assert spec is not None
        assert spec.requires_macro_df is True

    def test_compute_all_with_macro(self, sample_ohlcv, sample_macro_df):
        """FeatureRegistry.compute_all 传入 macro_df 后应包含宏观特征"""
        import scripts.memory_l4.bcrm2.bagua_feature_engine  # noqa: F401
        import scripts.memory_l4.bcrm2.fibonacci_features  # noqa: F401
        import scripts.memory_l4.bcrm2.macro_features  # noqa: F401
        from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry
        from scripts.memory_l4.bcrm2.macro_data_fetcher import MacroDataFetcher

        macro_aligned = MacroDataFetcher.align_to_klines(
            sample_macro_df, sample_ohlcv.index, lookahead_guard=1
        )

        features, feat_by_gua = FeatureRegistry.compute_all(
            df=sample_ohlcv,
            macro_df=macro_aligned,
            symbol="BTC",
            enabled=["bagua", "fibonacci", "macro"],
        )

        # macro 特征应在 feat_by_gua 中
        assert "macro" in feat_by_gua
        assert len(feat_by_gua["macro"]) == 25

        # 特征 DataFrame 中应包含宏观特征列
        assert "fgi_zscore" in features.columns
        assert "funding_rate_zscore" in features.columns

    def test_compute_all_skips_macro_when_missing(self, sample_ohlcv):
        """macro_df 缺失时应跳过 macro 模块"""
        import scripts.memory_l4.bcrm2.bagua_feature_engine  # noqa: F401
        import scripts.memory_l4.bcrm2.fibonacci_features  # noqa: F401
        import scripts.memory_l4.bcrm2.macro_features  # noqa: F401
        from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry

        features, feat_by_gua = FeatureRegistry.compute_all(
            df=sample_ohlcv,
            macro_df=None,
            symbol="BTC",
            enabled=["bagua", "fibonacci", "macro"],
        )

        # macro 模块应被跳过
        assert "macro" not in feat_by_gua
        # 但其他模块仍正常计算
        assert "bagua" in feat_by_gua or len(feat_by_gua) > 0
