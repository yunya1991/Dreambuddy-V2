#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1-04：11 子池状态文件 + 42 只读适配器（DEC-08）契约测试。

验收口径（49-SPEC §13.5 P1-04）：
- 42 可读 11-washout / 11-event-arbitrage 子池状态文件
- 无内存耦合：适配器只读 runtime/subpool_state/<tag>_state.json
- TTL 生效：updated_at 超龄的状态不发布
- 开关 ENABLE_11_STATE_ADAPTER=1：未设置时不发布（回滚路径）
- fail-open：状态文件缺失/损坏不阻断总线
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

_42_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _42_ROOT not in sys.path:
    sys.path.insert(0, _42_ROOT)

_ADAPTERS_DIR = os.path.join(_42_ROOT, "adapters")
if _ADAPTERS_DIR not in sys.path:
    sys.path.insert(0, _ADAPTERS_DIR)

from _subpool_state_common import (  # noqa: E402
    build_signals,
    is_fresh,
    load_state,
    run,
)


def _write_state(path, tag="washout_entry", updated_at=None, signals=None):
    if updated_at is None:
        updated_at = datetime.now(timezone.utc).isoformat()
    if signals is None:
        signals = {
            "UNI": {
                "direction": "UP",
                "confidence": 0.88,
                "price": 10.5,
                "ts": updated_at,
                "reason": "washout reversal",
            }
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"source_tag": tag, "updated_at": updated_at, "signals": signals},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


# ── 1. 加载：缺文件 fail-open ──
def test_load_state_missing_file(tmp_path):
    state, note = load_state(str(tmp_path / "nope_state.json"))
    assert state is None
    assert note


# ── 2. 加载：坏 JSON fail-open ──
def test_load_state_corrupt_json(tmp_path):
    p = tmp_path / "bad_state.json"
    p.write_text("{not json", encoding="utf-8")
    state, note = load_state(str(p))
    assert state is None
    assert note


# ── 3. 加载：缺 signals 字段 fail-open ──
def test_load_state_missing_signals(tmp_path):
    p = tmp_path / "empty_state.json"
    p.write_text(json.dumps({"source_tag": "x", "updated_at": "2026-11-07"}), encoding="utf-8")
    state, note = load_state(str(p))
    assert state is None
    assert note


# ── 4. TTL：新鲜状态通过 ──
def test_is_fresh_recent(tmp_path):
    p = tmp_path / "s_state.json"
    _write_state(p)
    state, _ = load_state(str(p))
    ok, age = is_fresh(state, max_age_hours=24)
    assert ok is True
    assert age < 1


# ── 5. TTL：超龄状态不通过（TTL 生效）──
def test_is_fresh_stale(tmp_path):
    p = tmp_path / "s_state.json"
    old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    _write_state(p, updated_at=old)
    state, _ = load_state(str(p))
    ok, age = is_fresh(state, max_age_hours=24)
    assert ok is False
    assert age > 24


# ── 6. build_signals 字段映射：UP→long / DOWN→short / 其他→neutral ──
def test_build_signals_direction_mapping():
    state = {
        "source_tag": "event_arbitrage",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "signals": {
            "AAA": {"direction": "UP", "confidence": 0.9, "price": 1.0, "ts": "t", "reason": ""},
            "BBB": {"direction": "DOWN", "confidence": 0.7, "price": 2.0, "ts": "t", "reason": ""},
            "CCC": {"direction": "FLAT", "confidence": 0.5, "price": 3.0, "ts": "t", "reason": ""},
        },
    }
    sigs = build_signals(state, source="11-event-arbitrage", horizon="hours", ttl_hours=4)
    by_symbol = {s["symbol"]: s for s in sigs}
    assert by_symbol["AAA"]["direction"] == "long"
    assert by_symbol["BBB"]["direction"] == "short"
    assert by_symbol["CCC"]["direction"] == "neutral"


