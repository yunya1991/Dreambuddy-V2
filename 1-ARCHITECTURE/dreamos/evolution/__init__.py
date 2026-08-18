"""
DreamOS Evolution — 自我进化层

职责:
    - 经验教训提炼 (Lesson Distillation)
    - 知行差距分析 (Gap Analysis)
    - 节点优化建议 (Node Optimization)
    - 历史数据驱动的持续改进

子模块:
    - types.py              类型定义 (Lesson/GapAnalysis/OptimizationSuggestion/EvolutionReport)
    - lesson_distiller.py   经验教训提炼器
    - gap_analyzer.py       知行差距分析器
    - node_optimizer.py     节点优化建议器
    - engine.py             进化引擎主入口

快速上手:
    from dreamos.evolution import EvolutionEngine

    engine = EvolutionEngine()
    report = engine.evolve(history_entries)
    print(f"Gap score: {report.gap_analysis.overall_gap_score}")
    print(f"Lessons: {len(report.lessons)}")
    print(f"Suggestions: {len(report.suggestions)}")
"""

from dreamos.shared.state import State

from .types import (
    Lesson, GapAnalysis, OptimizationSuggestion, EvolutionReport,
)
from .lesson_distiller import LessonDistiller
from .gap_analyzer import GapAnalyzer
from .node_optimizer import NodeOptimizer
from .engine import EvolutionEngine

__all__ = [
    # types
    "Lesson", "GapAnalysis", "OptimizationSuggestion", "EvolutionReport",
    # components
    "LessonDistiller", "GapAnalyzer", "NodeOptimizer", "EvolutionEngine",
]
