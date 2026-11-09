#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同源同标取最新（source+symbol 唯一）契约测试。"""

import json  # noqa: I001
import os
import sys
from datetime import datetime, timedelta, timezone

_42_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _42_ROOT not in sys.path:
    sys.path.insert(0, _42_ROOT)

from signal_bus import SignalBus  # noqa: E402


def _sig(source, symbol, day_offset, confidence=0.8):
    """day_offset 相对 now 的天数偏移，确保信号在测试运行时未过期。"""
    base = datetime.now(timezone.utc).replace(
        hour=3, minute=0, second=0, microsecond=0
    ) + timedelta(days=day_offset)
    return {
        "signal_id": "sig_{}_{}_{}".format(
            source.replace("-", "_"), symbol, base.strftime("%Y%m%d")
        ),
        "source": source,
        "ts": base.isoformat(),
        "symbol": symbol,
        "direction": "long",
        "confidence": confidence,
        "horizon": "days",
        "risk_exposure_hint": 0.5,
        "expires_at": (base + timedelta(hours=48)).isoformat(),
        "payload": {},
    }


# ── 1. 同源同标两条（不同日）→ 只保留最新 ──
def test_same_source_symbol_keeps_latest(tmp_path):
    bus = SignalBus(state_path=str(tmp_path / "bus.json"))
    bus.publish(_sig("40-cycle", "MACRO", 6))
    bus.publish(_sig("40-cycle", "MACRO", 7))
    assert len(bus.signals) == 1
    expected_date = (
        datetime.now(timezone.utc).replace(hour=3, minute=0, second=0, microsecond=0)
        + timedelta(days=7)
    ).strftime("%Y%m%d")
    assert bus.signals[0]["signal_id"] == "sig_40_cycle_MACRO_{}".format(expected_date)


# ── 2. 后发信号更旧 → 拒绝，保留已有较新 ──
def test_older_signal_rejected(tmp_path):
    bus = SignalBus(state_path=str(tmp_path / "bus.json"))
    bus.publish(_sig("40-cycle", "MACRO", 7))
    result = bus.publish(_sig("40-cycle", "MACRO", 6))
    assert result["status"] == "rejected"
    assert len(bus.signals) == 1
    expected_date = (
        datetime.now(timezone.utc).replace(hour=3, minute=0, second=0, microsecond=0)
        + timedelta(days=7)
    ).strftime("%Y%m%d")
    assert bus.signals[0]["signal_id"] == "sig_40_cycle_MACRO_{}".format(expected_date)


# ── 3. 不同源同标 → 各保留一条 ──
def test_different_source_same_symbol_kept(tmp_path):
    bus = SignalBus(state_path=str(tmp_path / "bus.json"))
    bus.publish(_sig("40-cycle", "MACRO", 7))
    bus.publish(_sig("29-event", "MACRO", 7))
    assert len(bus.signals) == 2


# ── 4. 同源不同标 → 各保留一条 ──
def test_same_source_different_symbol_kept(tmp_path):
    bus = SignalBus(state_path=str(tmp_path / "bus.json"))
    bus.publish(_sig("29-event", "BTC", 7))
    bus.publish(_sig("29-event", "ETH", 7))
    assert len(bus.signals) == 2


# ── 5. persist 加载旧文件时也去重（防历史脏数据）──
def test_load_persistent_state_dedupes(monkeypatch, tmp_path):
    monkeypatch.setenv("SIGNAL_BUS_PERSIST", "1")
    bus_path = tmp_path / "bus.json"
    bus_path.write_text(
        json.dumps(
            {
                "signals": [
                    _sig("40-cycle", "MACRO", 6),
                    _sig("40-cycle", "MACRO", 7),
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    bus = SignalBus(state_path=str(bus_path))
    assert len(bus.signals) == 1
    expected_date = (
        datetime.now(timezone.utc).replace(hour=3, minute=0, second=0, microsecond=0)
        + timedelta(days=7)
    ).strftime("%Y%m%d")
    assert bus.signals[0]["signal_id"] == "sig_40_cycle_MACRO_{}".format(expected_date)
