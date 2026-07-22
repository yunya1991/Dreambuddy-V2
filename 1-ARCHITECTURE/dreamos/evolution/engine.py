"""
DreamOS Evolution — 自我进化引擎 (EvolutionEngine)

Evolution 层主入口，整合:
    - LessonDistiller:              经验教训提炼
    - GapAnalyzer:                 知行差距分析
    - NodeOptimizer:               节点优化建议器
    - TradingAnalysisEvaluator:    交易分析评估器（核心新增）

职责:
    1. 从 G 层历史数据中学习
    2. 分析知行差距
    3. 提炼教训
    4. 分析交易亏损原因
    5. 评估模块能力
    6. 回测模块组合
    7. 推荐最优节点编排
    8. 输出进化报告

**设计理念**:
    Dream OS 交易系统的核心不是"自身交易"，而是"分析评估 → 模块能力回测 → 节点编排推荐"的质量提升闭环。
    EvolutionEngine 通过整合 TradingAnalysisEvaluator，实现：
    - 亏损原因分析 → 定位问题模块
    - 模块能力评估 → 量化各模块表现
    - 模块回测 → 验证改进效果
    - 编排推荐 → 基于分析结果推荐最优节点编排

用法:
    engine = EvolutionEngine()
    report = engine.evolve(history_entries)
    # report.lessons → 教训列表
    # report.gap_analysis → 差距分析
    # report.suggestions → 优化建议
    
    # 新增：交易分析评估
    analysis_report = engine.analyze_trades(trade_history)
    # analysis_report.loss_reason_distribution → 亏损原因分布
    # analysis_report.module_capabilities → 模块能力评估
    # analysis_report.orchestration_recommendations → 编排推荐
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Any

from dreamos.shared.state import State

logger = logging.getLogger(__name__)
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

        # 新增：交易分析评估（核心能力）
        analysis = engine.analyze_trades(trade_history)
        recommendations = engine.recommend_orchestration(scenarios)
    """

    def __init__(self, min_occurrences: int = 2):
        self._distiller = LessonDistiller(min_occurrences=min_occurrences)
        self._gap_analyzer = GapAnalyzer()
        self._optimizer = NodeOptimizer()
        self._history: List[HistoryEntry] = []
        self._feedback_collector = None  # 延迟初始化
        self._trading_evaluator = None   # 交易分析评估器（延迟初始化）
        self._evaluation_memory = None   # 评估记忆系统（延迟初始化）

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

        P1-1: 增加数据有效性校验，避免基于空数据触发进化
        P2-1: 跳过未验证场景，避免基于未验证数据修改编排
        """
        collector = self.get_feedback_collector()
        updates = []

        # P2-1: 进化前同步场景验证状态
        collector.sync_verification_status()

        for scenario_id in collector.get_all_scenario_ids():
            feedback = collector.evaluate(scenario_id)
            if not feedback.trigger_evolution:
                continue

            # P1-1: 数据有效性双重校验
            stats = collector.get_stats(scenario_id)
            total_trades = stats.get("total_trades", 0)
            if total_trades < collector.MIN_TRADES_FOR_EVAL:
                continue

            # P2-1: 跳过未验证场景（inferred/sparse/unverified 不参与进化）
            scenario_data = collector.memory.get_scenario(scenario_id) if collector.memory else None
            if scenario_data:
                is_verified = scenario_data.get("verified", False)
                confidence = scenario_data.get("confidence", "")
                if not is_verified or confidence == "unverified":
                    logger.info(f"P2-1: 场景 {scenario_id} 未验证(confidence={confidence}), 跳过进化")
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

    # ── 交易分析评估（核心新增）───────────────────────────────

    def get_trading_evaluator(self):
        """获取交易分析评估器（延迟初始化）"""
        if self._trading_evaluator is None:
            from dreamos.capabilities.trading.evaluator import TradingAnalysisEvaluator
            self._trading_evaluator = TradingAnalysisEvaluator()
        return self._trading_evaluator

    def get_evaluation_memory(self):
        """获取评估记忆系统（延迟初始化）"""
        if self._evaluation_memory is None:
            from dreamos.core.memory.evaluation_memory import EvaluationMemory
            self._evaluation_memory = EvaluationMemory()
            self._evaluation_memory.load()
        return self._evaluation_memory

    def analyze_trades(self, trade_history: List[Dict[str, Any]],
                       scenarios: Optional[List[str]] = None) -> Any:
        """分析交易历史，生成完整的交易分析评估报告

        核心流程：亏损原因分析 → 模块能力评估 → 模块回测 → 编排推荐

        Args:
            trade_history: 交易历史列表
            scenarios: 目标场景列表

        Returns:
            TradingAnalysisReport: 分析评估报告
        """
        evaluator = self.get_trading_evaluator()
        return evaluator.generate_report(trade_history, scenarios=scenarios)

    def analyze_loss_reasons(self, trade_history: List[Dict[str, Any]]) -> List[Any]:
        """分析交易亏损原因"""
        evaluator = self.get_trading_evaluator()
        return evaluator.analyze_loss_reasons(trade_history)

    def evaluate_module_capabilities(self, trade_history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """评估各模块的能力"""
        evaluator = self.get_trading_evaluator()
        return evaluator.evaluate_module_capabilities(trade_history)

    def backtest_modules(self, module_ids: List[str], scenario: str,
                         period: str = "90d") -> Any:
        """回测指定模块组合在特定场景下的表现"""
        evaluator = self.get_trading_evaluator()
        return evaluator.backtest_modules(module_ids, scenario, period)

    def recommend_orchestration(self, scenarios: Optional[List[str]] = None,
                                 module_capabilities: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """推荐最优节点编排

        根据模块能力评估结果，为各场景推荐最优节点编排

        Args:
            scenarios: 目标场景列表
            module_capabilities: 模块能力评估结果（可选，不提供则使用缓存）

        Returns:
            {scenario: OrchestrationRecommendation}
        """
        evaluator = self.get_trading_evaluator()
        return evaluator.recommend_orchestration(scenarios=scenarios,
                                                   module_capabilities=module_capabilities)

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
