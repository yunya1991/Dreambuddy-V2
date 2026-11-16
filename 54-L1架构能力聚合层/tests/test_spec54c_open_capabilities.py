"""SPEC-54c：E14/G21/G23/A14/A16/E19/K02 放开与产物落盘验收。"""

from __future__ import annotations

import json
import math
import os
import sys

import pytest

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_L1 = os.path.join(_REPO, "54-L1架构能力聚合层")
_SCRIPTS = os.path.join(_REPO, "3.1-FRONTEND", "scripts")
_L1_SCRIPTS = os.path.join(_L1, "scripts")
for _p in (_L1, _SCRIPTS, _L1_SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import capability_resolve as cr  # noqa: E402
import discovery_scan  # noqa: E402
from l1agg.capabilities.eval_exports import discovery_query  # noqa: E402

_DB_READY = os.path.exists(cr.DB_PATH)
_needs_db = pytest.mark.skipif(not _DB_READY, reason="dreambuddy_core.db 不存在")


@_needs_db
def test_e14_relaxed_gate_reports_thresholds():
    result = cr.resolve("D-E14", {"days": 750})
    assert result["code"] == "ok", result.get("data", {}).get("answer")
    block = result["data"]["data"]["capabilities"]["D-E14"]
    params = result["data"]["data"]["params"]
    assert params["min_bucket_nonoverlap_n"] == cr.E14_MIN_BUCKET_N == 100
    assert params["window"] == cr.E14_WINDOW == 120
    assert block["buckets"] >= 2
    assert "历史统计" in result["data"]["answer"]


def test_panel_lists_drops_short_history(monkeypatch):
    """G21 根因回归：最短资产不得把公共轴截断到 250 天以下。"""
    long_days = [f"2024-{m:02d}-{d:02d}" for m in range(1, 13) for d in range(1, 29)]
    short_days = long_days[-150:]
    panel = {
        "LONG_A": {day: 100.0 + i for i, day in enumerate(long_days)},
        "LONG_B": {day: 200.0 + i for i, day in enumerate(long_days)},
        "SHORT": {day: 50.0 + i for i, day in enumerate(short_days)},
    }
    monkeypatch.setattr(cr, "_panel_map", lambda days: panel)
    cr._PANEL_LIST_CACHE.clear()
    common, columns = cr._panel_lists(750)
    cr._PANEL_LIST_CACHE.clear()
    assert "SHORT" not in columns
    assert len(common) >= cr.PANEL_MIN_DATES
    assert set(columns) == {"LONG_A", "LONG_B"}


@_needs_db
def test_g21_produces_enough_cross_sections():
    result = cr.resolve("D-G21", {"days": 750})
    assert result["code"] == "ok", result.get("data", {}).get("answer")
    params = result["data"]["data"]["params"]
    assert params["n_periods"] >= 250
    assert params["n_assets"] >= 2


@_needs_db
def test_g23_uses_events_and_a14_a16_report_data():
    for capability_id in ("D-G23", "D-A14", "D-A16"):
        result = cr.resolve(capability_id, {"days": 750})
        assert result["code"] != "unsupported", capability_id
        assert result["code"] != "not_found", capability_id
    a14 = cr.resolve("D-A14", {"days": 750})
    assert a14["code"] == "ok"
    assert set(a14["data"]["data"]["capabilities"]["D-A14"]["components"]) == {
        "funding_rate",
        "open_interest",
        "long_short_ratio",
    }
    a16 = cr.resolve("D-A16", {"days": 750})
    assert a16["code"] == "ok"
    block = a16["data"]["data"]["capabilities"]["D-A16"]
    assert block["growth_7d"] is not None


def test_lights_entries_artifact_roundtrip(tmp_path, monkeypatch):
    path = tmp_path / "lights_latest.json"
    path.write_text(
        json.dumps({"as_of": "2026-11-17", "entries": [{"symbol": "BTC", "axes": {}}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cr, "_lights_artifact_path", lambda: str(path))
    assert cr._load_lights_entries() == [{"symbol": "BTC", "axes": {}}]
    monkeypatch.setattr(cr, "_lights_artifact_path", lambda: str(tmp_path / "none.json"))
    assert cr._load_lights_entries() == []


def test_discovery_scan_transforms_and_fdr():
    values = [100.0 + i * 0.5 for i in range(300)]
    assert discovery_scan._transform(values, "raw")[0] == 100.0
    assert discovery_scan._transform(values, "diff")[0] is None
    assert discovery_scan._transform(values, "pct")[1] > 0
    assert math.isfinite(discovery_scan._transform(values, "zscore60")[-1])
    assert 0.0 <= discovery_scan._transform(values, "ts_rank60")[-1] <= 1.0
    assert 0.0 <= discovery_scan._transform(values, "quintile5")[-1] <= 4.0
    adjusted = discovery_scan._bh_fdr([0.001, 0.4, 0.9], 0.05)
    assert adjusted[0] is not None
    assert adjusted[1] is None and adjusted[2] is None


def test_discovery_report_is_consumed_by_k02(tmp_path):
    space = {
        "version": 1,
        "space_hash": "x" * 64,
        "seed": 42,
        "series": ["A"],
        "methods": ["M01", "B14"],
        "horizons": [1],
        "fdr": {"enabled": True, "alpha": 0.05},
        "split": {"screen_ratio": 0.7},
        "dedupe": {"corr_threshold": 0.95},
        "budget": {"max_findings": 50},
        "estimates": {"total_units": 1},
    }
    findings = [
        {
            "method": "B14",
            "series": "BTC",
            "target": "btc_open_interest",
            "transform": "diff",
            "horizon": 1,
            "n": 500,
            "rank_ic": 0.42,
            "holdout_ic": 0.31,
            "stability": 1.0,
            "p_adj": 0.0001,
        }
    ]
    meta = {
        "units": 1,
        "evaluated": 1,
        "truncated": False,
        "skipped": {},
        "series_loaded": 2,
        "passed_fdr": 1,
    }
    directory = discovery_scan._write_report(str(tmp_path), space, findings, meta)
    assert os.path.isfile(os.path.join(directory, "manifest.json"))
    assert os.path.isfile(os.path.join(directory, "findings.jsonl"))
    result = discovery_query(reports_dir=str(tmp_path))
    assert result["ok"] is True
    block = result["data"]["capabilities"]["D-K02"]
    assert block["items"][0]["series"] == "BTC"
    assert block["items"][0]["rank_ic"] == 0.42
