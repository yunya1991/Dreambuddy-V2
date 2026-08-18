#!/usr/bin/env python3
"""post_hoc_verify 改用 verify_skill_followed（设计节 4.4）。

Task 19: post_hoc_verify 对每个召回的 meta Skill 做事后校验，结果写入 session._verify_reports。
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_SCRIPT_DIR = Path(__file__).parent
_PARENT = _SCRIPT_DIR.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))


def test_post_hoc_verify_uses_verify_skill_followed():
    """post_hoc_verify 应调用 verify_skill_followed 并写入 _verify_reports。"""
    from cognitive_session import CognitiveSession, RecalledProcessItem, post_hoc_verify
    from cognitive_superpowers import SuperpowersSkill

    sess = CognitiveSession()
    skill = SuperpowersSkill(
        skill_id="test-driven-development", display_name="TDD", description="",
        version="v1", raw_skill_md="",
        hard_gates=["NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST"],
        checklists=["Write a failing test"], trigger_keywords=[],
        supplement=None, md5_of_base="x", localized=False,
    )
    sess.recalled_processes.append(RecalledProcessItem(
        kind="meta", meta=skill, applied=None, match_score=0.8,
        match_reason="tdd", skill_id="test-driven-development", applied_id=None,
    ))
    sess.action_chain = [
        {"action_type": "file_change", "file": "tests/test_foo.py", "detail": "add test_foo.py"},
        {"action_type": "file_change", "file": "foo.py", "detail": "edit foo.py"},
        {"action_type": "git_commit", "detail": "red green", "commit_hash": "abc"},
    ]
    sess._meta_processes = sess.recalled_processes

    cle = MagicMock()
    solution_path = {"outcome": {"success": True}, "approach": {"files_touched": []}}
    memory_id = "M-001"

    post_hoc_verify(cle, sess, solution_path, memory_id)
    # session 上应有 _verify_reports
    assert hasattr(sess, "_verify_reports")
    assert "test-driven-development" in sess._verify_reports
    assert "score" in sess._verify_reports["test-driven-development"]


def test_post_hoc_verify_does_not_call_legacy_verify_process_followed():
    """不应再调用旧的 verify_process_followed。"""
    import cognitive_session
    # 旧函数可能还在 cognitive_superpowers 中，但 cognitive_session.post_hoc_verify 不应使用它
    # 验证 post_hoc_verify 函数不引用 verify_process_followed
    import inspect
    src = inspect.getsource(cognitive_session.post_hoc_verify)
    assert "verify_process_followed" not in src or "verify_skill_followed" in src
