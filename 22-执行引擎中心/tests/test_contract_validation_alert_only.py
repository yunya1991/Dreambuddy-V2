"""22 网关 v1.2 契约校验（alert-only）测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_GW_DIR = Path(__file__).resolve().parents[1]
if str(_GW_DIR) not in sys.path:
    sys.path.insert(0, str(_GW_DIR))

from trade_execution_gateway import TradeExecutionGateway  # noqa: E402


def _valid_v12() -> dict:
    return {
        "signal_id": "23-evolution|d1",
        "decision_id": "d1",
        "source": "23-evolution",
        "ts": "2026-11-17T12:00:00Z",
        "symbol": "BTC-USDT-SWAP",
        "direction": "long",
        "confidence": 0.8,
        "horizon": "hours",
        "risk_exposure_hint": 0.5,
        "expires_at": "2026-11-17T12:15:00Z",
        "mode": "live",
        "action": "open",
        "pos_side": "long",
        "sl_px": 90.0,
        "tp_px": 120.0,
        "payload": {
            "action": "open",
            "position_tier": "standard",
            "position_mult": 1.0,
            "d_star": "p1",
            "ri": 0.1,
            "l4_v": 0.2,
            "regime": "trend",
            "primary_contradiction": {
                "dimension": "structure",
                "direction": "long",
                "strength": 0.6,
            },
            "contradiction_shift": {},
            "elastic_result": {},
            "cross_validation": {},
            "path": {"optimal_path": "p1"},
        },
    }


def _gateway(tmp_path) -> TradeExecutionGateway:
    gw = TradeExecutionGateway(shadow_only=True, audit_path=tmp_path / "audit" / "gateway.jsonl")
    gw._submit_impl = lambda sig: "SUBMITTED"  # type: ignore[method-assign]
    gw._record_ledger = lambda sig, res: None  # type: ignore[method-assign]
    return gw


def _violations(tmp_path) -> list[dict]:
    path = tmp_path / "audit" / "contract_violations.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_valid_signal_has_no_violation(tmp_path):
    gw = _gateway(tmp_path)
    assert gw.submit(_valid_v12()) == "SUBMITTED"
    assert _violations(tmp_path) == []


def test_invalid_signal_alerts_but_still_submits(tmp_path):
    bad = _valid_v12()
    bad["payload"].pop("regime")
    gw = _gateway(tmp_path)
    assert gw.submit(bad) == "SUBMITTED"
    records = _violations(tmp_path)
    assert len(records) == 1
    assert records[0]["mode"] == "alert"
    assert any("regime" in e for e in records[0]["errors"])


def test_non_23_source_only_checks_core_fields(tmp_path):
    legacy = {
        "signal_id": "50|n1",
        "source": "50-nn",
        "symbol": "ETH-USDT-SWAP",
        "direction": "short",
        "confidence": 0.6,
        "expires_at": "2026-11-17T12:15:00Z",
    }
    gw = _gateway(tmp_path)
    assert gw.submit(legacy) == "SUBMITTED"
    assert _violations(tmp_path) == []


def test_non_23_missing_core_is_recorded(tmp_path):
    gw = _gateway(tmp_path)
    gw.submit({"signal_id": "x", "source": "50-nn", "symbol": "BTC-USDT-SWAP"})
    records = _violations(tmp_path)
    assert len(records) == 1
    assert any("missing:direction" in e for e in records[0]["errors"])
