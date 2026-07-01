#!/usr/bin/env python3
"""
共享模块

位置: experiments/ab-trading/core/shared/

定义跨层共享的接口、类型和错误处理
"""

from .interfaces import (
    NodeExecutorInterface,
    NodeExecutionStatus,
    ExecutionStrategy,
)

from .errors import (
    ErrorCode,
    OSBaseError,
    ModuleError,
    NodeError,
    AdapterError,
    ExecutionError,
    ValidationError,
    DataError,
    OrchestrationError,
    wrap_exception,
    ErrorInfo,
)

__all__ = [
    # 接口
    "NodeExecutorInterface",
    "NodeExecutionStatus",
    "ExecutionStrategy",
    # 错误码
    "ErrorCode",
    "OSBaseError",
    "ModuleError",
    "NodeError",
    "AdapterError",
    "ExecutionError",
    "ValidationError",
    "DataError",
    "OrchestrationError",
    "wrap_exception",
    "ErrorInfo",
]
