#!/usr/bin/env python3
"""
C层 - 节点执行器

位置: experiments/ab-trading/core/c_execution_layer/node_executor.py

职责：
1. 对接适配器框架（ModuleExecutor）
2. 节点执行器核心实现
3. 管理节点执行生命周期
4. 支持降级容错
"""

import time
from typing import Dict, List, Optional, Any, Callable

from ..shared.interfaces import NodeExecutorInterface, NodeExecutionStatus
from .types import (
    ExecutionContext,
    NodeExecutionResult as CNodeExecutionResult,
    NodeStatus,
)


# ============================================================
# C层：节点执行器 - 核心实现
# ============================================================

class NodeExecutor(NodeExecutorInterface):
    """节点执行器

    C层核心实现，对接适配器框架
    实现 A层的 NodeExecutorInterface
    """

    def __init__(self):
        """初始化节点执行器"""
        self._adapter_cache: Dict[str, Any] = {}
        self._module_registry = None
        self._skill_loader = None

        # 节点schema注册表（可选）
        self._node_schemas: Dict[str, Dict] = {}

    def _get_module_registry(self):
        """获取模块注册表"""
        if self._module_registry is None:
            try:
                from ..modules.module_registry import get_module_registry
                self._module_registry = get_module_registry()
            except Exception:
                self._module_registry = None
        return self._module_registry

    def _get_skill_loader(self):
        """获取Skill加载器"""
        if self._skill_loader is None:
            try:
                from ..modules.skill_loader import SkillLoader
                self._skill_loader = SkillLoader()
            except Exception:
                self._skill_loader = None
        return self._skill_loader

    def register_node_schema(self, node_id: str, schema: Dict):
        """注册节点schema

        Args:
            node_id: 节点ID
            schema: 节点schema定义，包含 inputs/outputs 等
        """
        self._node_schemas[node_id] = schema

    def get_node_schema(self, node_id: str) -> Optional[Dict]:
        """获取节点schema定义"""
        return self._node_schemas.get(node_id)

    def execute_node(
        self,
        node_id: str,
        inputs: Dict[str, Any],
        context: Dict[str, Any],
    ) -> NodeExecutionStatus:
        """
        执行单个节点

        Args:
            node_id: 节点ID
            inputs: 节点输入参数
            context: 执行上下文

        Returns:
            NodeExecutionStatus - A层的节点执行状态
        """
        # 创建C层执行结果
        result = CNodeExecutionResult(
            node_id=node_id,
            inputs=inputs,
        )

        try:
            # 获取节点schema
            schema = self.get_node_schema(node_id)

            # 构建适配器执行上下文
            exec_context = self._build_execution_context(context, inputs)

            # 获取并执行适配器
            adapter = self._get_adapter(node_id, schema)

            if adapter is None:
                # 没有适配器，使用默认处理器
                result = self._execute_default_handler(node_id, inputs, exec_context, result)
            else:
                # 使用适配器执行
                result = self._execute_with_adapter(adapter, inputs, exec_context, result)

        except Exception as e:
            result.mark_failed(str(e), "EXECUTION_ERROR")

        # 转换为A层状态
        return self._to_orchestrator_status(result)

    def _build_execution_context(
        self,
        context: Dict[str, Any],
        inputs: Dict[str, Any],
    ) -> ExecutionContext:
        """构建C层执行上下文"""
        exec_ctx = ExecutionContext()

        # 从context中复制信息
        exec_ctx.blueprint_id = context.get("blueprint_id", "")
        exec_ctx.objective_id = context.get("objective_id", "")
        exec_ctx.okr_mode = context.get("okr_mode", "")
        exec_ctx.complexity = context.get("complexity", "")

        # 添加执行状态
        if "completed_nodes" in context:
            exec_ctx.completed_nodes = context["completed_nodes"]
        if "node_outputs" in context:
            exec_ctx.node_outputs = context["node_outputs"]

        # 从inputs中获取市场数据等
        if "previous_output" in inputs:
            exec_ctx.metadata["previous_output"] = inputs["previous_output"]
        if "all_outputs" in inputs:
            exec_ctx.metadata["all_outputs"] = inputs["all_outputs"]

        return exec_ctx

    def _get_adapter(
        self,
        node_id: str,
        schema: Optional[Dict],
    ) -> Optional[Any]:
        """获取节点适配器"""
        # 优先使用缓存
        if node_id in self._adapter_cache:
            return self._adapter_cache[node_id]

        # 如果有schema定义，从schema获取
        if schema and "module_id" in schema:
            module_id = schema["module_id"]
            adapter_type = schema.get("adapter_type", "module")

            if adapter_type == "skill":
                return self._create_skill_adapter(module_id, schema.get("skill_name", ""))
            elif adapter_type == "api":
                return self._create_api_adapter(module_id)
            else:
                return self._create_module_adapter(module_id)

        # 尝试从注册表查找
        registry = self._get_module_registry()
        if registry:
            module_info = registry.get(node_id)
            if module_info:
                return self._create_module_adapter(node_id)

        return None

    def _create_module_adapter(self, module_id: str) -> Optional[Any]:
        """创建模块适配器"""
        try:
            from ..modules.adapter_framework import ModuleExecutor

            # 尝试创建适配器
            executor = ModuleExecutor(module_id)
            self._adapter_cache[module_id] = executor
            return executor
        except Exception:
            return None

    def _create_skill_adapter(self, module_id: str, skill_name: str) -> Optional[Any]:
        """创建Skill适配器"""
        try:
            from ..modules.adapter_framework import SkillAdapter

            adapter = SkillAdapter(module_id, skill_name)
            self._adapter_cache[module_id] = adapter
            return adapter
        except Exception:
            return None

    def _create_api_adapter(self, module_id: str) -> Optional[Any]:
        """创建API适配器"""
        try:
            from ..modules.adapter_framework import APIAdapter

            adapter = APIAdapter(module_id)
            self._adapter_cache[module_id] = adapter
            return adapter
        except Exception:
            return None

    def _execute_with_adapter(
        self,
        adapter: Any,
        inputs: Dict[str, Any],
        exec_context: ExecutionContext,
        result: CNodeExecutionResult,
    ) -> CNodeExecutionResult:
        """使用适配器执行节点"""
        result.mark_started()

        try:
            # 准备适配器输入
            adapter_inputs = self._prepare_adapter_inputs(inputs, exec_context)

            # 调用适配器
            if hasattr(adapter, "execute"):
                module_result = adapter.execute(adapter_inputs, exec_context)

                if module_result.success:
                    result.mark_completed(module_result.outputs)
                    result.confidence = module_result.confidence
                    result.tokens_used = module_result.tokens_used
                    result.cost = module_result.tokens_used * 0.0001  # 估算成本
                    result.metadata = module_result.metadata
                    if hasattr(module_result, "warnings"):
                        result.metadata["warnings"] = module_result.warnings
                else:
                    result.mark_failed(
                        module_result.errors[0] if module_result.errors else "Unknown error",
                        "ADAPTER_ERROR"
                    )
                    result.metadata = module_result.metadata
            else:
                result.mark_failed("适配器没有execute方法", "INVALID_ADAPTER")

        except Exception as e:
            result.mark_failed(str(e), "ADAPTER_EXECUTION_ERROR")

        return result

    def _execute_default_handler(
        self,
        node_id: str,
        inputs: Dict[str, Any],
        exec_context: ExecutionContext,
        result: CNodeExecutionResult,
    ) -> CNodeExecutionResult:
        """默认处理器 - 当没有适配器时"""
        result.mark_started()

        # 尝试从模块注册表获取默认实现
        registry = self._get_module_registry()
        if registry:
            module_info = registry.get(node_id)
            if module_info:
                result.source_module = module_info.id
                result.source_chain = module_info.chain

                # 这里可以调用模块的默认实现
                # 目前返回模拟结果
                output = {
                    "status": "completed",
                    "message": f"节点 {node_id} 执行完成",
                    "node_id": node_id,
                    "module_name": module_info.name,
                }
                result.mark_completed(output)
                result.confidence = module_info.historical_accuracy / 100.0 if module_info.historical_accuracy else 0.7
                return result

        # 如果没有任何实现，返回失败
        result.mark_failed(f"节点 {node_id} 没有找到对应的执行器", "NO_ADAPTER")
        return result

    def _prepare_adapter_inputs(
        self,
        inputs: Dict[str, Any],
        context: ExecutionContext,
    ) -> Dict[str, Any]:
        """准备适配器输入"""
        adapter_inputs = inputs.copy()

        # 添加上下文信息
        if "previous_output" in inputs:
            adapter_inputs["previous_output"] = inputs["previous_output"]
        if "all_outputs" in inputs:
            adapter_inputs["all_outputs"] = inputs["all_outputs"]

        # 添加执行上下文中的市场数据等
        if hasattr(context, "metadata"):
            adapter_inputs["_context_metadata"] = context.metadata

        return adapter_inputs

    def _to_orchestrator_status(self, result: CNodeExecutionResult) -> NodeExecutionStatus:
        """转换为A层节点执行状态"""
        status = NodeExecutionStatus(
            node_id=result.node_id,
            status=result.status.value,
            start_time=result.start_time,
            end_time=result.end_time,
            result=result.outputs or result.raw_result,
            error=result.error,
            retry_count=result.retry_count,
            confidence=result.confidence,
        )
        return status


