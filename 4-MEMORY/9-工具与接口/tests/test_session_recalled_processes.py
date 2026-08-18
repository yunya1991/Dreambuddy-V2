#!/usr/bin/env python3
"""cognitive_session recalled_processes 强类型单测（设计节 4.2）。

Task 17: RecalledProcessItem dataclass + session.recalled_processes 强类型。
"""
import sys
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).parent
_PARENT = _SCRIPT_DIR.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))


def test_recalled_process_item_dataclass():
    from cognitive_session import RecalledProcessItem
    from cognitive_superpowers import SuperpowersSkill
    item = RecalledProcessItem(
        kind="meta",
        meta=SuperpowersSkill(
            skill_id="tdd", display_name="TDD", description="",
            version="v1", raw_skill_md="", hard_gates=[], checklists=[],
            trigger_keywords=[], supplement=None, md5_of_base="x", localized=False,
        ),
        applied=None,
        match_score=0.8,
        match_reason="命中 tdd",
        skill_id="tdd",
        applied_id=None,
    )
    assert item.kind == "meta"
    assert item.skill_id == "tdd"
    assert item.meta is not None
    assert item.applied is None


def test_recalled_process_item_applied_kind():
    from cognitive_session import RecalledProcessItem
    item = RecalledProcessItem(
        kind="applied",
        meta=None,
        applied={"applied_id": "APP-001", "title": "test"},
        match_score=0.7,
        match_reason="命中",
        skill_id="tdd",
        applied_id="APP-001",
    )
    assert item.kind == "applied"
    assert item.applied_id == "APP-001"


def test_session_recalled_processes_typed():
    """session.recalled_processes 应为 List[RecalledProcessItem]。"""
    from cognitive_session import CognitiveSession, RecalledProcessItem
    sess = CognitiveSession()
    assert isinstance(sess.recalled_processes, list)
    item = RecalledProcessItem(
        kind="meta", meta=None, applied=None, match_score=0.5,
        match_reason="x", skill_id="tdd", applied_id=None,
    )
    sess.recalled_processes.append(item)
    assert len(sess.recalled_processes) == 1
    assert isinstance(sess.recalled_processes[0], RecalledProcessItem)
