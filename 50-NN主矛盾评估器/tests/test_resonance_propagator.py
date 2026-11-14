"""M4 共振传导：龙头同向放大、反向衰减、时滞/降级跳过。"""

from __future__ import annotations

import sys
from pathlib import Path

_50_ROOT = Path(__file__).resolve().parents[1]
if str(_50_ROOT) not in sys.path:
    sys.path.insert(0, str(_50_ROOT))

from core.resonance_propagator import propagate  # noqa: E402
from core.resonance_sensor import SensorSnapshot  # noqa: E402


class FakeSensor:
    def __init__(self, snap: SensorSnapshot):
        self.snap = snap

    def get_snapshot(self, symbol: str) -> SensorSnapshot:
        return self.snap


def _snap(corr0=0.9, down_corr=0.8, t_arrive=0.5, degraded=None) -> SensorSnapshot:
    return SensorSnapshot(
        symbol="ETH/USDT",
        r={
            "corr0": corr0,
            "lag_profile": [],
            "beta": 1.0,
            "down_corr": down_corr,
            "granger_p": 0.05,
        },
        f_macro={"D1": 0.1, "D2": 0.0, "D4": 0.0, "washout": 0.0},
        t_arrive=t_arrive,
        regime_overlay="range",
        layer="L1_anchor",
        degraded=degraded or [],
        cache_age_sec=0.1,
    )


def _decision(direction="long", confidence=0.6, symbol="ETH-USDT-SWAP"):
    return {"symbol": symbol, "direction": direction, "confidence": confidence}


def _leader(direction="long"):
    return [{"symbol": "BTC", "direction": direction, "confidence": 0.8}]


def test_same_direction_amplifies_confidence():
    d = _decision(confidence=0.6)
    out = propagate(d, _leader("long"), "crypto_usdt", FakeSensor(_snap()))
    assert out["confidence"] == 0.681
    res = out["payload"]["resonance"]
    assert res["applied"] is True and res["multiplier"] == 1.135


def test_opposite_direction_damps_confidence():
    d = _decision(confidence=0.6)
    out = propagate(d, _leader("short"), "crypto_usdt", FakeSensor(_snap()))
    assert out["confidence"] == 0.528
    assert out["payload"]["resonance"]["multiplier"] == 0.88


def test_leader_symbol_itself_not_propagated():
    d = _decision(confidence=0.6, symbol="BTC-USDT-SWAP")
    out = propagate(d, _leader("long"), "crypto_usdt", FakeSensor(_snap()))
    assert out["confidence"] == 0.6
    assert out["payload"]["resonance"]["applied"] is False


def test_degraded_sensor_skips():
    d = _decision(confidence=0.6)
    out = propagate(
        d, _leader("long"), "crypto_usdt", FakeSensor(_snap(degraded=["symbol_not_in_layers"]))
    )
    assert out["confidence"] == 0.6


def test_lag_too_long_skips():
    d = _decision(confidence=0.6)
    out = propagate(d, _leader("long"), "crypto_usdt", FakeSensor(_snap(t_arrive=5.0)))
    assert out["confidence"] == 0.6
    assert out["payload"]["resonance"]["skip_reason"] == "lag_too_long"


def test_no_leader_evidence_skips():
    d = _decision(confidence=0.6)
    out = propagate(d, [], "crypto_usdt", FakeSensor(_snap()))
    assert out["confidence"] == 0.6
    assert out["payload"]["resonance"]["leader_direction"] is None
