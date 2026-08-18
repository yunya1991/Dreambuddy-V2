#!/usr/bin/env python3
"""
⚠️  归档文件：Legacy (pre-upstream-Superpowers) 自创流程模板 6 个
⚠️  来源: cognitive_superpowers.py DEFAULT_TEMPLATES
⚠️  归档日期: 2026-08-01
⚠️  用途: 仅用于追溯自创 6 类模板的原始内容；新代码不得引用本文件
⚠️  迁移后替代: 原版 14 个 Skill (obra/superpowers v6.2.0) 通过 SkillLoader 动态加载
"""

# ============================================================
# 以下为提取的 DEFAULT_TEMPLATES 定义全文（字节不变，仅移除类内部缩进）
# 起止行号（原 cognitive_superpowers.py）: L390-L457
# ============================================================
DEFAULT_TEMPLATES = [
    {
        "template_id": "TDD-001",
        "name": "测试驱动开发",
        "steps": ["理解需求", "写失败测试", "写最小实现", "测试通过", "重构"],
        "description": "先写测试再写代码的工程实践",
        "confidence": 0.85,
        "verify_count": 15,
        "source": "software-engineering-best-practices",
        "tags": ["testing", "development", "quality"],
        "layer": "meta",
    },
    {
        "template_id": "DEBUG-001",
        "name": "系统化调试",
        "steps": ["复现问题", "定位根因", "编写修复", "验证修复", "添加防御"],
        "description": "科学调试方法论",
        "confidence": 0.80,
        "verify_count": 12,
        "source": "software-engineering-best-practices",
        "tags": ["debugging", "troubleshooting"],
        "layer": "meta",
    },
    {
        "template_id": "REFACTOR-001",
        "name": "代码重构",
        "steps": ["识别坏味道", "小步修改", "运行测试", "验证行为"],
        "description": "安全重构的渐进式方法",
        "confidence": 0.75,
        "verify_count": 10,
        "source": "software-engineering-best-practices",
        "tags": ["refactoring", "clean-code"],
        "layer": "meta",
    },
    {
        "template_id": "REVIEW-001",
        "name": "代码审查",
        "steps": ["检查逻辑正确性", "检查边界条件", "检查命名清晰度", "检查文档完整性"],
        "description": "系统性代码审查流程",
        "confidence": 0.70,
        "verify_count": 8,
        "source": "software-engineering-best-practices",
        "tags": ["review", "quality"],
        "layer": "meta",
    },
    {
        "template_id": "DESIGN-001",
        "name": "系统化设计",
        "steps": ["明确需求", "分析矛盾", "设计方案", "验证可行性", "落地实现"],
        "description": "系统化设计方法论（对齐矛盾分析）",
        "confidence": 0.70,
        "verify_count": 5,
        "source": "systems-engineering",
        "tags": ["design", "architecture", "contradiction"],
        "layer": "meta",
    },
    {
        "template_id": "TDD-DEBUG-001",
        "name": "TDD+调试复合流程",
        "steps": ["复现问题", "写失败测试", "定位根因", "写最小实现", "测试通过"],
        "description": "TDD与调试结合的复合流程",
        "confidence": 0.65,
        "verify_count": 3,
        "source": "composed-practice",
        "tags": ["testing", "debugging", "composite"],
        "layer": "meta",
    },
]
# ============================================================
# 归档结束
# ============================================================
