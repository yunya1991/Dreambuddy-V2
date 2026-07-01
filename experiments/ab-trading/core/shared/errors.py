#!/usr/bin/env python3
"""
错误码体系 + 异常处理标准化

位置: experiments/ab-trading/core/shared/errors.py

错误码分类:
- 1xxx: 系统级错误
- 2xxx: 模块/节点错误
- 3xxx: 适配器错误
- 4xxx: 执行错误
- 5xxx: 数据错误
- 6xxx: 编排错误

设计原则:
- 分层错误码，每层有明确的范围
- 错误码可追溯到具体模块/节点
- 支持错误链（cause）
- 支持降级标记
"""

from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field


# ============================================================
# 错误码定义
# ============================================================

class ErrorCode:
    """错误码常量"""

    # === 1xxx: 系统级 ===
    SYSTEM_ERROR = 1000
    SYSTEM_TIMEOUT = 1001
    SYSTEM_UNAVAILABLE = 1002
    SYSTEM_SHUTTING_DOWN = 1003
    SYSTEM_OUT_OF_MEMORY = 1004

    # === 2xxx: 模块/节点错误 ===
    MODULE_NOT_FOUND = 2000
    MODULE_DISABLED = 2001
    MODULE_DEPRECATED = 2002
    MODULE_INIT_FAILED = 2003
    NODE_NOT_FOUND = 2100
    NODE_DISABLED = 2101
    NODE_HANDLER_MISSING = 2102

    # === 3xxx: 适配器错误 ===
    ADAPTER_NOT_FOUND = 3000
    ADAPTER_INIT_FAILED = 3001
    ADAPTER_EXECUTION_ERROR = 3002
    ADAPTER_TIMEOUT = 3003
    SKILL_LOAD_FAILED = 3100
    SKILL_EXECUTION_FAILED = 3101
    API_CONNECTION_FAILED = 3200
    API_REQUEST_FAILED = 3201
    API_RATE_LIMITED = 3202

    # === 4xxx: 执行错误 ===
    EXECUTION_FAILED = 4000
    EXECUTION_TIMEOUT = 4001
    EXECUTION_INTERRUPTED = 4002
    EXECUTION_RETRY_EXHAUSTED = 4003
    EXECUTION_FALLBACK_FAILED = 4004
    VALIDATION_FAILED = 4100
    INPUT_VALIDATION_FAILED = 4101
    OUTPUT_VALIDATION_FAILED = 4102

    # === 5xxx: 数据错误 ===
    DATA_NOT_FOUND = 5000
    DATA_FORMAT_ERROR = 5001
    DATA_INCOMPLETE = 5002
    DATA_STALE = 5003

    # === 6xxx: 编排错误 ===
    ORCHESTRATION_ERROR = 6000
    GRAPH_INVALID = 6001
    CYCLE_DETECTED = 6002
    DEPENDENCY_FAILED = 6003
    NODE_SEQUENCE_ERROR = 6004
    PARALLEL_EXECUTION_ERROR = 6005

    # 错误码描述映射
    _DESCRIPTIONS = {
        1000: "系统错误",
        1001: "系统超时",
        1002: "系统不可用",
        1003: "系统关闭中",
        1004: "系统内存不足",
        2000: "模块未找到",
        2001: "模块已禁用",
        2002: "模块已废弃",
        2003: "模块初始化失败",
        2100: "节点未找到",
        2101: "节点已禁用",
        2102: "节点处理器缺失",
        3000: "适配器未找到",
        3001: "适配器初始化失败",
        3002: "适配器执行错误",
        3003: "适配器超时",
        3100: "SKILL加载失败",
        3101: "SKILL执行失败",
        3200: "API连接失败",
        3201: "API请求失败",
        3202: "API限流",
        4000: "执行失败",
        4001: "执行超时",
        4002: "执行被中断",
        4003: "重试次数耗尽",
        4004: "降级执行失败",
        4100: "校验失败",
        4101: "输入校验失败",
        4102: "输出校验失败",
        5000: "数据未找到",
        5001: "数据格式错误",
        5002: "数据不完整",
        5003: "数据已过期",
        6000: "编排错误",
        6001: "图结构无效",
        6002: "检测到循环依赖",
        6003: "依赖执行失败",
        6004: "节点序列错误",
        6005: "并行执行错误",
    }

    @classmethod
    def get_description(cls, code: int) -> str:
        """获取错误码描述"""
        return cls._DESCRIPTIONS.get(code, "未知错误")

    @classmethod
    def is_retryable(cls, code: int) -> bool:
        """判断错误是否可重试"""
        retryable_codes = {
            1001,  # 系统超时
            1002,  # 系统不可用（临时）
            3003,  # 适配器超时
            3200,  # API连接失败
            3201,  # API请求失败（可能临时）
            3202,  # API限流（等待后可重试）
            4001,  # 执行超时
            4003,  # 重试耗尽（不应该再重试，但列表保留）
            5003,  # 数据过期（刷新后可重试）
        }
        return code in retryable_codes

    @classmethod
    def is_fallback_allowed(cls, code: int) -> bool:
        """判断是否允许降级"""
        # 大部分错误都允许降级，除了严重的系统错误
        non_fallback_codes = {
            1003,  # 系统关闭中
            1004,  # 系统内存不足
        }
        return code not in non_fallback_codes


