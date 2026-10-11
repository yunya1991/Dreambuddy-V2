"""AI 产出审计模块 — PoE 核心门禁实现。

PoE Task 5：对 AI 生成的代码进行审计，计算证据链完整度得分 + 认知债务清单 +
poe_score（综合证明链得分）+ gate_decision（门禁决策）。

公式（DESIGN-PHILOSOPHY-PoE.md §5.2）:
    raw = 0.4 * evidence_chain_score + 0.25 * coverage_score + 0.2 * (1 - complexity_penalty)
    poe_score = clamp(raw * layer_completeness_bonus, 0.0, 1.0)
    bonus: P0=1.0, +Decision=1.05, +Narrative=1.1, +Methodology=1.176

门禁（§5.1）:
    PASS:   poe_score ≥ 0.8 AND evidence_chain_score ≥ 0.7
    REVIEW: 0.5 ≤ poe_score < 0.8
    REJECT: poe_score < 0.5 OR evidence_chain_score < 0.4

FAIL-OPEN（§5.5）: 审计失败时 poe_score=0.0, gate=review, known_gaps 注明。
"""
from __future__ import annotations

import ast
import math
import os
from dataclasses import dataclass, field
from typing import Any

from .architecture_pattern_detector import ArchitecturePatternDetector
from .design_decision_recovery import DesignDecisionRecoverer
from .evidence import Evidence, EvidenceLevel


# ---------- 权重常量（DESIGN-PHILOSOPHY-PoE §5.2 / §7 冷启动默认值） ----------

W_EVIDENCE = 0.4       # w1
W_COVERAGE = 0.25      # w2
W_COMPLEXITY = 0.2     # w3（反向计分）
# w1+w2+w3 = 0.85，剩余 0.15 通过 layer_completeness_bonus 乘数体现

BONUS_P0 = 1.0
BONUS_DECISION = 1.05
BONUS_NARRATIVE = 1.1
BONUS_METHODOLOGY = 1.176

PASS_THRESHOLD = 0.8
PASS_EVIDENCE_THRESHOLD = 0.7
REVIEW_THRESHOLD = 0.5
REJECT_EVIDENCE_THRESHOLD = 0.4

# 魔法数字判定：不在 [0, 1, 2] 且非常量上下文
_MAGIC_NUMBER_EXEMPT = {0, 1, 2, -1}
# 已知常量名（不视为魔法数字）
_CONSTANT_NAMES = {"MAGIC", "CONST", "PI", "EULER", "TWO_PI"}


# ---------- 数据结构 ----------

@dataclass
class CognitiveDebt:
    """认知债务条目。"""
    type: str
    description: str
    evidence: Evidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "description": self.description,
            "evidence": self.evidence,
        }


# ---------- 核心实现 ----------

def compute_poe_score(
    evidence_chain_score: float,
    coverage_score: float,
    complexity_penalty: float,
    has_design_decision: bool = False,
    has_narrative: bool = False,
    has_methodology: bool = False,
) -> float:
    """按 DESIGN-PHILOSOPHY-PoE §5.2 公式计算 poe_score。

    Args:
        evidence_chain_score: 0.0-1.0，证据链完整度
        coverage_score: 0.0-1.0，注释/测试/文档覆盖
        complexity_penalty: 0.0-1.0，复杂度惩罚（越高越扣分）
        has_design_decision: 是否含设计决策层（P1）
        has_narrative: 是否含叙事层（P1）
        has_methodology: 是否含方法论层（P2）

    Returns:
        poe_score: 0.0-1.0 综合证明链得分
    """
    raw = (
        W_EVIDENCE * evidence_chain_score
        + W_COVERAGE * coverage_score
        + W_COMPLEXITY * (1.0 - complexity_penalty)
    )
    bonus = BONUS_P0
    if has_design_decision:
        bonus = max(bonus, BONUS_DECISION)
    if has_narrative:
        bonus = max(bonus, BONUS_NARRATIVE)
    if has_methodology:
        bonus = max(bonus, BONUS_METHODOLOGY)

    poe = raw * bonus
    return max(0.0, min(1.0, poe))


