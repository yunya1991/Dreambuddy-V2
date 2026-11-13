"""50 run_live 调度入口测试（过滤过期证据 + live 决策落盘）。"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_50_ROOT = Path(__file__).resolve().parents[1]
for p in (str(_50_ROOT), str(_50_ROOT / "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

import run_live  # noqa: E402


def _evidence(symbol: str, expires_at: datetime) -> dict:
    return {
        "signal_id": f"sig-{symbol}",
        "symbol": symbol,
        "expires_at": expires_at.isoformat(),
    }


def test_run_skips_when_all_evidences_expired(monkeypatch, tmp_path):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(
        run_live, "load_evidences", lambda _: [_evidence("BTC", now - timedelta(hours=1))]
    )
    result = run_live.run(tmp_path / "bus.json", tmp_path / "out", ("BTC-USDT-SWAP",), "m-1")
    assert result["status"] == "skipped"
    assert result["fresh_evidence_count"] == 0
    assert not (tmp_path / "out" / "outbox.jsonl").exists()


def test_run_emits_live_decision_for_fresh_evidence(monkeypatch, tmp_path):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(
        run_live, "load_evidences", lambda _: [_evidence("BTC", now + timedelta(hours=1))]
    )
    monkeypatch.setattr(run_live, "load_rights", lambda: {"symbols": {}})
    monkeypatch.setattr(run_live, "load_constraints", lambda: {})
    monkeypatch.setattr(run_live, "is_kill_switch_on", lambda: False)

    def fake_decision(evidences, **kwargs):
        assert kwargs["mode"] == "live"
        assert kwargs["symbol"] == "BTC-USDT-SWAP"
        return {
            "signal_id": "50-nn|BTC-USDT-SWAP|1",
            "symbol": "BTC-USDT-SWAP",
            "direction": "long",
            "execution": {"outcome": "live:50-bypass", "allowed": True},
        }

    monkeypatch.setattr(run_live, "make_decision", fake_decision)
    result = run_live.run(tmp_path / "bus.json", tmp_path / "out", ("BTC-USDT-SWAP",), "m-1")
    assert result["status"] == "ok"
    assert len(result["decisions"]) == 1
    rows = (tmp_path / "out" / "outbox.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(rows[0])["decision_id"].startswith("50-nn|")


def test_decision_id_stable_across_runs_for_same_evidence(monkeypatch, tmp_path):
    """同一批证据重复调度必须得到同一 decision_id（22 幂等依赖）。"""
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(
        run_live, "load_evidences", lambda _: [_evidence("BTC", now + timedelta(hours=1))]
    )
    monkeypatch.setattr(run_live, "load_rights", lambda: {"symbols": {}})
    monkeypatch.setattr(run_live, "load_constraints", lambda: {})
    monkeypatch.setattr(run_live, "is_kill_switch_on", lambda: False)
    monkeypatch.setattr(
        run_live,
        "make_decision",
        lambda evidences, **kwargs: {
            "signal_id": "50-nn|ephemeral",
            "symbol": "BTC-USDT-SWAP",
            "direction": "long",
            "execution": {"outcome": "live:50-bypass", "allowed": True},
        },
    )

    first = run_live.run(tmp_path / "bus.json", tmp_path / "out", ("BTC-USDT-SWAP",), "m-1")
    second = run_live.run(tmp_path / "bus.json", tmp_path / "out", ("BTC-USDT-SWAP",), "m-1")
    assert first["decisions"][0]["decision_id"] == second["decisions"][0]["decision_id"]


def test_decision_id_changes_when_evidence_changes(monkeypatch, tmp_path):
    now = datetime.now(timezone.utc)
    evidences = [_evidence("BTC", now + timedelta(hours=1))]
    monkeypatch.setattr(run_live, "load_evidences", lambda _: list(evidences))
    monkeypatch.setattr(run_live, "load_rights", lambda: {"symbols": {}})
    monkeypatch.setattr(run_live, "load_constraints", lambda: {})
    monkeypatch.setattr(run_live, "is_kill_switch_on", lambda: False)
    monkeypatch.setattr(
        run_live,
        "make_decision",
        lambda evidences, **kwargs: {
            "signal_id": "50-nn|ephemeral",
            "symbol": "BTC-USDT-SWAP",
            "direction": "long",
            "execution": {"outcome": "live:50-bypass", "allowed": True},
        },
    )

    first = run_live.run(tmp_path / "bus.json", tmp_path / "out", ("BTC-USDT-SWAP",), "m-1")
    evidences.append(
        {
            "signal_id": "sig-BTC-extra",
            "symbol": "BTC",
            "expires_at": (now + timedelta(hours=1)).isoformat(),
        }
    )
    second = run_live.run(tmp_path / "bus.json", tmp_path / "out", ("BTC-USDT-SWAP",), "m-1")
    assert first["decisions"][0]["decision_id"] != second["decisions"][0]["decision_id"]


def test_run_respects_kill_switch(monkeypatch, tmp_path):
    monkeypatch.setattr(run_live, "is_kill_switch_on", lambda: True)
    result = run_live.run(tmp_path / "bus.json", tmp_path / "out", ("BTC-USDT-SWAP",), "m-1")
    assert result["status"] == "skipped"
    assert "kill" in result["reason"].lower()
