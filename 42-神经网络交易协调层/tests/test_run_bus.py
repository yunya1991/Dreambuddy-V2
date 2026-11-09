#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""42 总线运行入口 run_bus 契约测试（C 阶段：仅 40-cycle / 29-event + 指标）。"""

import json  # noqa: I001
import os
import sys

_42_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _42_ROOT not in sys.path:
    sys.path.insert(0, _42_ROOT)

import run_bus  # noqa: E402


# ── 1. 默认白名单（R0-03 扩展 + N4 40-divergence）──
def test_default_whitelist():
    assert run_bus.DEFAULT_WHITELIST == (
        "40-cycle",
        "40-divergence",
        "29-event",
        "43-strategic",
        "23-contradiction",
        "11-bcrm",
        "11-bdsm",
        "11-bcrm-tactical",
        "11-washout",
        "11-event-arbitrage",
    )


# ── 2. select_subsystems 按白名单过滤 registry ──
def test_select_subsystems_default():
    subs = run_bus.select_subsystems()
    names = [s["name"] for s in subs]
    assert names == [
        "40-cycle",
        "40-divergence",
        "29-event",
        "43-strategic",
        "23-contradiction",
        "11-bcrm",
        "11-bdsm",
        "11-bcrm-tactical",
        "11-washout",
        "11-event-arbitrage",
    ], names
    assert all(s["publisher"] for s in subs)


def test_select_subsystems_custom_whitelist():
    subs = run_bus.select_subsystems(whitelist=("11-bcrm",))
    assert [s["name"] for s in subs] == ["11-bcrm"]


def test_select_subsystems_unknown_name_ignored():
    subs = run_bus.select_subsystems(whitelist=("not-exist",))
    assert subs == []


# ── 3. run 只执行白名单源（注入 runner，不真跑适配器）──
def test_run_only_whitelisted():
    called = []

    def fake_runner(sub):
        called.append(sub["name"])
        return 0

    result = run_bus.run(runner=fake_runner, flush=False)
    expected = [
        "40-cycle",
        "40-divergence",
        "29-event",
        "43-strategic",
        "23-contradiction",
        "11-bcrm",
        "11-bdsm",
        "11-bcrm-tactical",
        "11-washout",
        "11-event-arbitrage",
    ]
    assert called == expected, called
    assert result["executed"] == expected
    assert result["status"] == "ok"


# ── 4. 适配器失败不影响其余源（fail-open），并记录 ──
def test_run_failopen_on_adapter_error():
    def bad_runner(sub):
        if sub["name"] == "40-cycle":
            raise RuntimeError("boom")
        return 0

    result = run_bus.run(runner=bad_runner, flush=False)
    assert result["status"] == "degraded"
    assert result["executed"] == [
        "40-divergence",
        "29-event",
        "43-strategic",
        "23-contradiction",
        "11-bcrm",
        "11-bdsm",
        "11-bcrm-tactical",
        "11-washout",
        "11-event-arbitrage",
    ]
    assert any(e["name"] == "40-cycle" for e in result["errors"])


# ── 5. run 设置 persist + metrics 开关（小步验证需可观测）──
def test_run_sets_observability_env(monkeypatch):
    for k in ("SIGNAL_BUS_PERSIST", "SIGNAL_BUS_METRICS"):
        monkeypatch.delenv(k, raising=False)
    run_bus.run(runner=lambda sub: 0, flush=False)
    assert os.environ.get("SIGNAL_BUS_PERSIST") == "1"
    assert os.environ.get("SIGNAL_BUS_METRICS") == "1"


# ── 6. run 结束兜底 flush：即使所有适配器秒退也产出 bus_state + metrics ──
def test_run_flush_writes_state_and_metrics(monkeypatch, tmp_path):
    monkeypatch.setenv("SIGNAL_BUS_PERSIST", "1")
    monkeypatch.setenv("SIGNAL_BUS_METRICS", "1")
    bus_path = str(tmp_path / "bus_state.json")
    metrics_path = str(tmp_path / "metrics.json")
    result = run_bus.run(
        runner=lambda sub: 0,
        flush=True,
        bus_state_path=bus_path,
        metrics_path=metrics_path,
    )
    assert result["status"] == "ok"
    assert os.path.exists(bus_path)
    assert os.path.exists(metrics_path)
    with open(metrics_path, encoding="utf-8") as f:
        m = json.load(f)
    assert "alert" in m and "source_counts" in m