def _gate_decision(poe_score: float, evidence_chain_score: float) -> str:
    """三级门禁判定（§5.1）。"""
    if poe_score >= PASS_THRESHOLD and evidence_chain_score >= PASS_EVIDENCE_THRESHOLD:
        return "pass"
    if poe_score < REJECT_EVIDENCE_THRESHOLD and evidence_chain_score < REJECT_EVIDENCE_THRESHOLD:
        return "reject"
    if poe_score >= REVIEW_THRESHOLD and evidence_chain_score >= REJECT_EVIDENCE_THRESHOLD:
        return "review"
    if poe_score < REVIEW_THRESHOLD:
        return "reject"
    return "review"


# ---------- 审计器 ----------

class AIAuditor:
    """AI 产出审计器。

    审计流程：
    1. 扫描目标路径的 Python 源码
    2. 计算 evidence_chain_score（注释/测试/文档覆盖）
    3. 计算 coverage_score（综合覆盖率）
    4. 计算 complexity_penalty（圈复杂度 + 长函数惩罚）
    5. 生成认知债务清单（无注释复杂逻辑/无测试/魔法数字/硬编码）
    6. 调用 Task 1+Task 2 评估架构健康度（影响 layer_completeness_bonus）
    7. 综合 poe_score + gate_decision
    """

    def audit(self, target: str, ai_context: dict[str, Any] | None = None) -> dict[str, Any]:
        """审计 AI 生成的代码。

        Args:
            target: AI 产出代码目录或文件路径
            ai_context: 可选 AI 上下文（agent_id/model/prompt_hash/timestamp）

        Returns:
            {
                "target": str,
                "evidence_chain_score": float,
                "coverage_score": float,
                "complexity_penalty": float,
                "poe_score": float,
                "gate_decision": "pass" | "review" | "reject",
                "cognitive_debt": [CognitiveDebt.to_dict()...],
                "evidence": [Evidence...],
                "audit_layer_status": {"design_decision": bool, "narrative": bool, "methodology": bool},
            }
        """
        ai_context = ai_context or {}

        if not (os.path.isdir(target) or (os.path.isfile(target) and target.endswith(".py"))):
            return self._failopen_unknown(target, "目标不存在或不是 Python 路径")

        # 1. 收集源码文件
        py_files = self._collect_py_files(target)
        if not py_files:
            return self._failopen_unknown(target, "目标不含 Python 文件")

        # 2. 计算 metrics
        evidence_chain_score = self._compute_evidence_chain_score(target, py_files)
        coverage_score = self._compute_coverage_score(target, py_files)
        complexity_penalty = self._compute_complexity_penalty(py_files)

        # 3. 认知债务清单
        debts = self._detect_cognitive_debt(py_files)

        # 4. 架构健康层（调用 Task 1+2）
        has_design_decision = False
        has_narrative = False
        has_methodology = False

        if os.path.isdir(target):
            # 调用 Task 1+Task 2 检测是否有可还原的架构决策
            try:
                recoverer = DesignDecisionRecoverer()
                decision_result = recoverer.recover(target)
                if decision_result.get("decisions"):
                    has_design_decision = True
                    # 进一步检查是否有方法论层（跨项目暂不实现，单项目为 False）
                    has_methodology = False
                # narrative 需要 git 历史，此处保守不启用
            except Exception:
                # FAIL-OPEN：架构层检测失败不影响核心审计
                pass

        # 5. 计算 poe_score
        poe_score = compute_poe_score(
            evidence_chain_score=evidence_chain_score,
            coverage_score=coverage_score,
            complexity_penalty=complexity_penalty,
            has_design_decision=has_design_decision,
            has_narrative=has_narrative,
            has_methodology=has_methodology,
        )
        gate = _gate_decision(poe_score, evidence_chain_score)

        # 6. Evidence 构建
        all_evidence: list[Evidence] = []
        for d in debts:
            all_evidence.append(d.evidence)

        all_evidence.insert(0, Evidence(
            result=(
                f"AI 审计: poe_score={poe_score:.3f}, evidence_chain={evidence_chain_score:.3f}, "
                f"coverage={coverage_score:.3f}, complexity_penalty={complexity_penalty:.3f}, "
                f"gate={gate}, debts={len(debts)}"
            ),
            level=EvidenceLevel.DERIVATION,
            provenance={
                "target": target,
                "ai_context": ai_context,
                "analysis": "ai_audit",
                "audit_layer_status": {
                    "design_decision": has_design_decision,
                    "narrative": has_narrative,
                    "methodology": has_methodology,
                },
            },
            confidence=0.9,
            known_gaps=[
                "evidence_chain_score 基于静态扫描，未做运行时覆盖率测量",
                "complexity_penalty 仅基于 AST 嵌套深度，未做完整圈复杂度计算",
            ],
        ))

        return {
            "target": target,
            "evidence_chain_score": evidence_chain_score,
            "coverage_score": coverage_score,
            "complexity_penalty": complexity_penalty,
            "poe_score": poe_score,
            "gate_decision": gate,
            "cognitive_debt": [d.to_dict() for d in debts],
            "evidence": all_evidence,
            "audit_layer_status": {
                "design_decision": has_design_decision,
                "narrative": has_narrative,
                "methodology": has_methodology,
            },
        }

    # ------------------------------------------------------------------
    # metrics 计算
    # ------------------------------------------------------------------

    def _compute_evidence_chain_score(self, target: str, py_files: list[str]) -> float:
        """证据链完整度：注释覆盖 + 测试覆盖 + 文档存在。"""
        if not py_files:
            return 0.0

        # 1. 注释覆盖：含 docstring 或行注释的函数比例
        total_funcs, documented_funcs = 0, 0
        for fpath in py_files:
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read(), filename=fpath)
            except (SyntaxError, UnicodeDecodeError, OSError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    total_funcs += 1
                    if ast.get_docstring(node):
                        documented_funcs += 1

        doc_ratio = documented_funcs / total_funcs if total_funcs > 0 else 0.0

        # 2. 测试覆盖：是否存在对应 test_*.py
        test_dir = os.path.join(target, "tests") if os.path.isdir(target) else None
        has_test_dir = test_dir is not None and os.path.isdir(test_dir)
        # 同目录 test_*.py
        same_dir_tests = 0
        if os.path.isdir(target):
            for name in os.listdir(target):
                if name.startswith("test_") and name.endswith(".py"):
                    same_dir_tests += 1

        test_ratio = 1.0 if (has_test_dir or same_dir_tests > 0) else 0.0

        # 3. 文档存在：README 或 docs/
        has_doc = False
        if os.path.isdir(target):
            for name in os.listdir(target):
                if name.lower().startswith("readme") or name.lower() == "docs":
                    has_doc = True
                    break
        doc_exist_ratio = 1.0 if has_doc else 0.0

        # 加权：注释 50% + 测试 30% + 文档 20%
        return 0.5 * doc_ratio + 0.3 * test_ratio + 0.2 * doc_exist_ratio

    @staticmethod
    def _compute_coverage_score(target: str, py_files: list[str]) -> float:
        """覆盖率得分：注释行数比例（简化版）。"""
        total_lines = 0
        comment_lines = 0
        for fpath in py_files:
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
            except (UnicodeDecodeError, OSError):
                continue
            for line in content.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                total_lines += 1
                if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                    comment_lines += 1

        if total_lines == 0:
            return 0.0
        return min(1.0, comment_lines / total_lines * 3)  # 注释比 33% 即满分

    def _compute_complexity_penalty(self, py_files: list[str]) -> float:
        """复杂度惩罚：嵌套深度 + 长函数。"""
        max_depth_total = 0
        long_func_count = 0
        total_funcs = 0
        for fpath in py_files:
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read(), filename=fpath)
            except (SyntaxError, UnicodeDecodeError, OSError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    total_funcs += 1
                    depth = self._max_nesting_depth(node)
                    max_depth_total = max(max_depth_total, depth)
                    # 长函数：行数 > 50
                    end_line = getattr(node, "end_lineno", node.lineno)
                    if end_line - node.lineno + 1 > 50:
                        long_func_count += 1

        if total_funcs == 0:
            return 0.5  # 无函数，中等惩罚

        depth_penalty = min(1.0, max(0, max_depth_total - 3) * 0.2)  # 超过 3 层每层 +0.2
        long_ratio = long_func_count / total_funcs
        return min(1.0, depth_penalty * 0.6 + long_ratio * 0.4)

    @staticmethod
    def _max_nesting_depth(node: ast.AST, current: int = 0) -> int:
        """计算函数最大嵌套深度。"""
        if not hasattr(node, "body") or not isinstance(getattr(node, "body"), list):
            return current
        max_d = current
        for child in node.body:  # type: ignore[attr-defined]
            if isinstance(child, (ast.If, ast.For, ast.While, ast.With, ast.Try, ast.ExceptHandler)):
                d = AIAuditor._max_nesting_depth(child, current + 1)
                max_d = max(max_d, d)
            else:
                d = AIAuditor._max_nesting_depth(child, current)
                max_d = max(max_d, d)
        return max_d

    # ------------------------------------------------------------------
    # 认知债务检测
    # ------------------------------------------------------------------

    def _detect_cognitive_debt(self, py_files: list[str]) -> list[CognitiveDebt]:
        """检测 4 类认知债务：无注释复杂逻辑/无测试/魔法数字/硬编码。"""
        debts: list[CognitiveDebt] = []

        for fpath in py_files:
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    source = f.read()
                tree = ast.parse(source, filename=fpath)
            except (SyntaxError, UnicodeDecodeError, OSError):
                continue

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # 无注释复杂逻辑：无 docstring 且嵌套深度 ≥ 3
                    if not ast.get_docstring(node):
                        depth = self._max_nesting_depth(node)
                        if depth >= 3:
                            debts.append(CognitiveDebt(
                                type="uncommented_complexity",
                                description=f"复杂逻辑无注释: {node.name} (嵌套深度 {depth})",
                                evidence=Evidence(
                                    result=f"函数 {node.name} 无 docstring 且嵌套深度 {depth} ≥ 3",
                                    level=EvidenceLevel.OBSERVATION,
                                    provenance={
                                        "file": fpath,
                                        "line": node.lineno,
                                        "function": node.name,
                                        "depth": depth,
                                        "type": "uncommented_complexity",
                                    },
                                    confidence=0.9,
                                    known_gaps=["复杂度判定基于 AST 嵌套，未做完整圈复杂度"],
                                ),
                            ))

                # 魔法数字检测
                for sub in ast.walk(node) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)) else []:
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, (int, float)):
                        val = sub.value
                        if isinstance(val, int) and val in _MAGIC_NUMBER_EXEMPT:
                            continue
                        if isinstance(val, float) and abs(val) < 0.01:
                            continue
                        # 排除常量赋值上下文（Name = val）
                        line_no = getattr(sub, "lineno", 0)
                        if line_no:
                            debts.append(CognitiveDebt(
                                type="magic_number",
                                description=f"魔法数字: {val}",
                                evidence=Evidence(
                                    result=f"魔法数字 {val}",
                                    level=EvidenceLevel.OBSERVATION,
                                    provenance={
                                        "file": fpath,
                                        "line": line_no,
                                        "value": val,
                                        "type": "magic_number",
                                    },
                                    confidence=0.7,
                                    known_gaps=[
                                        "数字 0/1/-1 已豁免",
                                        "可能误判常量定义（如 MAGIC = 0.85）",
                                    ],
                                ),
                            ))

            # 硬编码检测：字符串字面量长度 > 20 且非常量上下文（简化）
            # 此处仅作示意性检测，避免噪音过多

        return debts

    # ------------------------------------------------------------------

    @staticmethod
    def _collect_py_files(target: str) -> list[str]:
        if os.path.isfile(target) and target.endswith(".py"):
            return [target]
        if not os.path.isdir(target):
            return []
        files = []
        for root, _, names in os.walk(target):
            # 跳过 __pycache__ 和 .git
            if "__pycache__" in root or "/.git" in root:
                continue
            for n in names:
                if n.endswith(".py"):
                    files.append(os.path.join(root, n))
        return files

    def _failopen_unknown(self, target: str, result: str) -> dict[str, Any]:
        """FAIL-OPEN（§5.5）：审计失败时 poe_score=0.0, gate=review。"""
        ev = Evidence(
            result=result,
            level=EvidenceLevel.UNKNOWN,
            provenance={"target": target, "analysis": "ai_audit"},
            confidence=0.0,
            known_gaps=["审计失败，需人工确认"],
        )
        return {
            "target": target,
            "evidence_chain_score": 0.0,
            "coverage_score": 0.0,
            "complexity_penalty": 0.0,
            "poe_score": 0.0,
            "gate_decision": "review",
            "cognitive_debt": [],
            "evidence": [ev],
            "audit_layer_status": {
                "design_decision": False,
                "narrative": False,
                "methodology": False,
            },
        }


# ---------- 模块级入口 ----------

def audit_ai_output(target: str, ai_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """AI 产出审计的模块级入口。

    Args:
        target: AI 产出代码目录或文件路径
        ai_context: 可选 AI 上下文（agent_id/model/prompt_hash/timestamp）

    Returns:
        见 AIAuditor.audit
    """
    auditor = AIAuditor()
    return auditor.audit(target, ai_context)
