"""FeatureRegistry 单元测试 — 验证插件注册机制和特征一致性"""
import sys
import os
import pytest
import pandas as pd
import numpy as np
from pathlib import Path

# 确保项目根目录在 path 中
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# Fixture: 合成 OHLCV 数据
# ============================================================
@pytest.fixture
def sample_ohlcv():
    """生成 500 根 1H K 线合成数据（含趋势+波动，足够所有特征模块计算）"""
    np.random.seed(42)
    n = 500
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")

    # 合成价格：趋势 + 波动 + 均值回归
    returns = np.random.normal(0.0002, 0.02, n)
    returns[100:150] += 0.005  # 上涨段
    returns[250:300] -= 0.005  # 下跌段
    close_arr = 50000 * np.exp(np.cumsum(returns))

    close = pd.Series(close_arr, index=dates)
    high = pd.Series(close_arr * (1 + np.abs(np.random.normal(0, 0.005, n))), index=dates)
    low = pd.Series(close_arr * (1 - np.abs(np.random.normal(0, 0.005, n))), index=dates)
    open_ = close.shift(1).fillna(close.iloc[0])
    volume = pd.Series(np.random.lognormal(10, 1, n), index=dates)

    df = pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })
    return df


@pytest.fixture
def btc_ref_df():
    """BTC 参考数据（用于跨资产特征）"""
    np.random.seed(99)
    n = 500
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    returns = np.random.normal(0.0001, 0.015, n)
    close_arr = 60000 * np.exp(np.cumsum(returns))
    close = pd.Series(close_arr, index=dates)
    high = pd.Series(close_arr * (1 + np.abs(np.random.normal(0, 0.004, n))), index=dates)
    low = pd.Series(close_arr * (1 - np.abs(np.random.normal(0, 0.004, n))), index=dates)
    open_ = close.shift(1).fillna(close.iloc[0])
    volume = pd.Series(np.random.lognormal(11, 1, n), index=dates)
    return pd.DataFrame({
        "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
    })


# ============================================================
# 测试组 1: 注册机制基础功能
# ============================================================
class TestRegistryBasics:
    """验证 FeatureRegistry 的注册/列表功能"""

    def test_registry_can_register_and_list(self):
        """注册后能列出模块名"""
        from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry

        # 使用临时名避免污染全局注册表
        FeatureRegistry.register("test_module_a", factory=lambda: None)
        modules = FeatureRegistry.list_modules()
        assert "test_module_a" in modules

    def test_registry_preserves_registration_order(self):
        """注册顺序保持不变"""
        from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry

        FeatureRegistry.register("test_order_1", factory=lambda: None)
        FeatureRegistry.register("test_order_2", factory=lambda: None)
        modules = FeatureRegistry.list_modules()
        idx1 = modules.index("test_order_1")
        idx2 = modules.index("test_order_2")
        assert idx1 < idx2