# ── 7. build_signals：confidence clip 到 [0,1]，signal_id 确定性，horizon/expires 正确 ──
def test_build_signals_contract():
    state = {
        "source_tag": "washout_entry",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "signals": {
            "UNI": {"direction": "UP", "confidence": 1.7, "price": 1.0, "ts": "t", "reason": "r"},
        },
    }
    sigs = build_signals(state, source="11-washout", horizon="hours", ttl_hours=24)
    assert len(sigs) == 1
    s = sigs[0]
    assert s["confidence"] == 1.0, "confidence 必须 clip 到 [0,1]"
    assert s["source"] == "11-washout"
    assert s["horizon"] == "hours"
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    assert s["signal_id"] == "sig_11-washout_UNI_{}".format(
        today
    ), "signal_id 必须确定性（当日重跑幂等替换）"
    exp = datetime.fromisoformat(s["expires_at"])
    ts = datetime.fromisoformat(s["ts"])
    assert 23.9 < (exp - ts).total_seconds() / 3600.0 <= 24.0
    assert s["payload"]["price"] == 1.0


# ── 8. 开关：ENABLE_11_STATE_ADAPTER 未设置 → 不发布（回滚路径）──
def test_run_disabled_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ENABLE_11_STATE_ADAPTER", raising=False)
    p = tmp_path / "s_state.json"
    _write_state(p)
    bus_path = tmp_path / "bus_state.json"
    rc = run(
        source="11-washout",
        state_path=str(p),
        horizon="hours",
        ttl_hours=24,
        max_age_hours=24,
        bus_state_path=str(bus_path),
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "disabled"
    assert not bus_path.exists(), "开关关闭时不得写总线"


# ── 9. 端到端：ENABLE=1 时发布到总线 accepted ──
def test_run_enabled_publishes(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ENABLE_11_STATE_ADAPTER", "1")
    monkeypatch.setenv("SIGNAL_BUS_PERSIST", "1")
    p = tmp_path / "s_state.json"
    _write_state(p)
    bus_path = tmp_path / "bus_state.json"
    rc = run(
        source="11-washout",
        state_path=str(p),
        horizon="hours",
        ttl_hours=24,
        max_age_hours=24,
        bus_state_path=str(bus_path),
    )
    out = json.loads(capsys.readouterr().out)
    assert rc == 0, "发布成功应返回 0，输出: {}".format(out)
    assert out["publish_result"] == "accepted"
    bus = json.loads(bus_path.read_text(encoding="utf-8"))
    assert bus["signals"][0]["source"] == "11-washout"


# ── 10. 端到端：超龄状态即使 ENABLE=1 也不发布（TTL 生效）──
def test_run_stale_not_published(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ENABLE_11_STATE_ADAPTER", "1")
    monkeypatch.setenv("SIGNAL_BUS_PERSIST", "1")
    p = tmp_path / "s_state.json"
    old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    _write_state(p, updated_at=old)
    bus_path = tmp_path / "bus_state.json"
    rc = run(
        source="11-event-arbitrage",
        state_path=str(p),
        horizon="hours",
        ttl_hours=4,
        max_age_hours=4,
        bus_state_path=str(bus_path),
    )
    out = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert out["status"] == "stale"
    assert not bus_path.exists() or not json.loads(bus_path.read_text(encoding="utf-8"))["signals"]


# ── 11. registry.yaml 已注册两个新子系统且 publisher 文件存在 ──
def test_registry_has_new_subsystems():
    import yaml

    with open(os.path.join(_42_ROOT, "registry.yaml"), encoding="utf-8") as f:
        reg = yaml.safe_load(f)
    subs = {s["name"]: s for s in reg["subsystems"]}
    for name in ("11-washout", "11-event-arbitrage"):
        assert name in subs, "registry.yaml 缺少子系统 {}".format(name)
        assert subs[name]["horizon"] == "hours"
        pub = os.path.join(_42_ROOT, subs[name]["publisher"])
        assert os.path.exists(pub), "publisher 文件不存在: {}".format(pub)
