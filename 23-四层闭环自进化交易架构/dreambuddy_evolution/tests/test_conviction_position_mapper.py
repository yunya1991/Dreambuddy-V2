"""
Phase 2: ConvictionPositionMapper TDD 测试
SPEC §4.6.2 — 置信度→仓位/策略映射 (5档参数化)

5档映射:
  0.0-0.30  wait          position_scale=0.0
  0.30-0.50 range         position_scale=0.3  sl_mult=1.5
  0.50-0.70 trend_emerge  position_scale=0.7
  0.70-0.85 trend_set     position_scale=1.2  addon=True
  0.85-1.0  strong_trend  position_scale=1.5

FOMC阶段基线置信度:
  build=0.30 / rise=0.55 / jump=0.75 / digest=0.60 / event=0.40 / repricing=0.50

HC: 开关关断时返回 position_scale=1.0 中性默认
HC: FAIL-OPEN 异常返回中性默认
"""
from __future__ import annotations

import pytest


@pytest.fixture
def enable_mapper(monkeypatch):
    from dreambuddy_evolution.agi_config import set_switch, reset_switches
    reset_switches()
    set_switch("enable_agi_core", True)
    set_switch("enable_contradiction_driven_layer", True)
    set_switch("enable_conviction_position_mapper", True)
    yield
    reset_switches()


class TestConvictionPositionMapper:
    """置信度→仓位映射单元测试"""

    def test_module_importable(self):
        """RED: 模块可导入"""
        from dreambuddy_evolution.engines.conviction_position_mapper import (
            ConvictionPositionMapper,
            POSITION_TIERS,
            FOMC_PHASE_CONFIDENCE_BASELINE,
        )
        assert ConvictionPositionMapper is not None
        assert POSITION_TIERS is not None
        assert FOMC_PHASE_CONFIDENCE_BASELINE is not None

    def test_position_tiers_has_5_levels(self, enable_mapper):
        """POSITION_TIERS 包含 5 档"""
        from dreambuddy_evolution.engines.conviction_position_mapper import POSITION_TIERS
        assert len(POSITION_TIERS) == 5
        tiers = [t["tier"] for t in POSITION_TIERS]
        assert tiers == ["wait", "range", "trend_emerge", "trend_set", "strong_trend"]

    def test_map_wait_tier_low_conviction(self, enable_mapper):
        """置信度 0.15 → wait, position_scale=0.0"""
        from dreambuddy_evolution.engines.conviction_position_mapper import ConvictionPositionMapper
        mapper = ConvictionPositionMapper()
        result = mapper.map(0.15)
        assert result["tier"] == "wait"
        assert result["position_scale"] == 0.0

    def test_map_range_tier(self, enable_mapper):
        """置信度 0.40 → range, position_scale=0.3"""
        from dreambuddy_evolution.engines.conviction_position_mapper import ConvictionPositionMapper
        mapper = ConvictionPositionMapper()
        result = mapper.map(0.40)
        assert result["tier"] == "range"
        assert result["position_scale"] == 0.3
        assert result["sl_mult"] == 1.5

    def test_map_trend_emerge_tier(self, enable_mapper):
        """置信度 0.60 → trend_emerge, position_scale=0.7"""
        from dreambuddy_evolution.engines.conviction_position_mapper import ConvictionPositionMapper
        mapper = ConvictionPositionMapper()
        result = mapper.map(0.60)
        assert result["tier"] == "trend_emerge"
        assert result["position_scale"] == 0.7

    def test_map_trend_set_tier(self, enable_mapper):
        """置信度 0.75 → trend_set, position_scale=1.2, addon=True"""
        from dreambuddy_evolution.engines.conviction_position_mapper import ConvictionPositionMapper
        mapper = ConvictionPositionMapper()
        result = mapper.map(0.75)
        assert result["tier"] == "trend_set"
        assert result["position_scale"] == 1.2
        assert result["addon"] is True
        assert result["trailing_stop"] is True

    def test_map_strong_trend_tier(self, enable_mapper):
        """置信度 0.90 → strong_trend, position_scale=1.5"""
        from dreambuddy_evolution.engines.conviction_position_mapper import ConvictionPositionMapper
        mapper = ConvictionPositionMapper()
        result = mapper.map(0.90)
        assert result["tier"] == "strong_trend"
        assert result["position_scale"] == 1.5

    def test_map_with_fomc_baseline(self, enable_mapper):
        """FOMC阶段基线置信度调整: expectation_jump基线0.75"""
        from dreambuddy_evolution.engines.conviction_position_mapper import ConvictionPositionMapper
        mapper = ConvictionPositionMapper()
        # 传入 fomc_phase，使用基线置信度作为下限
        result = mapper.map(0.50, fomc_phase="expectation_jump")
        # expectation_jump 基线 0.75 → 至少 trend_set
        assert result["position_scale"] >= 1.2

    def test_map_fomc_baseline_event_conservative(self, enable_mapper):
        """event阶段基线0.40 → 保守"""
        from dreambuddy_evolution.engines.conviction_position_mapper import ConvictionPositionMapper
        mapper = ConvictionPositionMapper()
        result = mapper.map(0.50, fomc_phase="event")
        # event基线0.40 + 实际0.50 → 取max(0.40, 0.50)=0.50 → trend_emerge
        assert result["tier"] == "trend_emerge"

    def test_switch_off_returns_neutral(self):
        """HC: 开关关断时返回 position_scale=1.0 中性默认"""
        from dreambuddy_evolution.agi_config import set_switch, reset_switches
        from dreambuddy_evolution.engines.conviction_position_mapper import ConvictionPositionMapper
        reset_switches()
        set_switch("enable_agi_core", True)
        set_switch("enable_contradiction_driven_layer", False)
        set_switch("enable_conviction_position_mapper", True)
        mapper = ConvictionPositionMapper()
        result = mapper.map(0.90)
        assert result["position_scale"] == 1.0
        assert result["tier"] == "neutral"

    def test_fail_open_on_exception(self, enable_mapper):
        """HC: 异常时 FAIL-OPEN 返回中性默认"""
        from dreambuddy_evolution.engines.conviction_position_mapper import ConvictionPositionMapper
        mapper = ConvictionPositionMapper()
        result = mapper.map(None)
        assert result["position_scale"] == 1.0

    def test_boundary_0_30(self, enable_mapper):
        """边界 0.30 → range（>=0.30）"""
        from dreambuddy_evolution.engines.conviction_position_mapper import ConvictionPositionMapper
        mapper = ConvictionPositionMapper()
        result = mapper.map(0.30)
        assert result["tier"] == "range"

    def test_boundary_0_85(self, enable_mapper):
        """边界 0.85 → strong_trend（>=0.85）"""
        from dreambuddy_evolution.engines.conviction_position_mapper import ConvictionPositionMapper
        mapper = ConvictionPositionMapper()
        result = mapper.map(0.85)
        assert result["tier"] == "strong_trend"
