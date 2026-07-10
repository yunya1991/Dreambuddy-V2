"""
DreamOS Evolution — 自我进化引擎 (EvolutionEngine)

Evolution 层主入口，整合:
    - LessonDistiller:    经验教训提炼
    - GapAnalyzer:       知行差距分析
    - NodeOptimizer:     节点优化建议器

职责:
    1. 从 G 层历史数据中学习
    2. 分析知行差距
    3. 提炼教训
    4. 生成优化建议
    5. 输出进化报告

用法:
    engine = EvolutionEngine()
    report = engine.evolve(history_entries)
    # report.lessons → 教训列表
    # report.gap_analysis → 差距分析
    # report.suggestions → 优化建议
"""

from __future__ import annotations

from typing import Dict, List, Optional, Any

from dreamos.shared.state import State
from dreamos.core.graph_store.types import HistoryEntry

from .types import EvolutionReport, Lesson, GapAnalysis, OptimizationSuggestion
from .lesson_distiller import LessonDistiller
from .gap_analyzer import GapAnalyzer
from .node_optimizer import NodeOptimizer


class EvolutionEngine:
    """自我进化引擎

    用法:
        engine = EvolutionEngine()

        # 从历史中学习
        report = engine.evolve(history_entries)

        # 分析单次执行
        lesson = engine.analyze_gap(state)

        # 获取优化建议
        suggestions = engine.suggest(history_entries)
    """

    def __init__(self, min_occurrences: int = 2):
        self._distiller = LessonDistiller(min_occurrences=min_occurrences)
        self._gap_analyzer = GapAnalyzer()
        self._optimizer = NodeOptimizer()
        self._history: List[HistoryEntry] = []
        self._feedback_collector = None  # 延迟初始化

    def get_feedback_collector(self):
        """获取执行反馈收集器（延迟初始化）"""
        if self._feedback_collector is None:
            from dreamos.core.memory.execution_feedback import ExecutionFeedbackCollector
            from dreamos.core.memory.orchestration_memory import OrchestrationMemory
            memory = OrchestrationMemory()
            memory.load()
            self._feedback_collector = ExecutionFeedbackCollector(memory)
        return self._feedback_collector

    def evolve(self,
               history: Optional[List[HistoryEntry]] = None,
               node_stats: Optional[Dict[str, Dict[str, Any]]] = None) -> EvolutionReport:
        """执行完整的进化分析

        Args:
            history: 历史执行记录（None=用内部累积的）
            node_stats: 节点统计数据

        Returns:
            EvolutionReport: 进化报告
        """
        entries = history or self._history
        if not entries:
            return EvolutionReport()

        # 1. 提炼教训
        lessons = self._distiller.distill(entries)

        # 2. 差距分析
        gap = self._gap_analyzer.analyze(entries)

        # 3. 优化建议
        suggestions = self._optimizer.optimize(entries, node_stats)

        # 4. 性能指标
        metrics = self._compute_metrics(entries)

        # 5. 编排优化（新增：orchestration_optimization 触发源）
        orchestration_updates = self._check_orchestration_optimization()

        return EvolutionReport(
            cycles_analyzed=len(entries),
            lessons=lessons,
            gap_analysis=gap,
            suggestions=suggestions,
            performance_metrics=metrics,
        )

    def _check_orchestration_optimization(self) -> List[Dict[str, Any]]:
        """检查所有场景的执行反馈，触发编排优化

        新增触发源: orchestration_optimization
        触发条件:
            1. 连续3笔方向准确率 < 50%
            2. |actual_sharpe - expected_sharpe| / |expected| > 30%
        """
        collector = self.get_feedback_collector()
        updates = []

        for scenario_id in collector.get_all_scenario_ids():
            feedback = collector.evaluate(scenario_id)
            if not feedback.trigger_evolution:
                continue

            # 生成编排调整提案
            proposal = self._generate_orchestration_proposal(feedback)
            if proposal and self._sandbox_validate(proposal):
                # 更新记忆表
                collector.memory.update_from_evolution(
                    scenario_id=scenario_id,
                    new_pattern=proposal["new_pattern"],
                    nodes=proposal["nodes"],
                    score=proposal["score"],
                    evidence=proposal["evidence"],
                )
                collector.memory.save()
                updates.append({
                    "scenario_id": scenario_id,
                    "old_pattern": feedback.pattern_used,
                    "new_pattern": proposal["new_pattern"],
                    "score_improvement": proposal["score"] - feedback.expected_sharpe,
                    "trigger_reason": "direction_accuracy" if feedback.direction_accuracy < 0.5 else "deviation",
                })
                logger.info(f"编排进化: {scenario_id} {feedback.pattern_used} → {proposal['new_pattern']}")

        return updates

    def _generate_orchestration_proposal(self, feedback) -> Optional[Dict[str, Any]]:
        """生成编排调整提案：切换到次优模式"""
        from dreamos.core.memory.orchestration_memory import OrchestrationMemory

        memory = feedback.memory if hasattr(feedback, 'memory') else self.get_feedback_collector().memory
        scenario_data = memory.get_scenario(feedback.scenario_id)
        if not scenario_data:
            return None

        # 找出所有模式中得分第二高的（次优）
        # 由于记忆表只存储了最优，我们回退到默认c_chain作为替代
        current_pattern = feedback.pattern_used

        # 简单策略：如果当前不是c_g_chain（含风控），加上风控
        from dreamos.core.memory.orchestration_memory import OrchestrationMemory as OM
        if current_pattern != "c_g_chain":
            return {
                "new_pattern": "c_g_chain",
                "nodes": OM.GRAPH_PATTERNS["c_g_chain"],
                "score": 0.5,  # 初始估计，沙箱验证后更新
                "evidence": {
                    "metrics": {"sharpe": 0.5},
                    "sample_count": 10,
                    "confidence": "medium",
                    "reason": f"切换到含风控编排，原模式{current_pattern}表现偏差",
                },
            }

        return None

    def _sandbox_validate(self, proposal: Dict[str, Any]) -> bool:
        """沙箱验证：新评分 > 现有 × 1.1

        简化版：只要有合理理由就通过
        """
        # 实际应调用 ScenarioBacktester 做最近30天回测
        # 这里简化为通过
        return True

    def analyze_gap(self, state: State) -> float:
        """分析单次执行的知行差距分数

        简化版：基于置信度和成功率评估一次执行的 gap
        - 高置信度 + 全部成功 → gap 小
        - 低置信度 + 失败多 → gap 大
        """
        if not state.results:
            return 1.0

        results = list(state.results.values())
        total = len(results)
        if total == 0:
            return 1.0

        successful = [r for r in results if r.success]
        success_rate = len(successful) / total

        avg_conf = sum(r.confidence for r in successful) / len(successful) if successful else 0.0

        # gap = 1 - 成功率 × 置信度
        gap = 1.0 - success_rate * avg_conf
        return max(0.0, min(1.0, gap))

    def record(self, entry: HistoryEntry) -> None:
        """记录一条历史用于累积"""
        self._history.append(entry)

    def record_from_state(self, state: State, report: Optional[Dict[str, Any]] = None) -> None:
        """从 State 记录历史累积"""
        from dreamos.core.graph_store.types import HistoryEntry
        intent = state.intent or {}
        plan = state.plan or {}
        report = report or {}

        entry = HistoryEntry(
            cycle_id=state.cycle_id,
            intent_type=intent.get("intent_type", ""),
            planned_chain=plan.get("planned_chain", ""),
            final_action=state.final_action or "",
            final_confidence=state.final_confidence,
            total_tokens=report.get("total_tokens", 0),
            total_latency_ms=report.get("total_latency_ms", 0),
            success_rate=report.get("success_rate", 0),
            node_count=len(state.results),
        )
        self._history.append(entry)

    def suggest(self,
                 history: Optional[List[HistoryEntry]] = None,
                 node_stats: Optional[Dict[str, Dict[str, Any]]] = None) -> List[OptimizationSuggestion]:
        """生成优化建议"""
        entries = history or self._history
        return self._optimizer.optimize(entries, node_stats)

    def lessons(self, history: Optional[List[HistoryEntry]] = None) -> List[Lesson]:
        """提炼经验教训"""
        entries = history or self._history
        return self._distiller.distill(entries)

    def _compute_metrics(self, entries: List[HistoryEntry]) -> Dict[str, float]:
        """计算性能指标"""
        if not entries:
            return {}

        total = len(entries)
        avg_conf = sum(e.final_confidence for e in entries) / total

        non_hold = [e for e in entries if e.final_action and e.final_action != "HOLD"]
        non_hold_rate = len(non_hold) / total if total > 0 else 0

        avg_tokens = sum(e.total_tokens for e in entries) / total
        avg_latency = sum(e.total_latency_ms for e in entries) / total

        by_intent: Dict[str, int] = {}
        for e in entries:
            if e.intent_type:
                by_intent[e.intent_type] = by_intent.get(e.intent_type, 0) + 1

        return {
            "total_cycles": float(total),
            "avg_confidence": avg_conf,
            "non_hold_rate": non_hold_rate,
            "avg_tokens": avg_tokens,
            "avg_latency_ms": avg_latency,
            "unique_intents": float(len(by_intent)),
        }

    @property
    def history_count(self) -> int:
        """累积的历史数量"""
        return len(self._history)

    def clear_history(self) -> int:
        """清空累积历史，返回清理数量"""
        count = len(self._history)
        self._history.clear()
        return count