# ============================================================
# 测试组 2: compute_all 基础功能
# ============================================================
class TestComputeAll:
    """验证 compute_all 返回正确类型和结构"""

    def test_returns_dataframe_and_gua_map(self, sample_ohlcv):
        """compute_all 返回 (DataFrame, dict) 元组"""
        from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry
        # 触发模块注册
        import scripts.memory_l4.bcrm2.bagua_feature_engine  # noqa

        features, gua_map = FeatureRegistry.compute_all(
            df=sample_ohlcv,
            symbol="BTC",
            enabled=["bagua"],
        )
        assert isinstance(features, pd.DataFrame)
        assert isinstance(gua_map, dict)
        assert len(features) == len(sample_ohlcv)
        # bagua 的 feature_names_by_gua 来自实例属性
        assert len(gua_map) > 0

    def test_enabled_filter_only_runs_specified(self, sample_ohlcv):
        """enabled 参数精确控制启用模块"""
        from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry
        import scripts.memory_l4.bcrm2.bagua_feature_engine  # noqa
        import scripts.memory_l4.bcrm2.classic_experience_features  # noqa

        _, gua_map = FeatureRegistry.compute_all(
            df=sample_ohlcv,
            symbol="BTC",
            enabled=["bagua"],
        )
        assert "classic_exp" not in gua_map

    def test_wdh_sub_keys_split(self, sample_ohlcv):
        """wdh 拆为 4 个子 key"""
        from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry
        import scripts.memory_l4.bcrm2.wdh_features  # noqa

        _, gua_map = FeatureRegistry.compute_all(
            df=sample_ohlcv,
            symbol="BTC",
            enabled=["wdh"],
        )
        assert "wdh_weekly_accum" in gua_map
        assert "wdh_daily_confirm" in gua_map
        assert "wdh_hourly_timing" in gua_map
        assert "wdh_qual_trigger" in gua_map

    def test_cycle_sub_keys_split(self, sample_ohlcv):
        """cycle 拆为 4 个子 key"""
        from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry
        import scripts.memory_l4.bcrm2.cycle_features  # noqa

        _, gua_map = FeatureRegistry.compute_all(
            df=sample_ohlcv,
            symbol="BTC",
            enabled=["cycle"],
        )
        assert "cycle_halving" in gua_map
        assert "cycle_ath" in gua_map
        assert "cycle_inventory" in gua_map
        assert "cycle_long_term" in gua_map

    def test_cross_asset_skipped_without_ref_df(self, sample_ohlcv):
        """无 ref_df 时跳过 cross_asset"""
        from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry
        import scripts.memory_l4.bcrm2.cross_asset_features  # noqa

        _, gua_map = FeatureRegistry.compute_all(
            df=sample_ohlcv,
            symbol="ETH",
            enabled=["cross_asset"],
        )
        assert "cross_asset" not in gua_map

    def test_cross_asset_runs_with_ref_df(self, sample_ohlcv, btc_ref_df):
        """有 ref_df 时计算 cross_asset"""
        from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry
        import scripts.memory_l4.bcrm2.cross_asset_features  # noqa

        _, gua_map = FeatureRegistry.compute_all(
            df=sample_ohlcv,
            ref_df=btc_ref_df,
            symbol="ETH",
            enabled=["cross_asset"],
        )
        assert "cross_asset" in gua_map
        assert len(gua_map["cross_asset"]) > 0


