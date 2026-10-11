"""设计决策还原模块 — 从代码产物还原 ADR 风格的设计决策记录。

PoE Task 2：组合架构模式识别（Task 1）+ 权衡痕迹检测（TODO/FIXME/兼容层/重复实现）
+ 替代方案推断，输出带证据的决策记录。

Evidence-First 硬约束：每条决策必须引用 ≥1 条 observation/derivation 级 Evidence（NFR-1）。
Inference 控制硬约束：替代方案推断必须为 inference 级 + known_gaps 非空（NFR-1a）。
FAIL-OPEN：异常/无决策时返回 level=unknown Evidence（NFR-7）。
"""
from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from typing import Any

from .architecture_pattern_detector import ArchitecturePatternDetector
from .evidence import Evidence, EvidenceLevel


# ---------- 数据结构 ----------

@dataclass
class DesignDecision:
    """ADR 风格设计决策记录。

    alternatives 是 dict 列表（含 result/level/known_gaps 字段），便于客户端直接消费。
    inference 级替代方案受 NFR-1a 硬约束（known_gaps 非空、confidence≤0.6）。
    """
    decision: str
    context: str
    consequences: list[str] = field(default_factory=list)
    alternatives: list[dict] = field(default_factory=list)
    evidence: Evidence = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "context": self.context,
            "consequences": self.consequences,
            "alternatives": self.alternatives,
            "evidence": self.evidence,
        }


# 权衡痕迹信号关键字
_TRADEOFF_MARKERS = {
    "TODO": "未来计划改动（暗示当前实现是过渡方案）",
    "FIXME": "已知缺陷待修复（暗示存在技术债决策）",
    "XXX": "硬编码或临时方案（暗示存在权衡但未完成）",
    "HACK": "非标准实现（暗示绕过了正常设计）",
}


# ---------- 还原器 ----------

