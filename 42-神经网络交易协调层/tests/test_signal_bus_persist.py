#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1-01：SignalBus 单实例持久化模式（SIGNAL_BUS_PERSIST=1）契约测试。

验收口径（49-SPEC §13.5 P1-01）：
- 6 源共存：多个 adapter 串行运行（各自新建 SignalBus 实例）信号不被互相覆盖
- 重启不丢：新实例加载既有 bus_state.json
- 过期剪枝：expires_at 已过期的信号在加载与落盘时被剪除
- 按 signal_id 合并：同 signal_id 重复发布为替换而非追加
- 回滚：SIGNAL_BUS_PERSIST 未设置/置 0 时保持旧的整文件覆盖行为
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


def _sig(
    signal_id, source="src-a", symbol="BTC/USDT", direction="long", confidence=0.8, ttl_hours=24
):
    now = datetime.now(timezone.utc)
    return {
        "signal_id": signal_id,
        "source": source,
        "ts": now.isoformat(),
        "symbol": symbol,
        "direction": direction,
        "confidence": confidence,
        "horizon": "hours",
        "risk_exposure_hint": 0.5,
        "expires_at": (now + timedelta(hours=ttl_hours)).isoformat(),
        "payload": {},
    }


def _write_state(path, signals):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "bus_id": "bus_seed",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "signal_count": len(signals),
                "rejected_count": 0,
                "sources": sorted({s["source"] for s in signals}),
                "signals": signals,
                "rejected": [],
                "note": "seed",
            }
        ),
        encoding="utf-8",
    )


def _read_state(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def persist_on(monkeypatch):
    monkeypatch.setenv("SIGNAL_BUS_PERSIST", "1")


@pytest.fixture
def persist_off(monkeypatch):
    monkeypatch.delenv("SIGNAL_BUS_PERSIST", raising=False)


# ── 1. 重启不丢：实例B加载实例A落盘的信号 ──
def test_persist_loads_existing_state(tmp_path, persist_on):
    path = tmp_path / "bus_state.json"
    bus_a = SignalBus(state_path=str(path))
    bus_a.publish(_sig("sig_a1", source="src-a"))
    bus_a.flush()

    bus_b = SignalBus(state_path=str(path))
    ids = [s["signal_id"] for s in bus_b.signals]
    assert "sig_a1" in ids, "persist 模式新实例必须加载既有信号（重启不丢）"


# ── 2. 按 signal_id 合并：同 ID 替换而非追加 ──
def test_persist_upsert_same_signal_id(tmp_path, persist_on):
    path = tmp_path / "bus_state.json"
    bus_a = SignalBus(state_path=str(path))
    bus_a.publish(_sig("sig_x", source="src-a", confidence=0.8))
    bus_a.flush()

    bus_b = SignalBus(state_path=str(path))
    bus_b.publish(_sig("sig_x", source="src-a", confidence=0.5))
    bus_b.flush()
    state = _read_state(path)

    matches = [s for s in state["signals"] if s["signal_id"] == "sig_x"]
    assert len(matches) == 1, "同 signal_id 必须合并为 1 条，实际 {} 条".format(len(matches))
    assert matches[0]["confidence"] == 0.5, "同 signal_id 重复发布应替换为最新值"


# ── 3. 过期剪枝（加载时）──
def test_persist_prunes_expired_on_load(tmp_path, persist_on):
    path = tmp_path / "bus_state.json"
    expired = _sig("sig_old", source="src-a", symbol="BTC/USDT", ttl_hours=24)
    expired["expires_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    fresh = _sig("sig_fresh", source="src-a", symbol="ETH/USDT", ttl_hours=24)
    _write_state(path, [expired, fresh])

    bus = SignalBus(state_path=str(path))
    ids = [s["signal_id"] for s in bus.signals]
    assert "sig_old" not in ids, "加载时必须剪除已过期信号"
    assert "sig_fresh" in ids


# ── 4. 过期剪枝（落盘时）：运行期间过期的信号不写入文件 ──
def test_persist_prunes_expired_on_flush(tmp_path, persist_on):
    path = tmp_path / "bus_state.json"
    bus = SignalBus(state_path=str(path))
    bus.publish(_sig("sig_live", source="src-a", symbol="BTC/USDT", ttl_hours=24))
    bus.publish(_sig("sig_dying", source="src-a", symbol="ETH/USDT", ttl_hours=1))
    # 模拟运行期间过期：直接篡改内存中信号的 expires_at
    for s in bus.signals:
        if s["signal_id"] == "sig_dying":
            s["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    bus.flush()

    state = _read_state(path)
    ids = [s["signal_id"] for s in state["signals"]]
    assert "sig_dying" not in ids, "落盘时必须剪除已过期信号"
    assert "sig_live" in ids


# ── 5. 回滚路径：开关关闭时保持旧的整文件覆盖行为 ──
def test_persist_off_keeps_overwrite_behavior(tmp_path, persist_off):
    path = tmp_path / "bus_state.json"
    bus_a = SignalBus(state_path=str(path))
    bus_a.publish(_sig("sig_a1", source="src-a"))
    bus_a.flush()

    bus_b = SignalBus(state_path=str(path))
    assert [s["signal_id"] for s in bus_b.signals] == [], "开关关闭时新实例不加载旧状态"
    bus_b.publish(_sig("sig_b1", source="src-b"))
    bus_b.flush()

    state = _read_state(path)
    ids = [s["signal_id"] for s in state["signals"]]
    assert ids == ["sig_b1"], "开关关闭时 flush 必须整文件覆盖（旧行为）"


# ── 6. 原子写：无 .tmp 残留且 JSON 可解析 ──
def test_persist_atomic_write_no_tmp_left(tmp_path, persist_on):
    path = tmp_path / "bus_state.json"
    bus = SignalBus(state_path=str(path))
    bus.publish(_sig("sig_a1", source="src-a"))
    bus.flush()

    assert path.exists()
    assert not (tmp_path / "bus_state.json.tmp").exists(), "原子写后不得残留 .tmp"
    state = _read_state(path)  # JSON 可解析即通过
    assert state["signal_count"] == len(state["signals"])


# ── 7. 6 源共存：6 个独立实例串行发布，最终 bus 条数 ≥6 ──
def test_six_sources_coexist(tmp_path, persist_on):
    path = tmp_path / "bus_state.json"
    sources = [
        "43-strategic-extension",
        "40-cycle",
        "23-contradiction",
        "29-event",
        "11-bcrm",
        "bdsm",
    ]
    for i, src in enumerate(sources):
        bus = SignalBus(state_path=str(path))  # 每次新建实例模拟独立 adapter 进程
        bus.publish(_sig("sig_{}".format(i), source=src, symbol="SYM{}".format(i)))
        bus.flush()

    state = _read_state(path)
    assert state["signal_count"] >= 6, "6 源串行发布后 bus 条数必须 ≥6，实际 {}".format(
        state["signal_count"]
    )
    assert set(state["sources"]) == set(sources), "6 源必须共存，实际 {}".format(state["sources"])
