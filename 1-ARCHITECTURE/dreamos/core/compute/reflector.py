"""
DreamOS C层 — 反射决策器

职责:
    在每个节点执行后进行反射决策:
        - CONTINUE: 正常继续
        - REDO: 重新执行（置信度低但可挽救）
        - INSERT_BEFORE: 插入补充节点（矛盾/缺失上下文）
        - JUMP_TO: 跳转到其他节点（预算不足/当前路径无效）
        - EARLY_TERMINATE: 提前终止（已有足够信息）
        - SKIP: 跳过当前节点

决策规则（文档 §3.4.3 启发式）:
    1. confidence < 0.3 → REDO
    2. 与前序节点矛盾 → INSERT_BEFORE（补充节点）
    3. budget < 20% → JUMP("A9")
    4. confidence > 0.85 + late_stage → EARLY_TERMINATE
    5. 连续 3 个方向一致 + 高置信度 → EARLY_TERMINATE
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
            budget_remaining=0.5,
        )
    """

    CONFIDENCE_HIGH = 0.7
    CONFIDENCE_LOW = 0.3
    CONFIDENCE_TERMINATE = 0.85

    DIRECTION_CONSISTENCY_THRESHOLD = 3

    BUDGET_CRITICAL = 0.2
    BUDGET_WARNING = 0.4

    CONFLICT_NODE_MAP = {
        "A2": "A0",
        "A3": "A0",
        "A4": "A0",
        "C2": "C1",
        "F2": "F1",
    }

    def __init__(self,
                 max_retries_per_node: int = 2,
                 enable_early_terminate: bool = True,
                 enable_budget_check: bool = True,
                 enable_conflict_check: bool = True):
        self._max_retries = max_retries_per_node
        self._enable_early_terminate = enable_early_terminate
        self._enable_budget_check = enable_budget_check
        self._enable_conflict_check = enable_conflict_check

    def decide(self,
               current_node_id: str,
               result: Optional[NodeResult],
               state: State,
               graph: Graph,
               executed_count: int,
               max_nodes: int,
               record: Optional[NodeExecutionRecord] = None,
               budget_remaining_ratio: Optional[float] = None,
               total_budget: int = 0,
               used_budget: int = 0) -> ReflectDecision:
        """进行反射决策

        Args:
            current_node_id: 当前执行的节点 ID
            result: 当前节点的执行结果
            state: 全局状态
            graph: 执行图
            executed_count: 已执行节点数
            max_nodes: 计划执行的总节点数
            record: 执行记录
            budget_remaining_ratio: 剩余预算比例 (0.0 ~ 1.0)
            total_budget: 总预算 tokens
            used_budget: 已用 tokens

        Returns:
            ReflectDecision: 决策结果
        """
        if result is None:
            return ReflectDecision(
                action=ReflectAction.SKIP,
                reason=f"节点 {current_node_id} 无结果",
            )

        if result.status == NodeStatus.FAILED:
            return self._decide_on_failure(current_node_id, result, record)

        if result.status == NodeStatus.DEGRADED:
            return ReflectDecision(
                action=ReflectAction.CONTINUE,
                reason=f"节点 {current_node_id} 降级执行，置信度={result.confidence:.2f}",
                confidence=result.confidence,
                suggestions=["检查数据源是否正常"],
            )

        # 1. 预算检查（最高优先级，预算不足时直接跳转收尾）
        if self._enable_budget_check and budget_remaining_ratio is not None:
            budget_decision = self._check_budget(
                current_node_id, result, budget_remaining_ratio, graph
            )
            if budget_decision:
                return budget_decision

        # 2. 低置信度 → REDO
        if result.confidence < self.CONFIDENCE_LOW:
            retries = record.retries if record else 0
            if retries < self._max_retries:
                return ReflectDecision(
                    action=ReflectAction.REDO,
                    reason=(
                        f"节点 {current_node_id} 置信度过低 ({result.confidence:.2f}"
                        f" < {self.CONFIDENCE_LOW})，尝试重做获取更可靠结果"
                    ),
                    confidence=result.confidence,
                )
            # 重试耗尽 → 继续往下走，靠后续节点补强

        # 3. 矛盾检测 → INSERT_BEFORE
        if self._enable_conflict_check:
            conflict_decision = self._check_conflict(
                current_node_id, result, state, graph
            )
            if conflict_decision:
                return conflict_decision

        # 4. 提前终止检查
        if self._enable_early_terminate:
            early = self._check_early_terminate(current_node_id, result, state, executed_count)
            if early:
                return early

        # 5. 正常继续
        return ReflectDecision(
            action=ReflectAction.CONTINUE,
            reason=f"节点 {current_node_id} 正常完成，置信度={result.confidence:.2f}",
            confidence=result.confidence,
        )

    # ── 内部方法 ──────────────────────────

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

        return ReflectDecision(
            action=ReflectAction.SKIP,
            reason=f"节点 {node_id} 重试耗尽，跳过",
            confidence=0.0,
            suggestions=[f"检查 {node_id} 的依赖数据是否正常"],
        )

    def _check_budget(self, node_id: str, result: NodeResult,
                      remaining_ratio: float, graph: Graph) -> Optional[ReflectDecision]:
        """预算检查：剩余预算不足时跳转到收尾节点

        文档 §3.4.3 启发式规则: budget_remaining < 0.2 → JUMP("A9")
        """
        if remaining_ratio <= self.BUDGET_CRITICAL:
            exit_node = None
            for n in graph.all_nodes():
                if n.node_id in ("A9", "G2", "C5"):
                    exit_node = n.node_id
                    break

            if exit_node:
                return ReflectDecision(
                    action=ReflectAction.JUMP_TO,
                    reason=(
                        f"预算不足（剩余 {remaining_ratio:.0%} < "
                        f"{self.BUDGET_CRITICAL:.0%}），跳转到 {exit_node} 收尾"
                    ),
                    confidence=result.confidence,
                    jump_to=exit_node,
                )

        return None

    def _check_conflict(self, node_id: str, result: NodeResult,
                        state: State, graph: Graph) -> Optional[ReflectDecision]:
        """矛盾检测：与前序节点方向冲突时插入补充节点

        文档 §3.4.3: 当前节点结果与前序节点矛盾 → INSERT（补充节点）
        策略: 从 CONFLICT_NODE_MAP 查找推荐的补充节点
        """
        if not result.direction or result.direction in ("NEUTRAL", "HOLD"):
            return None

        results = state.results if state.results else {}
        prev_results = [r for r in results.values()
                        if r.node_id != node_id and r.direction]

        if not prev_results:
            return None

        conflicts = [r for r in prev_results
                     if r.direction != result.direction
                     and r.direction not in ("NEUTRAL", "HOLD")
                     and r.confidence > self.CONFIDENCE_HIGH]

        if not conflicts:
            return None

        insert_node_id = self.CONFLICT_NODE_MAP.get(node_id)
        if insert_node_id and insert_node_id not in results:
            target_node = graph.get_node(insert_node_id) if hasattr(graph, "get_node") else None
            if target_node:
                return ReflectDecision(
                    action=ReflectAction.INSERT_BEFORE,
                    reason=(
                        f"节点 {node_id}({result.direction}) 与前序"
                        f"({conflicts[0].node_id}/{conflicts[0].direction})矛盾，"
                        f"插入 {insert_node_id} 做矛盾分析"
                    ),
                    confidence=result.confidence,
                    insert_node_id=insert_node_id,
                )

        return None

    def _check_early_terminate(self, current_node_id: str, result: NodeResult,
                               state: State, executed_count: int) -> Optional[ReflectDecision]:
        """检查是否可以提前终止"""
        if result.confidence >= self.CONFIDENCE_TERMINATE and executed_count >= 3:
            return ReflectDecision(
                action=ReflectAction.EARLY_TERMINATE,
                reason=f"置信度极高 ({result.confidence:.2f})，已有足够信息",
                confidence=result.confidence,
            )

        direction = result.direction
        if direction and direction != "NEUTRAL" and direction != "HOLD":
            results = state.results if state.results else {}
            recent = list(results.values())[-self.DIRECTION_CONSISTENCY_THRESHOLD:]
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
