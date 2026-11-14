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


def test_dynamic_allowlist_uses_bus_confidence_and_registry():
    """置信度 ≥0.8 的 long/short 且注册表内可交易的标的才进 allowlist。"""
    now = datetime.now(timezone.utc)
    fresh = [
        {
            "symbol": "ARB",
            "direction": "long",
            "confidence": 0.9,
            "expires_at": (now + timedelta(hours=1)).isoformat(),
        },
        {
            "symbol": "ETH",
            "direction": "long",
            "confidence": 0.7,
            "expires_at": (now + timedelta(hours=1)).isoformat(),
        },
        {
            "symbol": "SNDK",
            "direction": "long",
            "confidence": 0.99,
            "expires_at": (now + timedelta(hours=1)).isoformat(),
        },
        {
            "symbol": "MACRO",
            "direction": "short",
            "confidence": 0.8,
            "expires_at": (now + timedelta(hours=1)).isoformat(),
        },
        {
            "symbol": "XAG",
            "direction": "short",
            "confidence": 0.85,
            "expires_at": (now + timedelta(hours=1)).isoformat(),
        },
    ]
    assert run_live._dynamic_allowlist(fresh) == {"ARB-USDT-SWAP", "XAG-USDT-SWAP"}


def test_run_uses_dynamic_allowlist_when_symbols_empty(monkeypatch, tmp_path):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(
        run_live,
        "load_evidences",
        lambda _: [
            {
                "signal_id": "s1",
                "symbol": "ARB",
                "direction": "long",
                "confidence": 0.9,
                "expires_at": (now + timedelta(hours=1)).isoformat(),
            },
            {
                "signal_id": "s2",
                "symbol": "ETH",
                "direction": "long",
                "confidence": 0.6,
                "expires_at": (now + timedelta(hours=1)).isoformat(),
            },
        ],
    )
    monkeypatch.setattr(run_live, "load_rights", lambda: {"symbols": {}})
    monkeypatch.setattr(run_live, "load_constraints", lambda: {})
    monkeypatch.setattr(run_live, "is_kill_switch_on", lambda: False)
    monkeypatch.setattr(run_live, "propagate_resonance", lambda d, e, c: d)
    seen = []

    def fake_decision(evidences, **kwargs):
        seen.append((kwargs["symbol"], kwargs["asset_class"]))
        return {
            "signal_id": "50-nn|x",
            "symbol": kwargs["symbol"],
            "direction": "long",
            "execution": {"outcome": "live:50-bypass", "allowed": True},
        }

    monkeypatch.setattr(run_live, "make_decision", fake_decision)
    result = run_live.run(tmp_path / "bus.json", tmp_path / "out", (), "m-1")
    assert result["allowlist"] == ["ARB-USDT-SWAP"]
    assert seen == [("ARB-USDT-SWAP", "crypto")]


def test_run_respects_kill_switch(monkeypatch, tmp_path):
    monkeypatch.setattr(run_live, "is_kill_switch_on", lambda: True)
    result = run_live.run(tmp_path / "bus.json", tmp_path / "out", ("BTC-USDT-SWAP",), "m-1")
    assert result["status"] == "skipped"
    assert "kill" in result["reason"].lower()


def test_run_declares_small_notional_and_records_overlay_meta(monkeypatch, tmp_path):
    """M4-4：小额名义上限与灰度参数随决策落盘，供 22 执行与事后归因。"""
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
            "signal_id": "50-nn|BTC-USDT-SWAP|1",
            "symbol": "BTC-USDT-SWAP",
            "direction": "long",
            "payload": {},
            "execution": {"outcome": "live:50-bypass", "allowed": True},
        },
    )

    result = run_live.run(
        tmp_path / "bus.json", tmp_path / "out", ("BTC-USDT-SWAP",), "m-1", notional_usdt=20.0
    )
    assert result["notional_usdt"] == 20.0
    assert set(result["overlay"]) == {"enabled", "coef", "coef_source"}

    row = json.loads(
        (tmp_path / "out" / "outbox.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert row["notional_usdt"] == 20.0
    assert row["payload"]["notional_usdt"] == 20.0
