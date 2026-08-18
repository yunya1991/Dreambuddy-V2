#!/usr/bin/env python3
"""
C层 - 动态链融合编排器

位置: experiments/ab-trading/core/c_execution_layer/fusion_orchestrator.py

职责：
1. 整合所有动态链融合组件
2. 控制融合流程：分析 → 决策 → 执行 → 重规划 → 反思
3. 管理执行状态和历史
4. 提供统一的融合执行接口

完整流程：
1. 执行节点
2. LLM分析结果质量
3. 动态决策下一步
4. 如果需要重规划 → 调用重规划器
5. 执行完成后 → 执行反思进化
"""

from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field

from .types import (
    NodeExecutionResult,
    ChainFusionDecision,
    ExecutionContext,
    NodeStatus,
)
from .llm_result_analyzer import LLMResultAnalyzer, ResultAnalysis
from .dynamic_decision_maker import DynamicDecisionMaker
from .dynamic_replanner import DynamicReplanner, ReplanningResult
from .execution_reflector import ExecutionReflector, ExecutionReflection


# ============================================================
# 融合编排器
# ============================================================

class FusionOrchestrator:
    """动态链融合编排器

    整合分析器、决策器、重规划器、反思器
    提供完整的动态链融合能力
    """

    def __init__(
        self,
        use_llm: bool = True,
        enable_replanning: bool = True,
        enable_reflection: bool = True,
        max_replans: int = 3,
        quality_threshold: float = 0.6,
        replan_threshold: float = 0.3,
        llm_purpose_prefix: str = "chain_fusion",
    ):
        """
        Args:
            use_llm: 是否使用LLM
            enable_replanning: 是否启用动态重规划
            enable_reflection: 是否启用执行反思
            max_replans: 最大重规划次数
            quality_threshold: 质量阈值
            replan_threshold: 重规划阈值
            llm_purpose_prefix: LLM调用用途前缀
        """
        self.use_llm = use_llm
        self.enable_replanning = enable_replanning
        self.enable_reflection = enable_reflection
        self.max_replans = max_replans

        # 组件
        self.analyzer = LLMResultAnalyzer(
            purpose=f"{llm_purpose_prefix}_analysis",
            use_llm=use_llm,
        )

        self.decision_maker = DynamicDecisionMaker(
            purpose=f"{llm_purpose_prefix}_decision",
            use_llm=use_llm,
            quality_threshold=quality_threshold,
            replan_threshold=replan_threshold,
        )

        self.replanner = DynamicReplanner(
            max_replans=max_replans,
            use_llm=use_llm,
            llm_purpose=f"{llm_purpose_prefix}_replan",
        )

        self.reflector = ExecutionReflector(
            use_llm=use_llm,
            llm_purpose=f"{llm_purpose_prefix}_reflection",
            enable_persistence=False,  # 默认不持久化，需要时手动开启
        )

        # 执行状态
        self.execution_history: List[NodeExecutionResult] = []
        self.decision_history: List[ChainFusionDecision] = []
        self.replan_history: List[ReplanningResult] = []

        # 回调
        self._on_decision: Optional[Callable] = None
        self._on_replan: Optional[Callable] = None

    def reset(self):
        """重置状态"""
        self.execution_history = []
        self.decision_history = []
        self.replan_history = []
        self.replanner.reset()

    def set_callbacks(
        self,
        on_decision: Optional[Callable] = None,
        on_replan: Optional[Callable] = None,
    ):
        """设置回调"""
        self._on_decision = on_decision
        self._on_replan = on_replan

    def process_node_result(
        self,
        node_result: NodeExecutionResult,
        available_nodes: List[str],
        context: Optional[Dict] = None,
        objective_info: Optional[Dict] = None,
    ) -> ChainFusionDecision:
        """
        处理节点执行结果并做出决策

        Args:
            node_result: 节点执行结果
            available_nodes: 可用节点列表
            context: 执行上下文
            objective_info: 目标信息

        Returns:
            ChainFusionDecision - 决策结果
        """
        # 记录历史
        self.execution_history.append(node_result)

        # 1. 分析结果
        analysis_context = {
            "previous_results": [
                r.to_dict() for r in self.execution_history[-3:]
            ],
        }
        if context:
            analysis_context.update(context)

        analysis = self.analyzer.analyze(
            node_result,
            context=analysis_context,
            objective_info=objective_info,
        )

        # 2. 做出决策
        decision = self.decision_maker.decide(
            node_result,
            analysis,
            available_nodes,
            context=context,
        )

        # 记录决策
        self.decision_history.append(decision)

        # 回调
        if self._on_decision:
            self._on_decision(decision, analysis)

        return decision

    def handle_replan(
        self,
        current_blueprint: Any,
        failed_node_id: str,
        reason: str,
        context: Optional[Dict] = None,
    ) -> ReplanningResult:
        """
        处理重规划请求

        Args:
            current_blueprint: 当前蓝图
            failed_node_id: 失败节点ID
            reason: 重规划原因
            context: 执行上下文

        Returns:
            ReplanningResult - 重规划结果
        """
        if not self.enable_replanning:
            result = ReplanningResult()
            result.success = False
            result.reason = "重规划功能未启用"
            return result

        result = self.replanner.replan(
            current_blueprint,
            failed_node_id,
            reason,
            self.execution_history,
            context,
        )

        self.replan_history.append(result)

        if self._on_replan:
            self._on_replan(result)

        return result

    def reflect(
        self,
        blueprint: Optional[Any] = None,
        context: Optional[Dict] = None,
    ) -> ExecutionReflection:
        """
        执行反思

        Args:
            blueprint: 执行蓝图
            context: 执行上下文

        Returns:
            ExecutionReflection - 反思结果
        """
        if not self.enable_reflection:
            reflection = ExecutionReflection()
            reflection.overall_score = 0.0
            reflection.lessons_learned.append("反思功能未启用")
            return reflection

        return self.reflector.reflect(
            self.execution_history,
            blueprint,
            context,
        )

    def get_execution_summary(self) -> Dict:
        """获取执行摘要"""
        if not self.execution_history:
            return {"total_nodes": 0}

        total = len(self.execution_history)
        successful = sum(1 for r in self.execution_history if r.is_success)
        failed = sum(1 for r in self.execution_history if r.is_failure)
        avg_confidence = sum(r.confidence for r in self.execution_history) / total
        total_duration = sum(r.duration_ms for r in self.execution_history)

        return {
            "total_nodes": total,
            "successful": successful,
            "failed": failed,
            "avg_confidence": avg_confidence,
            "total_duration_ms": total_duration,
            "replans_triggered": len(self.replan_history),
            "decisions_made": len(self.decision_history),
            "node_sequence": [r.node_id for r in self.execution_history],
        }
