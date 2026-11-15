# -*- coding: utf-8 -*-
"""L1D-08 动态轴权重单测（ADR-V18/V19：默认关闭 + 等权否决）。"""

import math
import os
import sys

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.trading import weights  # noqa: E402

_N = 300
_FWD = [0.01 * math.sin(i / 5.0) for i in range(_N)]
_AXES = {
    "trend": _FWD,
    "adx": [0.01 * math.cos(i / 5.0) for i in range(_N)],
    "inertia": [0.01 * (-1) ** i for i in range(_N)],
    "coherence": [0.01 * math.cos(i / 7.0) for i in range(_N)],
}
_GOOD_EXCESS = [0.001 + 0.0002 * math.sin(i) for i in range(_N)]
_BAD_EXCESS = [-0.001 + 0.0002 * math.sin(i) for i in range(_N)]


def test_disabled_returns_static_weights():
    out = weights.dynamic_weights(_AXES, _FWD)
    assert out["enabled"] is False
    assert out["weights"] == weights.STATIC_WEIGHTS
    assert out["weight_fallback"] is False
    assert "dynamic_disabled" in out["flags"]
    assert out["weights_hash"] == weights.weights_hash(weights.STATIC_WEIGHTS)


def test_oos_gate_requires_sample_and_significance():
    assert weights.oos_gate(None)["passed"] is False
    weak = weights.oos_gate(_GOOD_EXCESS[:100])  # n < 250
    assert weak["passed"] is False and weak["reason"] == "insufficient_oos"
    bad = weights.oos_gate(_BAD_EXCESS)
    assert bad["passed"] is False and bad["reason"] == "excess_not_positive"
    good = weights.oos_gate(_GOOD_EXCESS)
    assert good["passed"] is True and good["p_value"] < weights.ALPHA


def test_fallback_to_equal_when_gate_fails():
    out = weights.dynamic_weights(_AXES, _FWD, enabled=True, oos_excess=_BAD_EXCESS)
    assert out["weight_fallback"] is True
    assert out["weights"] == weights.EQUAL_WEIGHTS
    assert "weight_fallback" in out["flags"]
    assert out["gate"]["passed"] is False


def test_dynamic_weights_bounded_and_dominant_axis():
    out = weights.dynamic_weights(_AXES, _FWD, enabled=True, oos_excess=_GOOD_EXCESS)
    w = out["weights"]
    assert out["weight_fallback"] is False
    assert sum(w.values()) == 1.0 or abs(sum(w.values()) - 1.0) < 1e-6
    for axis in weights.AXES:
        assert weights.MIN_WEIGHT - 1e-9 <= w[axis] <= weights.MAX_WEIGHT + 1e-9
    assert w["trend"] == max(w.values())
    assert out["weights_hash"] == weights.weights_hash(w)
    assert out["turnover"] <= weights.MAX_TURNOVER + 1e-9


def test_turnover_is_capped_against_previous_weights():
    out = weights.dynamic_weights(
        _AXES,
        _FWD,
        enabled=True,
        oos_excess=_GOOD_EXCESS,
        previous_weights=weights.EQUAL_WEIGHTS,
    )
    assert out["turnover"] <= weights.MAX_TURNOVER + 1e-9
    assert 0.0 < out["turnover"] <= 0.15


def test_dynamic_weights_are_deterministic():
    first = weights.dynamic_weights(_AXES, _FWD, enabled=True, oos_excess=_GOOD_EXCESS)
    second = weights.dynamic_weights(_AXES, _FWD, enabled=True, oos_excess=_GOOD_EXCESS)
    assert first == second


# ---------------- SPEC §4.13：先验×IC/σ · 部分调整 · 周度冻结 · 回放锁 · 不确定性 ----------------


def test_axis_reliability_uses_ic_over_sigma():
    rel = weights.axis_reliability(_AXES, _FWD)
    assert set(rel) == set(weights.AXES)
    assert rel["trend"]["ic"] > 0.99
    assert rel["trend"]["reliability"] > rel["inertia"]["reliability"]
    assert rel["inertia"]["sigma"] > 0.0


def test_weight_sources_and_axis_weights_are_published():
    out = weights.dynamic_weights(_AXES, _FWD, enabled=True, oos_excess=_GOOD_EXCESS)
    assert out["weights_version"] == weights.WEIGHTS_VERSION
    assert out["rebalance"] == "W-MON"
    sources = out["weight_sources"]
    for key in ("prior", "ic", "sigma", "reliability", "uncertainty", "stability"):
        assert key in sources
    assert set(out["axis_weights"]) == set(weights.AXES) | {"gap"}
    assert out["axis_weights"]["gap"] == 0.0
    assert sources["prior"]["trend"] == weights.PRIOR_WEIGHTS["trend"]
    # 估计窗口不足 500 日必须显式披露（expanding window）
    assert "estimation_window_lt_500" in out["flags"]


def test_partial_adjustment_limits_single_step_move():
    """α=0.1：一次调仓最多走 10% 的差距，防止权重跳变。"""
    out = weights.dynamic_weights(_AXES, _FWD, enabled=True, oos_excess=_GOOD_EXCESS)
    target_move = out["weights"]["trend"] - weights.STATIC_WEIGHTS["trend"]
    assert abs(target_move) <= 0.1 * weights.STATIC_WEIGHTS["trend"] + 1e-9


def test_weekly_freeze_between_rebalances():
    assert weights.is_rebalance_day("2026-11-16") is True
    assert weights.is_rebalance_day("2026-11-17") is False
    frozen = weights.dynamic_weights(
        _AXES,
        _FWD,
        enabled=True,
        oos_excess=_GOOD_EXCESS,
        previous_weights=weights.EQUAL_WEIGHTS,
        as_of="2026-11-17",
        last_effective_date="2026-11-16",
    )
    assert frozen["frozen"] is True
    assert frozen["weights"] == weights.EQUAL_WEIGHTS
    assert frozen["turnover"] == 0.0
    assert "weights_frozen" in frozen["flags"]
    assert frozen["weights_effective_date"] == "2026-11-16"


def test_replay_lock_never_adjusts_weights():
    locked = weights.dynamic_weights(
        _AXES,
        _FWD,
        enabled=True,
        oos_excess=_GOOD_EXCESS,
        replay_locked=True,
        previous_weights=weights.STATIC_WEIGHTS,
    )
    assert locked["frozen"] is True
    assert locked["weights"] == weights.STATIC_WEIGHTS
    assert "weights_locked_replay" in locked["flags"]


def test_uncertainty_shrinks_weights_toward_prior():
    base = weights.dynamic_weights(_AXES, _FWD, enabled=True, oos_excess=_GOOD_EXCESS)
    high = weights.dynamic_weights(
        _AXES, _FWD, enabled=True, oos_excess=_GOOD_EXCESS, uncertainty=1.0
    )
    assert "uncertainty_shrink" in high["flags"]
    assert high["weight_sources"]["uncertainty"] == 0.5
    prior_trend = weights.PRIOR_WEIGHTS["trend"]
    assert (
        abs(high["weights"]["trend"] - prior_trend)
        <= abs(base["weights"]["trend"] - prior_trend) + 1e-9
    )


def test_weights_hash_reproduces_identical_weights():
    out = weights.dynamic_weights(_AXES, _FWD, enabled=True, oos_excess=_GOOD_EXCESS)
    again = weights.dynamic_weights(_AXES, _FWD, enabled=True, oos_excess=_GOOD_EXCESS)
    assert out["weights_hash"] == again["weights_hash"]
    assert out["weights_hash"] == weights.weights_hash(out["weights"])
