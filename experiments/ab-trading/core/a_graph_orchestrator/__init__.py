#!/usr/bin/env python3
"""
A层 - 图编排引擎

位置: experiments/ab-trading/core/a_graph_orchestrator/

架构说明:
- S层: 意图识别 → ExecutionBlueprint
- A层: 图编排引擎 → 编排节点执行顺序/并行/条件
- C层: 执行层 → 具体执行节点

模块:
- types: 图执行结果、执行策略
- graph_orchestrator: 图编排引擎核心

使用示例:
```python
from core.a_graph_orchestrator import GraphOrchestrator, ExecutionStrategy
from core.shared.interfaces import NodeExecutorInterface

# 实现节点执行器
class MyNodeExecutor(NodeExecutorInterface):
    def execute_node(self, node_id, inputs, context):
        # 调用具体的节点执行逻辑
        ...

# 创建编排器
executor = MyNodeExecutor()
orchestrator = GraphOrchestrator(executor)

# 执行蓝图
result = orchestrator.execute(blueprint, initial_inputs)
```
"""

from .types import GraphExecutionResult
from ..shared.interfaces import (
    NodeExecutionStatus,
    ExecutionStrategy,
)
from .graph_orchestrator import GraphOrchestrator

__all__ = [
    # 类型
    "GraphExecutionResult",
    "NodeExecutionStatus",
    "ExecutionStrategy",
    # 核心
    "GraphOrchestrator",
]
