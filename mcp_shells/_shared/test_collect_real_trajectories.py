#!/usr/bin/env python3
"""test_collect_real_trajectories.py — 真实 trajectory 采集链路验收

覆盖：shadow_hook 默认关闭 / 开启后落盘 shadow- trace + 真实质量字段 /
真实域操作采集（data 域真实文件读取） / 未知域名 FAIL-OPEN /
collect 用真实 degraded 轨迹实测 psi（drift 与 psi 硬同步）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COG_DIR = _REPO_ROOT / "4-MEMORY" / "9-工具与接口"
for _p in (str(_REPO_ROOT), str(_COG_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import collect_domain_discovery_data as cdd  # noqa: E402
from drift_detector import classify_drift  # noqa: E402

from mcp_shells._shared import shadow_hook  # noqa: E402
from mcp_shells._shared.agent_mail_shadow import SHADOW_PREFIX  # noqa: E402
from mcp_shells._shared.collect_real_trajectories import (  # noqa: E402
    collect_real_trajectories,
)
from mcp_shells._shared.envelope_wrap import wrap  # noqa: E402


def _read_entries(store: Path) -> list:
    return [json.loads(ln) for ln in store.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ---------- shadow_hook（壳生产接线） ----------
def test_shadow_hook_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_MAIL_SHADOW", raising=False)
    store = tmp_path / "t.jsonl"
    monkeypatch.setenv("AGENT_MAIL_SHADOW_STORE", str(store))
    shadow_hook.observe_envelope(wrap({"x": 1}, "l0.data.mcp"))
    assert not store.exists()


def test_shadow_hook_observes_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_MAIL_SHADOW", "1")
    monkeypatch.setenv("AGENT_MAIL_SHADOW_STORE", str(tmp_path / "t.jsonl"))
    monkeypatch.delenv("AGENT_MAIL_SHADOW_HEAD", raising=False)
    shadow_hook._shadow = None  # 重置单例，绑定新 store
    env = wrap(None, "l0.data.mcp", degraded=True, error_code="unavailable", trace_id="tr-1")
    shadow_hook.observe_envelope(json.dumps(env))
    shadow_hook._shadow = None

    entries = _read_entries(tmp_path / "t.jsonl")
    assert len(entries) == 1
    assert entries[0]["agent_domain"] == "data"
    assert entries[0]["trace_id"].startswith(SHADOW_PREFIX)
    # 真实信封质量信号落盘（合成轨迹没有这些字段）
    assert entries[0]["degraded"] is True
    assert entries[0]["error_code"] == "unavailable"


# ---------- 真实域操作采集 ----------
def test_collect_real_trajectories_data_domain(tmp_path):
    store = tmp_path / "traj.jsonl"
    summary = collect_real_trajectories(waves=1, domains=["data"], store_path=str(store))
    assert summary["observed"] >= 5
    assert "data" in summary["domains"]

    entries = _read_entries(store)
    assert len(entries) == summary["observed"]
    assert all(e["agent_domain"] == "data" for e in entries)
    assert all(e["trace_id"].startswith(SHADOW_PREFIX) for e in entries)
    assert all("degraded" in e for e in entries)
    # 真实调用一定有真实耗时
    assert all(e["cost"]["latency_ms"] >= 0.0 for e in entries)


def test_collect_real_trajectories_unknown_domain_fail_open(tmp_path):
    summary = collect_real_trajectories(
        waves=1, domains=["nope"], store_path=str(tmp_path / "t.jsonl")
    )
    assert summary["observed"] == 0
    assert summary["domains"] == []


# ---------- collect 实测 psi ----------
def test_compute_real_psi_map_marks_degraded_domain():
    trajs = [
        {"agent_domain": "data", "degraded": False},
        {"agent_domain": "data", "degraded": False},
        {"agent_domain": "eval", "degraded": True},
        {"agent_domain": "eval", "degraded": True},
        {"agent_domain": "search", "degraded": True},
        {"agent_domain": "search", "degraded": False},
        {"agent_domain": "rea"},  # 无 degraded 字段 → 合成轨迹，不参与
    ]
    psi_map = cdd.compute_real_psi_map(trajs)
    assert set(psi_map) == {"data", "eval", "search"}
    assert psi_map["data"] == pytest.approx(0.0, abs=1e-6)
    assert classify_drift(psi_map["eval"]) == "severe_drift"
    assert classify_drift(psi_map["search"]) in {"minor_drift", "severe_drift"}
    assert 0.0 <= psi_map["eval"] <= 1.0


def test_collect_uses_real_psi_from_degraded_trajectories(tmp_path):
    store = tmp_path / "traj.jsonl"
    rows = [
        {"agent_domain": "data", "degraded": False, "trace_id": "shadow-d1"},
        {"agent_domain": "data", "degraded": False, "trace_id": "shadow-d2"},
        {"agent_domain": "eval", "degraded": True, "trace_id": "shadow-e1"},
        {"agent_domain": "eval", "degraded": True, "trace_id": "shadow-e2"},
    ]
    store.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    out = tmp_path / "train.jsonl"
    cdd.collect(shadow_store_path=str(store), output_path=str(out), num_samples=4, seed=11)
    samples = [json.loads(ln) for ln in out.read_text(encoding="utf-8").splitlines()]

    psi_map = cdd.compute_real_psi_map(rows)
    for sample in samples:
        states = sample["input"]["domain_states"]
        for s in states.values():
            assert s["drift"] == classify_drift(s["psi"])
        assert states["eval"]["psi"] == pytest.approx(psi_map["eval"], abs=1e-4)
        assert states["data"]["psi"] == pytest.approx(psi_map["data"], abs=1e-4)
        assert states["eval"]["drift"] == "severe_drift"
