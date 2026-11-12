"""T-G15 ADR 化 — RED 测试

SPEC-33-G §2.11.5 / §2.12.3：
  - 模式 → ADR 草案（≥2 候选方案、PoE 评分、影响面、回滚与灰度、L2 任务清单）
  - 模式候选门槛：≥5 条同类 Case 且跨 ≥3 次迭代；背景 Evidence ≥2
  - L3 评审入口：AI 评审 + 人终审两步，缺一不得 approved
  - L2 任务拆解：每个任务必须落在 L2 边界（单模块 ≤3 文件 ≤200 行），超出即拒绝

RED 契约：core.evolution.adr_builder 不存在。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from core.evolution.adr_builder import AdrBuilder, AdrError

BASE = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, now=BASE):
        self.now = now

    def __call__(self):
        return self.now


def _pattern(**overrides):
    payload = {
        "pattern_id": "PAT-001",
        "summary": "取证前移可减少无证据改动",
        "module": "33-REA逆向解析工程",
        "change_type": "code",
        "defect_type": "missing_evidence",
        "cases": [
            {
                "case_id": f"C-{index}",
                "iteration_id": f"ITER-{index % 3}",
            }
            for index in range(5)
        ],
        "evidence_refs": ["EV-L0-REA-1", "EV-CASE-2"],
    }
    payload.update(overrides)
    return payload


def _task(**overrides):
    payload = {
        "task_id": "L2-1",
        "title": "实现取证门禁",
        "module": "33-REA逆向解析工程",
        "files": ["33-REA逆向解析工程/core/evolution/demo.py"],
        "lines_changed": 80,
        "acceptance": "取证为空时拒绝进入门禁",
    }
    payload.update(overrides)
    return payload


def _builder(tmp_path, **overrides):
    kwargs = {"root": tmp_path / "decisions", "clock": Clock()}
    kwargs.update(overrides)
    return AdrBuilder(**kwargs)


def _build(builder, **overrides):
    payload = {
        "pattern": _pattern(),
        "title": "取证前移",
        "options": [
            {"name": "A", "description": "门禁前移", "poe_score": 0.72},
            {"name": "B", "description": "并行取证", "poe_score": 0.61},
        ],
        "impact": "仅影响 evolution 研发流水线",
        "rollback": "关闭取证门禁开关即回到旧路径",
        "l2_tasks": [_task()],
    }
    payload.update(overrides)
    return builder.build(**payload)


def test_build_writes_adr_with_required_sections(tmp_path):
    builder = _builder(tmp_path)
    result = _build(builder)

    assert result["adr_id"] == "ADR-001"
    assert result["status"] == "pending_review"
    path = tmp_path / "decisions" / "ADR-001-取证前移.md"
    assert path.is_file()

    content = path.read_text(encoding="utf-8")
    for keyword in ("背景与触发证据", "候选方案", "PoE", "影响面", "回滚与灰度", "L2 任务"):
        assert keyword in content
    assert "EV-L0-REA-1" in content
    assert "PAT-001" in content


def test_build_writes_review_entry(tmp_path):
    builder = _builder(tmp_path)
    result = _build(builder)

    queue = tmp_path / "decisions" / "review_queue.jsonl"
    assert queue.is_file()
    entry = json.loads(queue.read_text(encoding="utf-8").splitlines()[0])
    assert entry["adr_id"] == result["adr_id"]
    assert entry["status"] == "pending_review"
    assert entry["reviews"] == []
    assert set(entry["required_reviewers"]) == {"ai_reviewer", "human_reviewer"}


def test_build_rejects_pattern_with_too_few_cases(tmp_path):
    pattern = _pattern(cases=[{"case_id": f"C-{i}", "iteration_id": f"ITER-{i}"} for i in range(4)])
    with pytest.raises(AdrError) as excinfo:
        _build(_builder(tmp_path), pattern=pattern)
    assert "5" in str(excinfo.value) or "案例" in str(excinfo.value)


def test_build_rejects_pattern_with_too_few_iterations(tmp_path):
    pattern = _pattern(cases=[{"case_id": f"C-{i}", "iteration_id": "ITER-0"} for i in range(6)])
    with pytest.raises(AdrError) as excinfo:
        _build(_builder(tmp_path), pattern=pattern)
    assert "迭代" in str(excinfo.value)


def test_build_rejects_insufficient_evidence(tmp_path):
    with pytest.raises(AdrError) as excinfo:
        _build(_builder(tmp_path), pattern=_pattern(evidence_refs=["EV-1"]))
    assert "Evidence" in str(excinfo.value) or "证据" in str(excinfo.value)


def test_build_rejects_single_option(tmp_path):
    with pytest.raises(AdrError) as excinfo:
        _build(_builder(tmp_path), options=[{"name": "A", "description": "唯一方案"}])
    assert "候选方案" in str(excinfo.value) or "2" in str(excinfo.value)


def test_build_rejects_l2_task_beyond_boundary(tmp_path):
    task = _task(
        files=[
            "33-REA逆向解析工程/core/a.py",
            "4-MEMORY/9-工具与接口/b.py",
        ]
    )
    with pytest.raises(AdrError) as excinfo:
        _build(_builder(tmp_path), l2_tasks=[task])
    assert "L2" in str(excinfo.value) and (
        "拆分" in str(excinfo.value) or "边界" in str(excinfo.value)
    )


def test_build_rejects_task_without_acceptance(tmp_path):
    task = _task(acceptance="")
    with pytest.raises(AdrError) as excinfo:
        _build(_builder(tmp_path), l2_tasks=[task])
    assert "acceptance" in str(excinfo.value) or "验收" in str(excinfo.value)


def test_adr_number_autoincrements(tmp_path):
    builder = _builder(tmp_path)
    _build(builder, title="第一份")
    second = _build(builder, title="第二份")
    assert second["adr_id"] == "ADR-002"


def test_review_requires_ai_then_human(tmp_path):
    builder = _builder(tmp_path)
    result = _build(builder)
    adr_id = result["adr_id"]

    with pytest.raises(AdrError):
        builder.record_review(
            adr_id, reviewer="human_reviewer", decision="approve", notes="直接终审"
        )

    builder.record_review(adr_id, reviewer="ai_reviewer", decision="approve", notes="AI 通过")
    pending = builder.pending_reviews()
    assert pending[0]["status"] == "awaiting_human"
    assert len(pending[0]["reviews"]) == 1

    builder.record_review(adr_id, reviewer="human_reviewer", decision="approve", notes="人工终审")
    assert builder.pending_reviews() == []


def test_review_rejection_is_terminal(tmp_path):
    builder = _builder(tmp_path)
    adr_id = _build(builder)["adr_id"]

    builder.record_review(adr_id, reviewer="ai_reviewer", decision="reject", notes="证据不足")
    assert builder.pending_reviews() == []
