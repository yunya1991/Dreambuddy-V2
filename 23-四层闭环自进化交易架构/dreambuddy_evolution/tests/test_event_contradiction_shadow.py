"""B-04: event contradiction shadow tests."""
from __future__ import annotations

import copy

import pytest

from dreambuddy_evolution.core.event_contradiction_shadow import (
    compute_event_contradiction_shadow,
)


@pytest.fixture
def switches_off():
    from dreambuddy_evolution.agi_config import reset_switches

    reset_switches()
    yield
    reset_switches()


class TestEventContradictionShadow:
    def test_disabled_returns_none(self):
        assert compute_event_contradiction_shadow({}, enabled=False) is None

    def test_fomc_shadow(self):
        data = {
            "event_context": {
                "in_fomc_cycle": True,
                "cycle_phase": "expectation_jump",
                "hike_prob": 0.85,
                "probability_trend": "rising",
            }
        }
        shadow = compute_event_contradiction_shadow(data, enabled=True)
        assert shadow["available"] is True
        assert shadow["shadow_only"] is True
        assert shadow["primary"] == "fomc_rate_decision"
        assert 0.60 <= shadow["intensity"] <= 0.66
        assert shadow["cycle_phase"] == "expectation_jump"
        assert "gold" in shadow["affected_assets"]

    def test_inflation_shadow(self):
        data = {
            "cpi_actual": 5.2,
            "cpi_expected": 4.0,
            "event_context": {"in_fomc_cycle": False, "cycle_phase": "neutral"},
        }
        shadow = compute_event_contradiction_shadow(data, enabled=True)
        assert shadow["primary"] == "inflation_shock"
        assert shadow["intensity"] > 0.3

    def test_ai_capex_shadow(self):
        data = {
            "ai_cycle_score": 0.85,
            "event_context": {"in_fomc_cycle": False, "cycle_phase": "neutral"},
        }
        shadow = compute_event_contradiction_shadow(data, enabled=True)
        assert shadow["primary"] == "ai_capex_cycle"
        assert "semiconductors" in shadow["affected_assets"]

    def test_invalid_data_fail_open(self):
        shadow = compute_event_contradiction_shadow(None, enabled=True)
        assert shadow["available"] is False
        assert shadow["reason"] == "no_kline_data"
        # empty dict is valid input → neutral detection, not an exception
        neutral = compute_event_contradiction_shadow({}, enabled=True)
        assert neutral["available"] is True
        assert neutral["primary"] == "unknown"
        assert neutral["intensity"] == 0.0

    def test_force_bypasses_production_switches(self, switches_off):
        from dreambuddy_evolution.engines.primary_contradiction_detector import (
            PrimaryContradictionDetector,
        )

        data = {
            "event_context": {
                "in_fomc_cycle": True,
                "hike_prob": 0.85,
                "probability_trend": "rising",
            }
        }
        detector = PrimaryContradictionDetector()
        # 生产开关关闭 → neutral
        assert detector.detect(data).primary == "unknown"
        # shadow force → 正常识别
        forced = detector.detect(data, force=True)
        assert forced.primary == "fomc_rate_decision"

    def test_does_not_mutate_input(self):
        data = {
            "cpi_actual": 5.2,
            "cpi_expected": 4.0,
            "event_context": {"in_fomc_cycle": False, "cycle_phase": "neutral"},
        }
        before = copy.deepcopy(data)
        compute_event_contradiction_shadow(data, enabled=True)
        assert data == before

    def test_switches_default_off(self):
        from dreambuddy_evolution.agi_config import get_switch

        assert get_switch("enable_primary_contradiction_detector", False) is False
        assert get_switch("enable_event_contradiction_shadow", False) is False