#!/usr/bin/env python3
"""test_skill_adapter_boundary.py — skill_adapter Autonomy Boundary 提取测试

TDD: 验证 parse_skill_metadata 支持提取 ## Autonomy Boundary 段落
覆盖 AC-5
"""
import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


SKILL_WITH_BOUNDARY = """---
name: Test Skill
chain: A
description: A test skill
---

# Test Skill

## System
你是一个测试分析节点。

## Autonomy Boundary
可自主执行：数据查询、指标计算
需用户确认：下单、撤单、修改仓位

## Description
这是一个测试技能。
"""

SKILL_WITHOUT_BOUNDARY = """---
name: Test Skill No Boundary
chain: A
---

# Test Skill No Boundary

## System
你是一个测试分析节点。
"""


def test_parse_autonomy_boundary_present():
    """TR-3.1: 含 ## Autonomy Boundary 的 SKILL.md → meta['autonomy_boundary'] 非空"""
    from dreamos.adapters.skill_adapter import parse_skill_metadata

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(SKILL_WITH_BOUNDARY)
        path = f.name

    try:
        meta = parse_skill_metadata(path)
        assert "autonomy_boundary" in meta
        assert meta["autonomy_boundary"] != "", "autonomy_boundary 不应为空"
        assert "下单" in meta["autonomy_boundary"]
        assert "需用户确认" in meta["autonomy_boundary"]
    finally:
        os.unlink(path)


def test_parse_autonomy_boundary_absent():
    """TR-3.2: 不含 ## Autonomy Boundary 的 SKILL.md → meta['autonomy_boundary'] 为空字符串"""
    from dreamos.adapters.skill_adapter import parse_skill_metadata

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(SKILL_WITHOUT_BOUNDARY)
        path = f.name

    try:
        meta = parse_skill_metadata(path)
        # 字段应存在但为空字符串（不报错）
        assert "autonomy_boundary" in meta
        assert meta["autonomy_boundary"] == ""
    finally:
        os.unlink(path)


if __name__ == "__main__":
    test_parse_autonomy_boundary_present()
    test_parse_autonomy_boundary_absent()
    print("All tests passed!")
