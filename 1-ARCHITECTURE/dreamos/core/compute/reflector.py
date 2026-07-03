"""
DreamOS C层 — 反射决策器

职责:
    在每个节点执行后进行反射决策:
        - CONTINUE: 正常继续
        - REDO: 重新执行（置信度低但可挽救）
        - INSERT_BEFORE: 插入补充节点（缺少上下文）
        - JUMP_TO: 跳转到其他节点（当前路径无效）
        - EARLY_TERMINATE: 提前终止（已有足够信息）
        - SKIP: 跳过当前节点

决策规则:
    1. 节点成功 + 置信度 >= 0.5 → CONTINUE
    2. 节点成功 + 置信度 < 0.3 → INSERT_BEFORE（可能缺少上下文）
    3. 节点失败 + 可重试 + 未达上限 → REDO
    4. 节点失败 + 不可重试 → SKIP（降级后继续）
    5. 多个节点方向一致 + 置信度高 → EARLY_TERMINATE
    6. 节点置信度极低 → EARLY_TERMINATE
"""

from __future__ import annotations

from typing import List, Optional, Dict, Any

from dreamos.shared.state import State, NodeResult, NodeStatus
from dreamos.shared.interfaces import Node, Graph

from .types import ReflectAction, ReflectDecision, NodeExecutionRecord


class Reflector:
    """反射决策器

    用法:
        reflector = Reflector()
        decision = reflector.decide(
            current_node_id="A1",
            result=state.get_result("A1"),
            state=state,
            graph=graph,
            executed_count=2,
            max_nodes=5,
        )
        if decision.should_continue:
            ...
    """

    # 置信度阈值
    CONFIDENCE_HIGH = 0.7          # 高置信度
    CONFIDENCE_LOW = 0.3           # 低置信度
    CONFIDENCE_TERMINATE = 0.85    # 足够高可提前终止

    # 方向一致性终止阈值
    DIRECTION_CONSISTENCY_THRESHOLD = 3  # 连续 3 个方向一致

    def __init__(self,
                 max_retries_per_node: int = 2,
                 enable_early_terminate: bool = True):
        self._max_retries = max_retries_per_node
        self._enable_early_terminate = enable_early_terminate

    def decide(self,
               current_node_id: str,
               result: Optional[NodeResult],
               state: State,
               graph: Graph,
               executed_count: int,
               max_nodes: int,
               record: Optional[NodeExecutionRecord] = None) -> ReflectDecision:
        """进行反射决策

        Args:
            current_node_id: 当前执行的节点 ID
            result: 当前节点的执行结果
            state: 全局状态
            graph: 执行图
            executed_count: 已执行节点数
            max_nodes: 计划执行的总节点数
            record: 执行记录

        Returns:
            ReflectDecision: 决策结果
        """
        # 没有结果 → 跳过
        if result is None:
            return ReflectDecision(
                action=ReflectAction.SKIP,
                reason=f"节点 {current_node_id} 无结果",
            )

        # 失败处理
        if result.status == NodeStatus.FAILED:
            return self._decide_on_failure(current_node_id, result, record)

        # 降级处理
        if result.status == NodeStatus.DEGRADED:
            return ReflectDecision(
                action=ReflectAction.CONTINUE,
                reason=f"节点 {current_node_id} 降级执行，置信度={result.confidence:.2f}",
                confidence=result.confidence,
                suggestions=["检查数据源是否正常"],
            )

        # 成功但置信度极低
        if result.confidence < self.CONFIDENCE_LOW:
            # 可能缺少上下文 → 插入补充节点
            next_node = graph.get_next(current_node_id, state)
            if next_node and executed_count < max_nodes:
                return ReflectDecision(
                    action=ReflectAction.CONTINUE,
                    reason=f"节点 {current_node_id} 置信度低 ({result.confidence:.2f})，继续执行获取更多信息",
                    confidence=result.confidence,
                )
            return ReflectDecision(
                action=ReflectAction.EARLY_TERMINATE,
                reason=f"节点 {current_node_id} 置信度极低 ({result.confidence:.2f})，无法继续",
                confidence=result.confidence,
            )

        # 检查是否可以提前终止
        if self._enable_early_terminate:
            early = self._check_early_terminate(current_node_id, result, state, executed_count)
            if early:
                return early

        # 正常继续
        return ReflectDecision(
            action=ReflectAction.CONTINUE,
            reason=f"节点 {current_node_id} 正常完成，置信度={result.confidence:.2f}",
            confidence=result.confidence,
        )

    # ── 内部方法 ───────────────────────────────────────

    def _decide_on_failure(self, node_id: str, result: NodeResult,
                           record: Optional[NodeExecutionRecord]) -> ReflectDecision:
        """失败时的决策"""
        retries = record.retries if record else 0

        if retries < self._max_retries:
            return ReflectDecision(
                action=ReflectAction.REDO,
                reason=f"节点 {node_id} 失败（{result.error}），重试 {retries + 1}/{self._max_retries}",
                confidence=0.0,
            )

        # 重试耗尽 → 跳过
        return ReflectDecision(
            action=ReflectAction.SKIP,
            reason=f"节点 {node_id} 重试耗尽，跳过",
            confidence=0.0,
            suggestions=[f"检查 {node_id} 的依赖数据是否正常"],
        )

    def _check_early_terminate(self, current_node_id: str, result: NodeResult,
                               state: State, executed_count: int) -> Optional[ReflectDecision]:
        """检查是否可以提前终止"""
        # 置信度极高
        if result.confidence >= self.CONFIDENCE_TERMINATE and executed_count >= 2:
            return ReflectDecision(
                action=ReflectAction.EARLY_TERMINATE,
                reason=f"置信度极高 ({result.confidence:.2f})，已有足够信息",
                confidence=result.confidence,
            )

        # 方向一致性检查
        direction = result.direction
        if direction and direction != "NEUTRAL":
            recent = list(state.results.values())[-self.DIRECTION_CONSISTENCY_THRESHOLD:]
            consistent = [r for r in recent
                          if r.direction == direction and r.confidence > self.CONFIDENCE_HIGH]
            if len(consistent) >= self.DIRECTION_CONSISTENCY_THRESHOLD:
                avg_conf = sum(r.confidence for r in consistent) / len(consistent)
                return ReflectDecision(
                    action=ReflectAction.EARLY_TERMINATE,
                    reason=f"连续 {len(consistent)} 个节点方向一致 ({direction})，平均置信度={avg_conf:.2f}",
                    confidence=avg_conf,
                )

        return None
