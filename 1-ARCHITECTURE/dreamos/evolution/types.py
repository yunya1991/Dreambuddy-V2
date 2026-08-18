"""
DreamOS Evolution — 类型定义

核心数据结构:
    - Lesson:            经验教训
    - GapAnalysis:       知行差距分析
    - EvolutionReport:   进化报告
    - OptimizationSuggestion: 优化建议
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime


# ============================================================
# 经验教训
# ============================================================

@dataclass
class Lesson:
    """经验教训 — 从执行结果中提炼的可复用知识"""
    lesson_id: str
    title: str = ""
    description: str = ""
    category: str = ""              # strategy / risk / execution / data
    severity: str = "medium"        # low / medium / high / critical
    context: Dict[str, Any] = field(default_factory=dict)
    action_suggestion: str = ""
    learned_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    confidence: float = 0.0         # 教训的可信度

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lesson_id": self.lesson_id,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "severity": self.severity,
            "context": self.context,
            "action_suggestion": self.action_suggestion,
            "learned_at": self.learned_at,
            "confidence": round(self.confidence, 3),
        }


# ============================================================
# 知行差距分析
# ============================================================

@dataclass
class GapAnalysis:
    """知行差距分析 — 分析"计划的"和"实际发生的"之间的差距

    维度:
        - intent_gap:     意图识别 vs 实际结果
        - plan_gap:       规划 vs 实际执行
        - direction_gap:  方向判断 vs 实际走势
        - confidence_gap: 预测置信度 vs 实际正确率
    """
    overall_gap_score: float = 0.0          # 0-1, 越小越好
    intent_accuracy: float = 0.0            # 意图识别准确率
    plan_completion_rate: float = 0.0       # 计划完成率
    direction_accuracy: float = 0.0         # 方向判断准确率
    confidence_calibration: float = 0.0     # 置信度校准度
    gaps: List[Dict[str, Any]] = field(default_factory=list)
    top_insights: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_gap_score": round(self.overall_gap_score, 3),
            "intent_accuracy": round(self.intent_accuracy, 3),
            "plan_completion_rate": round(self.plan_completion_rate, 3),
            "direction_accuracy": round(self.direction_accuracy, 3),
            "confidence_calibration": round(self.confidence_calibration, 3),
            "gaps": self.gaps,
            "top_insights": self.top_insights,
        }


# ============================================================
# 优化建议
# ============================================================

@dataclass
class OptimizationSuggestion:
    """节点/策略优化建议"""
    suggestion_id: str
    target: str = ""                 # 优化目标: node / chain / strategy / config
    target_id: str = ""              # 具体目标 ID
    type: str = ""                   # add / remove / modify / reorder
    description: str = ""
    expected_improvement: float = 0.0  # 预期提升幅度
    evidence: str = ""                # 证据/数据支撑
    priority: int = 2                  # 0=紧急, 1=高, 2=中, 3=低

    def to_dict(self) -> Dict[str, Any]:
        return {
            "suggestion_id": self.suggestion_id,
            "target": self.target,
            "target_id": self.target_id,
            "type": self.type,
            "description": self.description,
            "expected_improvement": round(self.expected_improvement, 3),
            "evidence": self.evidence,
            "priority": self.priority,
        }


# ============================================================
# 进化报告
# ============================================================

@dataclass
class EvolutionReport:
    """进化报告 — 一次进化分析的完整输出"""
    cycles_analyzed: int = 0
    lessons: List[Lesson] = field(default_factory=list)
    gap_analysis: Optional[GapAnalysis] = None
    suggestions: List[OptimizationSuggestion] = field(default_factory=list)
    performance_metrics: Dict[str, float] = field(default_factory=dict)
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycles_analyzed": self.cycles_analyzed,
            "lessons": [l.to_dict() for l in self.lessons],
            "gap_analysis": self.gap_analysis.to_dict() if self.gap_analysis else None,
            "suggestions": [s.to_dict() for s in self.suggestions],
            "performance_metrics": {k: round(v, 3) for k, v in self.performance_metrics.items()},
            "generated_at": self.generated_at,
        }
