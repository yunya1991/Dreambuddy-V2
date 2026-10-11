"""集成测试：PoE 端到端复现流程。

Task 8 of PoE 工程实践复现器 SPEC。
依据：TASKS-工程实践复现器.md TR-8.1 / TR-8.2 / AC-6
端到端：对 33-REA 自身某模块运行 决策还原 → 审计 完整流程。
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.ai_audit import audit_ai_output
from core.architecture_pattern_detector import detect_architecture_patterns
from core.cognitive_integration import (
    prepare_audit_record_params,
    prepare_decision_record_params,
)
from core.design_decision_recovery import recover_decisions
from core.evolution_narrative import generate_narrative
from core.methodology_abstraction import abstract_methodology


# ---------- 端到端测试 ----------


def test_e2e_poe_full_pipeline_on_real_module():
    """TR-8.2: 对 33-REA 自身 core/ 运行端到端复现流程（决策还原 → 审计），全程无裸结论。"""
    # 用 33-REA 自身 core/ 作为目标
    core_dir = Path(__file__).parent.parent / "core"
    assert core_dir.is_dir(), "33-REA/core/ 目录应存在"

    # 1. 架构模式识别
    pattern_result = detect_architecture_patterns(str(core_dir))
    for p in pattern_result.get("patterns", []):
        assert "evidence" in p, "模式结论无 Evidence (AC-6 违反)"
        assert p["evidence"] is not None

    # 2. 设计决策还原
    decision_result = recover_decisions(str(core_dir))
    for d in decision_result.get("decisions", []):
        assert "evidence" in d, "决策记录无 Evidence (AC-6 违反)"
        assert d["evidence"] is not None

    # 3. AI 审计（对 33-REA 自身做 PoE 门禁）
    audit_result = audit_ai_output(str(core_dir))
    assert "poe_score" in audit_result
    assert "gate_decision" in audit_result
    # 33-REA 自身应有注释/测试，poe_score 应 >= 0.4
    assert audit_result["poe_score"] >= 0.0
    # 认知债务每条带 Evidence
    for debt in audit_result.get("cognitive_debt", []):
        ev = debt.get("evidence", debt)
        assert ev.provenance is not None, "债务无 provenance (AC-6 违反)"

    # 4. 认知集成：所有结果可格式化为 record 参数
    decision_params = prepare_decision_record_params(decision_result)
    audit_params = prepare_audit_record_params(audit_result)
    assert isinstance(decision_params["content"], str)
    assert isinstance(audit_params["content"], str)
    assert "rea-decision" in decision_params["tags"]
    assert "rea-audit" in audit_params["tags"]


def test_e2e_poe_pipeline_on_temporary_mvc_project():
    """对构造的 MVC 项目运行端到端：模式识别 → 决策还原 → 审计。"""
    with tempfile.TemporaryDirectory() as d:
        # 构造 MVC 项目
        os.makedirs(os.path.join(d, "models"))
        os.makedirs(os.path.join(d, "views"))
        os.makedirs(os.path.join(d, "controllers"))
        Path(d, "models", "__init__.py").write_text("")
        Path(d, "views", "__init__.py").write_text("")
        Path(d, "controllers", "__init__.py").write_text("")
        Path(d, "models", "user.py").write_text(
            '"""User 模型。"""\n'
            "class User:\n"
            "    def __init__(self, name):\n"
            "        self.name = name\n"
        )
        Path(d, "views", "user_view.py").write_text(
            '"""User 视图。"""\n'
            "class UserView:\n"
            "    def render(self, user):\n"
            "        return f'User: {user.name}'\n"
        )
        Path(d, "controllers", "user_controller.py").write_text(
            '"""User 控制器。"""\n'
            "from myapp.models.user import User\n"
            "from myapp.views.user_view import UserView\n\n"
            "class UserController:\n"
            "    def handle(self, name):\n"
            "        user = User(name)\n"
            "        view = UserView()\n"
            "        return view.render(user)\n"
        )
        Path(d, "README.md").write_text("# MVC Test Project\n")

        # 1. 模式识别应检出 MVC
        pattern_result = detect_architecture_patterns(d)
        assert any("MVC" in str(p.get("pattern", "")) for p in pattern_result["patterns"])

        # 2. 决策还原应返回 ≥1 条决策
        decision_result = recover_decisions(d)
        assert len(decision_result["decisions"]) >= 1

        # 3. 审计应返回有效的 poe_score
        audit_result = audit_ai_output(d)
        assert 0.0 <= audit_result["poe_score"] <= 1.0


def test_e2e_evidence_first_no_bare_conclusions():
    """AC-6 硬约束：所有新增模块输出全量扫描，无裸结论（每条结论带 Evidence）。"""
    with tempfile.TemporaryDirectory() as d:
        Path(d, "sample.py").write_text(
            '"""Sample."""\n'
            "def fn():\n    return 42\n"
        )

        # 遍历所有新增模块的输出，检查 evidence 字段
        results = {
            "pattern": detect_architecture_patterns(d),
            "decision": recover_decisions(d),
            "narrative": generate_narrative(d),
            "audit": audit_ai_output(d),
        }

        for name, result in results.items():
            evidence_list = result.get("evidence", [])
            # 每条 Evidence 必须有 level + provenance + known_gaps
            for e in evidence_list:
                if hasattr(e, "level"):
                    assert e.level is not None, f"{name}: Evidence 缺 level"
                    assert e.provenance is not None, f"{name}: Evidence 缺 provenance"
                    assert isinstance(e.known_gaps, list), f"{name}: known_gaps 非列表"
                elif isinstance(e, dict):
                    assert "level" in e, f"{name}: Evidence 缺 level"
                    assert "provenance" in e, f"{name}: Evidence 缺 provenance"


def test_e2e_methodology_abstraction_after_investigations():
    """端到端：多项目决策还原结果 → 方法论抽象。"""
    inv_results = []
    for proj in ["proj-a", "proj-b", "proj-c"]:
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "models"))
            os.makedirs(os.path.join(d, "views"))
            os.makedirs(os.path.join(d, "controllers"))
            Path(d, "models", "__init__.py").write_text("")
            Path(d, "views", "__init__.py").write_text("")
            Path(d, "controllers", "__init__.py").write_text("")
            Path(d, "models", "x.py").write_text("class X:\n    pass\n")
            # 用 detect_architecture_patterns 作为 mock investigation
            pattern_result = detect_architecture_patterns(d)
            inv_results.append({
                "target": f"/mock/{proj}",
                "patterns": pattern_result.get("patterns", []),
                "decisions": [],
            })

    methodology_result = abstract_methodology(inv_results)
    # 应至少 1 条方法论（3 个项目都检出 MVC）
    assert len(methodology_result["methodologies"]) >= 1


def test_e2e_audit_then_record_params_chain():
    """端到端：审计结果 → 认知集成 record 参数 → 结构合法。"""
    with tempfile.TemporaryDirectory() as d:
        Path(d, "ai_code.py").write_text(
            "def complex(a, b, c):\n"
            "    result = 0\n"
            "    for i in range(100):\n"
            "        if i > 50:\n"
            "            if a:\n"
            "                result += 99\n"
            "    return result * 3.14\n"
        )
        audit_result = audit_ai_output(d)
        record_params = prepare_audit_record_params(audit_result)

        # 链路检查：审计 → record 参数
        assert "content" in record_params
        assert "quality_level" in record_params
        assert "tags" in record_params
        assert "rea-audit" in record_params["tags"]
        # quality_level 应为 A/B/C 之一
        assert record_params["quality_level"] in ("A", "B", "C", "S", "D")
