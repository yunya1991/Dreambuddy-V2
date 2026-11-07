"""R0-06: shadow_decision + audit_logger 测试。"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from adapters.audit_logger import log_decision
from core.shadow_decision import make_shadow_decision

NOW = datetime(2026, 11, 8, 1, 0, tzinfo=timezone.utc)


def evidence(**over):
    base = {
        "evidence_id": "e1",
        "source": "11-bdsm",
        "symbol": "BTC-USDT-SWAP",
        "granularity": "per_symbol",
        "direction": "long",
        "confidence": 0.8,
        "horizon": "hours",
        "intent": None,
        "ts": "2026-11-08T00:00:00Z",
        "expires_at": "2026-11-08T02:00:00Z",
        "provenance": "42-bus",
        "payload": {},
    }
    base.update(over)
    return base


def test_shadow_decision_long():
    decision = make_shadow_decision([evidence()], {}, now=NOW)
    assert decision["source"] == "50-nn"
    assert decision["shadow"] is True
    assert decision["direction"] == "long"
    assert decision["payload"]["path_count"] == 1


def test_shadow_decision_short():
    decision = make_shadow_decision([evidence(direction="short")], {}, now=NOW)
    assert decision["direction"] == "short"


def test_shadow_decision_applies_position_clamp():
    constraints = {"position_band": [0, 1]}
    decision = make_shadow_decision([evidence()], constraints, now=NOW)
    assert 0.0 <= decision["payload"]["position_pct"] <= 1.0


def test_audit_logger_appends_jsonl(tmp_path):
    audit = tmp_path / "audit.jsonl"
    log_decision({"signal_id": "x", "direction": "long"}, str(audit))
    log_decision({"signal_id": "y", "direction": "short"}, str(audit))
    lines = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    assert lines[0]["decision"]["signal_id"] == "x"
    assert lines[0]["logged_at"]
