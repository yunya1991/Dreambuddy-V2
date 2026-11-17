"""链路事件与信号参数透传测试（TD §13.2–13.4）。"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from dreambuddy_evolution.engines.result_aggregator import ResultAggregator
from dreambuddy_evolution.execution import build_entry_decision
from dreambuddy_evolution.execution.chain_events import emit_stage, event_path


def test_emit_stage_writes_chain_event(tmp_path, monkeypatch):
    monkeypatch.setenv("EVOLUTION_CHAIN_EVENTS_DIR", str(tmp_path))
    ts = datetime(2026, 11, 17, 12, 0, 0, tzinfo=timezone.utc)
    emit_stage(
        "N12",
        "entry_loop.dispatch",
        "BTC-USDT-SWAP",
        "pass",
        chain_id="chain-1",
        decision_id="dec-1",
        trace_id="trace-1",
        duration_ms=3.5,
        data={"action": "open"},
        ts=ts,
    )
    path = event_path(ts)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["schema"] == "chain_event.v1"
    assert rows[0]["stage"] == "N12"
    assert rows[0]["chain_id"] == "chain-1"
    assert rows[0]["data"] == {"action": "open"}


def test_emit_stage_never_raises_on_bad_dir(monkeypatch):
    monkeypatch.setenv("EVOLUTION_CHAIN_EVENTS_DIR", "/dev/null/not-a-dir")
    emit_stage("N1", "test", "BTC", "enter")  # 不应抛异常


def test_build_entry_decision_carries_trace_and_semantics():
    sig = build_entry_decision(
        symbol="BTC-USDT-SWAP",
        direction="long",
        confidence=0.62,
        notional_usdt=120.0,
        tier="standard",
        price=100.0,
        d_star="long",
        ri=0.62,
        l4_v=0.11,
        regime="TREND_UP",
        primary_contradiction={"dimension": "structure", "direction": "long", "strength": 0.6},
        cross_validation={"confidence_mult": 0.8},
        elastic_result={"constraint_active": False},
        trace_id="trace-9",
    )
    assert sig["payload"]["ri"] == 0.62
    assert sig["payload"]["l4_v"] == 0.11
    assert sig["payload"]["regime"] == "TREND_UP"
    assert sig["payload"]["trace_id"] == "trace-9"


def test_result_aggregator_passes_ri_and_regime(tmp_path, monkeypatch):
    monkeypatch.setenv("EVOLUTION_CHAIN_EVENTS_DIR", str(tmp_path))
    captured = {}

    def _cb(**kwargs):
        captured.update(kwargs)

    agg = ResultAggregator(build_position_callback=_cb, router=object())
    agg.trigger_build_position(
        "BTC-USDT-SWAP",
        "long",
        "long",
        0.66,
        0.7,
        "standard",
        price=100.0,
        regime="TREND_UP",
        l4_v=0.2,
        trace_id="trace-agg",
    )
    sig = captured["signal"]
    assert sig["payload"]["ri"] == 0.66
    assert sig["payload"]["l4_v"] == 0.2
    assert sig["payload"]["regime"] == "TREND_UP"
    assert sig["payload"]["trace_id"] == "trace-agg"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
