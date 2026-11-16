# -*- coding: utf-8 -*-
"""L1-D `direction_rule` 纯函数单测（SPEC-54 §4.7 / L1D-01 验收）。"""

import json
import os
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg import direction_rule as DR  # noqa: E402


def _slopes(*slopes, t_sign=None):
    windows = (20, 60, 120, 250)
    rows = []
    for window, slope in zip(windows, slopes, strict=False):
        if slope is None:
            rows.append({"window": window, "slope": None, "se": None, "t": None, "r2": None})
            continue
        sign = 1 if slope > 0 else -1
        t = (sign if t_sign is None else t_sign) * 3.0
        rows.append({"window": window, "slope": slope, "se": 0.001, "t": t, "r2": 0.7})
    return rows


_LONG = {
    "slope_table": _slopes(0.010, 0.008, 0.006, 0.004),
    "adx": {"adx14": 30.0, "plus_di": 28.0, "minus_di": 12.0},
    "ema": {"ema12": 110.0, "ema26": 105.0, "ema50": 100.0, "order": "bull"},
    "same_direction_rate": {"r": 0.8, "n": 30},
    "p_adj": 0.01,
}

_SHORT = {
    "slope_table": _slopes(-0.010, -0.008, -0.006, -0.004),
    "adx": {"adx14": 30.0, "plus_di": 10.0, "minus_di": 30.0},
    "ema": {"ema12": 90.0, "ema26": 95.0, "ema50": 100.0, "order": "bear"},
    "same_direction_rate": {"r": 0.9, "n": 30},
    "p_adj": 0.01,
}


def test_params_yaml_and_hash_stable():
    params = DR.load_params()
    assert params["version"] == "dr-1.1.0"
    assert params["windows"] == [20, 60, 120, 250]
    assert len(DR.params_hash(params)) == 64
    assert DR.params_hash(params) == DR.params_hash(dict(params))
    changed = dict(params, flat_threshold=31)
    assert DR.params_hash(changed) != DR.params_hash(params)


def test_validate_params_rejects_bad_weights():
    params = dict(DR.DEFAULT_PARAMS)
    params["window_weights"] = [0.15, 0.25, 0.30]
    with pytest.raises(DR.DirectionRuleError):
        DR.validate_params(params)


def test_long_four_axes_matches_spec():
    record = DR.decide(_LONG, as_of="2026-11-14", symbol="BTC")
    assert record["axes"] == {"trend": 40.0, "adx": 25.0, "inertia": 20.0, "coherence": 9.0}
    assert record["total"] == 94.0
    assert record["direction"] == 1
    assert record["strength"] == 0.94
    assert record["band"] == "strong"
    assert record["rule_version"] == "dr-1.1.0"
    assert "flat" not in record["flags"]


def test_flat_below_threshold():
    inputs = {
        "slope_table": _slopes(0.01, -0.01, 0.01, -0.01),
        "adx": {"adx14": 18.0, "plus_di": 20.0, "minus_di": 15.0},
        "ema": {"ema12": 100.0, "ema26": 100.0, "ema50": 100.0, "order": "mixed"},
        "same_direction_rate": {"r": 0.5, "n": 30},
    }
    record = DR.decide(inputs)
    assert record["total"] == 4.0
    assert record["direction"] == 0
    assert record["strength"] == 0.04
    assert record["band"] == "flat"
    assert "flat" in record["flags"]


def test_short_direction():
    record = DR.decide(_SHORT)
    assert record["axes"]["trend"] == -40.0
    assert record["axes"]["adx"] == -25.0
    assert record["axes"]["inertia"] == -20.0
    assert record["axes"]["coherence"] == -12.0
    assert record["total"] == -97.0
    assert record["direction"] == -1
    assert record["band"] == "strong"


def test_degraded_inputs_never_raise():
    record = DR.decide({})
    assert record["total"] == 0.0
    assert record["direction"] == 0
    assert record["strength"] == 0.0
    for flag in ("trend_data_missing", "adx_missing", "ema_missing", "coherence_missing"):
        assert flag in record["flags"]


def test_missing_window_normalises_and_flags():
    inputs = dict(_LONG, slope_table=_slopes(0.010, 0.008, None, None))
    record = DR.decide(inputs)
    assert record["axes"]["trend"] == 40.0
    assert "degraded_windows" in record["flags"]


def test_sign_mismatch_counts_as_inconsistent():
    inputs = dict(_LONG, slope_table=_slopes(0.01, 0.008, 0.006, 0.004, t_sign=-1))
    record = DR.decide(inputs)
    assert record["axes"]["trend"] == 0.0


def test_hac_insignificant_halves_strength_axis():
    record = DR.decide(dict(_LONG, p_adj=0.20))
    assert record["axes"]["adx"] == 12.5
    assert "hac_insignificant" in record["flags"]


