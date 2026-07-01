#!/usr/bin/env python3
"""
C层 - 结果聚合器

位置: experiments/ab-trading/core/c_execution_layer/result_aggregator.py

职责：
1. 聚合多链/多模块的执行结果
2. 计算综合置信度
3. 生成最终决策和建议
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from .types import (
    NodeExecutionResult,
    AggregatedResult,
)


# ============================================================
# C层：结果聚合器 - 核心实现
# ============================================================

class ResultAggregator:
    """结果聚合器

    聚合多链/多模块的执行结果
    """

    def __init__(self):
        """初始化结果聚合器"""
        self.aggregation_mode = "weighted"

    def aggregate(
        self,
        node_results: List[NodeExecutionResult],
        mode: str = "weighted",
    ) -> AggregatedResult:
        """
        聚合结果

        Args:
            node_results: 节点执行结果列表
            mode: 聚合模式
                - weighted: 加权平均（默认）
                - max: 取最大值
                - min: 取最小值
                - voting: 投票制（用于分类）
                - sequential: 顺序覆盖（用于流程）

        Returns:
            AggregatedResult - 聚合结果
        """
        aggregated = AggregatedResult()
        aggregated.mode = mode
        aggregated.node_results = node_results

        if not node_results:
            aggregated.rationale = "没有可聚合的结果"
            return aggregated

        # 根据模式聚合
        if mode == "weighted":
            self._aggregate_weighted(aggregated, node_results)
        elif mode == "max":
            self._aggregate_max(aggregated, node_results)
        elif mode == "min":
            self._aggregate_min(aggregated, node_results)
        elif mode == "voting":
            self._aggregate_voting(aggregated, node_results)
        elif mode == "sequential":
            self._aggregate_sequential(aggregated, node_results)
        else:
            self._aggregate_weighted(aggregated, node_results)

        return aggregated

    def _aggregate_weighted(
        self,
        aggregated: AggregatedResult,
        node_results: List[NodeExecutionResult],
    ):
        """加权平均聚合"""
        successful_results = [r for r in node_results if r.is_success]
        if not successful_results:
            aggregated.rationale = "所有节点执行失败"
            return

        # 计算总权重
        total_weight = sum(r.confidence for r in successful_results)
        if total_weight == 0:
            total_weight = len(successful_results)

        # 加权聚合输出
        aggregated_outputs = {}
        for result in successful_results:
            weight = result.confidence / total_weight
            if result.outputs:
                for key, value in result.outputs.items():
                    if value is not None:
                        if key not in aggregated_outputs:
                            aggregated_outputs[key] = 0
                        if isinstance(value, (int, float)):
                            aggregated_outputs[key] += value * weight
                        else:
                            aggregated_outputs[key] = value

        aggregated.aggregated_output = aggregated_outputs

        # 计算综合置信度
        overall_confidence = sum(
            r.confidence * r.confidence
            for r in successful_results
        ) / sum(r.confidence for r in successful_results) if successful_results else 0

        aggregated.overall_confidence = overall_confidence

        # 置信度分解
        aggregated.confidence_breakdown = {
            r.node_id: r.confidence
            for r in successful_results
        }

        # 生成决策
        self._generate_decision(aggregated, successful_results)

        aggregated.rationale = (
            f"加权聚合 {len(successful_results)} 个成功结果，"
            f"综合置信度 {overall_confidence:.2f}"
        )

    def _aggregate_max(
        self,
        aggregated: AggregatedResult,
        node_results: List[NodeExecutionResult],
    ):
        """最大值聚合"""
        successful_results = [r for r in node_results if r.is_success]
        if not successful_results:
            aggregated.rationale = "所有节点执行失败"
            return

        # 取置信度最高的
        best = max(successful_results, key=lambda r: r.confidence)
        aggregated.aggregated_output = best.outputs
        aggregated.overall_confidence = best.confidence
        aggregated.confidence_breakdown = {best.node_id: best.confidence}
        self._generate_decision(aggregated, successful_results)

        aggregated.rationale = f"选择置信度最高的节点 {best.node_id} ({best.confidence:.2f})"

    def _aggregate_min(
        self,
        aggregated: AggregatedResult,
        node_results: List[NodeExecutionResult],
    ):
        """最小值聚合"""
        successful_results = [r for r in node_results if r.is_success]
        if not successful_results:
            aggregated.rationale = "所有节点执行失败"
            return

        # 取置信度最低但成功的（保守策略）
        best = min(successful_results, key=lambda r: r.confidence)
        aggregated.aggregated_output = best.outputs
        aggregated.overall_confidence = best.confidence
        aggregated.confidence_breakdown = {best.node_id: best.confidence}
        self._generate_decision(aggregated, successful_results)

        aggregated.rationale = f"选择置信度最低的成功节点 {best.node_id} ({best.confidence:.2f})"

    def _aggregate_voting(
        self,
        aggregated: AggregatedResult,
        node_results: List[NodeExecutionResult],
    ):
        """投票制聚合（用于分类问题）"""
        successful_results = [r for r in node_results if r.is_success]
        if not successful_results:
            aggregated.rationale = "所有节点执行失败"
            return

        # 收集所有决策
        votes: Dict[str, float] = {}
        for result in successful_results:
            if result.outputs:
                direction = result.outputs.get("direction")
                if direction:
                    confidence = result.confidence
                    votes[direction] = votes.get(direction, 0) + confidence

        if votes:
            best_direction = max(votes.items(), key=lambda x: x[1])
            aggregated.final_decision = best_direction[0]
            aggregated.aggregated_output = {"direction": best_direction[0], "votes": votes}
            aggregated.overall_confidence = best_direction[1] / sum(votes.values())
        else:
            aggregated.final_decision = "neutral"
            aggregated.aggregated_output = {}

        aggregated.confidence_breakdown = {
            r.node_id: r.confidence
            for r in successful_results
        }

        aggregated.rationale = f"投票结果: {aggregated.final_decision}"

    def _aggregate_sequential(
        self,
        aggregated: AggregatedResult,
        node_results: List[NodeExecutionResult],
    ):
        """顺序覆盖聚合"""
        successful_results = [r for r in node_results if r.is_success]
        if not successful_results:
            aggregated.rationale = "所有节点执行失败"
            return

        # 按顺序覆盖，后面的覆盖前面的
        aggregated_outputs = {}
        total_confidence = 0

        for result in successful_results:
            if result.outputs:
                aggregated_outputs.update(result.outputs)
            total_confidence += result.confidence

        aggregated.aggregated_output = aggregated_outputs
        aggregated.overall_confidence = total_confidence / len(successful_results)
        aggregated.confidence_breakdown = {
            r.node_id: r.confidence
            for r in successful_results
        }
        self._generate_decision(aggregated, successful_results)

        aggregated.rationale = f"顺序覆盖 {len(successful_results)} 个结果"

    def _generate_decision(
        self,
        aggregated: AggregatedResult,
        successful_results: List[NodeExecutionResult],
    ):
        """生成最终决策"""
        if not successful_results:
            aggregated.final_decision = "no_result"
            return

        # 从最高置信度的结果中提取决策
        best = max(successful_results, key=lambda r: r.confidence)
        if best.outputs:
            # 优先使用 direction
            if "direction" in best.outputs:
                aggregated.final_decision = best.outputs["direction"]
            # 其次使用 final_decision
            elif "final_decision" in best.outputs:
                aggregated.final_decision = best.outputs["final_decision"]
            # 使用趋势判断
            elif "trend" in best.outputs:
                aggregated.final_decision = best.outputs["trend"]
            else:
                aggregated.final_decision = "completed"
        else:
            aggregated.final_decision = "completed"


# ============================================================
# C层：结果聚合器 - 便捷函数
# ============================================================

def aggregate_results(
    node_results: List[NodeExecutionResult],
    mode: str = "weighted",
) -> AggregatedResult:
    """便捷函数：聚合结果"""
    aggregator = ResultAggregator()
    return aggregator.aggregate(node_results, mode)