# ============================================================
# 标准化异常基类
# ============================================================

class OSBaseError(Exception):
    """操作系统级异常基类

    所有自定义异常都继承自此类
    """

    def __init__(
        self,
        message: str,
        error_code: int = ErrorCode.SYSTEM_ERROR,
        node_id: Optional[str] = None,
        module_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
        retryable: Optional[bool] = None,
        fallback_allowed: Optional[bool] = None,
    ):
        super().__init__(message)
        self.error_code = error_code
        self.node_id = node_id
        self.module_id = module_id
        self.details = details or {}
        self.cause = cause
        self._retryable = retryable
        self._fallback_allowed = fallback_allowed
        self.timestamp = __import__('time').time()

    @property
    def code_description(self) -> str:
        return ErrorCode.get_description(self.error_code)

    @property
    def is_retryable(self) -> bool:
        if self._retryable is not None:
            return self._retryable
        return ErrorCode.is_retryable(self.error_code)

    @property
    def is_fallback_allowed(self) -> bool:
        if self._fallback_allowed is not None:
            return self._fallback_allowed
        return ErrorCode.is_fallback_allowed(self.error_code)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_code": self.error_code,
            "error_description": self.code_description,
            "message": str(self),
            "node_id": self.node_id,
            "module_id": self.module_id,
            "details": self.details,
            "retryable": self.is_retryable,
            "fallback_allowed": self.is_fallback_allowed,
            "timestamp": self.timestamp,
            "cause": str(self.cause) if self.cause else None,
        }

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} [{self.error_code}] {self}>"


# ============================================================
# 具体异常类
# ============================================================

class ModuleError(OSBaseError):
    """模块相关错误"""
    def __init__(self, message: str, module_id: str, error_code: int = ErrorCode.MODULE_NOT_FOUND, **kwargs):
        super().__init__(message, error_code=error_code, module_id=module_id, **kwargs)


class NodeError(OSBaseError):
    """节点相关错误"""
    def __init__(self, message: str, node_id: str, error_code: int = ErrorCode.NODE_NOT_FOUND, **kwargs):
        super().__init__(message, error_code=error_code, node_id=node_id, **kwargs)


class AdapterError(OSBaseError):
    """适配器相关错误"""
    def __init__(self, message: str, error_code: int = ErrorCode.ADAPTER_EXECUTION_ERROR, **kwargs):
        super().__init__(message, error_code=error_code, **kwargs)


class ExecutionError(OSBaseError):
    """执行相关错误"""
    def __init__(self, message: str, error_code: int = ErrorCode.EXECUTION_FAILED, **kwargs):
        super().__init__(message, error_code=error_code, **kwargs)