# ============================================================
# 测试组 3: 特征值一致性（Characterization Tests）
# ============================================================
class TestFeatureConsistency:
    """验证通过 Registry 调用与直接调用产生的特征值一致"""

    def test_bagua_features_match_direct_call(self, sample_ohlcv):
        """bagua 特征值与直接调用 BaguaFeatureEngine 一致"""
        from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry
        from scripts.memory_l4.bcrm2.bagua_feature_engine import BaguaFeatureEngine
        import scripts.memory_l4.bcrm2.bagua_feature_engine  # noqa: F811

        # 直接调用
        direct = BaguaFeatureEngine().compute(sample_ohlcv)

        # 通过 Registry 调用
        registry, _ = FeatureRegistry.compute_all(
            df=sample_ohlcv,
            symbol="BTC",
            enabled=["bagua"],
        )

        # 列顺序和值应一致
        pd.testing.assert_frame_equal(
            direct, registry,
            check_dtype=False,
            check_like=True,  # 忽略列顺序
        )

    def test_classic_features_match_direct_call(self, sample_ohlcv):
        """classic_exp 特征值与直接调用一致"""
        from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry
        from scripts.memory_l4.bcrm2.classic_experience_features import ClassicExperienceFeatures
        import scripts.memory_l4.bcrm2.classic_experience_features  # noqa

        direct = ClassicExperienceFeatures().compute(sample_ohlcv)
        registry, _ = FeatureRegistry.compute_all(
            df=sample_ohlcv,
            symbol="BTC",
            enabled=["classic_exp"],
        )
        pd.testing.assert_frame_equal(direct, registry, check_dtype=False, check_like=True)

    def test_fibonacci_features_match_direct_call(self, sample_ohlcv):
        """fibonacci 特征值与直接调用一致"""
        from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry
        from scripts.memory_l4.bcrm2.fibonacci_features import FibonacciFeatures
        import scripts.memory_l4.bcrm2.fibonacci_features  # noqa

        direct = FibonacciFeatures().compute(sample_ohlcv)
        registry, _ = FeatureRegistry.compute_all(
            df=sample_ohlcv,
            symbol="BTC",
            enabled=["fibonacci"],
        )
        pd.testing.assert_frame_equal(direct, registry, check_dtype=False, check_like=True)

    def test_pivot_features_match_direct_call(self, sample_ohlcv):
        """pivot_point 特征值与直接调用一致"""
        from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry
        from scripts.memory_l4.bcrm2.pivot_point_features import PivotPointFeatures
        import scripts.memory_l4.bcrm2.pivot_point_features  # noqa

        direct = PivotPointFeatures().compute(sample_ohlcv)
        registry, _ = FeatureRegistry.compute_all(
            df=sample_ohlcv,
            symbol="BTC",
            enabled=["pivot_point"],
        )
        pd.testing.assert_frame_equal(direct, registry, check_dtype=False, check_like=True)

    def test_rsi_features_match_direct_call(self, sample_ohlcv):
        """rsi_sentiment 特征值与直接调用一致"""
        from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry
        from scripts.memory_l4.bcrm2.rsi_sentiment_features import RSISentimentFeatures
        import scripts.memory_l4.bcrm2.rsi_sentiment_features  # noqa

        direct = RSISentimentFeatures().compute(sample_ohlcv)
        registry, _ = FeatureRegistry.compute_all(
            df=sample_ohlcv,
            symbol="BTC",
            enabled=["rsi_sentiment"],
        )
        pd.testing.assert_frame_equal(direct, registry, check_dtype=False, check_like=True)

    def test_wdh_features_match_direct_call(self, sample_ohlcv):
        """wdh 特征值与直接调用一致"""
        from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry
        from scripts.memory_l4.bcrm2.wdh_features import WDHFeatures
        import scripts.memory_l4.bcrm2.wdh_features  # noqa

        direct = WDHFeatures().compute(sample_ohlcv)
        registry, _ = FeatureRegistry.compute_all(
            df=sample_ohlcv,
            symbol="BTC",
            enabled=["wdh"],
        )
        pd.testing.assert_frame_equal(direct, registry, check_dtype=False, check_like=True)

    def test_cycle_features_match_direct_call(self, sample_ohlcv):
        """cycle 特征值与直接调用一致"""
        from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry
        from scripts.memory_l4.bcrm2.cycle_features import CycleFeatures
        import scripts.memory_l4.bcrm2.cycle_features  # noqa

        direct = CycleFeatures(symbol="BTC").compute(sample_ohlcv)
        registry, _ = FeatureRegistry.compute_all(
            df=sample_ohlcv,
            symbol="BTC",
            enabled=["cycle"],
        )
        pd.testing.assert_frame_equal(direct, registry, check_dtype=False, check_like=True)

    def test_market_cap_features_match_direct_call(self, sample_ohlcv):
        """market_cap 特征值与直接调用一致"""
        from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry
        from scripts.memory_l4.bcrm2.market_cap import MarketCapClassifier
        import scripts.memory_l4.bcrm2.market_cap  # noqa

        direct = MarketCapClassifier().get_mcap_features("BTC", sample_ohlcv)
        registry, _ = FeatureRegistry.compute_all(
            df=sample_ohlcv,
            symbol="BTC",
            enabled=["market_cap"],
        )
        pd.testing.assert_frame_equal(direct, registry, check_dtype=False, check_like=True)

    def test_cross_asset_features_match_direct_call(self, sample_ohlcv, btc_ref_df):
        """cross_asset 特征值与直接调用一致"""
        from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry
        from scripts.memory_l4.bcrm2.cross_asset_features import compute_cross_asset_features
        import scripts.memory_l4.bcrm2.cross_asset_features  # noqa

        direct = compute_cross_asset_features(sample_ohlcv, btc_ref_df, symbol="ETH")
        registry, _ = FeatureRegistry.compute_all(
            df=sample_ohlcv,
            ref_df=btc_ref_df,
            symbol="ETH",
            enabled=["cross_asset"],
        )
        pd.testing.assert_frame_equal(direct, registry, check_dtype=False, check_like=True)

    def test_merrill_features_match_direct_call(self, sample_ohlcv, btc_ref_df):
        """merrill_clock 特征值与直接调用一致（含 cycle_phase 依赖传递）"""
        from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry
        from scripts.memory_l4.bcrm2.merrill_clock_features import MerrillClockFeatures
        from scripts.memory_l4.bcrm2.cycle_features import CycleFeatures
        import scripts.memory_l4.bcrm2.merrill_clock_features  # noqa
        import scripts.memory_l4.bcrm2.cycle_features  # noqa

        # 直接调用：需要先算 cycle，再传给 merrill
        cycle_feats = CycleFeatures(symbol="BTC").compute(sample_ohlcv)
        direct = MerrillClockFeatures(symbol="BTC").compute(
            sample_ohlcv, ref_df=btc_ref_df, cycle_phase=cycle_feats,
        )

        # 通过 Registry 调用（Registry 内部自动传递 cycle_phase）
        registry, _ = FeatureRegistry.compute_all(
            df=sample_ohlcv,
            ref_df=btc_ref_df,
            symbol="BTC",
            enabled=["cycle", "merrill_clock"],
        )
        # 提取 merrill_clock 的特征列
        merrill_cols = [c for c in registry.columns
                       if c not in cycle_feats.columns]
        registry_merrill = registry[merrill_cols]

        pd.testing.assert_frame_equal(
            direct, registry_merrill,
            check_dtype=False, check_like=True,
        )


