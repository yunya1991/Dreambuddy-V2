"""R0-04: 23 层冻结快照固化/加载/转换/diff 全链路一致性测试。"""

from __future__ import annotations

import json

import pytest
import tools.differential_harness as dh
from tools.differential_harness import (
    diff_path_sets,
    freeze_control_snapshot,
    to_path_set,
)


@pytest.fixture()
def _snap():
    return {
        "WLD": {"symbol": "WLD", "action": "long", "u_open": 0.4},
        "RAY": {"symbol": "RAY", "action": "short", "u_open": 0.7},
        "TAO": {"symbol": "TAO", "action": "neutral", "u_open": 0.0},
    }


def test_freeze_and_load_roundtrip(tmp_path, monkeypatch, _snap):
    monkeypatch.setattr(dh, "CONTROL_SNAPSHOT_DIR", tmp_path)
    out = dh.freeze_control_snapshot(_snap, label="test-rt")
    assert "test-rt" in out
    loaded = dh.load_control_snapshot("control_test-rt")
    assert loaded["_meta"]["coin_count"] == 3
    assert loaded["coins"]["WLD"]["action"] == "long"


def test_freeze_rejects_empty():
    with pytest.raises(ValueError):
        freeze_control_snapshot({})


def test_to_path_set_mapping(_snap):
    paths = to_path_set(_snap)
    by_id = {p["path_id"]: p for p in paths}
    assert by_id["23-WLD"]["direction"] == "long"
    assert by_id["23-WLD"]["confidence"] == 0.4
    assert by_id["23-RAY"]["direction"] == "short"
    assert by_id["23-TAO"]["direction"] == "flat"
    assert by_id["23-TAO"]["confidence"] == 0.0
    for p in paths:
        assert p["dimension"] == "D3"
        assert p["horizon"] == "hours"
        assert p["intent"] == "trend"


def test_to_path_set_clamps_confidence():
    snap = {"X": {"action": "long", "u_open": 5.0}, "Y": {"action": "long", "u_open": -1.0}}
    paths = {p["path_id"]: p for p in to_path_set(snap)}
    assert paths["23-X"]["confidence"] == 1.0
    assert paths["23-Y"]["confidence"] == 0.0


def test_frozen_snapshot_diff_self_zero(_snap):
    paths = to_path_set(_snap)
    result = diff_path_sets(paths, paths)
    assert result["divergence_rate"] == 0.0


def test_frozen_snapshot_diff_detects_change(_snap):
    control = to_path_set(_snap)
    changed = json.loads(json.dumps(control))
    changed[0]["direction"] = "short"
    result = diff_path_sets(control, changed)
    assert len(result["field_diffs"]) == 1
    assert result["field_diffs"][0]["field"] == "direction"
