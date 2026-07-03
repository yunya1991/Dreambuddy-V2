"""
Dreambuddy OS — 错误码体系

6 大类错误码，覆盖全场景:
    SYS_     系统级     — 系统故障、资源耗尽、服务不可用
    NODE_    节点级     — 节点不存在、版本不兼容、初始化失败
    ADAPTER_ 适配器级   — 适配器类型不支持、连接失败
    EXEC_    执行级     — 超时、执行失败、重试耗尽
    DATA_    数据级     — 输入校验失败、输出格式错误、数据缺失
    ORCH_    编排级     — 循环依赖、节点冲突、无可达路径

错误分类:
    - 可重试错误 (retryable=True): 网络抖动、临时不可用
    - 不可重试错误 (retryable=False): 参数错误、配置错误
"""

from __future__ import annotations
from typing import Optional, Dict, Any


class ErrorCode:
    """错误码常量"""

    # ── 系统级 SYS_ ────────────────────────────────────
    SYS_001 = "SYS_001"   # 系统内部错误
    SYS_002 = "SYS_002"   # 资源耗尽（内存/连接池）
    SYS_003 = "SYS_003"   # 服务不可用

    # ── 节点级 NODE_ ────────────────────────────────────
    NODE_001 = "NODE_001"   # 节点未找到
    NODE_002 = "NODE_002"   # 节点版本不兼容
    NODE_003 = "NODE_003"   # 节点初始化失败
    NODE_004 = "NODE_004"   # 节点未注册

    # ── 适配器级 ADAPTER_ ───────────────────────────────
    ADAPTER_001 = "ADAPTER_001"   # 适配器类型不支持
    ADAPTER_002 = "ADAPTER_002"   # 适配器连接失败
    ADAPTER_003 = "ADAPTER_003"   # 适配器初始化失败

    # ── 执行级 EXEC_ ────────────────────────────────────
    EXEC_001 = "EXEC_001"   # 执行超时
    EXEC_002 = "EXEC_002"   # 执行失败
    EXEC_003 = "EXEC_003"   # 重试耗尽
    EXEC_004 = "EXEC_004"   # 降级失败

    # ── 数据级 DATA_ ────────────────────────────────────
    DATA_001 = "DATA_001"   # 输入参数校验失败
    DATA_002 = "DATA_002"   # 输出格式错误
    DATA_003 = "DATA_003"   # 数据缺失
    DATA_004 = "DATA_004"   # 数据源不可用

    # ── 编排级 ORCH_ ────────────────────────────────────
    ORCH_001 = "ORCH_001"   # 循环依赖检测
    ORCH_002 = "ORCH_002"   # 节点冲突
    ORCH_003 = "ORCH_003"   # 无可达路径
    ORCH_004 = "ORCH_004"   # 预算超限

    @classmethod
    def all_codes(cls) -> Dict[str, str]:
        """所有错误码"""
        return {k: v for k, v in vars(cls).items()
                if k[0].isupper() and isinstance(v, str)}


# ============================================================
# OS 异常基类
# ============================================================

class OSError(Exception):
    """Dreambuddy OS 基础异常

    Attributes:
        code:       错误码 (ErrorCode.XXX)
        message:    错误信息
        retryable: 是否可重试
        node_id:    出错的节点 ID (可选)
        context:    上下文信息 (可选)
    """

    def __init__(self, code: str, message: str, retryable: bool = False,
                 node_id: Optional[str] = None,
                 context: Optional[Dict[str, Any]] = None):
        self.code = code
        self.message = message
        self.retryable = retryable
        self.node_id = node_id
        self.context = context or {}
        super().__init__(f"[{code}] {message}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "node_id": self.node_id,
            "context": self.context,
        }

    def __repr__(self) -> str:
        return f"OSError(code={self.code}, retryable={self.retryable}, node={self.node_id})"


# ============================================================
# 便捷工厂函数
# ============================================================

def node_not_found(node_id: str) -> OSError:
    return OSError(ErrorCode.NODE_001, f"节点未找到: {node_id}",
                   retryable=False, node_id=node_id)


def node_not_registered(node_id: str) -> OSError:
    return OSError(ErrorCode.NODE_004, f"节点未注册: {node_id}",
                   retryable=False, node_id=node_id)


def exec_timeout(node_id: str, timeout_ms: int) -> OSError:
    return OSError(ErrorCode.EXEC_001, f"执行超时: {timeout_ms}ms",
                   retryable=True, node_id=node_id)


def exec_failed(node_id: str, reason: str) -> OSError:
    return OSError(ErrorCode.EXEC_002, f"执行失败: {reason}",
                   retryable=True, node_id=node_id)


def data_invalid(node_id: str, field: str, reason: str) -> OSError:
    return OSError(ErrorCode.DATA_001, f"输入校验失败 [{field}]: {reason}",
                   retryable=False, node_id=node_id)


def orch_cycle_detected(cycle: str) -> OSError:
    return OSError(ErrorCode.ORCH_001, f"检测到循环依赖: {cycle}",
                   retryable=False)


def orch_budget_exceeded(budget: int, used: int) -> OSError:
    return OSError(ErrorCode.ORCH_004, f"预算超限: {used}/{budget}",
                   retryable=False)
