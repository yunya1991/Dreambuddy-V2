#!/usr/bin/env python3
"""
Task 12: applied_flow 测试（设计节 4.3 + 4.6）
父 Skill 选择算法 follow_score + LEGACY_TO_NEW 退化映射表。
"""

import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

_SCRIPT_DIR = Path(__file__).parent
_PARENT = _SCRIPT_DIR.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

from cognitive_superpowers import SkillLoader


LEGACY_TO_NEW: Dict[str, str] = {
    "TDD-001":        "test-driven-development",
    "DEBUG-001":      "systematic-debugging",
    "REFACTOR-001":   "test-driven-development",
    "REVIEW-001":     "requesting-code-review",
    "DESIGN-001":     "brainstorming",
    "TDD-DEBUG-001":  "subagent-driven-development",
}


def test_legacy_mapping_all_6_keys_present() -> None:
    expected_keys = {"TDD-001", "DEBUG-001", "REFACTOR-001", "REVIEW-001", "DESIGN-001", "TDD-DEBUG-001"}
    actual_keys = set(LEGACY_TO_NEW.keys())
    assert len(LEGACY_TO_NEW) == 6, f"Expected 6 keys, got {len(LEGACY_TO_NEW)}: {list(LEGACY_TO_NEW.keys())}"
    assert actual_keys == expected_keys, (
        f"LEGACY_TO_NEW keys mismatch.\n"
        f"Expected: {sorted(expected_keys)}\n"
        f"Actual:   {sorted(actual_keys)}\n"
        f"Missing:  {sorted(expected_keys - actual_keys)}\n"
        f"Extra:    {sorted(actual_keys - expected_keys)}"
    )

    loader = SkillLoader()
    valid_skill_ids = set(loader.skills.keys())
    for v in LEGACY_TO_NEW.values():
        assert v in valid_skill_ids, (
            f"LEGACY_TO_NEW value {v!r} not in 14 original skill_ids: {sorted(valid_skill_ids)}"
        )


def test_legacy_mapping_values_valid_skill_ids() -> None:
    loader = SkillLoader()
    for v in LEGACY_TO_NEW.values():
        assert v in loader.skills, (
            f"{v!r} not found in SkillLoader().skills keys: {sorted(loader.skills.keys())}"
        )


def compute_follow_score(
    matched_checklist: int,
    total_checklist: int,
    matched_gate: int,
    total_gate: int,
    threshold: float = 0.35,
) -> Tuple[float, bool]:
    """
    设计节 4.3: 父 Skill 选择算法
    follow_score = Checklist * 0.6 + Gate * 0.4
    should_follow = follow_score >= 0.35
    """
    if total_checklist == 0:
        cl_ratio = 0.0
    else:
        cl_ratio = matched_checklist / total_checklist

    if total_gate == 0:
        g_ratio = 0.0
    else:
        g_ratio = matched_gate / total_gate

    score = cl_ratio * 0.6 + g_ratio * 0.4
    score = round(score, 4)
    should_follow = score >= threshold
    return score, should_follow


def test_follow_score_calculation() -> None:
    s1, f1 = compute_follow_score(3, 4, 1, 2)
    assert s1 == pytest.approx(0.65, abs=0.01), (
        f"Case 1: 3/4 cl + 1/2 gate = (3/4)*0.6 + (1/2)*0.4 = 0.45 + 0.20 = 0.65, got {s1}"
    )
    assert f1 is True, f"0.65 >= 0.35 → should be True, got {f1}"

    s2, f2 = compute_follow_score(0, 0, 0, 0)
    assert s2 == pytest.approx(0.00, abs=0.01), (
        f"Case 2: 0/0 cl + 0/0 gate = 0.00, got {s2}"
    )
    assert f2 is False, f"0.00 < 0.35 → should be False, got {f2}"

    s3, f3 = compute_follow_score(1, 8, 0, 2)
    expected_3 = (1 / 8) * 0.6 + 0.0
    assert s3 == pytest.approx(expected_3, abs=0.01), (
        f"Case 3: 1/8 cl + 0/2 gate = 0.075, got {s3}"
    )
    assert s3 == pytest.approx(0.075, abs=0.01)
    assert f3 is False, f"0.075 < 0.35 → should be False, got {f3}"

    s4, f4 = compute_follow_score(2, 4, 1, 1)
    expected_4 = (2 / 4) * 0.6 + (1 / 1) * 0.4
    assert s4 == pytest.approx(0.70, abs=0.01), (
        f"Case 4: 2/4 cl + 1/1 gate = 0.30 + 0.40 = 0.70, got {s4}"
    )
    assert f4 is True, f"0.70 >= 0.35 → should be True, got {f4}"


def test_applied_parent_multiple_supported() -> None:
    loader = SkillLoader()

    applied_record = {
        "applied_id": "APP-TEST-MULTI-PARENT",
        "parent_skill_ids": [
            "test-driven-development",
            "systematic-debugging",
        ],
        "steps": ["复现问题", "写失败测试", "定位根因", "写实现", "验证修复"],
        "notes": "TDD + 调试复合场景",
    }

    assert len(applied_record["parent_skill_ids"]) >= 2, (
        f"parent_skill_ids 长度不足 2: {applied_record['parent_skill_ids']}"
    )

    valid_ids = set(loader.skills.keys())
    for pid in applied_record["parent_skill_ids"]:
        assert pid in valid_ids, (
            f"parent_skill_id {pid!r} 不在 SkillLoader().skills 中。可用 skill_ids: {sorted(valid_ids)}"
        )

    assert "test-driven-development" in applied_record["parent_skill_ids"]
    assert "systematic-debugging" in applied_record["parent_skill_ids"]
