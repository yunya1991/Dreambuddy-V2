"""
T10f: AssetBiasResolver TDD 测试
SPEC §4.5.3 — 资产分化方向偏置

资产分化规则:
  gold: hike + pre_event → short_bias / cut → long_bias
  btc: 30天相关性 < 0.3 → neutral / hike + corr < 0 + pre_event → short_bias
  semiconductors: AI周期 > 0.7 → neutral / hike → short_bias

HC: 开关关断时返回 {"bias": "neutral", "confidence": 0.0}
HC: FAIL-OPEN 异常返回 neutral
"""
from __future__ import annotations

import pytest


@pytest.fixture
def enable_resolver(monkeypatch):
    from dreambuddy_evolution.agi_config import set_switch, reset_switches
    reset_switches()
    set_switch("enable_agi_core", True)
    set_switch("enable_contradiction_driven_layer", True)
    set_switch("enable_asset_bias_resolver", True)
    yield
    reset_switches()


class TestAssetBiasResolver:
    """资产分化方向偏置单元测试 (T10f)"""

    def test_module_importable(self):
        """RED: 模块可导入"""
        from dreambuddy_evolution.engines.asset_bias_resolver import (
            AssetBiasResolver,
            AssetBias,
        )
        assert AssetBiasResolver is not None
        assert AssetBias is not None

    def test_gold_hike_pre_event_short_bias(self, enable_resolver):
        """gold: hike + pre_event → short_bias"""
        from dreambuddy_evolution.engines.asset_bias_resolver import AssetBiasResolver
        resolver = AssetBiasResolver()
        result = resolver.get_asset_bias(
            asset="gold",
            fomc_phase="expectation_jump",
            rate_expectation="hike",
        )
        assert result.bias == "short"
        assert result.confidence > 0.5

    def test_gold_cut_long_bias(self, enable_resolver):
        """gold: cut → long_bias"""
        from dreambuddy_evolution.engines.asset_bias_resolver import AssetBiasResolver
        resolver = AssetBiasResolver()
        result = resolver.get_asset_bias(
            asset="gold",
            fomc_phase="repricing",
            rate_expectation="cut",
        )
        assert result.bias == "long"

    def test_btc_low_correlation_neutral(self, enable_resolver):
        """btc: 30天相关性 < 0.3 → neutral"""
        from dreambuddy_evolution.engines.asset_bias_resolver import AssetBiasResolver
        resolver = AssetBiasResolver()
        result = resolver.get_asset_bias(
            asset="btc",
            fomc_phase="expectation_rise",
            rate_expectation="hike",
            corr_30d=0.1,  # 低相关性
        )
        assert result.bias == "neutral"

    def test_btc_hike_negative_corr_pre_event_short_bias(self, enable_resolver):
        """btc: hike + corr < 0 + pre_event → short_bias"""
        from dreambuddy_evolution.engines.asset_bias_resolver import AssetBiasResolver
        resolver = AssetBiasResolver()
        result = resolver.get_asset_bias(
            asset="btc",
            fomc_phase="expectation_jump",
            rate_expectation="hike",
            corr_30d=-0.4,  # 负相关
        )
        assert result.bias == "short"

    def test_semiconductors_ai_cycle_high_neutral(self, enable_resolver):
        """semiconductors: AI周期 > 0.7 → neutral（AI对冲利率压力）"""
        from dreambuddy_evolution.engines.asset_bias_resolver import AssetBiasResolver
        resolver = AssetBiasResolver()
        result = resolver.get_asset_bias(
            asset="semiconductors",
            fomc_phase="expectation_rise",
            rate_expectation="hike",
            ai_cycle_score=0.85,
        )
        assert result.bias == "neutral"

    def test_semiconductors_hike_short_bias(self, enable_resolver):
        """semiconductors: hike (无AI对冲) → short_bias"""
        from dreambuddy_evolution.engines.asset_bias_resolver import AssetBiasResolver
        resolver = AssetBiasResolver()
        result = resolver.get_asset_bias(
            asset="semiconductors",
            fomc_phase="expectation_rise",
            rate_expectation="hike",
            ai_cycle_score=0.3,  # AI周期不强
        )
        assert result.bias == "short"

    def test_unknown_asset_neutral(self, enable_resolver):
        """未知资产 → neutral"""
        from dreambuddy_evolution.engines.asset_bias_resolver import AssetBiasResolver
        resolver = AssetBiasResolver()
        result = resolver.get_asset_bias(
            asset="unknown_asset",
            fomc_phase="event",
            rate_expectation="hold",
        )
        assert result.bias == "neutral"
        assert result.confidence == 0.0

    def test_hold_rate_neutral(self, enable_resolver):
        """利率预期 hold → neutral"""
        from dreambuddy_evolution.engines.asset_bias_resolver import AssetBiasResolver
        resolver = AssetBiasResolver()
        result = resolver.get_asset_bias(
            asset="gold",
            fomc_phase="expectation_build",
            rate_expectation="hold",
        )
        assert result.bias == "neutral"

    def test_switch_off_returns_neutral(self):
        """HC: 开关关断时返回 neutral"""
        from dreambuddy_evolution.agi_config import set_switch, reset_switches
        from dreambuddy_evolution.engines.asset_bias_resolver import AssetBiasResolver
        reset_switches()
        set_switch("enable_agi_core", True)
        set_switch("enable_contradiction_driven_layer", False)
        set_switch("enable_asset_bias_resolver", True)
        resolver = AssetBiasResolver()
        result = resolver.get_asset_bias(
            asset="gold",
            fomc_phase="expectation_jump",
            rate_expectation="hike",
        )
        assert result.bias == "neutral"
        assert result.confidence == 0.0

    def test_fail_open_on_exception(self, enable_resolver):
        """HC: 异常时 FAIL-OPEN 返回 neutral"""
        from dreambuddy_evolution.engines.asset_bias_resolver import AssetBiasResolver
        resolver = AssetBiasResolver()
        result = resolver.get_asset_bias(
            asset=None,
            fomc_phase=None,
            rate_expectation=None,
        )
        assert result.bias == "neutral"

    def test_to_dict_serializable(self, enable_resolver):
        """AssetBias 可序列化"""
        from dreambuddy_evolution.engines.asset_bias_resolver import AssetBiasResolver
        resolver = AssetBiasResolver()
        result = resolver.get_asset_bias(
            asset="gold",
            fomc_phase="expectation_jump",
            rate_expectation="hike",
        )
        d = result.to_dict()
        assert "bias" in d
        assert "confidence" in d
        assert "reason" in d
