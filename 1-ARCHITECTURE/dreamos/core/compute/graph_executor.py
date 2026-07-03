"""
DreamOS C层 — 图执行器 (GraphExecutor)

C 层主入口，职责:
    1. 接收 A 层构建的 Graph 和 State
    2. 逐节点执行（通过 NodeRunner）
    3. 每步反射决策（通过 Reflector）
    4. 支持条件跳转和提前终止
    5. 执行完毕后聚合结果（通过 Aggregator）
    6. 输出 ExecutionReport

执行流程:
    Graph.get_entry()
        ↓
    NodeRunner.run(node, state)
        ↓
    Reflector.decide(result, state)
        ↓
    ┌───┴───────────────────┐
    CONTINUE   REDO  INSERT  JUMP  TERMINATE
    ↓          ↓     ↓       ↓     ↓
    next_node  redo  insert  jump  aggregate
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


class GraphExecutor:
    """图执行器 — C 层主入口

    用法:
        executor = GraphExecutor()
        report = executor.execute(graph, state)
        print(report.final_action)       # "LONG"
        print(report.final_confidence)   # 0.72
        print(report.success_rate)       # 0.8

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
                 max_steps: int = 20):
        self._runner = NodeRunner(max_retries=max_retries)
        self._reflector = Reflector(
            max_retries_per_node=max_retries,
            enable_early_terminate=enable_early_terminate,
        )
        self._aggregator = Aggregator()
        self._enable_reflect = enable_reflect
        self._max_steps = max_steps

    def execute(self,
                graph: Graph,
                state: State,
                plan: Optional[Any] = None,
                budget: Optional[Dict[str, int]] = None) -> ExecutionReport:
        """执行图

        Args:
            graph: A 层构建的执行图
            state: 全局状态
            plan: A 层的执行计划（可选，用于预算分配）
            budget: 节点预算 {node_id: tokens}（可选）

        Returns:
            ExecutionReport: 执行报告
        """
        timer = Timer("graph_executor")
        report = ExecutionReport()

        # 从计划中获取预算
        budget = budget or {}
        if plan and hasattr(plan, "budget") and plan.budget:
            budget = plan.budget.allocated

        # 获取入口节点
        current = graph.get_entry()
        if current is None:
            report.termination_reason = "图中无入口节点"
            return report

        # 总节点数
        all_node_ids = graph.topological_order()
        report.total_nodes = len(all_node_ids)

        executed_ids: List[str] = []
        step = 0

        while current is not None and step < self._max_steps:
            step += 1
            node_id = current.node_id

            # 跳过已执行的节点
            if node_id in executed_ids:
                current = graph.get_next(node_id, state)
                continue

            # 执行节点
            allocated_tokens = budget.get(node_id, 0)
            record = self._runner.run(current, state, allocated_tokens)
            report.add_record(record)
            executed_ids.append(node_id)

            # 反射决策
            if self._enable_reflect:
                decision = self._reflector.decide(
                    current_node_id=node_id,
                    result=state.get_result(node_id),
                    state=state,
                    graph=graph,
                    executed_count=report.executed_nodes,
                    max_nodes=report.total_nodes,
                    record=record,
                )

                report.reflect_history.append({
                    "node_id": node_id,
                    **decision.to_dict(),
                })

                # 处理决策
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
                    # 清除已执行标记，重新执行
                    if node_id in executed_ids:
                        executed_ids.remove(node_id)
                    continue
                elif action == ReflectAction.SKIP:
                    # 标记为跳过
                    pass

            # 获取下一个节点
            current = graph.get_next(node_id, state)

        # 聚合结果
        self._aggregator.aggregate(state, executed_ids, report)
        self._aggregator.update_state(state, report)

        with timer:
            pass

        return report
