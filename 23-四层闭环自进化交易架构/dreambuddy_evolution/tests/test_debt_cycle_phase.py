"""
T13b: DebtCyclePhase TDD 测试
SPEC §4.4 — Dalio 短期债务周期判定

规则:
  信贷增速 > GDP增速 → expansion
  信贷增速 < GDP增速 + 利率上行 → contraction
  否则 → neutral

HC: 开关关断时返回 "neutral"
HC: FAIL-OPEN 异常返回 "neutral"
"""
from __future__ import annotations

import pytest


@pytest.fixture
def enable_debt_cycle(monkeypatch):
    from dreambuddy_evolution.agi_config import set_switch
    set_switch("enable_agi_core", True)
    set_switch("enable_contradiction_driven_layer", True)
    set_switch("enable_debt_cycle_phase", True)
    yield


class TestDebtCyclePhase:
    """Dalio 债务周期判定单元测试 (T13b)"""

    def test_module_importable(self):
        from dreambuddy_evolution.engines.debt_cycle_phase import DebtCyclePhase
        assert DebtCyclePhase is not None

    def test_expansion_when_credit_above_gdp(self, enable_debt_cycle):
        """信贷增速 > GDP增速 → expansion"""
        from dreambuddy_evolution.engines.debt_cycle_phase import DebtCyclePhase
        phase = DebtCyclePhase()
        kline_data = {
            "credit_growth": 5.0,
            "gdp_growth": 2.0,
            "monetary_cycle": "easing",
        }
        result = phase.phase(kline_data)
        assert result == "expansion"

    def test_contraction_when_credit_below_gdp_and_tightening(self, enable_debt_cycle):
        """信贷增速 < GDP增速 + 利率上行 → contraction"""
        from dreambuddy_evolution.engines.debt_cycle_phase import DebtCyclePhase
        phase = DebtCyclePhase()
        kline_data = {
            "credit_growth": 1.0,
            "gdp_growth": 3.0,
            "monetary_cycle": "tightening",
        }
        result = phase.phase(kline_data)
        assert result == "contraction"

    def test_neutral_when_credit_below_gdp_but_easing(self, enable_debt_cycle):
        """信贷增速 < GDP增速 但利率下行 → neutral"""
        from dreambuddy_evolution.engines.debt_cycle_phase import DebtCyclePhase
        phase = DebtCyclePhase()
        kline_data = {
            "credit_growth": 1.0,
            "gdp_growth": 3.0,
            "monetary_cycle": "easing",
        }
        result = phase.phase(kline_data)
        assert result == "neutral"

    def test_neutral_when_no_data(self, enable_debt_cycle):
        """无数据 → neutral"""
        from dreambuddy_evolution.engines.debt_cycle_phase import DebtCyclePhase
        phase = DebtCyclePhase()
        result = phase.phase({})
        assert result == "neutral"

    def test_switch_off_returns_neutral(self):
        """HC: 开关关断时返回 neutral"""
        from dreambuddy_evolution.agi_config import set_switch
        from dreambuddy_evolution.engines.debt_cycle_phase import DebtCyclePhase
        set_switch("enable_agi_core", True)
        set_switch("enable_contradiction_driven_layer", False)
        set_switch("enable_debt_cycle_phase", True)
        phase = DebtCyclePhase()
        result = phase.phase({"credit_growth": 5.0, "gdp_growth": 2.0})
        assert result == "neutral"

    def test_fail_open_on_exception(self, enable_debt_cycle):
        """HC: 异常时 FAIL-OPEN 返回 neutral"""
        from dreambuddy_evolution.engines.debt_cycle_phase import DebtCyclePhase
        phase = DebtCyclePhase()
        result = phase.phase(None)
        assert result == "neutral"

    def test_with_context_output(self, enable_debt_cycle):
        """phase_with_context 输出包含 phase + details"""
        from dreambuddy_evolution.engines.debt_cycle_phase import DebtCyclePhase
        phase = DebtCyclePhase()
        kline_data = {
            "credit_growth": 5.0,
            "gdp_growth": 2.0,
            "monetary_cycle": "easing",
        }
        result = phase.phase_with_context(kline_data)
        assert result["phase"] == "expansion"
        assert "credit_growth" in result
        assert "gdp_growth" in result
