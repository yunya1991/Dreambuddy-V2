#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""源头无有效信号不发布（29-event 无事件 / 40-cycle 无技术锚数据）。"""

import json
import os
import sys
from datetime import datetime, timezone

import pytest

_42_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ADAPTERS = os.path.join(_42_ROOT, "adapters")
for _p in (_42_ROOT, _ADAPTERS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import cycle_state_adapter  # noqa: E402
import event_driven_adapter  # noqa: E402
import signal_bus  # noqa: E402


def _now():
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def bus_path(monkeypatch, tmp_path):
    path = str(tmp_path / "bus.json")
    monkeypatch.setattr(signal_bus, "_BUS_STATE_PATH", path)
    monkeypatch.setenv("SIGNAL_BUS_PERSIST", "1")
    return path


# ── 29-event：event_type=none → 不发布 ──
def test_event_none_not_published(monkeypatch, tmp_path, bus_path, capsys):
    state = {
        "symbol": "BTC",
        "updated_at": _now(),
        "signal": {"signal": "neutral", "strength": 0.0, "event_type": "none"},
    }
    state_path = tmp_path / "event_driven_state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(event_driven_adapter, "_29_STATE_PATH", str(state_path))

    rc = event_driven_adapter.main()
    assert rc == 1
    assert not os.path.exists(bus_path), "无事件不应写总线"
    assert "无有效事件" in capsys.readouterr().out


# ── 29-event：event_type 缺失 → 不发布 ──
def test_event_missing_type_not_published(monkeypatch, tmp_path, bus_path):
    state = {
        "symbol": "BTC",
        "updated_at": _now(),
        "signal": {"signal": "long", "strength": 0.7},
    }
    state_path = tmp_path / "event_driven_state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(event_driven_adapter, "_29_STATE_PATH", str(state_path))

    assert event_driven_adapter.main() == 1
    assert not os.path.exists(bus_path)


# ── 29-event：真实事件 → 正常发布 ──
def test_event_present_published(monkeypatch, tmp_path, bus_path):
    state = {
        "symbol": "BTC",
        "updated_at": _now(),
        "signal": {"signal": "long", "strength": 0.7, "event_type": "FOMC"},
    }
    state_path = tmp_path / "event_driven_state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(event_driven_adapter, "_29_STATE_PATH", str(state_path))

    assert event_driven_adapter.main() == 0
    with open(bus_path, encoding="utf-8") as f:
        bus = json.load(f)
    assert bus["signal_count"] == 1
    assert bus["signals"][0]["payload"]["event_type"] == "FOMC"


# ── 40-cycle：无技术锚资产（assets 空）→ 不发布 ──
def test_cycle_no_assets_not_published(monkeypatch, tmp_path, bus_path, capsys):
    state = {
        "real_cycle": {"state": "plateau", "confidence": "medium"},
        "technical_anchor": {"assets": {}},
        "generated_at": _now(),
    }
    state_path = tmp_path / "cycle_state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(cycle_state_adapter, "_40_STATE_PATH", str(state_path))

    rc = cycle_state_adapter.main()
    assert rc == 1
    assert not os.path.exists(bus_path)
    assert "无技术锚" in capsys.readouterr().out


# ── 40-cycle：有资产数据 → 正常发布 ──
def test_cycle_with_assets_published(monkeypatch, tmp_path, bus_path):
    state = {
        "real_cycle": {"state": "plateau", "confidence": "high"},
        "technical_anchor": {"assets": {"BTC": {"above": True}, "ETH": {"above": True}}},
        "generated_at": _now(),
    }
    state_path = tmp_path / "cycle_state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(cycle_state_adapter, "_40_STATE_PATH", str(state_path))

    assert cycle_state_adapter.main() == 0
    with open(bus_path, encoding="utf-8") as f:
        bus = json.load(f)
    assert bus["signal_count"] == 1
    assert bus["signals"][0]["direction"] == "long"
