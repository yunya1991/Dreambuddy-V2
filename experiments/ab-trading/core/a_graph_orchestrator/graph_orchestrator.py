#!/usr/bin/env python3
"""
A层 - 图编排引擎

位置: experiments/ab-trading/core/a_graph_orchestrator/graph_orchestrator.py

架构说明:
- S层: 意图识别 → ExecutionBlueprint
- A层: 图编排引擎 → 编排节点执行顺序/并行/条件
- C层: 执行层 → 具体执行节点

A层职责：
1. 接收 ExecutionBlueprint，按拓扑序编排节点执行
2. 支持三种执行模式：sequential / parallel / hybrid
3. 管理节点依赖关系（DAG执行）
4. 调用 C层执行器 执行节点
5. 处理执行结果和错误
"""

import time
from typing import Dict, List, Optional, Any, Callable, Set
from dataclasses import dataclass, field

from .types import GraphExecutionResult
from ..shared.interfaces import (
    NodeExecutorInterface,
    NodeExecutionStatus,
    ExecutionStrategy,
)


# ============================================================
# A层：图编排引擎 - 核心编排器
# ============================================================

class GraphOrchestrator:
    """图编排引擎（A层核心）

    基于 ExecutionBlueprint 编排和执行节点图

    使用方式：
    1. 传入 ExecutionBlueprint 和 C层执行器
    2. 调用 execute() 开始执行
    3. 获取 GraphExecutionResult
    """

    def __init__(
        self,
        node_executor: NodeExecutorInterface,
        strategy: Optional[ExecutionStrategy] = None,
    ):
        """
        初始化图编排引擎

        Args:
            node_executor: C层节点执行器
            strategy: 执行策略配置
        """
        self.node_executor = node_executor
        self.strategy = strategy or ExecutionStrategy()

        # 执行状态
        self._running: bool = False
        self._cancel_requested: bool = False

        # 进度回调
        self._progress_callback: Optional[Callable] = None

    def set_progress_callback(self, callback: Callable[[str, NodeExecutionStatus], None]):
        """设置进度回调"""
        self._progress_callback = callback

    def cancel(self):
        """请求取消执行"""
        self._cancel_requested = True

    def execute(
        self,
        blueprint: "ExecutionBlueprint",  # type: ignore
        initial_inputs: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> GraphExecutionResult:
        """
        执行图编排

        Args:
            blueprint: 执行蓝图（从S层来）
            initial_inputs: 初始输入参数
            context: 执行上下文

        Returns:
            GraphExecutionResult - 图执行结果
        """
        result = GraphExecutionResult()
        result.blueprint_id = blueprint.blueprint_id
        result.objective_id = blueprint.objective_id
        result.execution_mode = blueprint.execution_mode

        # 初始化输入上下文
        inputs = initial_inputs or {}
        ctx = context or {}

        # 添加蓝图信息到上下文
        ctx["blueprint_id"] = blueprint.blueprint_id
        ctx["objective_id"] = blueprint.objective_id
        ctx["okr_mode"] = blueprint.okr_mode
        ctx["complexity"] = blueprint.complexity

        # 构建节点输入映射（存储每个节点的输入）
        node_inputs: Dict[str, Dict[str, Any]] = {}

        # 初始化所有节点状态
        for node_id in blueprint.node_sequence:
            status = NodeExecutionStatus(node_id=node_id)
            result.add_node_status(status)
            node_inputs[node_id] = {}

        result.update_statistics()
        result.start_time = time.time()
        result.status = "running"

        try:
            # 根据执行模式执行
            if blueprint.execution_mode == "sequential":
                self._execute_sequential(
                    blueprint, result, inputs, ctx, node_inputs
                )
            elif blueprint.execution_mode == "parallel":
                self._execute_parallel(
                    blueprint, result, inputs, ctx, node_inputs
                )
            elif blueprint.execution_mode == "hybrid":
                self._execute_hybrid(
                    blueprint, result, inputs, ctx, node_inputs
                )
            else:
                # 默认顺序执行
                self._execute_sequential(
                    blueprint, result, inputs, ctx, node_inputs
                )

            # 更新最终状态
            result.end_time = time.time()
            result.update_statistics()

            # 判断整体状态
            if result.failed_nodes == 0:
                result.status = "completed"
            elif result.completed_nodes > 0:
                result.status = "partial"
            else:
                result.status = "failed"

        except Exception as e:
            result.status = "failed"
            result.error = str(e)
            result.end_time = time.time()

        return result

    def _execute_node(
        self,
        node_id: str,
        inputs: Dict[str, Any],
        context: Dict[str, Any],
        result: GraphExecutionResult,
    ) -> NodeExecutionStatus:
        """执行单个节点"""
        status = result.get_node_status(node_id)
        if status is None:
            status = NodeExecutionStatus(node_id=node_id)
            result.add_node_status(status)

        status.status = "running"
        status.start_time = time.time()

        # 调用进度回调
        if self._progress_callback:
            self._progress_callback("running", status)

        try:
            # 调用C层执行器
            status = self.node_executor.execute_node(node_id, inputs, context)

            # 更新状态
            result.node_statuses[node_id] = status

            if status.status == "completed":
                if self._progress_callback:
                    self._progress_callback("completed", status)
            else:
                if self._progress_callback:
                    self._progress_callback("failed", status)

        except Exception as e:
            status.status = "failed"
            status.error = str(e)
            status.end_time = time.time()
            if self._progress_callback:
                self._progress_callback("failed", status)

        return status

    def _execute_sequential(
        self,
        blueprint: "ExecutionBlueprint",  # type: ignore
        result: GraphExecutionResult,
        initial_inputs: Dict[str, Any],
        context: Dict[str, Any],
        node_inputs: Dict[str, Dict[str, Any]],
    ):
        """顺序执行"""
        result.execution_mode = "sequential"

        # 存储前一个节点的输出
        previous_output: Optional[Dict] = initial_inputs

        for node_id in blueprint.node_sequence:
            if self._cancel_requested:
                self._skip_remaining_nodes(blueprint, result, node_id)
                break

            # 获取节点依赖的前置输出
            deps = blueprint.dependencies.get(node_id, [])
            if deps and previous_output:
                node_inputs[node_id] = {
                    "previous_output": previous_output,
                    "all_outputs": result.get_completed_results(),
                }
            elif previous_output:
                node_inputs[node_id] = {"previous_output": previous_output}
            else:
                node_inputs[node_id] = {}

            # 执行节点
            status = self._execute_node(node_id, node_inputs[node_id], context, result)

            # 如果节点失败，根据策略决定是否继续
            if status.status == "failed":
                if self.strategy.stop_on_first_failure:
                    self._skip_remaining_nodes(blueprint, result, node_id)
                    break
                # 继续执行下一个节点

            # 保存输出供下一个节点使用
            if status.result is not None:
                previous_output = status.result

    def _execute_parallel(
        self,
        blueprint: "ExecutionBlueprint",  # type: ignore
        result: GraphExecutionResult,
        initial_inputs: Dict[str, Any],
        context: Dict[str, Any],
        node_inputs: Dict[str, Dict[str, Any]],
    ):
        """并行执行"""
        result.execution_mode = "parallel"

        # 并行执行所有节点
        import concurrent.futures

        def execute_with_inputs(node_id: str) -> NodeExecutionStatus:
            return self._execute_node(node_id, node_inputs.get(node_id, {}), context, result)

        # 限制并行度
        max_workers = min(self.strategy.max_parallel_nodes, len(blueprint.node_sequence))

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(execute_with_inputs, node_id): node_id
                for node_id in blueprint.node_sequence
            }

            for future in concurrent.futures.as_completed(futures):
                node_id = futures[future]
                try:
                    future.result()
                except Exception as e:
                    status = result.get_node_status(node_id)
                    if status:
                        status.status = "failed"
                        status.error = str(e)

    def _execute_hybrid(
        self,
        blueprint: "ExecutionBlueprint",  # type: ignore
        result: GraphExecutionResult,
        initial_inputs: Dict[str, Any],
        context: Dict[str, Any],
        node_inputs: Dict[str, Dict[str, Any]],
    ):
        """混合执行（顺序+并行）"""
        result.execution_mode = "hybrid"

        # parallel_groups: List[List[str]] 或 List[Dict]
        parallel_groups = blueprint.parallel_groups or []

        previous_output: Optional[Dict] = initial_inputs

        for group in parallel_groups:
            if self._cancel_requested:
                break

            # 检查是否是并行组
            if isinstance(group, list) and group and isinstance(group[0], list):
                # 嵌套列表：多行并行
                awaitables = []
                for sub_group in group:
                    for node_id in sub_group:
                        deps = blueprint.dependencies.get(node_id, [])
                        if deps and previous_output:
                            node_inputs[node_id] = {
                                "previous_output": previous_output,
                                "all_outputs": result.get_completed_results(),
                            }
                        elif previous_output:
                            node_inputs[node_id] = {"previous_output": previous_output}
                        else:
                            node_inputs[node_id] = {}

                        awaitables.append((node_id, node_inputs[node_id]))

                # 并行执行
                self._execute_parallel_nodes([n[0] for n in awaitables], node_inputs, context, result)

            elif isinstance(group, list):
                # 普通列表：一组可并行执行的节点
                for node_id in group:
                    deps = blueprint.dependencies.get(node_id, [])
                    if deps and previous_output:
                        node_inputs[node_id] = {
                            "previous_output": previous_output,
                            "all_outputs": result.get_completed_results(),
                        }
                    elif previous_output:
                        node_inputs[node_id] = {"previous_output": previous_output}
                    else:
                        node_inputs[node_id] = {}

                # 并行执行这组节点
                self._execute_parallel_nodes(group, node_inputs, context, result)

            # 更新previous_output（使用最后一个完成的节点输出）
            completed_results = result.get_completed_results()
            if completed_results:
                last_node = group[-1] if isinstance(group, list) else group
                if last_node in completed_results:
                    previous_output = completed_results[last_node]

    def _execute_parallel_nodes(
        self,
        node_ids: List[str],
        node_inputs: Dict[str, Dict[str, Any]],
        context: Dict[str, Any],
        result: GraphExecutionResult,
    ):
        """并行执行一组节点"""
        import concurrent.futures

        def execute_one(node_id: str) -> NodeExecutionStatus:
            return self._execute_node(node_id, node_inputs.get(node_id, {}), context, result)

        max_workers = min(self.strategy.max_parallel_nodes, len(node_ids))

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(execute_one, nid): nid for nid in node_ids}

            for future in concurrent.futures.as_completed(futures):
                node_id = futures[future]
                try:
                    future.result()
                except Exception as e:
                    status = result.get_node_status(node_id)
                    if status:
                        status.status = "failed"
                        status.error = str(e)

    def _skip_remaining_nodes(
        self,
        blueprint: "ExecutionBlueprint",  # type: ignore
        result: GraphExecutionResult,
        current_node_id: str,
    ):
        """跳过剩余节点"""
        current_index = blueprint.node_sequence.index(current_node_id)
        for node_id in blueprint.node_sequence[current_index + 1:]:
            status = result.get_node_status(node_id)
            if status and status.status == "pending":
                status.status = "skipped"
                status.start_time = time.time()
                status.end_time = time.time()
