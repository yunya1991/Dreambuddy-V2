"""FinalDecisionSignal v1.2 契约测试：23 开/平仓信号必须通过 JSON Schema。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest
from dreambuddy_evolution.execution import (
    EvolutionSignalDispatcher,
    build_entry_decision,
    build_exit_decision,
)

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "49-交易框架协议/contracts/final_decision_signal.v1.2.json"
)
_REQUIRED_PAYLOAD = {
    "action",
    "position_tier",
    "position_mult",
    "d_star",
    "ri",
    "l4_v",
    "regime",
    "primary_contradiction",
    "contradiction_shift",
    "elastic_result",
    "cross_validation",
    "path",
}


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate(schema: dict, signal: dict) -> None:
    jsonschema.validate(instance=signal, schema=schema)


def test_entry_signal_matches_v12(schema):
    now = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
    sig = build_entry_decision(
        symbol="BTC-USDT-SWAP",
        direction="long",
        confidence=0.82,
        notional_usdt=1600.0,
        tier="standard",
        price=100.0,
        atr_pct=0.01,
        d_star="path-42",
        regime="trend",
        primary_contradiction={"dimension": "structure", "direction": "long", "strength": 0.7},
        position_mult=0.8,
        path={"optimal_path": "path-42", "path_score": 0.9},
        now=now,
    )
    _validate(schema, sig)
    assert sig["ts"].endswith("Z")
    assert sig["horizon"] == "hours"
    assert sig["mode"] in {"live", "paper", "shadow"}
    assert 0.0 <= sig["risk_exposure_hint"] <= 1.0
    assert _REQUIRED_PAYLOAD.issubset(sig["payload"])
    assert sig["payload"]["d_star"] == "path-42"
    assert sig["payload"]["position_mult"] == 0.8
    assert sig["payload"]["primary_contradiction"]["dimension"] == "structure"
    assert sig["payload"]["path"]["optimal_path"] == "path-42"


def test_exit_signals_match_v12(schema):
    full = build_exit_decision("BTC-USDT-SWAP", "long", sz=10, reduce_ratio=1.0)
    part = build_exit_decision("ETH-USDT-SWAP", "short", sz=3, reduce_ratio=0.3)
    _validate(schema, full)
    _validate(schema, part)
    assert full["payload"]["action"] == "close"
    assert part["payload"]["action"] == "reduce"
    assert full["payload"]["position_tier"] == "none"
    assert full["payload"]["primary_contradiction"]["dimension"] == "exit"
    assert _REQUIRED_PAYLOAD.issubset(full["payload"])


def test_contract_rejects_missing_rich_fields(schema):
    bad = build_entry_decision("BTC-USDT-SWAP", "long", 0.5, 100.0)
    for key in ("regime", "d_star", "path"):
        bad["payload"].pop(key)
    with pytest.raises(jsonschema.ValidationError):
        _validate(schema, bad)


def test_audit_carries_full_signal(tmp_path, schema):
    dispatcher = EvolutionSignalDispatcher(gateway=None, runtime_dir=tmp_path)
    sig = build_entry_decision("BTC-USDT-SWAP", "long", 0.7, 100.0, d_star="p1")
    dispatcher.dispatch(sig)
    row = json.loads((tmp_path / "execution_decisions.jsonl").read_text().strip().splitlines()[-1])
    assert row["signal"]["signal_id"] == sig["signal_id"]
    _validate(schema, row["signal"])
