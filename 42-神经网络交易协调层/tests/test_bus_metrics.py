#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1-07：42 可观测性指标契约测试。

验收口径（49-SPEC §13.5 P1-07）：
- 指标文件可用：SIGNAL_BUS_METRICS=1 时 flush 落盘 runtime/metrics.json
- 指标内容：源计数（按 source 信号数）、丢弃计数（rejected 按原因）、
  TTL 观测（临近过期信号数）、空 bus 告警
- 空 bus 告警：signal_count==0 时 alert.empty_bus=true
- 开关 SIGNAL_BUS_METRICS=1；未设置时不产指标文件（回滚路径）
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

_42_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _42_ROOT not in sys.path:
    sys.path.insert(0, _42_ROOT)

from signal_bus import SignalBus  # noqa: E402


def _signal(source="11-bcrm", symbol="BTC", expires_hours=24, confidence=0.8):
    now = datetime.now(timezone.utc)
    return {
        "signal_id": "sig_{}_{}_{}".format(
            source.replace("-", "_"), symbol, now.strftime("%Y%m%d")
        ),
        "source": source,
        "ts": now.isoformat(),
        "symbol": symbol,
        "direction": "long",
        "confidence": confidence,
        "horizon": "days",
        "risk_exposure_hint": 0.5,
        "expires_at": (now + timedelta(hours=expires_hours)).isoformat(),
        "payload": {},
    }


# ── 1. 回滚路径：未设置开关时不产指标文件 ──
def test_metrics_disabled_default(monkeypatch, tmp_path):
    monkeypatch.delenv("SIGNAL_BUS_METRICS", raising=False)
    metrics_path = str(tmp_path / "metrics.json")
    bus = SignalBus(state_path=str(tmp_path / "bus_state.json"))
    bus.publish(_signal())
    bus.flush(metrics_path=metrics_path)
    assert not os.path.exists(metrics_path)


# ── 2. 指标文件内容：源计数 / 丢弃计数 / TTL / 告警字段 ──
def test_metrics_content(monkeypatch, tmp_path):
    monkeypatch.setenv("SIGNAL_BUS_METRICS", "1")
    metrics_path = str(tmp_path / "metrics.json")
    bus = SignalBus(state_path=str(tmp_path / "bus_state.json"))
    bus.publish(_signal(source="11-bcrm"))
    bus.publish(_signal(source="11-bdsm", symbol="ETH"))
    # 一条过期信号 → 丢弃
    bus.publish(_signal(source="29-event", symbol="SOL", expires_hours=-1))
    # 一条临近过期（0.5h）→ TTL 观测
    bus.publish(_signal(source="40-cycle", symbol="BNB", expires_hours=0.5))
    bus.flush(metrics_path=metrics_path)

    with open(metrics_path, encoding="utf-8") as f:
        m = json.load(f)
    assert m["signal_count"] == 3
    assert m["source_counts"] == {"11-bcrm": 1, "11-bdsm": 1, "40-cycle": 1}
    assert m["rejected_count"] == 1
    assert m["expiring_within_1h"] == 1, "TTL 观测：1h 内过期信号计数"
    assert m["alert"]["empty_bus"] is False
    assert "generated_at" in m


# ── 3. 空 bus 告警 ──
def test_metrics_empty_bus_alert(monkeypatch, tmp_path):
    monkeypatch.setenv("SIGNAL_BUS_METRICS", "1")
    metrics_path = str(tmp_path / "metrics.json")
    bus = SignalBus(state_path=str(tmp_path / "bus_state.json"))
    bus.flush(metrics_path=metrics_path)
    with open(metrics_path, encoding="utf-8") as f:
        m = json.load(f)
    assert m["signal_count"] == 0
    assert m["alert"]["empty_bus"] is True


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
