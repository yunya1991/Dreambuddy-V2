#!/usr/bin/env python3
"""
C层 - 大模型动态链融合器

位置: experiments/ab-trading/core/c_execution_layer/dynamic_chain_fusion.py

架构说明:
- S层: 意图识别 → ExecutionBlueprint
- A层: 图编排引擎 → 编排节点执行顺序/并行/条件
- C层: 执行层 → 具体执行节点

C层特色：
- AI大模型驱动的动态链融合
- 支持动态重规划
- 具备执行反思进化能力

动态链融合能力：
1. 节点执行结果分析 - 用大模型分析当前节点输出
2. 下一步决策 - 决定继续/跳过/重试/重定向
3. 动态重规划 - 当发现问题时触发重新规划
4. 执行反思 - 执行完成后反思整个执行过程
"""

from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field

from .types import (
    NodeExecutionResult,
    ChainFusionDecision,
)


# ============================================================
# C层：动态链融合器 - 接口定义
# ============================================================

class LLMAnalyzerInterface:
    """大模型分析器接口

    动态链融合需要的大模型分析能力
    """

    def analyze_result(
        self,
        node_id: str,
        node_output: Any,
        context: Dict[str, Any],
    ) -> str:
        """
        分析节点执行结果

        Args:
            node_id: 节点ID
            node_output: 节点输出
            context: 执行上下文

        Returns:
            分析结果（文本）
        """
        raise NotImplementedError

    def decide_next_action(
        self,
        current_node_id: str,
        analysis: str,
        available_nodes: List[str],
        context: Dict[str, Any],
    ) -> ChainFusionDecision:
        """
        决定下一步行动

        Args:
            current_node_id: 当前节点
            analysis: 分析结果
            available_nodes: 可用节点列表
            context: 执行上下文

        Returns:
            ChainFusionDecision - 决策
        """
        raise NotImplementedError

    def reflect_execution(
        self,
        execution_history: List[NodeExecutionResult],
        context: Dict[str, Any],
    ) -> str:
        """
        执行反思

        Args:
            execution_history: 执行历史
            context: 执行上下文

        Returns:
            反思结果（文本）
        """
        raise NotImplementedError


# ============================================================
# C层：动态链融合器 - 默认实现
# ============================================================

class DefaultLLMAnalyzer(LLMAnalyzerInterface):
    """默认大模型分析器

    当没有配置真正的大模型时使用的默认实现
    基于规则的分析
    """

    def analyze_result(
        self,
        node_id: str,
        node_output: Any,
        context: Dict[str, Any],
    ) -> str:
        """基于规则的简单分析"""
        if node_output is None:
            return f"节点 {node_id} 返回空结果"

        if isinstance(node_output, dict):
            if "error" in node_output:
                return f"节点 {node_id} 返回错误: {node_output['error']}"
            if "direction" in node_output:
                return f"节点 {node_id} 给出方向判断: {node_output['direction']}"
            if "confidence" in node_output:
                conf = node_output["confidence"]
                return f"节点 {node_id} 置信度: {conf:.2f}"

        return f"节点 {node_id} 执行完成"

    def decide_next_action(
        self,
        current_node_id: str,
        analysis: str,
        available_nodes: List[str],
        context: Dict[str, Any],
    ) -> ChainFusionDecision:
        """默认决策：继续执行"""
        decision = ChainFusionDecision()
        decision.node_id = current_node_id
        decision.analysis_result = analysis

        # 默认继续下一个节点
        if available_nodes:
            current_index = available_nodes.index(current_node_id) if current_node_id in available_nodes else -1
            if current_index < len(available_nodes) - 1:
                decision.action = "continue"
                decision.next_node_id = available_nodes[current_index + 1]
            else:
                decision.action = "complete"
        else:
            decision.action = "complete"

        decision.confidence = 0.8
        decision.reasoning = "默认决策：继续执行"

        return decision

    def reflect_execution(
        self,
        execution_history: List[NodeExecutionResult],
        context: Dict[str, Any],
    ) -> str:
        """简单反思"""
        total = len(execution_history)
        successful = sum(1 for r in execution_history if r.is_success)
        failed = sum(1 for r in execution_history if r.is_failure)

        avg_confidence = sum(r.confidence for r in execution_history) / total if total > 0 else 0

        return (
            f"执行完成: 共{total}个节点，"
            f"成功{successful}个，失败{failed}个，"
            f"平均置信度{avg_confidence:.2f}"
        )


