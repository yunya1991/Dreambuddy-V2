#!/usr/bin/env python3
"""skill_verifier 单测：verify_skill_followed + compute_follow_score（设计节 4.3/4.4）。

Task 12 遗漏交付物补齐——验证事后校验引擎对原版 SKILL.md 的 Checklist + HARD-GATE 校验。
"""
import sys
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).parent
_PARENT = _SCRIPT_DIR.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

from cognitive_superpowers import SuperpowersSkill
from skill_verifier import (
    verify_skill_followed,
    compute_follow_score,
    FOLLOW_SCORE_THRESHOLD,
)


def _make_skill(skill_id: str, gates: list, checklists: list) -> SuperpowersSkill:
    return SuperpowersSkill(
        skill_id=skill_id,
        display_name=skill_id,
        description="",
        version="v1",
        raw_skill_md="",
        hard_gates=gates,
        checklists=checklists,
        trigger_keywords=[],
        supplement=None,
        md5_of_base="x",
        localized=False,
    )


def _make_chain(*actions) -> list:
    """actions: tuple of (action_type, detail, **extra)"""
    chain = []
    for a in actions:
        atype, detail = a[0], a[1]
        extra = a[2] if len(a) > 2 else {}
        event = {"action_type": atype, "detail": detail}
        event.update(extra)
        chain.append(event)
    return chain


def test_follow_score_threshold_is_035():
    assert FOLLOW_SCORE_THRESHOLD == 0.35


def test_compute_follow_score_formula():
    """follow_score = (checklist_matched/total)*0.6 + (gate_respected/total)*0.4"""
    score = compute_follow_score(
        checklist_matched=2, checklist_total=3,
        gate_respected=2, gate_total=2,
    )
    expected = (2 / 3) * 0.6 + (2 / 2) * 0.4
    assert abs(score - expected) < 0.01


def test_compute_follow_score_zero_when_nothing_matched():
    score = compute_follow_score(0, 0, 0, 0)
    assert score == 0.0


def test_verify_tdd_followed_when_test_before_code():
    skill = _make_skill(
        "test-driven-development",
        gates=["NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST"],
        checklists=["Write a failing test", "Write minimal implementation"],
    )
    chain = _make_chain(
        ("file_change", "add test_foo.py", {"file": "tests/test_foo.py"}),
        ("file_change", "edit foo.py", {"file": "foo.py"}),
        ("git_commit", "red green", {"commit_hash": "abc"}),
    )
    result = verify_skill_followed(skill, chain)
    assert result["followed"] is True
    assert result["score"] > 0


def test_verify_tdd_violated_when_code_before_test():
    """设计节 4.4：HARD-GATE 违反判定看相对时序——先写代码后补测试且未删除=违反。"""
    skill = _make_skill(
        "test-driven-development",
        gates=["NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST"],
        checklists=["Write a failing test"],
    )
    chain = _make_chain(
        ("file_change", "edit foo.py", {"file": "foo.py"}),
        ("file_change", "add test_foo.py", {"file": "tests/test_foo.py"}),
        ("git_commit", "commit", {"commit_hash": "abc"}),
    )
    result = verify_skill_followed(skill, chain)
    assert result["score"] < 0.5 or len(result["gate_violations"]) > 0


def test_verify_custom_path_when_no_skill_followed():
    """设计节 4.3 Step 3：没有 follow_score ≥ 0.35 → followed=False。"""
    skill = _make_skill("x", gates=[], checklists=["write failing test first"])
    chain = _make_chain(("tool_call", "do something unrelated"))
    result = verify_skill_followed(skill, chain)
    assert result["followed"] is False
    assert result["score"] < FOLLOW_SCORE_THRESHOLD


def test_verify_result_has_required_fields():
    skill = _make_skill("x", gates=["g1"], checklists=["c1"])
    chain = _make_chain(("file_change", "edit x.py", {"file": "x.py"}))
    result = verify_skill_followed(skill, chain)
    for key in ("followed", "score", "checklist_matched", "checklist_missed",
                "gate_violations", "gate_respected"):
        assert key in result, f"Missing key: {key}"
