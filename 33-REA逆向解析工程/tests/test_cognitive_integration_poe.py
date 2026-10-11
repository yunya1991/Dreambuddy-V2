"""RED 测试：CognitiveIntegration 扩展 — Task 6 PoE 认知集成扩展。

依据：TASKS-工程实践复现器.md TR-6.1 / TR-6.2 / TR-6.3
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# RED: 函数尚未实现，import 应失败
from core.cognitive_integration import (
    prepare_audit_record_params,
    prepare_decision_record_params,
    prepare_methodology_record_params,
)


# ---------- 测试用例 ----------


def test_prepare_audit_record_params_tags():
    """TR-6.1: tags 含 'rea-audit'，content 包含证据链得分和债务摘要。"""
    audit_result = {
        "target": "/mock/ai_output",
        "evidence_chain_score": 0.45,
        "coverage_score": 0.3,
        "complexity_penalty": 0.4,
        "poe_score": 0.35,
        "gate_decision": "reject",
        "cognitive_debt": [
            {
                "type": "magic_number",
                "description": "魔法数字: 142",
                "evidence": type("E", (), {
                    "result": "魔法数字 142",
                    "level": type("L", (), {"value": "observation"})(),
                    "provenance": {"file": "/mock/x.py", "line": 5},
                    "confidence": 0.7,
                    "known_gaps": [],
                })(),
            }
        ],
        "evidence": [],
    }
    params = prepare_audit_record_params(audit_result)
    assert "content" in params
    assert "tags" in params
    tags = params["tags"].split(",")
    assert "rea-audit" in tags, f"tags 应含 rea-audit (TR-6.1): {tags}"
    assert "PoE" in tags or "poe" in params["tags"].lower(), "tags 应含 PoE"
    content = params["content"]
    assert "0.45" in content or "0.35" in content, f"content 应含证据链得分 (TR-6.1): {content[:200]}"
    assert "magic" in content.lower() or "魔法" in content or "reject" in content, "content 应含债务摘要"


def test_prepare_methodology_record_params_tags():
    """TR-6.2: tags 含 'rea-methodology'，content 包含 problem_pattern 和 solution_pattern。"""
    methodology_result = {
        "methodologies": [
            {
                "methodology_id": "mt_mvc_001",
                "problem_pattern": "MVC 架构组织",
                "solution_pattern": "采用 MVC 模式组织代码：models/views/controllers",
                "applicability": ["项目需要职责分离"],
                "known_gaps": [],
                "evidence": None,
                "source_projects": ["/mock/proj-a", "/mock/proj-b"],
            }
        ],
        "evidence": [],
    }
    params = prepare_methodology_record_params(methodology_result)
    tags = params["tags"].split(",")
    assert "rea-methodology" in tags, f"tags 应含 rea-methodology (TR-6.2): {tags}"
    content = params["content"]
    assert "MVC" in content, f"content 应含 problem_pattern (TR-6.2): {content[:200]}"
    assert "models" in content or "Solution" in content or "采用" in content, \
        f"content 应含 solution_pattern: {content[:200]}"


def test_prepare_decision_record_params_tags():
    """附加: tags 含 'rea-decision'，content 包含决策描述。"""
    decision_result = {
        "target": "/mock/proj",
        "decisions": [
            {
                "decision": "采用 MVC 架构模式",
                "context": "目录结构匹配 MVC",
                "consequences": ["约束后续模块组织"],
                "alternatives": [],
                "evidence": None,
            }
        ],
        "evidence": [],
    }
    params = prepare_decision_record_params(decision_result)
    tags = params["tags"].split(",")
    assert "rea-decision" in tags, f"tags 应含 rea-decision: {tags}"
    content = params["content"]
    assert "MVC" in content, "content 应含决策描述"


def test_prepare_audit_record_params_structure_legal():
    """TR-6.3: 输出参数可直接传给 record 工具（结构合法）。"""
    audit_result = {
        "target": "/mock",
        "evidence_chain_score": 0.5,
        "coverage_score": 0.5,
        "complexity_penalty": 0.2,
        "poe_score": 0.5,
        "gate_decision": "review",
        "cognitive_debt": [],
        "evidence": [],
    }
    params = prepare_audit_record_params(audit_result)
    # 结构合法性：content(str) + quality_level(str) + tags(str)
    assert isinstance(params["content"], str)
    assert "quality_level" in params
    assert isinstance(params["tags"], str)
    # quality_level 应为 B 或 A 之一
    assert params["quality_level"] in ("B", "A", "C", "S", "D")


def test_prepare_methodology_record_params_structure_legal():
    """TR-6.3: 方法论参数结构合法。"""
    methodology_result = {
        "methodologies": [],
        "evidence": [],
    }
    params = prepare_methodology_record_params(methodology_result)
    assert isinstance(params["content"], str)
    assert "quality_level" in params
    assert isinstance(params["tags"], str)


def test_prepare_decision_record_params_structure_legal():
    """TR-6.3: 决策参数结构合法。"""
    decision_result = {
        "target": "/mock",
        "decisions": [],
        "evidence": [],
    }
    params = prepare_decision_record_params(decision_result)
    assert isinstance(params["content"], str)
    assert "quality_level" in params
    assert isinstance(params["tags"], str)
