"""P2-4 SKILL 自验证入库门 TDD RED 测试

借鉴 Voyager (技能 self-verification)，新 SKILL 入库前必须通过验证门。
核心：verify-before-commit — 决定 SKILL 初始生命周期状态。

决策矩阵:
  - errors 存在    → "rejected" (拒绝入库)
  - 冲突存在      → "shadow" (需人工审查)
  - 漂移存在      → "shadow"
  - warnings 存在  → "shadow"
  - 全部通过      → "active"

RED 契约:
  1. skill_verification_gate 模块不存在 → ImportError
  2. SkillVerificationGate 类不存在
  3. VerificationResult dataclass 不存在
  4. verify() 方法不存在
  5. batch_verify() 方法不存在
  6. CognitiveLoopEntry 无 skill_gate 属性

参考: SPEC-CognitiveSystem-Evolution.md §4.3 P2-4
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


# ============================================================
# 测试用 SKILL.md 模板
# ============================================================

CLEAN_SKILL_MD = """---
name: test-clean-skill
description: 一个干净的测试 SKILL
version: 1.0.0
status: proposed
triggers:
  - test-clean-trigger
---

# Test Clean Skill

这是一个干净的测试 SKILL。
"""

ERROR_SKILL_MD = """---
description: 缺少 name 和 version
---

# Error Skill
"""

WARNING_SKILL_MD = """---
name: test-warning-skill
description: 有 warning 的 SKILL
version: not-semver
status: proposed
triggers:
  - test-warning-trigger
---

# Warning Skill
"""


class TestSkillVerificationGateCore:
    """SkillVerificationGate 核心验证能力。"""

    def test_import_gate(self):
        """RED: skill_verification_gate 模块可导入。"""
        from skill_verification_gate import SkillVerificationGate  # noqa: F401

    def test_verification_result_dataclass(self):
        """RED: VerificationResult dataclass 存在且有必要字段。"""
        from skill_verification_gate import VerificationResult

        r = VerificationResult(
            skill_id="test",
            status="active",
            valid=True,
            errors=[],
            warnings=[],
            conflicts=[],
            drift=[],
            confidence=0.0,
            reasons=[],
        )
        assert r.status == "active"
        assert hasattr(r, "errors")
        assert hasattr(r, "warnings")
        assert hasattr(r, "conflicts")
        assert hasattr(r, "drift")
        assert hasattr(r, "confidence")
        assert hasattr(r, "reasons")

    def test_verify_clean_skill_active(self, tmp_path):
        """RED: 干净 SKILL → status="active"。"""
        from skill_verification_gate import SkillVerificationGate

        skill_dir = tmp_path / "test-clean-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(CLEAN_SKILL_MD, encoding="utf-8")

        gate = SkillVerificationGate()
        result = gate.verify(skill_dir)

        assert result.skill_id == "test-clean-skill"
        assert result.status == "active"
        assert result.valid is True

    def test_verify_with_errors_rejected(self, tmp_path):
        """RED: 有 errors → status="rejected"。"""
        from skill_verification_gate import SkillVerificationGate

        skill_dir = tmp_path / "test-error-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(ERROR_SKILL_MD, encoding="utf-8")

        gate = SkillVerificationGate()
        result = gate.verify(skill_dir)

        assert result.status == "rejected"
        assert result.valid is False
        assert len(result.errors) > 0

    def test_verify_with_warnings_shadow(self, tmp_path):
        """RED: 有 warnings（无 errors）→ status="shadow"。"""
        from skill_verification_gate import SkillVerificationGate

        skill_dir = tmp_path / "test-warning-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(WARNING_SKILL_MD, encoding="utf-8")

        gate = SkillVerificationGate()
        result = gate.verify(skill_dir)

        # warning（version not semver）→ shadow
        assert result.status == "shadow"
        assert len(result.warnings) > 0

    def test_failopen_missing_file(self, tmp_path):
        """RED: SKILL.md 不存在 → FAIL-OPEN 返回 rejected（不抛异常）。"""
        from skill_verification_gate import SkillVerificationGate

        gate = SkillVerificationGate()
        result = gate.verify(tmp_path / "nonexistent")

        assert result.status == "rejected"
        assert result.valid is False

    def test_failopen_invalid_dir(self, tmp_path):
        """RED: 无效路径 → FAIL-OPEN。"""
        from skill_verification_gate import SkillVerificationGate

        gate = SkillVerificationGate()
        # 传入 None 或字符串路径
        result = gate.verify("/nonexistent/path/skill")
        assert result.status == "rejected"

    def test_batch_verify(self, tmp_path):
        """RED: batch_verify() 批量验证多个 SKILL。"""
        from skill_verification_gate import SkillVerificationGate

        # 创建 3 个 SKILL
        d1 = tmp_path / "skill-a"
        d1.mkdir()
        (d1 / "SKILL.md").write_text(CLEAN_SKILL_MD, encoding="utf-8")

        d2 = tmp_path / "skill-b"
        d2.mkdir()
        (d2 / "SKILL.md").write_text(ERROR_SKILL_MD, encoding="utf-8")

        d3 = tmp_path / "skill-c"
        d3.mkdir()
        (d3 / "SKILL.md").write_text(WARNING_SKILL_MD, encoding="utf-8")

        gate = SkillVerificationGate()
        results = gate.batch_verify([d1, d2, d3])

        assert len(results) == 3
        statuses = {r.skill_id: r.status for r in results}
        assert statuses.get("test-clean-skill") == "active"
        assert "rejected" in statuses.values()
        assert "shadow" in statuses.values()

    def test_verify_returns_confidence(self, tmp_path):
        """RED: verify() 返回 confidence 分数。"""
        from skill_verification_gate import SkillVerificationGate

        skill_dir = tmp_path / "test-clean-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(CLEAN_SKILL_MD, encoding="utf-8")

        gate = SkillVerificationGate()
        result = gate.verify(skill_dir)

        # active 应有较高 confidence
        assert result.confidence > 0.5

    def test_verify_returns_reasons(self, tmp_path):
        """RED: verify() 返回决策理由列表。"""
        from skill_verification_gate import SkillVerificationGate

        skill_dir = tmp_path / "test-error-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(ERROR_SKILL_MD, encoding="utf-8")

        gate = SkillVerificationGate()
        result = gate.verify(skill_dir)

        assert len(result.reasons) > 0

    def test_gate_decision_priority(self, tmp_path):
        """RED: 决策优先级正确：errors > conflicts > drift > warnings > clean。

        即使有 conflicts，若有 errors 仍应为 rejected。
        """
        from skill_verification_gate import SkillVerificationGate

        skill_dir = tmp_path / "test-priority"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(ERROR_SKILL_MD, encoding="utf-8")

        gate = SkillVerificationGate()
        result = gate.verify(skill_dir)

        # errors 优先级最高 → rejected（即使其他维度有问题）
        assert result.status == "rejected"


# ============================================================
# CognitiveLoopEntry 集成测试
# ============================================================


class TestCognitiveLoopEntrySkillGate:
    """CognitiveLoopEntry P2-4 集成点。"""

    def test_skill_gate_attribute_exists(self):
        """RED: CognitiveLoopEntry 应有 skill_gate 属性。"""
        from cognitive_loop_entry import CognitiveLoopEntry

        import inspect

        src = inspect.getsource(CognitiveLoopEntry.__init__)
        assert "skill_gate" in src
        assert "SkillVerificationGate" in src
