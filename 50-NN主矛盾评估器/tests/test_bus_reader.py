"""R0-06: bus_reader 测试（42 bus_state → evidence）。"""

from __future__ import annotations

import json

from adapters.bus_reader import load_evidences, to_evidence


def test_signal_maps_to_evidence():
    signal = {
        "signal_id": "sig_11-bdsm_BTC_20261108",
        "source": "11-bdsm",
        "ts": "2026-11-08T00:00:00Z",
        "symbol": "BTC-USDT-SWAP",
        "direction": "long",
        "confidence": 0.7,
        "horizon": "days",
        "risk_exposure_hint": 0.2,
        "expires_at": "2026-11-09T00:00:00Z",
        "payload": {"direction_constraint": "long", "dimension_hint": "C6"},
        "shadow": False,
    }
    evidence = to_evidence(signal)
    assert evidence["source"] == "11-bdsm"
    assert evidence["provenance"] == "42-bus"
    assert evidence["dimension_hint"] == "C6"
    assert evidence["granularity"] == "per_symbol"


def test_load_evidences_from_file(tmp_path):
    bus = {
        "bus_id": "bus_test",
        "generated_at": "2026-11-08T00:00:00Z",
        "signal_count": 1,
        "sources": ["11-bdsm"],
        "signals": [
            {
                "signal_id": "s1",
                "source": "11-bdsm",
                "ts": "2026-11-08T00:00:00Z",
                "symbol": "ETH-USDT-SWAP",
                "direction": "long",
                "confidence": 0.6,
                "horizon": "days",
                "expires_at": "2026-11-09T00:00:00Z",
                "payload": {},
            }
        ],
    }
    path = tmp_path / "bus_state.json"
    path.write_text(json.dumps(bus), encoding="utf-8")
    evidences = load_evidences(str(path))
    assert len(evidences) == 1
    assert evidences[0]["symbol"] == "ETH-USDT-SWAP"
    assert evidences[0]["provenance"] == "42-bus"


def test_missing_file_returns_empty(tmp_path):
    assert load_evidences(str(tmp_path / "nope.json")) == []
