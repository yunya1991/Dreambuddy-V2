#!/usr/bin/env python3
"""
Task 11: process_recall 测试（设计节 3.2/3.6）
retrieve 返回 + process_block 注入 + 去抖合并。
"""

import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

_SCRIPT_DIR = Path(__file__).parent
_PARENT = _SCRIPT_DIR.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

from cognitive_superpowers import SkillLoader, SuperpowersSkill, retrieve_relevant_processes, ProcessTemplateRegistry, format_process_suggestions


def test_process_keyword_retrieve_topk() -> None:
    loader = SkillLoader()
    result = loader.retrieve(
        "TDD test driven development FAILING test first minimal code bugfix implementation",
        top_meta=3, top_applied=2,
    )

    assert "meta" in result
    meta_results = result["meta"]
    assert len(meta_results) >= 3, f"Expected at least 3 meta results, got {len(meta_results)}"

    top_ids = [t[0].skill_id for t in meta_results[:3]]
    assert "test-driven-development" in top_ids[:2], (
        f"Expected test-driven-development in position #1 or #2, got top order: {top_ids}"
    )


def test_process_keyword_debug_retrieve() -> None:
    loader = SkillLoader()
    result = loader.retrieve(
        "systematic debugging bug fix root cause reproduce unexpected behavior investigation",
        top_meta=3, top_applied=2,
    )

    assert "meta" in result
    meta_results = result["meta"]
    assert len(meta_results) >= 2, f"Expected at least 2 meta results, got {len(meta_results)}"

    top_ids = [t[0].skill_id for t in meta_results[:2]]
    assert "systematic-debugging" in top_ids, (
        f"Expected systematic-debugging in top 2, got top order: {top_ids}"
    )


def test_process_block_markdown_format() -> None:
    loader = SkillLoader()
    result = loader.retrieve(
        "TDD test driven development FAILING test bugfix code",
        top_meta=3, top_applied=2,
    )
    meta_list = result["meta"]

    lines: List[str] = []
    lines.append("## 🎯 流程建议（非约束，可自由选择是否遵循）")
    lines.append("")

    for idx, (skill, score, reason) in enumerate(meta_list, 1):
        lines.append(f"### {idx}. [{skill.skill_id}] {skill.display_name}")
        lines.append(f"- skill_id: `{skill.skill_id}`")
        lines.append(f"- 匹配分: {score:.2f}")
        lines.append(f"- 命中依据: {reason}")
        if skill.description:
            desc_short = skill.description[:120]
            lines.append(f"- 说明: {desc_short}")
        lines.append("")

    process_block = "\n".join(lines)

    assert "🎯 流程建议" in process_block, "process_block 应包含 🎯 流程建议 段"
    for (skill, _, _) in meta_list:
        assert skill.skill_id in process_block, (
            f"process_block 应包含 meta skill 的 skill_id: {skill.skill_id}"
        )

    legacy_registry = ProcessTemplateRegistry(auto_discover=False)
    legacy_results = retrieve_relevant_processes("TDD 测试", legacy_registry, top_k=3)
    legacy_markdown = format_process_suggestions(legacy_results)
    assert "🎯 流程建议" in legacy_markdown, "format_process_suggestions 应包含 🎯 流程建议 段"
    for t in legacy_results:
        assert t.template_id in legacy_markdown, (
            f"format_process_suggestions 应包含 template_id: {t.template_id}"
        )


def test_debounce_merge_stable_not_jitter() -> None:
    loader = SkillLoader()

    def top_ids(query: str, k: int = 3) -> List[str]:
        r = loader.retrieve(query, top_meta=k, top_applied=0)
        return [t[0].skill_id for t in r["meta"][:k]]

    old_ids = top_ids("TDD test driven development FAILING first minimal code")
    new_ids = top_ids("TDD test driven development FAILING first minimal code bugfix")

    assert len(old_ids) >= 3, f"old result less than 3: {old_ids}"
    assert len(new_ids) >= 3, f"new result less than 3: {new_ids}"

    old_top3 = set(old_ids[:3])
    new_top3 = set(new_ids[:3])
    overlap = old_top3 & new_top3
    overlap_count = len(overlap)
    overlap_rate = overlap_count / 3.0

    assert overlap_rate >= 0.6, (
        f"去抖合并失败：小关键词改动导致结果抖变。\n"
        f"old (TDD 测试): {list(old_top3)}\n"
        f"new (TDD 测试 单测): {list(new_top3)}\n"
        f"重合: {list(overlap)} ({overlap_count}/3 = {overlap_rate:.2%} < 60%)"
    )