# ============================================================
# C层：节点执行器 - 简化版（用于测试）
# ============================================================

class SimpleNodeExecutor(NodeExecutorInterface):
    """简化版节点执行器

    用于测试，不依赖实际的适配器框架
    """

    def __init__(self, node_handlers: Optional[Dict[str, Callable]] = None):
        """
        Args:
            node_handlers: 节点ID -> 处理函数的映射
        """
        self.node_handlers = node_handlers or {}

    def register_handler(self, node_id: str, handler: Callable):
        """注册节点处理器"""
        self.node_handlers[node_id] = handler

    def execute_node(
        self,
        node_id: str,
        inputs: Dict[str, Any],
        context: Dict[str, Any],
    ) -> NodeExecutionStatus:
        """执行单个节点"""
        status = NodeExecutionStatus(node_id=node_id)
        status.status = "running"
        status.start_time = time.time()

        try:
            if node_id in self.node_handlers:
                handler = self.node_handlers[node_id]
                result = handler(inputs, context)
                status.status = "completed"
                status.result = result
                status.confidence = 0.8
            else:
                # 默认实现
                status.status = "completed"
                status.result = {
                    "node_id": node_id,
                    "message": f"节点 {node_id} 执行完成",
                    "inputs": inputs,
                }
                status.confidence = 0.7

        except Exception as e:
            status.status = "failed"
            status.error = str(e)

        status.end_time = time.time()
        return status

    def get_node_schema(self, node_id: str) -> Optional[Dict]:
        """获取节点schema"""
        return None