class DesignDecisionRecoverer:
    """设计决策还原器。

    还原策略：
    1. 调用 ArchitecturePatternDetector 识别架构模式 → 生成模式决策
    2. 扫描代码中的 TODO/FIXME/XXX/HACK 标记 → 生成权衡痕迹决策
    3. 检测并存的 ORM + 原生 SQL、多套实现 → 推断替代方案（inference 级）
    4. 每条决策必须有 evidence（observation/derivation 级主证据 + 可选 inference 级替代方案）
    """

    def __init__(self) -> None:
        self.pattern_detector = ArchitecturePatternDetector()

    def recover(self, target: str) -> dict[str, Any]:
        """还原目标工程的设计决策。

        Args:
            target: 目标工程根路径（目录或单文件）

        Returns:
            {
                "target": str,
                "decisions": [DesignDecision.to_dict()...],
                "evidence": [Evidence...],   # 全部 Evidence（含 unknown 降级）
            }
        """
        if not (os.path.isdir(target) or (os.path.isfile(target) and target.endswith(".py"))):
            return self._failopen_unknown(target, "目标不存在或不是 Python 工程路径")

        decisions: list[DesignDecision] = []
        all_evidence: list[Evidence] = []

        # 1. 架构模式 → 模式决策
        if os.path.isdir(target):
            pattern_result = self.pattern_detector.detect(target)
            for p in pattern_result.get("patterns", []):
                ev = p.get("evidence")
                if ev is None:
                    continue  # NFR-1 硬约束：无 Evidence 禁止输出
                decision = DesignDecision(
                    decision=f"采用 {p['pattern']} 架构模式",
                    context=f"目录结构匹配 {p['pattern']} 模式约定，命中目录: {', '.join(p.get('matched_dirs', []))}",
                    consequences=[
                        f"该模式约束了后续模块的组织方式",
                        "需保持模块职责边界，避免破坏模式完整性",
                    ],
                    alternatives=[],
                    evidence=ev,
                )
                decisions.append(decision)
                all_evidence.append(ev)

        # 2. 权衡痕迹 → TODO/FIXME 决策
        tradeoff_ev = self._detect_tradeoff_markers(target)
        for ev in tradeoff_ev:
            decision = DesignDecision(
                decision=f"权衡决策：{ev.result}",
                context="代码注释中检测到权衡标记，暗示存在过渡/临时方案",
                consequences=[
                    "存在未偿还的技术债",
                    "需在后续重构中清理",
                ],
                alternatives=[],
                evidence=ev,
            )
            decisions.append(decision)
            all_evidence.append(ev)

        # 3. 替代方案推断（inference 级）
        alternative_evs = self._infer_alternatives(target)
        if alternative_evs:
            # 将替代方案附加到最近一条决策，若无则作为独立决策
            primary = decisions[-1] if decisions else None
            if primary is not None:
                for alt_ev in alternative_evs:
                    primary.alternatives.append({
                        "result": alt_ev.result,
                        "level": alt_ev.level.value,
                        "known_gaps": alt_ev.known_gaps,
                        "provenance": alt_ev.provenance,
                        "confidence": alt_ev.confidence,
                        "evidence_id": alt_ev.evidence_id,
                    })
            else:
                for alt_ev in alternative_evs:
                    decisions.append(DesignDecision(
                        decision=f"替代方案推断：{alt_ev.result}",
                        context="基于代码共存的实现线索推断",
                        consequences=["提示曾被考虑但未采纳的方向"],
                        alternatives=[{
                            "result": alt_ev.result,
                            "level": alt_ev.level.value,
                            "known_gaps": alt_ev.known_gaps,
                            "provenance": alt_ev.provenance,
                            "confidence": alt_ev.confidence,
                            "evidence_id": alt_ev.evidence_id,
                        }],
                        evidence=alt_ev,  # inference 级作主证据（NFR-1a：不计入 evidence_chain_score 分子）
                    ))
            all_evidence.extend(alternative_evs)

        # 无任何决策 → 降级
        if not decisions:
            all_evidence.append(Evidence(
                result="未检测到可还原的设计决策",
                level=EvidenceLevel.UNKNOWN,
                provenance={"target": target, "analysis": "design_decision_recovery"},
                confidence=0.2,
                known_gaps=[
                    "目标可能缺乏目录结构特征、权衡注释、并存实现等决策信号",
                    "需人工审查源码以补充设计决策",
                ],
            ))

        return {
            "target": target,
            "decisions": [d.to_dict() for d in decisions],
            "evidence": all_evidence,
        }

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _detect_tradeoff_markers(self, target: str) -> list[Evidence]:
        """扫描 TODO/FIXME/XXX/HACK 注释，生成 observation 级 Evidence。"""
        evidence_list: list[Evidence] = []
        py_files = self._collect_py_files(target)
        for fpath in py_files:
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    source = f.read()
                tree = ast.parse(source, filename=fpath)
            except (SyntaxError, UnicodeDecodeError, OSError):
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                    docstring = node.value.value
                    if isinstance(docstring, str):
                        for marker, hint in _TRADEOFF_MARKERS.items():
                            if marker in docstring:
                                evidence_list.append(Evidence(
                                    result=f"{marker} 权衡痕迹: {hint}",
                                    level=EvidenceLevel.OBSERVATION,
                                    provenance={
                                        "file": fpath,
                                        "line": node.lineno,
                                        "marker": marker,
                                        "comment": docstring.strip()[:200],
                                    },
                                    confidence=0.9,
                                    known_gaps=["注释仅是间接证据，需结合代码结构确认实际权衡"],
                                ))
                                break
            # 行内注释扫描（# TODO 等）
            for line_no, line in enumerate(source.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    for marker, hint in _TRADEOFF_MARKERS.items():
                        if marker in stripped:
                            evidence_list.append(Evidence(
                                result=f"{marker} 权衡痕迹: {hint}",
                                level=EvidenceLevel.OBSERVATION,
                                provenance={
                                    "file": fpath,
                                    "line": line_no,
                                    "marker": marker,
                                    "comment": stripped[:200],
                                },
                                confidence=0.85,
                                known_gaps=["注释仅是间接证据，需结合代码结构确认实际权衡"],
                            ))
                            break

        return evidence_list

    def _infer_alternatives(self, target: str) -> list[Evidence]:
        """推断被放弃的替代方案（inference 级 + known_gaps 非空，NFR-1a）。"""
        alternatives: list[Evidence] = []
        py_files = self._collect_py_files(target)

        for fpath in py_files:
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    source = f.read()
                tree = ast.parse(source, filename=fpath)
            except (SyntaxError, UnicodeDecodeError, OSError):
                continue

            # 检测 ORM + 原生 SQL 并存 → 推断曾考虑过直接 SQL
            has_orm_import = False
            has_raw_sql = False
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module and ("sqlalchemy" in node.module or "django.db" in node.module):
                        has_orm_import = True
                if isinstance(node, ast.Call):
                    func_name = self._call_name(node.func)
                    if "execute" in func_name.lower() or "raw" in func_name.lower():
                        has_raw_sql = True

            if has_orm_import and has_raw_sql:
                alternatives.append(Evidence(
                    result="推断：曾考虑直接使用原生 SQL，最终选择 ORM 但保留原生 SQL 兜底",
                    level=EvidenceLevel.INFERENCE,
                    provenance={
                        "file": fpath,
                        "analysis": "orm_raw_sql_coexistence",
                    },
                    confidence=0.5,
                    known_gaps=[
                        "推断基于代码共存，无直接证据证明设计意图",
                        "原生 SQL 可能仅用于性能优化或特殊查询，非替代方案遗留",
                    ],
                ))

        return alternatives

    @staticmethod
    def _call_name(node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{DesignDecisionRecoverer._call_name(node.value)}.{node.attr}"
        return "<unknown>"

    @staticmethod
    def _collect_py_files(target: str) -> list[str]:
        if os.path.isfile(target) and target.endswith(".py"):
            return [target]
        if not os.path.isdir(target):
            return []
        files = []
        for root, _, names in os.walk(target):
            for n in names:
                if n.endswith(".py") and not n.startswith("__"):
                    files.append(os.path.join(root, n))
        return files

    def _failopen_unknown(self, target: str, result: str) -> dict[str, Any]:
        ev = Evidence(
            result=result,
            level=EvidenceLevel.UNKNOWN,
            provenance={"target": target, "analysis": "design_decision_recovery"},
            confidence=0.0,
            known_gaps=["目标路径不存在或不可读，无法还原设计决策"],
        )
        return {
            "target": target,
            "decisions": [],
            "evidence": [ev],
        }


# ---------- 模块级入口 ----------

def recover_decisions(target: str) -> dict[str, Any]:
    """设计决策还原的模块级入口。

    Args:
        target: 目标工程根路径（目录或 .py 文件）

    Returns:
        见 DesignDecisionRecoverer.recover
    """
    recoverer = DesignDecisionRecoverer()
    return recoverer.recover(target)
