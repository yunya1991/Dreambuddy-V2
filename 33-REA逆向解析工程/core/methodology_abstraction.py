"""方法论抽象层 — 跨项目模式聚类与通用解法蒸馏。

PoE Task 4：输入多个项目的 REA 调查结果，识别同类问题的不同解法，
输出可复用的方法论模板（problem_pattern / solution_pattern / applicability / evidence）。

Evidence-First 硬约束：每条方法论模板必须带 Evidence（NFR-1）。
方法论的 Evidence 标注为 derivation 级（基于多项目观察推导）。
FAIL-OPEN：空输入返回 level=unknown Evidence（NFR-7）。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .evidence import Evidence, EvidenceLevel


# ---------- 数据结构 ----------

@dataclass
class MethodologyTemplate:
    """方法论模板。"""
    methodology_id: str
    problem_pattern: str              # 问题描述（如 "MVC 架构组织"）
    solution_pattern: str            # 解法描述
    applicability: list[str]         # 适用条件
    known_gaps: list[str]
    evidence: Evidence = None
    source_projects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "methodology_id": self.methodology_id,
            "problem_pattern": self.problem_pattern,
            "solution_pattern": self.solution_pattern,
            "applicability": self.applicability,
            "known_gaps": self.known_gaps,
            "evidence": self.evidence,
            "source_projects": self.source_projects,
        }


# ---------- 抽象器 ----------

class MethodologyAbstractor:
    """方法论抽象器。

    抽象策略：
    1. 聚类：按 problem_pattern（架构模式名）分组各项目的调查结果
    2. 模板生成：每组 ≥2 个项目 → 蒸馏为通用方法论模板
    3. evidence 引用：合并各项目的原始 Evidence，标注 source_projects
    """

    def abstract(self, investigations: list[dict[str, Any]]) -> dict[str, Any]:
        """从多个项目调查结果抽象方法论模板。

        Args:
            investigations: 多个项目的 REA 调查结果列表，每项含 patterns/decisions

        Returns:
            {
                "methodologies": [MethodologyTemplate.to_dict()...],
                "evidence": [Evidence...],
            }
        """
        if not investigations:
            return self._failopen_empty()

        # 1. 聚类：按模式名收集每项目对该模式的采用情况
        clusters: dict[str, list[dict]] = defaultdict(list)
        for inv in investigations:
            target = inv.get("target", "/unknown")
            for p in inv.get("patterns", []):
                pattern_name = p.get("pattern", "unknown")
                ev = p.get("evidence")
                if ev is None:
                    continue  # NFR-1：无 Evidence 的模式不入聚类
                clusters[pattern_name].append({
                    "target": target,
                    "matched_dirs": p.get("matched_dirs", []),
                    "evidence": ev,
                })
            for d in inv.get("decisions", []):
                # 从决策中提取模式信号（如 "采用 MVC 架构模式" → MVC）
                decision_text = str(d.get("decision", ""))
                pattern_name = self._extract_pattern_name(decision_text)
                if pattern_name and pattern_name in clusters:
                    ev = d.get("evidence")
                    if ev is not None:
                        clusters[pattern_name].append({
                            "target": target,
                            "matched_dirs": [],
                            "evidence": ev,
                            "from_decision": True,
                        })

        # 2. 模板生成：每组 ≥2 个项目 → 蒸馏
        methodologies: list[MethodologyTemplate] = []
        all_evidence: list[Evidence] = []

        for pattern_name, items in clusters.items():
            if len(items) < 2:
                continue  # 仅 1 个项目，不足以蒸馏通用方法论

            source_projects = list({item["target"] for item in items})
            ref_evidences = [item["evidence"] for item in items]

            ev = Evidence(
                result=f"方法论模板：{pattern_name} 架构模式（跨 {len(source_projects)} 个项目蒸馏）",
                level=EvidenceLevel.DERIVATION,
                provenance={
                    "pattern": pattern_name,
                    "source_projects": source_projects,
                    "ref_evidence_ids": [e.evidence_id for e in ref_evidences],
                    "analysis": "methodology_abstraction",
                },
                confidence=0.75,
                known_gaps=[
                    "聚类仅基于模式名匹配，未做语义相似度计算",
                    "适用条件为模板化推导，需人工确认对具体项目的适配度",
                    f"基于 {len(source_projects)} 个项目样本，统计样本量偏小",
                ],
                observations=[
                    {"project": p, "evidence_id": e.evidence_id, "result": e.result}
                    for p, e in zip(source_projects, ref_evidences)
                ],
            )

            tpl = MethodologyTemplate(
                methodology_id=f"mt_{pattern_name.lower()}_001",
                problem_pattern=f"{pattern_name} 架构组织",
                solution_pattern=(
                    f"采用 {pattern_name} 模式组织代码："
                    f"按职责分离为 {', '.join(items[0]['matched_dirs']) if items[0]['matched_dirs'] else '约定目录'} 等"
                    f"模块，约束模块间依赖方向，保持模式完整性"
                ),
                applicability=[
                    f"项目需要明确的职责分离（{pattern_name} 核心约束）",
                    "模块数量足够多到需要组织约定",
                    "团队接受 {pattern_name} 模式的学习成本",
                ],
                known_gaps=[
                    "模板仅描述通用结构，未涵盖具体实现细节",
                    "不同项目对模式的变体实现可能差异较大",
                ],
                evidence=ev,
                source_projects=source_projects,
            )
            methodologies.append(tpl)
            all_evidence.append(ev)

        if not methodologies:
            all_evidence.append(Evidence(
                result="无足够共现项目，无法蒸馏方法论模板",
                level=EvidenceLevel.UNKNOWN,
                provenance={
                    "investigation_count": len(investigations),
                    "analysis": "methodology_abstraction",
                },
                confidence=0.3,
                known_gaps=[
                    "每个模式至少需要 2 个项目采用才能聚类",
                    "可能输入的项目采用的模式过于分散，无可聚类的共性",
                ],
            ))

        return {
            "methodologies": [m.to_dict() for m in methodologies],
            "evidence": all_evidence,
        }

    # ------------------------------------------------------------------

    @staticmethod
    def _extract_pattern_name(decision_text: str) -> str | None:
        """从决策文本中提取模式名（如 'MVC 架构模式' → 'MVC'）。"""
        # 匹配常见模式关键字
        candidates = ["MVC", "Layered", "Layered-API", "EventDriven", "Pipeline", "Plugin", "Microkernel"]
        for c in candidates:
            if c.lower() in decision_text.lower():
                return c
        return None

    def _failopen_empty(self) -> dict[str, Any]:
        ev = Evidence(
            result="输入调查结果为空，无法抽象方法论",
            level=EvidenceLevel.UNKNOWN,
            provenance={"analysis": "methodology_abstraction", "input": "empty"},
            confidence=0.0,
            known_gaps=["需要至少 2 个项目的调查结果才能蒸馏方法论模板"],
        )
        return {
            "methodologies": [],
            "evidence": [ev],
        }


# ---------- 模块级入口 ----------

def abstract_methodology(investigations: list[dict[str, Any]]) -> dict[str, Any]:
    """方法论抽象的模块级入口。

    Args:
        investigations: 多个项目的 REA 调查结果列表

    Returns:
        见 MethodologyAbstractor.abstract
    """
    abstractor = MethodologyAbstractor()
    return abstractor.abstract(investigations)
