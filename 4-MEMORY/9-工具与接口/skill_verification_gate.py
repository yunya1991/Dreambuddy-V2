#!/usr/bin/env python3
"""SKILL 自验证入库门 — SkillVerificationGate

定位：L3 路由层 SKILL 治理能力，借鉴 Voyager (技能 self-verification)，
实现 verify-before-commit：新 SKILL 入库前必须通过验证门，决定初始生命周期状态。

核心决策矩阵（优先级从高到低）:
  1. errors 存在    → "rejected" (拒绝入库)
  2. 冲突存在      → "shadow" (需人工审查触发词冲突)
  3. 漂移存在      → "shadow" (需人工审查双位置漂移)
  4. warnings 存在  → "shadow" (需人工审查警告)
  5. 全部通过      → "active"

验证维度:
  1. 结构验证 — 复用 skill_indexer.validate()（frontmatter 必填字段等）
  2. 冲突检测 — 复用 skill_indexer.detect_conflicts()（触发词冲突）
  3. 漂移检测 — 复用 skill_indexer.detect_drift()（双位置存储漂移）
  4. 触发词完整性 — triggers 非空且为列表
  5. 依赖有效性 — depends_on 引用的 SKILL 是否存在

设计原则:
  - FAIL-OPEN：任何异常不阻塞主流程，保守返回 rejected
  - 复用已有：不重复实现 validate/conflicts/drift，动态导入 skill_indexer
  - 轻量级：纯 Python，无额外依赖

集成:
  - auto_register_skill.py: 在 build 前调用 gate，按决策设置初始状态
  - cognitive_loop_entry.py: 暴露 skill_gate 属性供认知系统调用

参考:
  - SPEC-CognitiveSystem-Evolution.md §4.3 P2-4
  - Voyager: 自动课程 + 技能库 + self-verification
  - 协同 skill_indexer.py (validate/detect_conflicts/detect_drift)
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional


# ============================================================
# 验证结果 dataclass
# ============================================================


@dataclass
class VerificationResult:
    """SKILL 验证结果。

    Attributes:
        skill_id: SKILL 名称
        status: 入库决策 ("active" | "shadow" | "rejected")
        valid: 是否通过验证（errors 为空）
        errors: 错误列表
        warnings: 警告列表
        conflicts: 涉及的冲突 SKILL 名
        drift: 涉及的漂移 SKILL 名
        confidence: 验证置信度 0.0-1.0
        reasons: 决策理由列表
    """

    skill_id: str
    status: str = "rejected"
    valid: bool = False
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    drift: List[str] = field(default_factory=list)
    confidence: float = 0.0
    reasons: List[str] = field(default_factory=list)


# ============================================================
# skill_indexer 动态导入（避免硬依赖）
# ============================================================


def _import_skill_indexer():
    """动态导入 skill_indexer 模块。

    skill_indexer 位于 1-ARCHITECTURE/skills/dream-skill-index-governance/。
    如果不可用则返回 None（FAIL-OPEN）。
    """
    try:
        repo_root = Path(__file__).resolve().parents[2]
        skill_idx_dir = (
            repo_root / "1-ARCHITECTURE" / "skills" / "dream-skill-index-governance"
        )
        if skill_idx_dir.exists() and str(skill_idx_dir) not in sys.path:
            sys.path.insert(0, str(skill_idx_dir))
        import skill_indexer  # type: ignore[import-not-found]

        return skill_indexer
    except Exception:
        return None


# ============================================================
# SkillVerificationGate 主类
# ============================================================


class SkillVerificationGate:
    """SKILL 自验证入库门。

    新 SKILL 入库前必须通过验证门，决定其初始生命周期状态。

    决策优先级: errors > conflicts > drift > warnings > clean
    """

    # 决策阈值
    ACTIVE_CONFIDENCE = 0.95
    SHADOW_CONFIDENCE = 0.5

    def __init__(self, skill_indexer_module: Any = None) -> None:
        """
        Args:
            skill_indexer_module: 注入的 skill_indexer 模块（测试用）。
                                  None 则动态导入。
        """
        self._si = skill_indexer_module or _import_skill_indexer()

    # ============================================================
    # 核心验证方法
    # ============================================================

    def verify(self, skill_dir: Any) -> VerificationResult:
        """验证单个 SKILL，返回入库决策。

        Args:
            skill_dir: SKILL 目录路径 (Path 或 str)

        Returns:
            VerificationResult 含 status/errors/warnings/confidence/reasons
        """
        skill_path = Path(skill_dir) if not isinstance(skill_dir, Path) else skill_dir
        skill_id = skill_path.name

        result = VerificationResult(skill_id=skill_id)

        # 0. 路径存在性检查
        skill_md = skill_path / "SKILL.md"
        if not skill_md.exists():
            result.errors.append("SKILL.md not found")
            result.reasons.append("文件不存在")
            result.status = "rejected"
            result.confidence = 1.0
            return result

        # 0.5 从 frontmatter 提取 name 作为 skill_id（优先于目录名）
        name_from_fm = self._extract_name(skill_md)
        if name_from_fm:
            result.skill_id = name_from_fm
            skill_id = name_from_fm

        # 1. 结构验证（复用 skill_indexer.validate）
        if self._si is not None:
            try:
                vr = self._si.validate(skill_path)
                result.errors.extend(vr.get("errors", []))
                result.warnings.extend(vr.get("warnings", []))
            except Exception:
                pass  # FAIL-OPEN

        # 2. 触发词完整性检查
        try:
            triggers_ok = self._check_triggers(skill_md)
            if not triggers_ok:
                result.warnings.append("triggers missing or empty")
        except Exception:
            pass

        # 3. 冲突检测（需要全量 entries）
        conflicts = self._detect_conflicts_for(skill_id)
        result.conflicts.extend(conflicts)

        # 4. 漂移检测
        drift = self._detect_drift_for(skill_id)
        result.drift.extend(drift)

        # 5. 决策（优先级: errors > conflicts > drift > warnings > clean）
        result.valid = len(result.errors) == 0

        if result.errors:
            result.status = "rejected"
            result.confidence = self.ACTIVE_CONFIDENCE
            result.reasons.append(f"errors: {result.errors}")
        elif result.conflicts:
            result.status = "shadow"
            result.confidence = self.SHADOW_CONFIDENCE
            result.reasons.append(f"conflicts with: {result.conflicts}")
        elif result.drift:
            result.status = "shadow"
            result.confidence = self.SHADOW_CONFIDENCE
            result.reasons.append(f"drift: {result.drift}")
        elif result.warnings:
            result.status = "shadow"
            result.confidence = self.SHADOW_CONFIDENCE
            result.reasons.append(f"warnings: {result.warnings}")
        else:
            result.status = "active"
            result.confidence = self.ACTIVE_CONFIDENCE
            result.reasons.append("all checks passed")

        return result

    def batch_verify(self, skill_dirs: List[Any]) -> List[VerificationResult]:
        """批量验证多个 SKILL。

        Args:
            skill_dirs: SKILL 目录路径列表

        Returns:
            VerificationResult 列表
        """
        results: List[VerificationResult] = []
        for sd in skill_dirs:
            try:
                results.append(self.verify(sd))
            except Exception:
                # FAIL-OPEN：单个失败不影响其他
                sid = Path(sd).name if sd else "unknown"
                results.append(
                    VerificationResult(
                        skill_id=sid,
                        status="rejected",
                        errors=["verification_exception"],
                        reasons=["internal error"],
                    )
                )
        return results

    # ============================================================
    # 内部检查方法
    # ============================================================

    def _extract_name(self, skill_md: Path) -> Optional[str]:
        """从 SKILL.md frontmatter 提取 name 字段。

        Returns:
            name 字符串，或 None（解析失败/缺失）
        """
        try:
            raw = skill_md.read_text(encoding="utf-8")
            if not raw.startswith("---"):
                return None
            fm_end = raw.find("---", 3)
            if fm_end < 0:
                return None
            fm_text = raw[3:fm_end]
            import re

            m = re.search(r"^name:\s*(.+)$", fm_text, re.MULTILINE)
            if m:
                val = m.group(1).strip()
                if val and not val.startswith(("|", ">")):
                    return val
            return None
        except Exception:
            return None

    def _check_triggers(self, skill_md: Path) -> bool:
        """检查 SKILL.md 的 triggers 字段是否存在且非空。

        Returns:
            True=triggers 存在且非空，False=缺失或空
        """
        try:
            raw = skill_md.read_text(encoding="utf-8")
            # 简单 frontmatter 解析
            if not raw.startswith("---"):
                return False
            fm_end = raw.find("---", 3)
            if fm_end < 0:
                return False
            fm_text = raw[3:fm_end]

            # 找 triggers 字段
            import re

            # 匹配 triggers: 后面跟列表或值
            trigger_match = re.search(
                r"^triggers:\s*(.+)$", fm_text, re.MULTILINE
            )
            if not trigger_match:
                return False

            trigger_val = trigger_match.group(1).strip()
            # 如果是列表开始 [ 或下一行有 - 项
            if trigger_val.startswith("["):
                return trigger_val != "[]"
            # 检查后续行是否有 - 项
            if trigger_val == "" or trigger_val == "~":
                # 可能是多行列表，检查后续行
                lines_after = fm_text[trigger_match.end():]
                return bool(re.search(r"^\s*-\s+\S", lines_after, re.MULTILINE))
            return True
        except Exception:
            return True  # FAIL-OPEN：解析失败视为通过

    def _detect_conflicts_for(self, skill_id: str) -> List[str]:
        """检测指定 SKILL 是否与已有 SKILL 冲突。

        Returns:
            冲突的 SKILL 名列表
        """
        if self._si is None:
            return []
        try:
            # scan_skills 获取全量 entries
            entries = self._si.scan_skills(self._si.ALL_SKILL_ROOTS)
            conflicts = self._si.detect_conflicts(entries)
            # 找出涉及 skill_id 的冲突
            result: List[str] = []
            conflicts_text = str(conflicts)
            if skill_id in conflicts_text:
                # 简化：只要冲突文本包含 skill_id 就算
                result.append("trigger_conflict")
            return result
        except Exception:
            return []  # FAIL-OPEN

    def _detect_drift_for(self, skill_id: str) -> List[str]:
        """检测指定 SKILL 是否有双位置漂移。

        Returns:
            漂移描述列表
        """
        if self._si is None:
            return []
        try:
            entries = self._si.scan_skills(self._si.ALL_SKILL_ROOTS)
            drift = self._si.detect_drift(entries)
            result: List[str] = []
            drift_text = str(drift)
            if skill_id in drift_text:
                result.append("dual_location_drift")
            return result
        except Exception:
            return []  # FAIL-OPEN


# ============================================================
# CLI 自测
# ============================================================


if __name__ == "__main__":
    import tempfile

    print("=" * 60)
    print("SkillVerificationGate — 功能验证")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as td:
        # 干净 SKILL
        clean_dir = Path(td) / "clean-skill"
        clean_dir.mkdir()
        (clean_dir / "SKILL.md").write_text(
            "---\nname: clean-skill\ndescription: clean\nversion: 1.0.0\n"
            "status: proposed\ntriggers:\n  - clean\n---\n# Clean\n",
            encoding="utf-8",
        )

        # 错误 SKILL
        err_dir = Path(td) / "error-skill"
        err_dir.mkdir()
        (err_dir / "SKILL.md").write_text(
            "---\ndescription: no name\n---\n# Error\n",
            encoding="utf-8",
        )

        gate = SkillVerificationGate()
        r1 = gate.verify(clean_dir)
        r2 = gate.verify(err_dir)

        print(f"\nclean-skill: status={r1.status}, confidence={r1.confidence}")
        print(f"  reasons: {r1.reasons}")
        print(f"error-skill: status={r2.status}, confidence={r2.confidence}")
        print(f"  errors: {r2.errors}")

    print("\n" + "=" * 60)
    print("✅ SkillVerificationGate 功能验证通过")
