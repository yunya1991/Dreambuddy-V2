"""
DreamOS C层 — Compute 执行层

职责:
    - 执行图中的节点
    - 反射决策 (CONTINUE / REDO / INSERT_BEFORE / JUMP_TO / EARLY_TERMINATE)
    - 结果聚合
    - 失败重试 + 降级

子模块:
    - types.py           类型定义 (ReflectAction / ReflectDecision / ExecutionReport)
    - node_runner.py     节点执行器
    - reflector.py       反射决策器
    - aggregator.py      结果聚合器
    - graph_executor.py  图执行器主入口

快速上手:
    from dreamos.core.compute import GraphExecutor

    executor = GraphExecutor()
    report = executor.execute(graph, state)
    print(report.final_action, report.final_confidence)
"""

from dreamos.shared.state import State, NodeResult
from dreamos.shared.interfaces import Graph, Node

from .types import (
    ReflectAction, ReflectDecision, ExecutionReport, NodeExecutionRecord,
)
from .node_runner import NodeRunner
from .reflector import Reflector
from .aggregator import Aggregator
from .graph_executor import GraphExecutor

__all__ = [
    # types
    "ReflectAction", "ReflectDecision", "ExecutionReport", "NodeExecutionRecord",
    # components
    "NodeRunner", "Reflector", "Aggregator", "GraphExecutor",
]
