"""
DreamOS C层 — 图执行器 (GraphExecutor)

C 层主入口，职责:
    1. 接收 A 层构建的 Graph 和 State
    2. 逐节点执行（通过 NodeRunner）
    3. 每步反射决策（通过 Reflector）
    4. 支持条件跳转、前插、提前终止
    5. 自动保存检查点（每节点后 / 反射前 / 关键节点）
    6. 执行完毕后聚合结果（通过 Aggregator）
    7. 输出 ExecutionReport

执行流程:
    Graph.get_entry()
        ↓
    检查点（反射前）
        ↓
    NodeRunner.run(node, state)
        ↓
    检查点（节点后）
        ↓
    Reflector.decide(result, state)
        ↓
    ┌──┴──────────────────────────┐
    CONTINUE  REDO  INSERT  JUMP  TERMINATE
    ↓         ↓     ↓        ↓       ↓
    next_node redo  insert  jump  aggregate
    ↓
    ...循环...
    ↓
    Aggregator.aggregate(state)
    ↓
    ExecutionReport
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any

from dreamos.shared.state import State, NodeResult, NodeStatus
from dreamos.shared.interfaces import Node, Graph
from dreamos.shared.utils import Timer, safe_get

from .types import (
    ReflectAction, ReflectDecision, ExecutionReport, NodeExecutionRecord,
)
from .node_runner import NodeRunner
from .reflector import Reflector
from .aggregator import Aggregator


GATE_NODES = {"A4", "A7", "G1"}


class GraphExecutor:
    """图执行器 — C 层主入口

    用法:
        executor = GraphExecutor()
        report = executor.execute(graph, state)
        print(report.final_action)
        print(report.final_confidence)
        print(report.success_rate)

    带 A 层计划:
        from dreamos.core.arrange import GraphPlanner
        planner = GraphPlanner()
        plan = planner.plan(state)
        graph = planner.build_graph(plan)
        report = executor.execute(graph, state, plan=plan)
    """

    def __init__(self,
                 max_retries: int = 2,
                 enable_reflect: bool = True,
                 enable_early_terminate: bool = True,
                 max_steps: int = 20,
                 timeout_ms: int = 30000,
                 enable_checkpoint: bool = True,
                 graph_store: Optional[Any] = None,
                 registry: Optional[Any] = None):
        self._runner = NodeRunner(
            max_retries=max_retries,
            timeout_ms=timeout_ms,
        )
        self._reflector = Reflector(
            max_retries_per_node=max_retries,
            enable_early_terminate=enable_early_terminate,
        )
        self._aggregator = Aggregator()
        self._enable_reflect = enable_reflect
        self._max_steps = max_steps
        self._enable_checkpoint = enable_checkpoint
        self._graph_store = graph_store
        self._registry = registry

    def execute(self,
                graph: Graph,
                state: State,
                plan: Optional[Any] = None,
                budget: Optional[Dict[str, int]] = None,
                total_budget: int = 0,
                graph_store: Optional[Any] = None) -> ExecutionReport:
        """执行图

        Args:
            graph: A 层构建的执行图
            state: 全局状态
            plan: A 层的执行计划（可选，用于预算分配）
            budget: 节点预算 {node_id: tokens}（可选）
            total_budget: 本周期总预算 tokens
            graph_store: G 层存储实例（用于自动检查点，优先使用）

        Returns:
            ExecutionReport: 执行报告
        """
        timer = Timer("graph_executor")
        report = ExecutionReport()

        store = graph_store or self._graph_store

        budget = budget or {}
        if plan and hasattr(plan, "budget") and plan.budget:
            budget = plan.budget.allocated
            if not total_budget and hasattr(plan.budget, "total"):
                total_budget = plan.budget.total

        current = graph.get_entry()
        if current is None:
            report.termination_reason = "图中无入口节点"
            return report

        all_node_ids = graph.topological_order()
        report.total_nodes = len(all_node_ids)

        executed_ids: List[str] = []
        step = 0
        used_budget = 0

        while current is not None and step < self._max_steps:
            step += 1
            node_id = current.node_id

            if node_id in executed_ids:
                current = graph.get_next(node_id, state)
                continue

            is_gate = node_id in GATE_NODES

            # ── 检查点：门禁节点前（额外强制保存）─────────
            if is_gate and self._enable_checkpoint and store:
                store.checkpoint(state, node_id=node_id,
                                 metadata={"phase": "pre_gate", "step": step,
                                           "is_gate": True})

            # ── 检查点：反射前（节点执行前）─────────
            if self._enable_checkpoint and store:
                store.checkpoint(state, node_id=node_id,
                                 metadata={"phase": "pre_reflect", "step": step})

            # ── 执行节点 ──────────────────────────
            allocated = budget.get(node_id, 0)
            record = self._runner.run(current, state, allocated)
            report.add_record(record)
            executed_ids.append(node_id)
            used_budget += record.tokens_used

            # ── 检查点：节点执行后 ─────────────────
            if self._enable_checkpoint and store:
                store.checkpoint(
                    state,
                    node_id=node_id,
                    metadata={
                        "phase": "post_node",
                        "step": step,
                        "is_gate": is_gate,
                        "tokens_used": record.tokens_used,
                    },
                )

            # ── 检查点：门禁节点后（额外强制保存，供回滚）──
            if is_gate and self._enable_checkpoint and store:
                store.checkpoint(
                    state,
                    node_id=node_id,
                    metadata={"phase": "post_gate", "step": step,
                              "is_gate": True, "status": record.status.value
                              if hasattr(record.status, "value") else str(record.status)},
                )

            # ── 反射决策 ──────────────────────────
            if self._enable_reflect:
                remaining_ratio = None
                if total_budget > 0:
                    remaining_ratio = max(0.0, 1.0 - used_budget / total_budget)

                decision = self._reflector.decide(
                    current_node_id=node_id,
                    result=state.get_result(node_id),
                    state=state,
                    graph=graph,
                    executed_count=report.executed_nodes,
                    max_nodes=report.total_nodes,
                    record=record,
                    budget_remaining_ratio=remaining_ratio,
                    total_budget=total_budget,
                    used_budget=used_budget,
                )

                report.reflect_history.append({
                    "node_id": node_id,
                    **decision.to_dict(),
                })

                action = decision.action
                if action == ReflectAction.EARLY_TERMINATE:
                    report.early_terminated = True
                    report.termination_reason = decision.reason
                    break
                elif action == ReflectAction.JUMP_TO:
                    jump_node = graph.get_node(decision.jump_to) if hasattr(graph, "get_node") else None
                    if jump_node:
                        current = jump_node
                        continue
                elif action == ReflectAction.REDO:
                    if node_id in executed_ids:
                        executed_ids.remove(node_id)
                    continue
                elif action == ReflectAction.INSERT_BEFORE:
                    insert_id = decision.insert_node_id
                    if insert_id:
                        insert_node = None
                        if self._registry and hasattr(self._registry, "get"):
                            insert_node = self._registry.get(insert_id)
                        if insert_node is None and hasattr(graph, "get_node"):
                            insert_node = graph.get_node(insert_id)
                        if insert_node and hasattr(graph, "insert_before"):
                            try:
                                ok = graph.insert_before(node_id, insert_node)
                                if ok:
                                    report.total_nodes += 1
                                    current = insert_node
                                    continue
                            except Exception:
                                pass
                    continue
                elif action == ReflectAction.SKIP:
                    pass

            current = graph.get_next(node_id, state)

        self._aggregator.aggregate(state, executed_ids, report)
        self._aggregator.update_state(state, report)

        with timer:
            pass

        return report
