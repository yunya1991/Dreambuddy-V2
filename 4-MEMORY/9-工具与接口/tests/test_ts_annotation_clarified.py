#!/usr/bin/env python3
"""验证 TS 层注释已澄清与认知层 Process Layer 解耦（设计节 5.1 + GC2）。

Task 20: methodology-executor.ts + superpowers-skill-adapter.ts 头部注释澄清。
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
METHODOLOGY_EXECUTOR = PROJECT_ROOT / "6-图结构上下文压缩" / "planner" / "methodology-executor.ts"
SKILL_ADAPTER = PROJECT_ROOT / "6-图结构上下文压缩" / "planner" / "superpowers-skill-adapter.ts"


def test_methodology_executor_annotation_clarified():
    content = METHODOLOGY_EXECUTOR.read_text(encoding="utf-8")
    head = content[:1500]
    # 应明确"与认知层 Process Layer 解耦"
    assert "解耦" in head or "decoupled" in head.lower()
    # 应明确"交易节点质量门禁"定位
    assert "交易" in head or "trading" in head.lower() or "节点" in head
    # 不应再直接绑定 "Claude Code Superpowers 7阶段方法论"
    assert "7阶段方法论" not in content or "解耦" in content


def test_skill_adapter_annotation_clarified():
    content = SKILL_ADAPTER.read_text(encoding="utf-8")
    head = content[:1500]
    # 应明确"仅解析不执行"
    assert "解析" in head or "parser" in head.lower()
    # 应指向 Python SkillLoader 为通用认知层实现
    assert "Python" in head or "SkillLoader" in head or "skill_loader" in head
    # 应明确"不负责执行"
    assert "不负责执行" in head or "not execute" in head.lower() or "不执行" in head
