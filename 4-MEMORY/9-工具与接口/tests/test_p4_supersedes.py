#!/usr/bin/env python3
"""P4 再巩固单测：supersedes 预校验 fail-loud / 时序图标记 / 幂等 / recall 呈 superseded。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cognitive_loop_entry import CognitiveLoopEntry  # noqa: E402
from temporal_memory_graph import TemporalMemoryGraph  # noqa: E402


class _FakeVM:
    def __init__(self, rows: dict[str, dict]):
        self._rows = rows

    def get(self, memory_id: str):
        return self._rows.get(memory_id)


def _cle(tmp_path: Path, rows: dict[str, dict]) -> CognitiveLoopEntry:
    """只装配 supersedes 需要的三个依赖，避免初始化全部子系统污染仓库。"""
    cle = CognitiveLoopEntry.__new__(CognitiveLoopEntry)
    cle._vm = _FakeVM(rows)
    cle.temporal_graph = TemporalMemoryGraph(graph_path=tmp_path / "temporal.json")
    cle.poe_enforcement = "off"
    cle._check_poe_trust = lambda memory_id: (False, "")  # type: ignore[assignment]
    return cle


def test_validate_rejects_self_reference(tmp_path):
    cle = _cle(tmp_path, {"m1": {"id": "m1", "content": "x"}})
    out = cle._supersede_validate("m1", "m1")
    assert out["ok"] is False and out["error"] == "supersedes_self"


def test_validate_rejects_unknown_target(tmp_path):
    cle = _cle(tmp_path, {"m1": {"id": "m1", "content": "x"}})
    out = cle._supersede_validate("nope", "m1")
    assert out["ok"] is False and out["error"] == "superseded_target_not_found"


def test_apply_marks_superseded_and_persists(tmp_path):
    cle = _cle(tmp_path, {"old": {"id": "old", "content": "旧结论"}})
    report = cle._supersede_validate("old", "new")
    assert report["ok"] and report["entry_exists"] is False

    applied = cle._supersede_apply(report, {"content": "旧结论"})
    assert applied["ok"] is True and applied["persisted"] is True
    assert cle.temporal_graph.get("old")["invalidated_by"] == "new"

    # recall 侧呈现 superseded（不删行，只标记）
    results = [{"id": "old"}]
    cle.temporal_graph.filter_recall_results(results)
    assert results[0]["temporal_status"] == "superseded"
    assert results[0]["invalidated_by"] == "new"

    # 持久化落盘，可被新实例读回
    restored = TemporalMemoryGraph(graph_path=tmp_path / "temporal.json")
    assert restored.get("old")["invalidated_by"] == "new"


def test_apply_is_idempotent_and_reports_previous(tmp_path):
    cle = _cle(tmp_path, {"old": {"id": "old", "content": "x"}})
    cle._supersede_apply(cle._supersede_validate("old", "new1"), {"content": "x"})
    second = cle._supersede_validate("old", "new2")
    assert second["previous_invalidated_by"] == "new1"
    assert cle._supersede_apply(second, {"content": "x"})["ok"] is True
    assert cle.temporal_graph.get("old")["invalidated_by"] == "new2"


def test_verify_fails_loud_before_any_write(tmp_path):
    cle = _cle(tmp_path, {"new": {"id": "new", "content": "新结论", "confidence": 0.4}})
    out = cle.verify("new", success=True, supersedes="missing-old")
    assert out["success"] is False
    assert out["error"] == "superseded_target_not_found"
    assert out["supersedes"]["ok"] is False
    assert cle.temporal_graph.stats()["total_entries"] == 0, "校验不过不得产生任何写入"
