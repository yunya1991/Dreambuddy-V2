#!/usr/bin/env python3
"""能力缺口适配层单测：复用 registry / 同类聚合 / 复现计数 / 升级标记。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.capability_gap_adapter import list_aggregated, report_gap  # noqa: E402


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_dry_run_does_not_write(tmp_path):
    p = tmp_path / "gaps.jsonl"
    out = report_gap("向量去重", "OOM", "分块矩阵", path=p, dry_run=True)
    assert out["ok"] and out["action"] == "created" and out["dry_run"]
    assert not p.exists()


def test_same_category_aggregates_into_one_record(tmp_path):
    p = tmp_path / "gaps.jsonl"
    first = report_gap("向量去重", "OOM", "分块矩阵", path=p, dry_run=False)
    second = report_gap("向量去重", "OOM", "分块矩阵", path=p, dry_run=False)
    assert first["action"] == "created" and second["action"] == "aggregated"
    assert second["gap_id"] == first["gap_id"]
    assert second["occurrences"] == 2 and second["escalate"] is True
    assert len(_lines(p)) == 1, "同类必须聚合为 1 条，禁止新增平行记录"


def test_different_failure_mode_is_separate(tmp_path):
    p = tmp_path / "gaps.jsonl"
    report_gap("向量去重", "OOM", "分块矩阵", path=p, dry_run=False)
    out = report_gap("向量去重", "索引锁冲突", "分块矩阵", path=p, dry_run=False)
    assert out["action"] == "created"
    assert len(_lines(p)) == 2


def test_list_aggregated_marks_escalation(tmp_path):
    p = tmp_path / "gaps.jsonl"
    for _ in range(2):
        report_gap("REA 现拆", "超时", "增量索引", path=p, dry_run=False)
    report_gap("REA 现拆", "误报", "AST 校验", path=p, dry_run=False)
    out = list_aggregated(p)
    assert out["count"] == 2 and out["escalated"] == 1
    top = out["items"][0]
    assert top["occurrences"] == 2 and top["escalate"] is True


def test_registry_fields_preserved(tmp_path):
    p = tmp_path / "gaps.jsonl"
    out = report_gap(
        "大数据量去重",
        "OOM",
        "分块相似度",
        expected_enhancement="10 万级分块",
        path=p,
        dry_run=False,
    )
    gap = _lines(p)[0]
    assert gap["gap_id"] == out["gap_id"]
    assert gap["status"] == "open"
    assert gap["gap_type"] == "大数据量去重"
    assert gap["evidence"]["missing_tool"] == "分块相似度"
    assert gap["expected_value"] == "10 万级分块"
