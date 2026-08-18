#!/usr/bin/env python3
"""
统一节点执行器 (Unified Node Executor)

位置: experiments/ab-trading/core/c_execution_layer/unified_executor.py

职责:
1. 整合节点注册表 (NodeRegistry) 获取节点元数据
2. 对接适配器框架 (ModuleExecutor) 执行节点
3. 统一输入输出协议 (ExecutionContext + ModuleResult)
4. 标准化错误处理 + 重试 + 降级
5. 实现 A层 NodeExecutorInterface 接口

执行协议:
  输入: node_id + inputs(dict) + context(dict)
  输出: NodeExecutionStatus (A层兼容) + ModuleResult (标准化)
"""

import time
import threading
from typing import Dict, List, Optional, Any, Callable

from ..shared.interfaces import NodeExecutorInterface, NodeExecutionStatus
from ..shared.errors import (
    ErrorCode,
    OSBaseError,
    NodeError,
    wrap_exception,
    ErrorInfo,
)
from ..modules.unified_types import (
    ModuleResult,
    ExecutionContext as UnifiedExecutionContext,
    ModuleOutputs,
    create_success_result,
    create_failure_result,
    create_fallback_result,
)


# ============================================================
# 统一节点执行器
# ============================================================

class UnifiedNodeExecutor(NodeExecutorInterface):
    """
    统一节点执行器

    整合:
    - 节点注册表：获取节点元数据（Schema、超时、重试、降级策略）
    - 适配器框架：实际执行节点（Skill/API/Local/Module）
    - 错误码体系：标准化错误处理
    - 重试机制：基于节点配置的重试策略
    - 降级机制：基于节点配置的降级策略

    实现 A层 NodeExecutorInterface 接口，可直接被 GraphOrchestrator 使用
    """

    def __init__(
        self,
        node_registry: Optional[Any] = None,
        module_registry: Optional[Any] = None,
        enable_retry: bool = True,
        enable_fallback: bool = True,
    ):
        """
        初始化统一节点执行器

        Args:
            node_registry: 节点注册表（可选，默认使用全局）
            module_registry: 模块注册表（可选，默认使用全局）
            enable_retry: 是否启用重试
            enable_fallback: 是否启用降级
        """
        self._node_registry = node_registry
        self._module_registry = module_registry
        self.enable_retry = enable_retry
        self.enable_fallback = enable_fallback

        # 适配器缓存
        self._adapter_cache: Dict[str, Any] = {}
        self._cache_lock = threading.Lock()

        # 执行统计
        self._stats = {
            "total_calls": 0,
            "success": 0,
            "failed": 0,
            "retried": 0,
            "fallback": 0,
            "total_latency_ms": 0.0,
        }

    # ============================================================
    # 延迟加载依赖
    # ============================================================

    def _get_node_registry(self):
        """获取节点注册表"""
        if self._node_registry is None:
            try:
                from ..nodes.node_registry import get_node_registry
                self._node_registry = get_node_registry()
            except Exception:
                self._node_registry = None
        return self._node_registry

    def _get_module_registry(self):
        """获取模块注册表"""
        if self._module_registry is None:
            try:
                from ..modules.module_registry import get_module_registry
                self._module_registry = get_module_registry()
            except Exception:
                self._module_registry = None
        return self._module_registry

    def _get_node_info(self, node_id: str) -> Optional[Any]:
        """获取节点信息"""
        registry = self._get_node_registry()
        if registry:
            return registry.get(node_id)
        return None

    # ============================================================
    # NodeExecutorInterface 实现
    # ============================================================

    def execute_node(
        self,
        node_id: str,
        inputs: Dict[str, Any],
        context: Dict[str, Any],
    ) -> NodeExecutionStatus:
        """
        执行单个节点（A层接口）

        Args:
            node_id: 节点ID
            inputs: 节点输入参数
            context: 执行上下文

        Returns:
            NodeExecutionStatus - A层节点执行状态
        """
        start_time = time.time()

        # 完整执行，返回 ModuleResult（execute 内部会更新统计）
        module_result = self.execute(node_id, inputs, context)

        # 转换为 A层 NodeExecutionStatus
        status = self._module_result_to_status(node_id, module_result, start_time)

        return status

    def get_node_schema(self, node_id: str) -> Optional[Dict]:
        """
        获取节点Schema定义

        Args:
            node_id: 节点ID

        Returns:
            节点输入输出Schema
        """
        node_info = self._get_node_info(node_id)
        if node_info:
            return {
                "inputs": node_info.input_schema.to_dict(),
                "outputs": node_info.output_schema.to_dict(),
            }
        return None

    # ============================================================
    # 核心执行方法（返回 ModuleResult）
    # ============================================================

    def execute(
        self,
        node_id: str,
        inputs: Dict[str, Any],
        context: Dict[str, Any],
    ) -> ModuleResult:
        """
        执行节点（返回标准化 ModuleResult）

        执行流程:
        1. 查找节点元数据
        2. 构建执行上下文
        3. 获取适配器
        4. 执行（带重试）
        5. 失败时降级
        6. 返回结果

        Args:
            node_id: 节点ID
            inputs: 输入参数
            context: 执行上下文

        Returns:
            ModuleResult - 标准化执行结果
        """
        start_time = time.time()
        self._stats["total_calls"] += 1

        # 1. 查找节点元数据
        node_info = self._get_node_info(node_id)

        # 2. 构建统一执行上下文
        exec_ctx = self._build_execution_context(inputs, context)

        # 3. 获取适配器
        adapter = self._get_adapter(node_id, node_info)

        if adapter is None:
            # 没有适配器，尝试直接使用节点handler
            if node_info and node_info.handler:
                result = self._execute_with_handler(node_id, node_info, inputs, exec_ctx)
            else:
                # 找不到任何执行方式
                result = create_failure_result(
                    capability_id=node_id,
                    error=f"节点 {node_id} 未找到执行器",
                )
                result.metadata["error_info"] = ErrorInfo.create(
                    error_code=ErrorCode.NODE_HANDLER_MISSING,
                    message=f"节点 {node_id} 未找到执行器",
                    node_id=node_id,
                ).to_dict()
        else:
            # 4. 执行（带重试）
            result = self._execute_with_retry(node_id, node_info, adapter, inputs, exec_ctx)

            # 5. 失败时降级
            if not result.success and self.enable_fallback and node_info:
                fallback = node_info.fallback_policy
                if fallback.enabled and fallback.fallback_node_id:
                    result = self._execute_fallback(
                        node_id,
                        fallback.fallback_node_id,
                        inputs,
                        context,
                        result,
                    )

        # 更新统计
        latency = (time.time() - start_time) * 1000
        self._stats["total_latency_ms"] += latency
        if result.success or result.fallback_used:
            self._stats["success"] += 1
        else:
            self._stats["failed"] += 1
        if result.fallback_used:
            self._stats["fallback"] += 1

        return result

    # ============================================================
    # 执行上下文构建
    # ============================================================

    def _build_execution_context(
        self,
        inputs: Dict[str, Any],
        context: Dict[str, Any],
    ) -> UnifiedExecutionContext:
        """
        构建统一执行上下文

        从 inputs 和 context 中提取信息，构造标准化的 ExecutionContext
        """
        session_id = context.get("session_id", "") or context.get("blueprint_id", "unknown")

        # 从 inputs 中提取市场数据（mkt/memory/data 三元组）
        mkt = inputs.get("mkt", {})
        memory = inputs.get("memory", {})
        data = inputs.get("data", {})

        # 从 context 中补充
        if not mkt and "mkt" in context:
            mkt = context["mkt"]
        if not memory and "memory" in context:
            memory = context["memory"]

        # prior_outputs（之前节点的输出）
        prior_outputs = {}
        if "node_outputs" in context:
            prior_outputs = context["node_outputs"]
        elif "all_outputs" in inputs:
            prior_outputs = inputs["all_outputs"]

        ctx = UnifiedExecutionContext(
            session_id=session_id,
            intent=context.get("intent", "unknown"),
            symbol=context.get("symbol"),
            user_role=context.get("user_role", "FREE"),
            trading_mode=context.get("trading_mode", "hybrid"),
            prior_outputs=prior_outputs,
            market_condition=context.get("market_condition", "unknown"),
            mkt=mkt if isinstance(mkt, dict) else {},
            memory=memory if isinstance(memory, dict) else {},
        )

        # 将 data 放入 extra
        if isinstance(data, dict):
            ctx.extra.update(data)

        return ctx

    # ============================================================
    # 适配器获取
    # ============================================================

    def _get_adapter(self, node_id: str, node_info: Optional[Any]) -> Optional[Any]:
        """获取节点适配器"""
        # 优先使用缓存
        with self._cache_lock:
            if node_id in self._adapter_cache:
                return self._adapter_cache[node_id]

        # 从节点信息获取
        if node_info:
            adapter = self._create_adapter_from_node_info(node_info)
            if adapter:
                with self._cache_lock:
                    self._adapter_cache[node_id] = adapter
                return adapter

        # 尝试从模块注册表创建
        module_reg = self._get_module_registry()
        if module_reg:
            module_info = module_reg.get(node_id)
            if module_info:
                adapter = self._create_module_adapter(node_id)
                if adapter:
                    with self._cache_lock:
                        self._adapter_cache[node_id] = adapter
                    return adapter

        return None

    def _create_adapter_from_node_info(self, node_info: Any) -> Optional[Any]:
        """根据节点信息创建适配器"""
        node_type = node_info.node_type
        module_id = node_info.module_id or node_info.node_id

        if node_type == "skill_node":
            return self._create_skill_adapter(module_id)
        elif node_type == "api_node":
            return self._create_api_adapter(module_id)
        elif node_type in ("local_node", "composite_node"):
            return self._create_module_adapter(module_id)

        return None

    def _create_module_adapter(self, module_id: str) -> Optional[Any]:
        """创建模块适配器（ModuleExecutor）"""
        try:
            from ..modules.adapter_framework import ModuleExecutor
            return ModuleExecutor(module_id)
        except Exception:
            return None

    def _create_skill_adapter(self, module_id: str) -> Optional[Any]:
        """创建Skill适配器"""
        try:
            from ..modules.adapter_framework import SkillAdapter
            return SkillAdapter(module_id)
        except Exception:
            return None

    def _create_api_adapter(self, module_id: str) -> Optional[Any]:
        """创建API适配器"""
        try:
            from ..modules.adapter_framework import APIAdapter
            return APIAdapter(module_id)
        except Exception:
            return None

    # ============================================================
    # 执行：直接 handler 调用
    # ============================================================

    def _execute_with_handler(
        self,
        node_id: str,
        node_info: Any,
        inputs: Dict[str, Any],
        exec_ctx: UnifiedExecutionContext,
    ) -> ModuleResult:
        """
        直接使用节点handler执行

        用于本地节点（有本地实现函数的情况）
        """
        start = time.time()
        try:
            # 准备 mkt/memory/data 三元组参数
            mkt = inputs.get("mkt", exec_ctx.mkt)
            memory = inputs.get("memory", exec_ctx.memory)
            data = inputs.get("data", {})

            # 调用handler（传统三元组接口）
            handler = node_info.handler
            raw_result = handler(mkt, memory, data)

            # 转换为 ModuleResult
            result = self._raw_result_to_module_result(
                node_id, raw_result, start, exec_ctx
            )
            return result

        except Exception as e:
            latency_ms = int((time.time() - start) * 1000)
            err = wrap_exception(e, node_id=node_id, module_id=node_info.module_id)
            result = create_failure_result(node_id, str(err))
            result.latency_ms = latency_ms
            result.metadata["error_info"] = ErrorInfo.from_exception(err).to_dict()
            return result

    def _raw_result_to_module_result(
        self,
        node_id: str,
        raw_result: Any,
        start_time: float,
        exec_ctx: UnifiedExecutionContext,
    ) -> ModuleResult:
        """
        将原始结果转换为 ModuleResult

        支持多种返回格式:
        - dict: 包含 direction/confidence 等
        - tuple: (direction, confidence) 或 (direction, confidence, data)
        - ModuleResult: 直接返回
        """
        latency_ms = int((time.time() - start_time) * 1000)

        # 已经是 ModuleResult
        if isinstance(raw_result, ModuleResult):
            if raw_result.latency_ms is None:
                raw_result.latency_ms = latency_ms
            return raw_result

        outputs = {}

        # dict 格式
        if isinstance(raw_result, dict):
            outputs = raw_result
            # 提取 direction / confidence
            direction = raw_result.get("direction", "")
            confidence = raw_result.get("confidence", 0.0)
            if isinstance(confidence, (int, float)) and confidence <= 1.0:
                confidence = confidence * 100  # 转换为百分制

        # tuple 格式 (direction, confidence, ...)
        elif isinstance(raw_result, (tuple, list)) and len(raw_result) >= 2:
            direction = raw_result[0]
            confidence = raw_result[1]
            if isinstance(confidence, (int, float)) and confidence <= 1.0:
                confidence = confidence * 100
            if len(raw_result) >= 3:
                outputs["data"] = raw_result[2]
            outputs["direction"] = direction
            outputs["confidence"] = confidence

        # 其他格式
        else:
            direction = "hold"
            confidence = 50.0
            outputs["raw"] = raw_result

        result = create_success_result(
            capability_id=node_id,
            outputs=outputs,
            confidence=float(confidence) if confidence else 0.0,
        )
        result.latency_ms = latency_ms
        return result

    # ============================================================
    # 执行：适配器 + 重试
    # ============================================================

    def _execute_with_retry(
        self,
        node_id: str,
        node_info: Optional[Any],
        adapter: Any,
        inputs: Dict[str, Any],
        exec_ctx: UnifiedExecutionContext,
    ) -> ModuleResult:
        """
        执行适配器（带重试逻辑）
        """
        max_retries = 0
        if self.enable_retry and node_info and node_info.retry_policy.enabled:
            max_retries = node_info.retry_policy.max_retries

        last_result = None
        retry_count = 0

        for attempt in range(max_retries + 1):
            start = time.time()
            try:
                if hasattr(adapter, "execute"):
                    result = adapter.execute(inputs, exec_ctx)
                    result.latency_ms = result.latency_ms or int((time.time() - start) * 1000)

                    if result.success:
                        if retry_count > 0:
                            self._stats["retried"] += 1
                        return result
                    last_result = result

                    # 判断是否需要重试
                    if not self._should_retry(result, node_info):
                        break

                else:
                    last_result = create_failure_result(
                        node_id, "适配器没有execute方法"
                    )
                    break

            except Exception as e:
                latency_ms = int((time.time() - start) * 1000)
                err = wrap_exception(e, node_id=node_id)
                last_result = create_failure_result(node_id, str(err))
                last_result.latency_ms = latency_ms
                last_result.metadata["error_info"] = ErrorInfo.from_exception(err).to_dict()

                if not err.is_retryable:
                    break

            retry_count += 1
            if retry_count <= max_retries:
                # 简单的指数退避
                import time as _time
                _time.sleep(0.1 * (2 ** (retry_count - 1)))

        if last_result:
            return last_result

        return create_failure_result(node_id, "未知执行错误")

    def _should_retry(self, result: ModuleResult, node_info: Optional[Any]) -> bool:
        """判断是否应该重试"""
        if not self.enable_retry or not node_info or not node_info.retry_policy.enabled:
            return False

        error_info = result.metadata.get("error_info", {})
        if error_info.get("retryable"):
            return True

        # 检查错误码
        error_code = error_info.get("error_code")
        if error_code:
            from ..shared.errors import ErrorCode
            return ErrorCode.is_retryable(error_code)

        return False

    # ============================================================
    # 降级执行
    # ============================================================

    def _execute_fallback(
        self,
        original_node_id: str,
        fallback_node_id: str,
        inputs: Dict[str, Any],
        context: Dict[str, Any],
        original_result: ModuleResult,
    ) -> ModuleResult:
        """执行降级节点"""
        try:
            self._stats["fallback"] += 1
            fallback_result = self.execute(fallback_node_id, inputs, context)

            # 标记为降级结果
            fallback_result.fallback_used = True
            fallback_result.fallback_reason = original_result.error or "主节点执行失败"
            fallback_result.warnings.append(
                f"降级执行: 从 {original_node_id} 降级到 {fallback_node_id}"
            )
            fallback_result.metadata["original_error"] = original_result.error
            fallback_result.metadata["original_node"] = original_node_id

            return fallback_result

        except Exception as e:
            # 降级也失败了，返回原始失败结果
            original_result.warnings.append(f"降级执行也失败: {e}")
            return original_result

    # ============================================================
    # 结果转换
    # ============================================================

    def _module_result_to_status(
        self,
        node_id: str,
        result: ModuleResult,
        start_time: float,
    ) -> NodeExecutionStatus:
        """将 ModuleResult 转换为 A层 NodeExecutionStatus"""
        if result.success:
            status = "completed"
            error = None
        elif result.fallback_used:
            # 降级也算完成（但置信度低）
            status = "completed"
            error = None
        else:
            status = "failed"
            error = result.error

        node_status = NodeExecutionStatus(
            node_id=node_id,
            status=status,
            start_time=start_time,
            end_time=start_time + (result.latency_ms or 0) / 1000.0,
            result=result.outputs.to_dict() if result.outputs else {},
            error=error,
            retry_count=0,
            confidence=result.confidence / 100.0 if result.confidence > 1.0 else result.confidence,
        )

        return node_status

    # ============================================================
    # 统计
    # ============================================================

    def get_stats(self) -> Dict:
        """获取执行统计"""
        stats = dict(self._stats)
        if stats["total_calls"] > 0:
            stats["avg_latency_ms"] = stats["total_latency_ms"] / stats["total_calls"]
            stats["success_rate"] = stats["success"] / stats["total_calls"]
        else:
            stats["avg_latency_ms"] = 0
            stats["success_rate"] = 0
        return stats

    def reset_stats(self):
        """重置统计"""
        self._stats = {
            "total_calls": 0,
            "success": 0,
            "failed": 0,
            "retried": 0,
            "fallback": 0,
            "total_latency_ms": 0.0,
        }


# ============================================================
# 全局单例
# ============================================================

_global_executor: Optional[UnifiedNodeExecutor] = None
_global_lock = threading.Lock()


def get_unified_executor() -> UnifiedNodeExecutor:
    """获取全局统一节点执行器"""
    global _global_executor
    if _global_executor is None:
        with _global_lock:
            if _global_executor is None:
                _global_executor = UnifiedNodeExecutor()
    return _global_executor


__all__ = [
    "UnifiedNodeExecutor",
    "get_unified_executor",
]
