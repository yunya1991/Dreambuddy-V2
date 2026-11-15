# -*- coding: utf-8 -*-
"""L1 → 22 `FinalDecisionSignal v1.1` 映射单测（SPEC-54 §4.6 / L1X-01 验收）。"""

import datetime as dt
import json
import os
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg import direction_rule as DR  # noqa: E402
from l1agg import handoff as H  # noqa: E402

_NOW = dt.datetime(2026, 11, 15, 7, 0, tzinfo=dt.timezone.utc)
_RULE_INPUTS = {
    "slope_table": [
        {"window": window, "slope": slope, "se": 0.001, "t": 3.0, "r2": 0.7}
        for window, slope in zip((20, 60, 120, 250), (0.010, 0.008, 0.006, 0.004), strict=True)
    ],
    "adx": {"adx14": 30.0, "plus_di": 28.0, "minus_di": 12.0},
    "ema": {"ema12": 110.0, "ema26": 105.0, "ema50": 100.0, "order": "bull"},
    "same_direction_rate": {"r": 0.8, "n": 30},
    "p_adj": 0.01,
}


def _signal(**overrides):
    record = {
        "as_of": "2026-11-14",
        "symbol": "BTC",
        "rule_version": "dr-1.0.0",
        "params_hash": "b" * 64,
        "direction": 1,
        "strength": 0.94,
        "band": "strong",
        "flags": ["degraded_windows"],
        "seasonality": None,
    }
    record.update(overrides)
    return record


def test_crypto_signal_maps_and_passes_contract():
    decision = H.build_final_decision(_signal(), notional_usdt=200.0, now=_NOW)
    assert decision["source"] == "l1-chart"
    assert decision["symbol"] == "BTC-USDT-SWAP"
    assert decision["direction"] == "long"
    assert decision["confidence"] == 0.94
    assert decision["mode"] == "paper"
    assert decision["expires_at"] == "2026-11-15T07:15:00Z"
    assert decision["payload"]["action"] == "long"
    assert decision["payload"]["position_tier"] == "trend"
    assert decision["payload"]["position_mult"] == 0.94
    assert decision["payload"]["notional_usdt"] == 200.0
    H.validate_final_decision(decision)


def test_k06_decide_band_and_flags_reach_handoff_payload():
    signal = DR.decide(_RULE_INPUTS, as_of="2026-11-14", symbol="BTC")
    decision = H.build_final_decision(signal, now=_NOW)

    assert signal["band"] == "strong"
    assert decision["payload"]["l1_band"] == signal["band"]
    assert decision["payload"]["l1_flags"] == signal["flags"]
    H.validate_final_decision(decision)


def test_flat_maps_to_wait_and_no_tier():
    decision = H.build_final_decision(_signal(direction=0, strength=0.04), now=_NOW)
    assert decision["direction"] == "neutral"
    assert decision["payload"]["action"] == "WAIT"
    assert decision["payload"]["position_tier"] == "none"
    assert decision["payload"]["position_mult"] == 0.0
    assert decision["risk_exposure_hint"] == 0.0


def test_short_maps_to_short():
    decision = H.build_final_decision(_signal(direction=-1, strength=0.6), now=_NOW)
    assert decision["direction"] == "short"
    assert decision["payload"]["position_tier"] == "standard"


def test_non_crypto_asset_is_refused():
    for symbol in ("XAU", "US500", "CL", "VIX"):
        with pytest.raises(H.HandoffError):
            H.execution_symbol(symbol)


def test_decision_id_is_deterministic_and_idempotent():
    first = H.build_final_decision(_signal(), now=_NOW)
    second = H.build_final_decision(_signal(), now=_NOW)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["payload"]["decision_id"].startswith("dec-l1-BTC-2026-11-14-1-dr-1.0.0-")
    other = H.build_final_decision(_signal(params_hash="c" * 64), now=_NOW)
    assert other["payload"]["decision_id"] != first["payload"]["decision_id"]


def test_schema_rejects_broken_decision():
    decision = H.build_final_decision(_signal(), now=_NOW)
    broken = dict(decision, direction="up")
    with pytest.raises(H.HandoffError):
        H.validate_final_decision(broken)
    missing = {
        "signal_id": "x",
        "source": "l1-chart",
        "ts": "2026-11-15T07:00:00Z",
        "symbol": "BTC-USDT-SWAP",
        "direction": "long",
        "confidence": 0.5,
        "horizon": "days",
        "risk_exposure_hint": 0.5,
        "expires_at": "2026-11-15T07:15:00Z",
        "mode": "paper",
        "payload": {"action": "long"},
    }
    with pytest.raises(H.HandoffError):
        H.validate_final_decision(missing)


def test_missing_fields_raise():
    with pytest.raises(H.HandoffError):
        H.build_final_decision(_signal(params_hash=None), now=_NOW)
    with pytest.raises(H.HandoffError):
        H.build_final_decision(_signal(direction=3), now=_NOW)
