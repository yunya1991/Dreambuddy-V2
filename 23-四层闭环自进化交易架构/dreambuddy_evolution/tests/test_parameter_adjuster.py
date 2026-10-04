"""
T10e: ParameterAdjuster TDD 测试
SPEC §4.5.2 — 主要矛盾驱动的参数调整矩阵 (6阶段×7参数)

6 阶段: expectation_build / expectation_rise / expectation_jump / expectation_digest / event / repricing
7 参数: conf_threshold / position_scale / sl_distance_mult / macro_weight / tech_weight / max_hold_hours / tp_distance_mult

HC: 开关关断时返回 base_params 不修改，字节等价"模块不存在"
HC: FAIL-OPEN 异常返回 base_params
"""
from __future__ import annotations

import pytest


@pytest.fixture
def enable_adjuster(monkeypatch):
    from dreambuddy_evolution.agi_config import set_switch, reset_switches
    reset_switches()
    set_switch("enable_agi_core", True)
    set_switch("enable_contradiction_driven_layer", True)
    set_switch("enable_parameter_adjuster", True)
    yield
    reset_switches()


class TestParameterAdjuster:
    """参数调整矩阵单元测试 (T10e)"""

    def test_module_importable(self):
        """RED: 模块可导入"""
        from dreambuddy_evolution.engines.parameter_adjuster import (
            ParameterAdjuster,
            FOMC_PARAM_OVERRIDES,
        )
        assert ParameterAdjuster is not None
        assert FOMC_PARAM_OVERRIDES is not None

    def test_fomc_param_overrides_has_6_phases(self, enable_adjuster):
        """FOMC_PARAM_OVERRIDES 包含 6 个阶段"""
        from dreambuddy_evolution.engines.parameter_adjuster import FOMC_PARAM_OVERRIDES
        expected_phases = {
            "expectation_build", "expectation_rise", "expectation_jump",
            "expectation_digest", "event", "repricing",
        }
        assert set(FOMC_PARAM_OVERRIDES.keys()) == expected_phases

    def test_fomc_param_overrides_has_7_params(self, enable_adjuster):
        """每个阶段包含 7 个参数"""
        from dreambuddy_evolution.engines.parameter_adjuster import FOMC_PARAM_OVERRIDES
        required_params = {
            "conf_threshold", "position_scale", "sl_distance_mult",
            "macro_weight", "tech_weight", "max_hold_hours", "tp_distance_mult",
        }
        for phase, params in FOMC_PARAM_OVERRIDES.items():
            assert set(params.keys()) == required_params, f"Phase {phase} missing params"

    def test_adjust_expectation_jump_max_window(self, enable_adjuster):
        """expectation_jump 是最强窗口: position_scale=1.5"""
        from dreambuddy_evolution.engines.parameter_adjuster import ParameterAdjuster
        adjuster = ParameterAdjuster()
        base_params = {
            "conf_threshold": 0.65, "position_scale": 1.0, "sl_distance_mult": 1.0,
            "macro_weight": 0.30, "tech_weight": 0.40, "max_hold_hours": 48,
            "tp_distance_mult": 1.0,
        }
        result = adjuster.adjust("expectation_jump", base_params)
        assert result["position_scale"] == 1.5  # 最强窗口
        assert result["conf_threshold"] == 0.50  # 放宽置信度门槛
        assert result["max_hold_hours"] == 36

    def test_adjust_event_phase_conservative(self, enable_adjuster):
        """event 阶段保守: position_scale=0.5, sl_distance_mult=1.0"""
        from dreambuddy_evolution.engines.parameter_adjuster import ParameterAdjuster
        adjuster = ParameterAdjuster()
        base_params = {
            "conf_threshold": 0.65, "position_scale": 1.0, "sl_distance_mult": 1.5,
            "macro_weight": 0.30, "tech_weight": 0.40, "max_hold_hours": 48,
            "tp_distance_mult": 1.0,
        }
        result = adjuster.adjust("event", base_params)
        assert result["position_scale"] == 0.5  # 保守
        assert result["sl_distance_mult"] == 1.0  # 紧止损
        assert result["max_hold_hours"] == 12  # 短持

    def test_adjust_unknown_phase_returns_base(self, enable_adjuster):
        """未知阶段返回 base_params 不修改"""
        from dreambuddy_evolution.engines.parameter_adjuster import ParameterAdjuster
        adjuster = ParameterAdjuster()
        base_params = {
            "conf_threshold": 0.65, "position_scale": 1.0, "sl_distance_mult": 1.0,
            "macro_weight": 0.30, "tech_weight": 0.40, "max_hold_hours": 48,
            "tp_distance_mult": 1.0,
        }
        result = adjuster.adjust("neutral", base_params)
        assert result == base_params

    def test_adjust_preserves_extra_params(self, enable_adjuster):
        """adjust 保留 base_params 中的额外参数"""
        from dreambuddy_evolution.engines.parameter_adjuster import ParameterAdjuster
        adjuster = ParameterAdjuster()
        base_params = {
            "conf_threshold": 0.65, "position_scale": 1.0, "sl_distance_mult": 1.0,
            "macro_weight": 0.30, "tech_weight": 0.40, "max_hold_hours": 48,
            "tp_distance_mult": 1.0,
            "extra_param": "keep_me",  # 额外参数应保留
        }
        result = adjuster.adjust("event", base_params)
        assert result["extra_param"] == "keep_me"

    def test_switch_off_returns_base_unchanged(self):
        """HC: 开关关断时返回 base_params 不修改"""
        from dreambuddy_evolution.agi_config import set_switch, reset_switches
        from dreambuddy_evolution.engines.parameter_adjuster import ParameterAdjuster
        reset_switches()
        set_switch("enable_agi_core", True)
        set_switch("enable_contradiction_driven_layer", False)  # 层开关关断
        set_switch("enable_parameter_adjuster", True)  # 即使模块开关开
        adjuster = ParameterAdjuster()
        base_params = {
            "conf_threshold": 0.65, "position_scale": 1.0, "sl_distance_mult": 1.0,
            "macro_weight": 0.30, "tech_weight": 0.40, "max_hold_hours": 48,
            "tp_distance_mult": 1.0,
        }
        result = adjuster.adjust("expectation_jump", base_params)
        assert result == base_params  # 不修改

    def test_fail_open_on_exception(self, enable_adjuster):
        """HC: 异常时 FAIL-OPEN 返回 base_params"""
        from dreambuddy_evolution.engines.parameter_adjuster import ParameterAdjuster
        adjuster = ParameterAdjuster()
        base_params = {"conf_threshold": 0.65}
        # 传入非法 fomc_phase 类型
        result = adjuster.adjust(None, base_params)
        assert result == base_params

    def test_all_phases_position_scale_range(self, enable_adjuster):
        """所有阶段的 position_scale 在 0.0-2.0 范围内"""
        from dreambuddy_evolution.engines.parameter_adjuster import FOMC_PARAM_OVERRIDES
        for phase, params in FOMC_PARAM_OVERRIDES.items():
            assert 0.0 <= params["position_scale"] <= 2.0, f"{phase} position_scale out of range"
            assert 0.0 <= params["conf_threshold"] <= 1.0, f"{phase} conf_threshold out of range"
            assert 0.0 <= params["sl_distance_mult"] <= 3.0, f"{phase} sl_distance_mult out of range"
