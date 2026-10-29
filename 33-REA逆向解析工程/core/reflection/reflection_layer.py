"""P4 反思层：R1-R3 三级反思 + 纸上谈兵检测。

SPEC-33-反思层 v0.3 §6.1：
- R1 战略反思：分析方向选择是否被证据支撑；内外路径冲突裁决依据
- R2 战术反思：分析深度-成本权衡，识别过度分析/分析不足
- R3 执行反思：每条结论的证据完整度；纸上谈兵检测
  （声称分析但无证据链记录 → CRITICAL）

批评结论 100% 带 Evidence 结构（对齐 core.evidence 四级事实分级）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from core.evidence import Evidence, EvidenceLevel, reverse_evidence

SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_WARNING = "WARNING"
SEVERITY_INFO = "INFO"

# R2 阈值（可调）
OVER_ANALYSIS_CALLS = 200
UNDER_ANALYSIS_CALLS = 3
HIGH_UNCERTAINTY = 0.5


@dataclass
class CritiqueFinding:
    """一条批评发现（100% 带 Evidence）。"""

    level: str
    severity: str
    message: str
    evidence: Evidence
    target: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "severity": self.severity,
            "message": self.message,
            "target": self.target,
            "evidence": self.evidence.to_dict(),
        }


class ReflectionLayer:
    """R1-R3 三级反思器。"""

    def reflect(self, report: Dict[str, Any]) -> Dict[str, Any]:
        """对分析报告执行三级反思，返回批评报告。

        report 约定字段（均可缺省，缺省按空处理）：
        - decisions: [{direction, evidence_refs, ...}]
        - path_conflict: {topic, adjudication_basis, ...}
        - cost: {calls, tokens}
        - conclusions: [{claim, confidence, evidence_refs, ...}]
        """
        findings: List[CritiqueFinding] = []
        findings.extend(self._r1_strategy(report))
        findings.extend(self._r2_tactics(report))
        findings.extend(self._r3_execution(report))
        critical = [f for f in findings if f.severity == SEVERITY_CRITICAL]
        return {
            "findings": [f.to_dict() for f in findings],
            "total": len(findings),
            "critical_count": len(critical),
            "pass": len(critical) == 0,
        }

    def _r1_strategy(self, report: Dict[str, Any]) -> List[CritiqueFinding]:
        out: List[CritiqueFinding] = []
        for dec in report.get("decisions", []):
            if not dec.get("evidence_refs"):
                out.append(CritiqueFinding(
                    level="R1",
                    severity=SEVERITY_WARNING,
                    message="方向选择缺少证据支撑: " + str(dec.get("direction", "")),
                    target=str(dec.get("direction", "")),
                    evidence=reverse_evidence(
                        result="方向选择无证据引用",
                        level=EvidenceLevel.DERIVATION,
                        provenance={"stage": "R1", "decision": dec},
                        confidence=0.8,
                    ),
                ))
        conflict = report.get("path_conflict")
        if conflict and not conflict.get("adjudication_basis"):
            out.append(CritiqueFinding(
                level="R1",
                severity=SEVERITY_WARNING,
                message="内外路径冲突但无裁决依据记录",
                target=str(conflict.get("topic", "")),
                evidence=reverse_evidence(
                    result="路径冲突未记录裁决依据",
                    level=EvidenceLevel.DERIVATION,
                    provenance={"stage": "R1", "conflict": conflict},
                    confidence=0.9,
                ),
            ))
        return out

    def _r2_tactics(self, report: Dict[str, Any]) -> List[CritiqueFinding]:
        out: List[CritiqueFinding] = []
        cost = report.get("cost") or {}
        calls = int(cost.get("calls") or 0)
        conclusions = report.get("conclusions", [])
        if calls > OVER_ANALYSIS_CALLS:
            out.append(CritiqueFinding(
                level="R2",
                severity=SEVERITY_WARNING,
                message="疑似过度分析：调用数 " + str(calls) + " 超过阈值 " + str(OVER_ANALYSIS_CALLS),
                target="cost",
                evidence=reverse_evidence(
                    result="分析成本超阈值",
                    level=EvidenceLevel.DERIVATION,
                    provenance={"stage": "R2", "calls": calls},
                    confidence=0.7,
                ),
            ))
        uncertain = [
            c for c in conclusions
            if 1.0 - float(c.get("confidence", 1.0)) > HIGH_UNCERTAINTY
        ]
        if calls < UNDER_ANALYSIS_CALLS and uncertain:
            out.append(CritiqueFinding(
                level="R2",
                severity=SEVERITY_WARNING,
                message="疑似分析不足：调用数低但存在高不确定结论",
                target="cost",
                evidence=reverse_evidence(
                    result="分析深度不足",
                    level=EvidenceLevel.DERIVATION,
                    provenance={"stage": "R2", "calls": calls, "uncertain": len(uncertain)},
                    confidence=0.7,
                ),
            ))
        return out

    def _r3_execution(self, report: Dict[str, Any]) -> List[CritiqueFinding]:
        out: List[CritiqueFinding] = []
        for c in report.get("conclusions", []):
            if not c.get("evidence_refs"):
                out.append(CritiqueFinding(
                    level="R3",
                    severity=SEVERITY_CRITICAL,
                    message="纸上谈兵：声称分析结论但无证据链记录: " + str(c.get("claim", "")),
                    target=str(c.get("claim", "")),
                    evidence=reverse_evidence(
                        result="结论无证据链记录（纸上谈兵检测命中）",
                        level=EvidenceLevel.OBSERVATION,
                        provenance={"stage": "R3", "conclusion": c},
                        confidence=1.0,
                    ),
                ))
        return out
