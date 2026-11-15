#!/usr/bin/env python3
"""求解级联编排器单测：顺序 / 命中即停 / fail-open / D3-D4 回写 / telemetry。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cascade_orchestrator import CascadeOrchestrator, summarize  # noqa: E402


def test_stops_at_first_hit_and_keeps_order():
    calls: list[str] = []

    def make(stage, hit):
        def _h(query):
            calls.append(stage)
            return {"hit": hit, "payload": stage}

        return _h

    orch = CascadeOrchestrator(
        {"D0": make("D0", False), "D1": make("D1", True), "D2": make("D2", True)},
        telemetry_path=None,
    )
    out = orch.solve("问题")
    assert calls == ["D0", "D1"], "命中即停，D2 不得执行"
    assert out["ok"] and out["level"] == "D1"
    assert out["stages_tried"] == ["D0", "D1"]


def test_stage_error_is_fail_open(tmp_path):
    def boom(_q):
        raise RuntimeError("boom")

    orch = CascadeOrchestrator(
        {"D0": boom, "D1": lambda q: {"hit": True, "payload": "ok"}},
        telemetry_path=tmp_path / "t.jsonl",
    )
    out = orch.solve("问题")
    assert out["ok"] and out["level"] == "D1"
    assert out["telemetry"][0]["error"].startswith("D0")


def test_missing_stage_skipped():
    orch = CascadeOrchestrator({"D2": lambda q: {"hit": True}}, telemetry_path=None)
    out = orch.solve("问题")
    assert out["stages_tried"] == ["D2"]


def test_exhausted_reports_gap(tmp_path):
    reported = {}

    def gap(query, tried):
        reported["query"] = query
        reported["tried"] = tried

    orch = CascadeOrchestrator(
        {"D0": lambda q: {"hit": False}, "D1": lambda q: {"hit": False}},
        gap_reporter=gap,
        telemetry_path=tmp_path / "t.jsonl",
    )
    out = orch.solve("解不出来的问题")
    assert out["ok"] is False
    assert out["degraded_reason"] == "cascade_exhausted"
    assert out["next"] == "capability_gap_workorder"
    assert reported["tried"] == ["D0", "D1"]


def test_d3_writeback_required(tmp_path):
    written = []

    orch = CascadeOrchestrator(
        {"D3": lambda q: {"hit": True, "payload": "REA 结果"}},
        on_writeback=lambda stage, query, payload: written.append((stage, query)),
        telemetry_path=tmp_path / "t.jsonl",
    )
    out = orch.solve("架构问题")
    assert out["level"] == "D3"
    assert written == [("D3", "架构问题")], "D3/D4 命中必须回写记忆树"


def test_writeback_error_does_not_lose_answer(tmp_path):
    orch = CascadeOrchestrator(
        {"D4": lambda q: {"hit": True, "payload": "调研结果"}},
        on_writeback=lambda *a: (_ for _ in ()).throw(RuntimeError("tree down")),
        telemetry_path=tmp_path / "t.jsonl",
    )
    out = orch.solve("前沿问题")
    assert out["ok"] and out["level"] == "D4"
    assert "writeback_error" in out["telemetry"][-1]


def test_telemetry_summary(tmp_path):
    path = tmp_path / "t.jsonl"
    orch = CascadeOrchestrator(
        {"D0": lambda q: {"hit": False}, "D1": lambda q: {"hit": True}},
        telemetry_path=path,
    )
    orch.solve("a")
    orch.solve("b")
    summary = summarize(path)
    assert summary["ok"] and summary["runs"] == 2
    assert summary["per_stage"]["D0"]["hit_rate"] == 0.0
    assert summary["per_stage"]["D1"]["hit_rate"] == 1.0
    assert summary["solved_by_level"]["D1"] == 2


def test_unknown_stage_rejected():
    with pytest.raises(ValueError):
        CascadeOrchestrator({"D9": lambda q: True})


def test_telemetry_is_jsonl(tmp_path):
    path = tmp_path / "t.jsonl"
    CascadeOrchestrator({"D0": lambda q: {"hit": True}}, telemetry_path=path).solve("x")
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["stage"] == "D0"
