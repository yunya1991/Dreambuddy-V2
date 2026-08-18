"""
DreamOS A层 — Arrange 编排层

职责:
    - 根据意图编排执行图 (Graph)
    - 节点选择 (Node Selection)
    - 预算分配 (Budget Allocation)
    - 四维过滤: Token / 知识库 / 历史 / 标的

子模块:
    - types.py            类型定义 (ExecutionPlan / NodeMeta / BudgetAllocation / ChainSpec)
    - execution_graph.py  执行图实现 (SequentialGraph / ConditionalGraph)
    - node_selector.py     节点选择器
    - budget_allocator.py 预算分配器
    - graph_planner.py     图规划器主入口

快速上手:
    from dreamos.core.arrange import GraphPlanner

    planner = GraphPlanner()
    plan = planner.plan_from_intent(
        recommended_chain="A",
        base_chain=["A0", "A1", "A2"],
        confidence=0.72,
    )
    graph = planner.build_graph(plan)
    # graph 可交给 C 层执行
"""

from dreamos.shared.state import State
from dreamos.shared.interfaces import Graph

from .types import (
    ExecutionPlan, NodeMeta, BudgetAllocation, ChainSpec, STANDARD_CHAINS,
)
from .execution_graph import SequentialGraph, ConditionalGraph
from .node_selector import NodeSelector
from .budget_allocator import BudgetAllocator
from .graph_planner import GraphPlanner

__all__ = [
    # types
    "ExecutionPlan", "NodeMeta", "BudgetAllocation", "ChainSpec", "STANDARD_CHAINS",
    # graph
    "SequentialGraph", "ConditionalGraph",
    # components
    "NodeSelector", "BudgetAllocator", "GraphPlanner",
]