# ============================================================
# C层：动态链融合器 - 核心
# ============================================================

class DynamicChainFusion:
    """动态链融合器

    协调大模型分析和动态决策
    """

    def __init__(
        self,
        llm_analyzer: Optional[LLMAnalyzerInterface] = None,
        enable_dynamic_replan: bool = False,
        replan_threshold: float = 0.5,
    ):
        """
        Args:
            llm_analyzer: 大模型分析器（可选，默认使用规则分析）
            enable_dynamic_replan: 是否启用动态重规划
            replan_threshold: 重规划阈值（置信度低于此值时触发）
        """
        self.llm_analyzer = llm_analyzer or DefaultLLMAnalyzer()
        self.enable_dynamic_replan = enable_dynamic_replan
        self.replan_threshold = replan_threshold

        # 执行历史
        self.execution_history: List[NodeExecutionResult] = []

        # 决策历史
        self.decision_history: List[ChainFusionDecision] = []

    def reset(self):
        """重置状态"""
        self.execution_history = []
        self.decision_history = []

    def analyze_and_decide(
        self,
        current_result: NodeExecutionResult,
        available_nodes: List[str],
        context: Dict[str, Any],
    ) -> ChainFusionDecision:
        """
        分析结果并做出决策

        Args:
            current_result: 当前节点执行结果
            available_nodes: 可用的下一个节点
            context: 执行上下文

        Returns:
            ChainFusionDecision - 决策
        """
        # 添加到历史
        self.execution_history.append(current_result)

        # 分析结果
        analysis = self.llm_analyzer.analyze_result(
            current_result.node_id,
            current_result,
            context,
        )

        # 决定下一步
        decision = self.llm_analyzer.decide_next_action(
            current_result.node_id,
            analysis,
            available_nodes,
            context,
        )

        # 检查是否需要重规划
        if self.enable_dynamic_replan:
            if current_result.confidence < self.replan_threshold:
                decision.replan_required = True
                decision.replan_reason = (
                    f"置信度 {current_result.confidence:.2f} "
                    f"低于阈值 {self.replan_threshold:.2f}"
                )
                decision.action = "replan"

        # 添加到决策历史
        self.decision_history.append(decision)

        return decision

    def reflect(self, context: Dict[str, Any]) -> str:
        """
        执行反思

        Args:
            context: 执行上下文

        Returns:
            反思结果
        """
        return self.llm_analyzer.reflect_execution(self.execution_history, context)

    def get_execution_summary(self) -> Dict:
        """获取执行摘要"""
        if not self.execution_history:
            return {"total_nodes": 0}

        total = len(self.execution_history)
        successful = sum(1 for r in self.execution_history if r.is_success)
        failed = sum(1 for r in self.execution_history if r.is_failure)
        avg_confidence = sum(r.confidence for r in self.execution_history) / total

        replans = sum(1 for d in self.decision_history if d.replan_required)

        return {
            "total_nodes": total,
            "successful": successful,
            "failed": failed,
            "avg_confidence": avg_confidence,
            "replans_triggered": replans,
            "node_sequence": [r.node_id for r in self.execution_history],
        }


# ============================================================
# C层：动态链融合器 - 集成到执行流程
# ============================================================

class FusionEnabledNodeExecutor:
    """支持动态链融合的节点执行器

    将动态链融合能力集成到节点执行流程中
    """

    def __init__(
        self,
        base_executor: Any,  # NodeExecutorInterface
        fusion: Optional[DynamicChainFusion] = None,
    ):
        """
        Args:
            base_executor: 基础节点执行器
            fusion: 动态链融合器
        """
        self.base_executor = base_executor
        self.fusion = fusion or DynamicChainFusion()

    def execute_with_fusion(
        self,
        node_id: str,
        inputs: Dict[str, Any],
        context: Dict[str, Any],
        available_nodes: List[str],
    ) -> tuple:
        """
        带融合的节点执行

        Returns:
            (execution_status, fusion_decision)
        """
        # 执行节点
        status = self.base_executor.execute_node(node_id, inputs, context)

        # 创建NodeExecutionResult
        from .types import NodeExecutionResult, NodeStatus

        result = NodeExecutionResult(
            node_id=node_id,
            status=NodeStatus.COMPLETED if status.status == "completed" else NodeStatus.FAILED,
            outputs=status.result,
            confidence=status.confidence,
            error=status.error,
        )

        # 融合决策
        decision = self.fusion.analyze_and_decide(result, available_nodes, context)

        return status, decision