class ValidationError(OSBaseError):
    """校验相关错误"""
    def __init__(self, message: str, error_code: int = ErrorCode.VALIDATION_FAILED, **kwargs):
        super().__init__(message, error_code=error_code, **kwargs)


class DataError(OSBaseError):
    """数据相关错误"""
    def __init__(self, message: str, error_code: int = ErrorCode.DATA_NOT_FOUND, **kwargs):
        super().__init__(message, error_code=error_code, **kwargs)


class OrchestrationError(OSBaseError):
    """编排相关错误"""
    def __init__(self, message: str, error_code: int = ErrorCode.ORCHESTRATION_ERROR, **kwargs):
        super().__init__(message, error_code=error_code, **kwargs)


# ============================================================
# 错误包装工具
# ============================================================

def wrap_exception(
    exc: Exception,
    node_id: Optional[str] = None,
    module_id: Optional[str] = None,
    default_code: int = ErrorCode.EXECUTION_FAILED,
) -> OSBaseError:
    """将普通异常包装为标准化异常

    Args:
        exc: 原始异常
        node_id: 节点ID（可选）
        module_id: 模块ID（可选）
        default_code: 默认错误码

    Returns:
        OSBaseError 子类实例
    """
    # 如果已经是OSBaseError，直接返回（但补充信息）
    if isinstance(exc, OSBaseError):
        if node_id and not exc.node_id:
            exc.node_id = node_id
        if module_id and not exc.module_id:
            exc.module_id = module_id
        return exc

    # 识别常见异常类型
    if isinstance(exc, TimeoutError):
        code = ErrorCode.EXECUTION_TIMEOUT
    elif isinstance(exc, ValueError):
        code = ErrorCode.DATA_FORMAT_ERROR
    elif isinstance(exc, KeyError):
        code = ErrorCode.DATA_NOT_FOUND
    elif isinstance(exc, NotImplementedError):
        code = ErrorCode.ADAPTER_NOT_FOUND
    else:
        code = default_code

    return OSBaseError(
        message=str(exc),
        error_code=code,
        node_id=node_id,
        module_id=module_id,
        cause=exc,
    )


# ============================================================
# 错误结果构建工具
# ============================================================

@dataclass
class ErrorInfo:
    """标准化错误信息

    用于 ModuleResult / NodeExecutionResult 等结果结构中
    """
    error_code: int
    message: str
    description: str = ""
    node_id: Optional[str] = None
    module_id: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    retryable: bool = False
    fallback_allowed: bool = True

    def __post_init__(self):
        if not self.description:
            self.description = ErrorCode.get_description(self.error_code)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_code": self.error_code,
            "error_description": self.description,
            "message": self.message,
            "node_id": self.node_id,
            "module_id": self.module_id,
            "details": self.details,
            "retryable": self.retryable,
            "fallback_allowed": self.fallback_allowed,
        }

    @classmethod
    def from_exception(cls, exc: Exception, **kwargs) -> "ErrorInfo":
        """从异常构建ErrorInfo"""
        if isinstance(exc, OSBaseError):
            return cls(
                error_code=exc.error_code,
                message=str(exc),
                description=exc.code_description,
                node_id=exc.node_id,
                module_id=exc.module_id,
                details=exc.details,
                retryable=exc.is_retryable,
                fallback_allowed=exc.is_fallback_allowed,
            )
        return cls(
            error_code=ErrorCode.EXECUTION_FAILED,
            message=str(exc),
            **kwargs,
        )

    @classmethod
    def create(cls, error_code: int, message: str, **kwargs) -> "ErrorInfo":
        """创建ErrorInfo"""
        return cls(error_code=error_code, message=message, **kwargs)


__all__ = [
    # 错误码
    "ErrorCode",
    # 异常基类
    "OSBaseError",
    # 具体异常
    "ModuleError",
    "NodeError",
    "AdapterError",
    "ExecutionError",
    "ValidationError",
    "DataError",
    "OrchestrationError",
    # 工具函数
    "wrap_exception",
    "ErrorInfo",
]
