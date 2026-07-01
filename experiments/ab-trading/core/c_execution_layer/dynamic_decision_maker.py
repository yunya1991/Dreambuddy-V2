#!/usr/bin/env python3
"""
C层 - 动态决策器

位置: experiments/ab-trading/core/c_execution_layer/dynamic_decision_maker.py

职责：
1. 基于LLM分析结果决定下一步行动
2. 支持决策类型：continue / skip / retry / redirect / replan
3. 给出决策理由和置信度
4. 支持规则降级

决策类型说明：
- continue: 继续执行下一个节点
- skip: 跳过当前节点的后续处理（节点已完成，但结果不重要）
- retry: 重试当前节点（可调整参数）
- redirect: 跳转到指定节点
- replan: 触发重新规划整个蓝图
"""

import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from .types import NodeExecutionResult, ChainFusionDecision
from .llm_result_analyzer import ResultAnalysis


# ============================================================
# 动态决策器
# ============================================================

class DynamicDecisionMaker:
    """动态决策器

    基于分析结果决定下一步行动
    """

    SYSTEM_PROMPT = """你是专业的交易系统执行决策器。你的任务是根据节点执行结果的分析，
决定下一步应该做什么。

可选行动：
1. continue - 继续执行下一个节点（结果可接受，按计划继续）
2. skip - 跳过该节点的影响（节点完成了但结果没用，不影响后续）
3. retry - 重试当前节点（结果质量差，调整参数重跑）
4. redirect - 跳转到指定节点（需要走另一条路径）
5. replan - 触发重新规划（当前路径完全不对，需要重新设计）

请严格按照以下JSON格式输出（不要输出任何其他内容）：
{
  "action": "continue",
  "next_node_id": "next_node",
  "retry_params": null,
  "redirect_target": null,
  "replan_required": false,
  "replan_reason": null,
  "confidence": 0.9,
  "reasoning": "决策理由"
}

决策原则：
- 质量分 > 0.7 且无严重问题 → continue
- 质量分 0.5-0.7 且有可修复问题 → retry
- 质量分 < 0.3 或有致命矛盾 → replan
- 节点与目标无关 → skip
- 需要完全不同的路径 → redirect
"""

    def __init__(
        self,
        purpose: str = "chain_fusion_decision",
        max_tokens: int = 300,
        use_llm: bool = True,
        quality_threshold: float = 0.6,
        replan_threshold: float = 0.3,
    ):
        """
        Args:
            purpose: LLM调用用途
            max_tokens: 最大token数
            use_llm: 是否使用LLM
            quality_threshold: 质量阈值（低于则考虑重试）
            replan_threshold: 重规划阈值（低于则考虑重规划）
        """
        self.purpose = purpose
        self.max_tokens = max_tokens
        self.use_llm = use_llm
        self.quality_threshold = quality_threshold
        self.replan_threshold = replan_threshold

    def decide(
        self,
        node_result: NodeExecutionResult,
        analysis: ResultAnalysis,
        available_nodes: List[str],
        context: Optional[Dict] = None,
    ) -> ChainFusionDecision:
        """
        做出决策

        Args:
            node_result: 节点执行结果
            analysis: 结果分析
            available_nodes: 可用的后续节点列表
            context: 执行上下文

        Returns:
            ChainFusionDecision - 决策
        """
        if self.use_llm:
            try:
                decision = self._decide_with_llm(
                    node_result, analysis, available_nodes, context
                )
            except Exception as e:
                decision = self._decide_with_rules(
                    node_result, analysis, available_nodes
                )
                decision.reasoning = f"LLM决策失败，使用规则决策: {e}"
        else:
            decision = self._decide_with_rules(
                node_result, analysis, available_nodes
            )

        return decision

    def _decide_with_llm(
        self,
        node_result: NodeExecutionResult,
        analysis: ResultAnalysis,
        available_nodes: List[str],
        context: Optional[Dict],
    ) -> ChainFusionDecision:
        """使用LLM决策"""
        try:
            from ..llm_client import llm_chat
        except ImportError:
            return self._decide_with_rules(node_result, analysis, available_nodes)

        # 构建提示词
        prompt = self._build_decision_prompt(node_result, analysis, available_nodes, context)

        # 调用LLM
        llm_output = llm_chat(
            prompt=prompt,
            system=self.SYSTEM_PROMPT,
            max_tokens=self.max_tokens,
            purpose=self.purpose,
        )

        if not llm_output:
            return self._decide_with_rules(node_result, analysis, available_nodes)

        # 解析决策
        decision = self._parse_decision(llm_output, node_result.node_id)
        decision.analysis_result = analysis.summary

        return decision

    def _build_decision_prompt(
        self,
        node_result: NodeExecutionResult,
        analysis: ResultAnalysis,
        available_nodes: List[str],
        context: Optional[Dict],
    ) -> str:
        """构建决策提示词"""
        parts = []

        parts.append("## 当前节点")
        parts.append(f"- 节点ID: {node_result.node_id}")
        parts.append(f"- 置信度: {node_result.confidence:.2f}")
        parts.append("")

        parts.append("## 结果分析")
        parts.append(f"- 质量分: {analysis.quality_score:.2f}")
        parts.append(f"- 完整性: {analysis.completeness:.2f}")
        parts.append(f"- 一致性: {analysis.consistency:.2f}")
        parts.append(f"- 相关性: {analysis.relevance:.2f}")
        parts.append(f"- 是否可接受: {analysis.is_acceptable}")
        parts.append("")

        if analysis.issues:
            parts.append("## 发现的问题")
            for issue in analysis.issues:
                parts.append(f"- {issue}")
            parts.append("")

        if analysis.missing_info:
            parts.append("## 缺失信息")
            for info in analysis.missing_info:
                parts.append(f"- {info}")
            parts.append("")

        parts.append("## 可用节点")
        parts.append(f"后续节点列表: {available_nodes}")
        parts.append("")

        parts.append("分析摘要: " + analysis.summary)
        parts.append("")
        parts.append("请根据以上信息，决定下一步行动。")

        return "\n".join(parts)

    def _parse_decision(self, llm_output: str, node_id: str) -> ChainFusionDecision:
        """解析LLM决策输出"""
        from .types import ChainFusionDecision as Decision

        decision = Decision()
        decision.node_id = node_id

        try:
            json_str = llm_output
            start = llm_output.find("{")
            end = llm_output.rfind("}")
            if start >= 0 and end >= 0:
                json_str = llm_output[start:end + 1]

            data = json.loads(json_str)

            decision.action = data.get("action", "continue")
            decision.next_node_id = data.get("next_node_id")
            decision.retry_params = data.get("retry_params")
            decision.redirect_target = data.get("redirect_target")
            decision.replan_required = bool(data.get("replan_required", False))
            decision.replan_reason = data.get("replan_reason")
            decision.confidence = float(data.get("confidence", 0.7))
            decision.reasoning = str(data.get("reasoning", ""))

        except Exception as e:
            decision.action = "continue"
            decision.confidence = 0.5
            decision.reasoning = f"决策解析失败，默认继续: {e}"

        return decision

    def _decide_with_rules(
        self,
        node_result: NodeExecutionResult,
        analysis: ResultAnalysis,
        available_nodes: List[str],
    ) -> ChainFusionDecision:
        """基于规则的决策（降级用）"""
        from .types import ChainFusionDecision as Decision

        decision = Decision()
        decision.node_id = node_result.node_id
        decision.analysis_result = analysis.summary

        # 节点失败 → 重规划
        if not node_result.is_success:
            decision.action = "replan"
            decision.replan_required = True
            decision.replan_reason = f"节点执行失败: {node_result.error}"
            decision.confidence = 0.8
            decision.reasoning = "节点失败，需要重新规划"
            return decision

        # 质量分 < 重规划阈值 → 重规划
        if analysis.quality_score < self.replan_threshold:
            decision.action = "replan"
            decision.replan_required = True
            decision.replan_reason = f"结果质量过低({analysis.quality_score:.2f})"
            decision.confidence = 0.7
            decision.reasoning = "结果质量严重不达标，需要重新规划"
            return decision

        # 质量分 < 质量阈值 → 重试
        if analysis.quality_score < self.quality_threshold:
            decision.action = "retry"
            decision.retry_params = {
                "increase_depth": True,
                "add_missing_info": analysis.missing_info,
            }
            decision.confidence = 0.7
            decision.reasoning = "结果质量不足，重试并增加深度"
            return decision

        # 有严重矛盾 → 重试
        if analysis.contradictions:
            decision.action = "retry"
            decision.retry_params = {"resolve_contradictions": True}
            decision.confidence = 0.6
            decision.reasoning = "存在矛盾，需要重新分析确认"
            return decision

        # 正常 → 继续
        decision.action = "continue"
        if available_nodes:
            current_index = (
                available_nodes.index(node_result.node_id)
                if node_result.node_id in available_nodes
                else -1
            )
            if current_index < len(available_nodes) - 1:
                decision.next_node_id = available_nodes[current_index + 1]

        decision.confidence = 0.8
        decision.reasoning = "结果质量达标，继续执行"

        return decision
