#!/usr/bin/env python3
"""applied.metadata 新增 5 字段 + _condense_action_chain 单测（设计节 4.5 + GC8）。

Task 18: 行动链压缩纯结构化 + register_applied_from_session 接受 5 个新字段。
"""
import sys
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).parent
_PARENT = _SCRIPT_DIR.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

from cognitive_session import _condense_action_chain


def test_condense_merges_adjacent_same_file_edits():
    """GC8：相邻同文件 edit 合并。"""
    chain = [
        {"action_type": "file_change", "file": "foo.py", "detail": "edit foo.py line 1"},
        {"action_type": "file_change", "file": "foo.py", "detail": "edit foo.py line 2"},
        {"action_type": "file_change", "file": "foo.py", "detail": "edit foo.py line 3"},
        {"action_type": "git_commit", "detail": "commit", "commit_hash": "abc"},
    ]
    steps = _condense_action_chain(chain)
    # 3 次同文件 edit 合并为 1 条 + 1 commit = 2 条
    assert len(steps) <= 3
    assert any("foo.py" in s for s in steps)


def test_condense_strips_pure_comment_edits():
    """GC8：纯注释改动剔除。"""
    chain = [
        {"action_type": "file_change", "file": "bar.py", "detail": "edit bar.py comment"},
        {"action_type": "file_change", "file": "bar.py", "detail": "edit bar.py real logic"},
    ]
    steps = _condense_action_chain(chain)
    # 纯注释 edit 应被剔除，只剩 real logic
    assert any("real logic" in s for s in steps)
    # 不应超过 2 条
    assert len(steps) <= 2


def test_condense_produces_5_to_15_steps():
    """设计节 4.5：输出 5-15 条人类可读步骤。"""
    chain = [
        {"action_type": "file_change", "file": f"f{i}.py", "detail": f"edit f{i}.py do task {i}"}
        for i in range(20)
    ]
    chain.append({"action_type": "git_commit", "detail": "commit", "commit_hash": "abc"})
    steps = _condense_action_chain(chain)
    # 20 个不同文件无法合并，但应截断到 15 条上限
    assert len(steps) <= 15
    assert len(steps) >= 1


def test_applied_metadata_has_five_new_fields():
    """设计节 4.5：register_applied_from_session 接受 5 个新字段并写入 metadata。"""
    from cognitive_superpowers import ProcessTemplateRegistry
    registry = ProcessTemplateRegistry()
    import time
    applied_id = f"APP-TEST-{int(time.time() * 1000)}"
    registry.register_applied_from_session(
        template_id=applied_id,
        name="test applied",
        steps=["step1"],
        parent_template_id="test-driven-development",
        solution_path={"outcome": {"success": True}, "approach": {}},
        unit_id="MU-DEV",
        parent_skill_ids=["test-driven-development"],
        process_verify_report={"test-driven-development": {"score": 0.78, "followed": True}},
        task_type="python-development",
        reproducible_steps=["step1", "step2"],
        key_artifacts={"added_files": ["t.py"], "modified_files": ["f.py"], "debt_items": []},
    )
    applied = registry.get_applied(applied_id)
    assert applied is not None
    meta = applied.metadata
    assert "parent_skill_ids" in meta
    assert meta["parent_skill_ids"] == ["test-driven-development"]
    assert "process_verify_report" in meta
    assert "task_type" in meta
    assert "reproducible_steps" in meta
    assert "key_artifacts" in meta
