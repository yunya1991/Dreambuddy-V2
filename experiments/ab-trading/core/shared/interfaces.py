#!/usr/bin/env python3
"""
共享接口定义

位置: experiments/ab-trading/core/shared/interfaces.py

定义 A层 和 C层 之间共享的接口
"""

from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass


# ============================================================
# A层：图编排引擎 - 节点执行器接口
# ============================================================

class NodeExecutorInterface:
    """节点执行器接口

    A层（图编排引擎）通过此接口调用C层执行节点

    C层需实现此接口
    """

    def execute_node(
        self,
        node_id: str,
        inputs: Dict[str, Any],
        context: Dict[str, Any],
    ) -> "NodeExecutionStatus":
        """
        执行单个节点

        Args:
            node_id: 节点ID
            inputs: 节点输入参数
            context: 执行上下文

        Returns:
            NodeExecutionStatus - 节点执行状态
        """
        raise NotImplementedError

    def get_node_schema(self, node_id: str) -> Optional[Dict]:
        """
        获取节点schema定义

        Returns:
            节点输入输出schema
        """
        raise NotImplementedError


# ============================================================
# 节点执行状态（共享类型）
# ============================================================

@dataclass
class NodeExecutionStatus:
    """节点执行状态

    跟踪每个节点的执行状态
    """
    node_id: str
    status: str = "pending"  # pending / running / completed / failed / skipped
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    retry_count: int = 0
    confidence: float = 0.0

    @property
    def duration_ms(self) -> float:
        """执行耗时（毫秒）"""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time) * 1000
        return 0.0

    @property
    def is_complete(self) -> bool:
        return self.status in ("completed", "failed", "skipped")

    def to_dict(self) -> Dict:
        return {
            "node_id": self.node_id,
            "status": self.status,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "result": self.result,
            "error": self.error,
            "retry_count": self.retry_count,
            "confidence": self.confidence,
        }


# ============================================================
# 执行策略
# ============================================================

@dataclass
class ExecutionStrategy:
    """执行策略配置

    控制图编排引擎的执行行为
    """
    # 失败策略
    stop_on_first_failure: bool = False
    continue_on_optional_failure: bool = True

    # 并行策略
    max_parallel_nodes: int = 3
    enable_parallel: bool = True

    # 超时策略
    default_node_timeout_ms: int = 30000
    global_timeout_ms: int = 300000

    # 重试策略
    max_retries: int = 1
    retry_on_timeout: bool = True

    # 监控策略
    enable_progress_callback: bool = True
    progress_callback: Optional[Callable] = None

    def to_dict(self) -> Dict:
        return {
            "stop_on_first_failure": self.stop_on_first_failure,
            "continue_on_optional_failure": self.continue_on_optional_failure,
            "max_parallel_nodes": self.max_parallel_nodes,
            "enable_parallel": self.enable_parallel,
            "default_node_timeout_ms": self.default_node_timeout_ms,
            "global_timeout_ms": self.global_timeout_ms,
            "max_retries": self.max_retries,
            "retry_on_timeout": self.retry_on_timeout,
            "enable_progress_callback": self.enable_progress_callback,
        }


__all__ = [
    "NodeExecutorInterface",
    "NodeExecutionStatus",
    "ExecutionStrategy",
]