# ============================================================
# 测试组 4: 全量特征计算
# ============================================================
class TestFullFeatureSet:
    """验证全部模块一起计算时的结果"""

    def test_all_10_modules_produce_features(self, sample_ohlcv, btc_ref_df):
        """10 个模块全部启用时产出非空特征"""
        from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry
        # 触发所有模块注册
        import scripts.memory_l4.bcrm2.bagua_feature_engine  # noqa
        import scripts.memory_l4.bcrm2.classic_experience_features  # noqa
        import scripts.memory_l4.bcrm2.fibonacci_features  # noqa
        import scripts.memory_l4.bcrm2.pivot_point_features  # noqa
        import scripts.memory_l4.bcrm2.rsi_sentiment_features  # noqa
        import scripts.memory_l4.bcrm2.wdh_features  # noqa
        import scripts.memory_l4.bcrm2.cycle_features  # noqa
        import scripts.memory_l4.bcrm2.market_cap  # noqa
        import scripts.memory_l4.bcrm2.cross_asset_features  # noqa
        import scripts.memory_l4.bcrm2.merrill_clock_features  # noqa

        features, gua_map = FeatureRegistry.compute_all(
            df=sample_ohlcv,
            ref_df=btc_ref_df,
            symbol="BTC",
        )

        # 特征数应在 300-700 范围（10个L1模块含子模块展开）
        assert len(features.columns) >= 300, f"特征数过少: {len(features.columns)}"
        assert len(features.columns) <= 700, f"特征数过多: {len(features.columns)}"

        # feature_names_by_gua 应包含所有模块（含子模块 key）
        expected_keys = {
            "classic_exp", "fibonacci", "pivot_point", "rsi_sentiment",
            "wdh_weekly_accum", "wdh_daily_confirm", "wdh_hourly_timing",
            "wdh_qual_trigger",
            "cycle_halving", "cycle_ath", "cycle_inventory", "cycle_long_term",
            "market_cap", "cross_asset", "merrill_clock",
        }
        # bagua 的 key 来自实例属性（qian/kun/zhen/...），不在 expected_keys 中
        actual_keys = set(gua_map.keys())
        missing = expected_keys - actual_keys
        assert not missing, f"缺少模块 key: {missing}"
