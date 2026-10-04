"""
Phase 1 集成测试: T10d + T10e + T10f 三模块联动 + 开关关断等价验证

验证:
  1. 三模块可串联使用：PrimaryContradictionDetector → ParameterAdjuster → AssetBiasResolver
  2. 开关关断时三模块都返回中性默认，字节等价"新模块不存在"
  3. 开关启用时三模块正常工作
"""
from __future__ import annotations

import pytest


@pytest.fixture
def enable_phase1(monkeypatch):
    from dreambuddy_evolution.agi_config import set_switch, reset_switches
    reset_switches()
    set_switch("enable_agi_core", True)
    set_switch("enable_contradiction_driven_layer", True)
    set_switch("enable_primary_contradiction_detector", True)
    set_switch("enable_parameter_adjuster", True)
    set_switch("enable_asset_bias_resolver", True)
    yield
    reset_switches()


class TestPhase1Integration:
    """Phase 1 三模块联动集成测试"""

    def test_pipeline_detect_adjust_bias(self, enable_phase1):
        """完整流水线：识别主要矛盾 → 调整参数 → 计算资产偏置"""
        from dreambuddy_evolution.engines.primary_contradiction_detector import PrimaryContradictionDetector
        from dreambuddy_evolution.engines.parameter_adjuster import ParameterAdjuster
        from dreambuddy_evolution.engines.asset_bias_resolver import AssetBiasResolver

        # 1. 识别主要矛盾
        detector = PrimaryContradictionDetector()
        kline_data = {
            "event_context": {
                "in_fomc_cycle": True,
                "cycle_phase": "expectation_jump",
                "hike_prob": 0.85,
                "probability_trend": "rising",
            },
            "cpi_actual": 5.2,
            "cpi_expected": 4.0,
        }
        contradiction = detector.detect(kline_data)
        assert contradiction.primary == "fomc_rate_decision"
        assert contradiction.intensity > 0.5

        # 2. 根据 FOMC 阶段调整参数
        adjuster = ParameterAdjuster()
        base_params = {
            "conf_threshold": 0.65, "position_scale": 1.0, "sl_distance_mult": 1.0,
            "tp_distance_mult": 1.0, "macro_weight": 0.30, "tech_weight": 0.40,
            "max_hold_hours": 48,
        }
        adjusted = adjuster.adjust(contradiction.cycle_phase, base_params)
        assert adjusted["position_scale"] == 1.5  # expectation_jump 最强窗口

        # 3. 计算黄金方向偏置
        resolver = AssetBiasResolver()
        bias = resolver.get_asset_bias(
            asset="gold",
            fomc_phase=contradiction.cycle_phase,
            rate_expectation="hike",
        )
        assert bias.bias == "short"  # 加息前金价承压

    def test_switch_off_all_neutral(self):
        """HC: 总开关关断时三模块都返回中性默认"""
        from dreambuddy_evolution.agi_config import set_switch, reset_switches
        from dreambuddy_evolution.engines.primary_contradiction_detector import PrimaryContradictionDetector
        from dreambuddy_evolution.engines.parameter_adjuster import ParameterAdjuster
        from dreambuddy_evolution.engines.asset_bias_resolver import AssetBiasResolver

        reset_switches()
        set_switch("enable_agi_core", True)
        set_switch("enable_contradiction_driven_layer", False)  # 层开关关断
        # 即使子开关启用，层关断时也应返回中性
        set_switch("enable_primary_contradiction_detector", True)
        set_switch("enable_parameter_adjuster", True)
        set_switch("enable_asset_bias_resolver", True)

        kline_data = {
            "event_context": {
                "in_fomc_cycle": True, "cycle_phase": "expectation_jump",
                "hike_prob": 0.85, "probability_trend": "rising",
            },
        }

        # 1. 主要矛盾识别器返回中性
        detector = PrimaryContradictionDetector()
        result = detector.detect(kline_data)
        assert result.primary == "unknown"
        assert result.intensity == 0.0

        # 2. 参数调整器返回 base_params 不修改
        adjuster = ParameterAdjuster()
        base_params = {"conf_threshold": 0.65, "position_scale": 1.0}
        result = adjuster.adjust("expectation_jump", base_params)
        assert result == base_params

        # 3. 资产偏置返回中性
        resolver = AssetBiasResolver()
        result = resolver.get_asset_bias("gold", "expectation_jump", "hike")
        assert result.bias == "neutral"
        assert result.confidence == 0.0

    def test_partial_switch_on(self):
        """HC: 部分开关启用时仅对应模块激活"""
        from dreambuddy_evolution.agi_config import set_switch, reset_switches
        from dreambuddy_evolution.engines.primary_contradiction_detector import PrimaryContradictionDetector
        from dreambuddy_evolution.engines.parameter_adjuster import ParameterAdjuster

        reset_switches()
        set_switch("enable_agi_core", True)
        set_switch("enable_contradiction_driven_layer", True)
        set_switch("enable_primary_contradiction_detector", True)
        set_switch("enable_parameter_adjuster", False)  # 关断参数调整器

        kline_data = {
            "event_context": {
                "in_fomc_cycle": True, "cycle_phase": "expectation_jump",
                "hike_prob": 0.85, "probability_trend": "rising",
            },
        }

        # 1. 主要矛盾识别器正常工作
        detector = PrimaryContradictionDetector()
        result = detector.detect(kline_data)
        assert result.primary == "fomc_rate_decision"

        # 2. 参数调整器返回 base_params 不修改
        adjuster = ParameterAdjuster()
        base_params = {"conf_threshold": 0.65, "position_scale": 1.0}
        result = adjuster.adjust("expectation_jump", base_params)
        assert result == base_params