def test_significance_missing_is_flagged_not_silently_skipped():
    inputs = dict(_LONG)
    inputs.pop("p_adj")
    record = DR.decide(inputs)
    assert record["axes"]["adx"] == 25.0
    assert "significance_unavailable" in record["flags"]


def test_ema_order_derived_when_missing():
    inputs = dict(_LONG, ema={"ema12": 110.0, "ema26": 105.0, "ema50": 100.0})
    record = DR.decide(inputs)
    assert record["axes"]["inertia"] == 20.0
    assert "ema_order_derived" in record["flags"]


def test_seasonality_recorded_not_scored():
    deep = dict(_LONG, seasonality={"month_effect": 0.02, "depth_years": 7.0})
    shallow = dict(_LONG, seasonality={"month_effect": 0.02, "depth_years": 3.0})
    assert DR.decide(deep)["seasonality"] == {"depth_years": 7.0, "month_effect": 0.02}
    assert DR.decide(deep)["total"] == DR.decide(shallow)["total"]
    assert DR.decide(shallow)["seasonality"] is None
    assert "seasonality_depth_lt_5y" in DR.decide(shallow)["flags"]


def test_flat_threshold_is_applied_to_total():
    params = dict(DR.DEFAULT_PARAMS, flat_threshold=95)
    assert DR.decide(_LONG, params)["direction"] == 0
    assert DR.decide(_LONG, params)["band"] == "strong"


def test_replay_bytes_identical():
    first = json.dumps(DR.decide(_LONG, as_of="2026-11-14", symbol="BTC"), sort_keys=True)
    second = json.dumps(DR.decide(_LONG, as_of="2026-11-14", symbol="BTC"), sort_keys=True)
    assert first == second
    payload = json.loads(first)
    assert payload["params_hash"] == DR.params_hash(DR.DEFAULT_PARAMS)
    assert payload["inputs_snapshot"]["slope_table"][0]["window"] == 20


# ---------------- §4.12/§4.13：gap 轴 · MIDAS · strength 模式 ----------------


def _gap_params():
    params = dict(DR.DEFAULT_PARAMS)
    params["axis_weights"] = dict(params["axis_weights"], gap=10)
    params["gap_axis"] = dict(params["gap_axis"], enabled=True)
    return params


def test_gap_axis_disabled_by_default_keeps_four_axes():
    record = DR.decide(dict(_LONG, equilibrium_gap={"gap_z": 3.0}))
    assert set(record["axes"]) == {"trend", "adx", "inertia", "coherence"}
    assert record["axis_weights"] == {
        "trend": 40.0,
        "adx": 25.0,
        "inertia": 20.0,
        "coherence": 15.0,
    }
    assert record["total"] == 94.0


def test_gap_axis_mean_reversion_sign_and_clip():
    params = _gap_params()
    high = DR.decide(dict(_LONG, equilibrium_gap={"gap_z": 2.0}), params)
    assert high["axes"]["gap"] == -10.0
    assert high["total"] == 84.0
    assert high["axis_weights"]["gap"] == 10.0
    mild = DR.decide(dict(_LONG, equilibrium_gap={"gap_z": -0.5}), params)
    assert mild["axes"]["gap"] == 5.0


def test_gap_axis_missing_input_degrades_without_axis():
    record = DR.decide(_LONG, _gap_params())
    assert "gap" not in record["axes"]
    assert "gap_missing" in record["flags"]
    assert record["total"] == 94.0


def test_midas_switch_rewrites_window_weights_deterministically():
    params = dict(DR.DEFAULT_PARAMS, midas={"enabled": True, "theta1": 1.0, "theta2": 3.0})
    record = DR.decide(_LONG, params)
    assert "midas_weights" in record["flags"]
    assert record["axes"]["trend"] == 40.0
    assert DR.decide(_LONG, params) == record


def test_strength_mode_quantile_dispersion_uses_i36():
    params = dict(DR.DEFAULT_PARAMS, strength_mode="quantile_dispersion", dispersion_ref=0.1)
    record = DR.decide(
        dict(_LONG, forward_distribution={"q10": 0.01, "q90": 0.06, "dispersion": 0.05}),
        params,
    )
    assert record["strength"] == 0.5
    assert "strength_from_dispersion" in record["flags"]
    missing = DR.decide(_LONG, params)
    assert "forward_distribution_missing" in missing["flags"]
    assert missing["strength"] == 0.94


def test_validate_rejects_bad_axis_weights_and_strength_mode():
    bad = dict(
        DR.DEFAULT_PARAMS, axis_weights={"trend": -1, "adx": 0, "inertia": 0, "coherence": 0}
    )
    with pytest.raises(DR.DirectionRuleError):
        DR.validate_params(bad)
    with pytest.raises(DR.DirectionRuleError):
        DR.validate_params(dict(DR.DEFAULT_PARAMS, strength_mode="unknown"))
