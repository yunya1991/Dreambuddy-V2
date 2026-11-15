# -*- coding: utf-8 -*-
"""L1D-03 规则入参构造器 + L1D-04 平仓规则单测。"""

import os
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.direction_rule import decide  # noqa: E402
from l1agg.trading import exit_rule, rule_inputs  # noqa: E402

_TREND_BLOCK = {
    "gate": "ok",
    "ema": {"12": 110.0, "26": 105.0, "50": 100.0},
    "ema_order": "bull",
    "slope_table": [
        {
            "window": 20,
            "slope": 0.01,
            "se": 0.001,
            "t": 2.5,
            "r2": 0.6,
            "hac_corrected": False,
            "degraded": False,
        },
        {
            "window": 60,
            "slope": 0.008,
            "se": 0.001,
            "t": 3.1,
            "r2": 0.7,
            "hac_corrected": False,
            "degraded": False,
        },
        {
            "window": 120,
            "slope": 0.006,
            "se": 0.001,
            "t": 3.5,
            "r2": 0.75,
            "hac_corrected": False,
            "degraded": False,
        },
        {
            "window": 250,
            "slope": 0.004,
            "se": 0.001,
            "t": 4.0,
            "r2": 0.8,
            "hac_corrected": False,
            "degraded": False,
        },
    ],
    "adx": {"adx": 30.0, "plus_di": 28.0, "minus_di": 12.0},
}


def _caps(**blocks):
    base = {
        "D-E15": _TREND_BLOCK,
        "D-E11": {"gate": "ok", "cycle_alignment": {"ratio": 0.8, "pairs": 24, "months": 30}},
        "D-G22": {"gate": "ok", "newey_west": {"t_nw": 2.0, "se": 0.01, "lag": 3}},
        "D-E03": {"gate": "ok", "best_month": "2024-02", "seasonal_strength": {"strength": 0.3}},
    }
    base.update(blocks)
    return base


def test_build_inputs_projects_without_recomputing():
    inputs = rule_inputs.build_inputs(_caps(), seasonality_years=7.0)
    assert inputs["slope_table"][0]["window"] == 20
    assert inputs["adx"] == {"adx14": 30.0, "plus_di": 28.0, "minus_di": 12.0}
    assert inputs["ema"]["order"] == "bull"
    assert inputs["same_direction_rate"] == {"r": 0.8, "n": 30}
    assert inputs["p_adj"] == rule_inputs.two_sided_p(2.0)
    assert inputs["seasonality"]["depth_years"] == 7.0


def test_two_sided_p_reference_value():
    assert rule_inputs.two_sided_p(1.96) == pytest.approx(0.04999579, abs=1e-8)
    assert rule_inputs.two_sided_p(None) is None


def test_missing_blocks_degrade_to_none():
    inputs = rule_inputs.build_inputs({})
    assert inputs == {
        "slope_table": None,
        "adx": None,
        "ema": None,
        "same_direction_rate": None,
        "p_adj": None,
        "seasonality": None,
    }


def test_gate_not_ok_and_explicit_p_adj_wins():
    caps = _caps(**{"D-E15": {"gate": "insufficient_history"}, "D-E11": {"gate": "partial"}})
    caps["D-G22"] = {"gate": "ok", "p_adj": 0.2, "newey_west": {"t_nw": 5.0}}
    inputs = rule_inputs.build_inputs(caps)
    assert inputs["slope_table"] is None and inputs["adx"] is None
    assert inputs["same_direction_rate"] is None
    assert inputs["p_adj"] == 0.2


def test_build_inputs_feeds_decide():
    record = decide(rule_inputs.build_inputs(_caps()), as_of="2026-11-14", symbol="BTC")
    assert record["axes"] == {"trend": 40.0, "adx": 25.0, "inertia": 20.0, "coherence": 9.0}
    assert record["direction"] == 1


def test_shallow_seasonality_is_dropped_by_rule():
    record = decide(rule_inputs.build_inputs(_caps(), seasonality_years=3.0))
    assert record["seasonality"] is None
    assert "seasonality_depth_lt_5y" in record["flags"]


# ---------------- L1D-04 exit_rule ----------------


def test_rule1_direction_flip_exits():
    out = exit_rule.evaluate(1, total=-45.0, duration_bars=10, adx14=30.0, ema_order="bull")
    assert out["exit"] is True
    assert out["reason"] == exit_rule.DIRECTION_FLIP


def test_rule2_flat_needs_two_consecutive_bars():
    first = exit_rule.evaluate(1, total=5.0, duration_bars=10, low_bars=0)
    assert first["exit"] is False and first["low_bars"] == 1
    second = exit_rule.evaluate(1, total=5.0, duration_bars=10, low_bars=first["low_bars"])
    assert second["exit"] is True and second["reason"] == exit_rule.FLAT_CONFIRM


def test_rule2_counter_resets_above_threshold():
    out = exit_rule.evaluate(1, total=40.0, duration_bars=10, low_bars=1)
    assert out["exit"] is False and out["low_bars"] == 0


def test_rule3_structure_breakdown_exits():
    out = exit_rule.evaluate(1, total=35.0, duration_bars=10, adx14=18.0, ema_order="mixed")
    assert out["exit"] is True and out["reason"] == exit_rule.STRUCTURE_BREAKDOWN


def test_rule4_stop_loss_bypasses_min_hold():
    out = exit_rule.evaluate(1, total=60.0, duration_bars=1, stop_triggered=True)
    assert out["exit"] is True and out["reason"] == exit_rule.STOP_LOSS
    assert "stop_loss_bypass" in out["flags"]


def test_min_hold_blocks_rules_1_to_3():
    out = exit_rule.evaluate(1, total=-45.0, duration_bars=3, adx14=30.0, ema_order="bull")
    assert out["exit"] is False
    assert out["reason"] == exit_rule.MIN_HOLD_GUARD
    assert out["blocked_by_min_hold"] is True
    assert "pending:direction_flip" in out["flags"]


def test_no_trigger_holds():
    out = exit_rule.evaluate(1, total=60.0, duration_bars=10, adx14=35.0, ema_order="bull")
    assert out["exit"] is False and out["reason"] is None
    assert out["low_bars"] == 0


def test_invalid_position_direction_raises():
    with pytest.raises(ValueError):
        exit_rule.evaluate(0, total=10.0)
