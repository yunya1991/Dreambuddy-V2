"""RED 测试：DesignDecisionRecovery — 设计决策还原（ADR 风格）。

Task 2 of PoE 工程实践复现器 SPEC。
依据：TASKS-工程实践复现器.md TR-2.1 / TR-2.2 / TR-2.3
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# RED: 模块尚未实现，import 应失败
from core.design_decision_recovery import (
    DesignDecisionRecoverer,
    recover_decisions,
)


MVC_USER_MODEL = "class User:\n    def __init__(self, name):\n        self.name = name\n"
MVC_USER_VIEW = "class UserView:\n    def render(self, user):\n        return f'User: {user.name}'\n"
MVC_USER_CTRL = (
    "from myapp.models.user import User\n"
    "from myapp.views.user_view import UserView\n\n"
    "class UserController:\n"
    "    def handle(self, name):\n"
    "        user = User(name)\n"
    "        view = UserView()\n"
    "        return view.render(user)\n"
)

TODO_SAMPLE = """
# TODO: 未来考虑改为事件驱动架构
# FIXME: 当前实现耦合度太高，待重构
class LegacyService:
    def process(self, data):
        # XXX: 硬编码，需迁移到配置
        result = data + '_processed'
        return result
"""

ALTERNATIVE_HINT_SAMPLE = """
# 使用 ORM 但仍存在原生 SQL 片段 → 暗示曾考虑直接 SQL
from sqlalchemy.orm import Session

class UserRepository:
    def find(self, id, session: Session):
        # 走 ORM
        return session.query(User).filter(User.id == id).first()

    def raw_query(self, sql, session: Session):
        # 兜底原生 SQL
        return session.execute(sql)
"""


# ---------- 测试用例 ----------


def test_recover_decisions_mvc_returns_at_least_one():
    """TR-2.1: 对 MVC fixture，返回 ≥1 条决策记录，含 decision/context/evidence 字段。"""
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "models"))
        os.makedirs(os.path.join(d, "views"))
        os.makedirs(os.path.join(d, "controllers"))
        Path(d, "models", "__init__.py").write_text("")
        Path(d, "views", "__init__.py").write_text("")
        Path(d, "controllers", "__init__.py").write_text("")
        Path(d, "models", "user.py").write_text(MVC_USER_MODEL)
        Path(d, "views", "user_view.py").write_text(MVC_USER_VIEW)
        Path(d, "controllers", "user_controller.py").write_text(MVC_USER_CTRL)

        result = recover_decisions(d)
        assert "decisions" in result
        decisions = result["decisions"]
        assert isinstance(decisions, list)
        assert len(decisions) >= 1, "应至少返回 1 条决策记录"

        first = decisions[0]
        assert "decision" in first, "决策记录应含 decision 字段 (TR-2.1)"
        assert "context" in first, "决策记录应含 context 字段 (TR-2.1)"
        assert "evidence" in first, "决策记录应含 evidence 字段 (TR-2.1)"


def test_recover_decisions_evidence_level_observation_or_derivation():
    """TR-2.2: 每条决策记录的 evidence 引用 ≥1 条 observation 或 derivation 级 Evidence。"""
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "models"))
        os.makedirs(os.path.join(d, "views"))
        os.makedirs(os.path.join(d, "controllers"))
        Path(d, "models", "__init__.py").write_text("")
        Path(d, "views", "__init__.py").write_text("")
        Path(d, "controllers", "__init__.py").write_text("")
        Path(d, "models", "user.py").write_text(MVC_USER_MODEL)
        Path(d, "views", "user_view.py").write_text(MVC_USER_VIEW)
        Path(d, "controllers", "user_controller.py").write_text(MVC_USER_CTRL)

        result = recover_decisions(d)
        for decision in result["decisions"]:
            ev = decision["evidence"]
            assert ev.level.value in ("observation", "derivation"), (
                f"决策 evidence 应为 observation/derivation 级，实际 {ev.level} (TR-2.2)"
            )


def test_recover_decisions_alternatives_must_be_inference():
    """TR-2.3: alternatives 字段存在时，其 level 必须为 inference 且 known_gaps 非空。"""
    with tempfile.TemporaryDirectory() as d:
        Path(d, "repo.py").write_text(ALTERNATIVE_HINT_SAMPLE)

        result = recover_decisions(d)
        for decision in result["decisions"]:
            alts = decision.get("alternatives")
            if alts:
                assert isinstance(alts, list)
                for alt in alts:
                    assert alt.get("level") == "inference" or (
                        hasattr(alt, "level") and alt.level.value == "inference"
                    ), f"替代方案必须为 inference 级 (TR-2.3): {alt}"
                    gaps = alt.get("known_gaps") if isinstance(alt, dict) else alt.known_gaps
                    assert gaps, "替代方案 known_gaps 必须非空 (TR-2.3)"


def test_recover_decisions_tradeoff_traces_detected():
    """附加：权衡痕迹（TODO/FIXME）应被识别为决策证据。"""
    with tempfile.TemporaryDirectory() as d:
        Path(d, "legacy.py").write_text(TODO_SAMPLE)

        result = recover_decisions(d)
        # 至少应有 1 条决策记录（基于 TODO/FIXME 权衡痕迹）
        assert len(result["decisions"]) >= 1


def test_recover_decisions_nonexistent_dir_failopen():
    """FAIL-OPEN: 不存在的目录返回 level=unknown Evidence，不抛异常。"""
    result = recover_decisions("/nonexistent/path/xyz")
    assert "decisions" in result
    assert result["decisions"] == []
    evidence_list = result.get("evidence", [])
    assert len(evidence_list) > 0
    assert any(e.level.value == "unknown" for e in evidence_list)


def test_design_decision_recoverer_class_usable():
    """DesignDecisionRecoverer 类可直接实例化。"""
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "models"))
        os.makedirs(os.path.join(d, "views"))
        os.makedirs(os.path.join(d, "controllers"))
        Path(d, "models", "__init__.py").write_text("")
        Path(d, "views", "__init__.py").write_text("")
        Path(d, "controllers", "__init__.py").write_text("")
        Path(d, "models", "user.py").write_text(MVC_USER_MODEL)
        Path(d, "views", "user_view.py").write_text(MVC_USER_VIEW)
        Path(d, "controllers", "user_controller.py").write_text(MVC_USER_CTRL)

        recoverer = DesignDecisionRecoverer()
        result = recoverer.recover(d)
        assert "decisions" in result
        assert len(result["decisions"]) >= 1
