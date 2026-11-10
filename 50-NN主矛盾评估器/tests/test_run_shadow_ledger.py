"""run_shadow 决策账本落盘测试（decisions.jsonl + audit/decisions.jsonl）。"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

from adapters import audit_logger
from core import decision as decision_mod
from core import trigger_flap as flap_mod
from tools import run_shadow


def _bus_state(path):
    now = datetime.now(timezone.utc)
    signal = {
        "signal_id": "s1",
        "source": "11-bdsm",
        "symbol": "BTC-USDT-SWAP",
        "granularity": "per_symbol",
        "direction": "long",
        "confidence": 0.8,
        "horizon": "hours",
        "intent": None,
        "ts": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
        "payload": {},
    }
    path.write_text(json.dumps({"signals": [signal]}), encoding="utf-8")
    return path


def test_main_appends_decision_and_audit(tmp_path, monkeypatch):
    ledger = tmp_path / "decisions.jsonl"
    audit = tmp_path / "audit" / "decisions.jsonl"
    flap = tmp_path / "trigger_flap.jsonl"
    monkeypatch.setattr(decision_mod, "_DECISIONS_PATH", ledger)
    monkeypatch.setattr(audit_logger, "DEFAULT_AUDIT_PATH", audit)
    monkeypatch.setattr(flap_mod, "_FLAP_PATH", flap)

    bus = _bus_state(tmp_path / "bus_state.json")
    out_dir = tmp_path / "shadow"
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_shadow.py", "--bus-state", str(bus), "--out-dir", str(out_dir)],
    )

    assert run_shadow.main() == 0

    decisions = [json.loads(x) for x in ledger.read_text(encoding="utf-8").splitlines()]
    assert len(decisions) == 1
    assert decisions[0]["source"] == "50-nn"
    assert decisions[0]["mode"] == "shadow"

    audits = [json.loads(x) for x in audit.read_text(encoding="utf-8").splitlines()]
    assert len(audits) == 1
    assert audits[0]["decision"]["signal_id"] == decisions[0]["signal_id"]

    flaps = [json.loads(x) for x in flap.read_text(encoding="utf-8").splitlines()]
    assert len(flaps) == 1
    assert flaps[0]["symbol"] == "MULTI"
    assert flaps[0]["adopted_trigger"] == "default"
    assert decisions[0]["trigger"] == "default"
    assert decisions[0]["payload"]["trigger_flap"]["locked"] is False


def test_main_without_decision_skips_ledger(tmp_path, monkeypatch):
    ledger = tmp_path / "decisions.jsonl"
    audit = tmp_path / "audit" / "decisions.jsonl"
    flap = tmp_path / "trigger_flap.jsonl"
    monkeypatch.setattr(decision_mod, "_DECISIONS_PATH", ledger)
    monkeypatch.setattr(audit_logger, "DEFAULT_AUDIT_PATH", audit)
    monkeypatch.setattr(flap_mod, "_FLAP_PATH", flap)

    empty = tmp_path / "empty_bus.json"
    empty.write_text(json.dumps({"signals": []}), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_shadow.py", "--bus-state", str(empty), "--out-dir", str(tmp_path / "shadow")],
    )

    assert run_shadow.main() == 0
    assert not ledger.exists()
    assert not audit.exists()
    assert not flap.exists()
