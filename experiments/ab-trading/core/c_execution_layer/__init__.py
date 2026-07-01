#!/usr/bin/env python3
"""
C层 - 执行层

位置: experiments/ab-trading/core/c_execution_layer/

架构说明:
- S层: 意图识别 → ExecutionBlueprint
- A层: 图编排引擎 → 编排节点执行顺序/并行/条件
- C层: 执行层 → 具体执行节点 + AI大模型动态链融合

C层组件：
1. node_executor - 节点执行器（对接适配器框架）
2. result_aggregator - 结果聚合器（多链/多模块结果融合）
3. llm_result_analyzer - LLM结果分析器
4. dynamic_decision_maker - 动态决策器
5. dynamic_replanner - 动态重规划器
6. execution_reflector - 执行反思进化器
7. fusion_orchestrator - 融合编排器

C层特色：
- AI大模型驱动的动态链融合
- 支持动态重规划
- 具备执行反思进化能力
"""

from .types import (
    ExecutionContext,
    NodeStatus,
    NodeExecutionResult,
    ChainFusionDecision,
    AggregatedResult,
)

from .node_executor import (
    NodeExecutor,
    SimpleNodeExecutor,
)

from .result_aggregator import (
    ResultAggregator,
    aggregate_results,
)

from .llm_result_analyzer import (
    LLMResultAnalyzer,
    ResultAnalysis,
)

from .dynamic_decision_maker import (
    DynamicDecisionMaker,
)

from .dynamic_replanner import (
    DynamicReplanner,
    ReplanningResult,
)

from .execution_reflector import (
    ExecutionReflector,
    ExecutionReflection,
    ReflectionInsight,
    MemoryStore,
)

from .fusion_orchestrator import (
    FusionOrchestrator,
)

__all__ = [
    # 类型
    "ExecutionContext",
    "NodeStatus",
    "NodeExecutionResult",
    "ChainFusionDecision",
    "AggregatedResult",
    # 执行器
    "NodeExecutor",
    "SimpleNodeExecutor",
    # 聚合器
    "ResultAggregator",
    "aggregate_results",
    # LLM分析
    "LLMResultAnalyzer",
    "ResultAnalysis",
    # 动态决策
    "DynamicDecisionMaker",
    # 动态重规划
    "DynamicReplanner",
    "ReplanningResult",
    # 执行反思
    "ExecutionReflector",
    "ExecutionReflection",
    "ReflectionInsight",
    "MemoryStore",
    # 融合编排
    "FusionOrchestrator",
]
