"""
Dreambuddy OS — 适配器基类

适配器将外部能力（SKILL / API / 本地函数）统一包装为 Node，
使 OS 内核无需关心能力的具体实现方式。

设计:
    - Adapter (ABC)    在 shared/interfaces.py — 纯接口
    - BaseAdapter       在本文件 — 带通用工具方法
    - SkillAdapter      将 SKILL.md 包装为 Node
    - APIAdapter        将 HTTP API 包装为 Node
    - FunctionAdapter   将本地函数包装为 Node
"""

from __future__ import annotations

from abc import ABC
from typing import Any, Dict, Optional

from dreamos.shared.interfaces import Adapter, Node
from dreamos.shared.state import State, NodeResult, NodeStatus
from ..registry.base import BaseNode


class BaseAdapter(Adapter, ABC):
    """适配器基类 — 提供通用工具方法

    子类只需实现:
        - can_handle(config) → bool
        - to_node(config) → Node
    """

    adapter_type: str = "base"

    def __init__(self, **kwargs):
        self._options = kwargs

    @property
    def options(self) -> Dict[str, Any]:
        return self._options


# ============================================================
# 适配器管理器 — 多适配器分发
# ============================================================

class AdapterRegistry:
    """适配器注册表 — 管理多个 Adapter，自动分发

    用法:
        reg = AdapterRegistry()
        reg.register(FunctionAdapter())
        reg.register(SkillAdapter())
        reg.register(APIAdapter())

        node = reg.to_node({"type": "function", "handler": my_func})
    """

    def __init__(self):
        self._adapters: list[BaseAdapter] = []

    def register(self, adapter: BaseAdapter) -> "AdapterRegistry":
        """注册适配器"""
        self._adapters.append(adapter)
        return self

    def get(self, adapter_type: str) -> Optional[BaseAdapter]:
        """按类型获取适配器"""
        for adapter in self._adapters:
            if getattr(adapter, "adapter_type", "") == adapter_type:
                return adapter
        return None

    def to_node(self, config: Dict[str, Any]) -> Optional[Node]:
        """根据配置找到合适的适配器，转换为 Node

        Returns:
            Node 或 None（无适配器可处理）
        """
        for adapter in self._adapters:
            if adapter.can_handle(config):
                return adapter.to_node(config)
        return None

    def can_handle(self, config: Dict[str, Any]) -> bool:
        """是否有适配器能处理此配置"""
        return any(a.can_handle(config) for a in self._adapters)

    def list_adapters(self) -> list[BaseAdapter]:
        return list(self._adapters)

    def __len__(self) -> int:
        return len(self._adapters)


# ============================================================
# 默认适配器注册表
# ============================================================

_default_adapter_registry: Optional[AdapterRegistry] = None


def get_default_adapter_registry() -> AdapterRegistry:
    """获取默认适配器注册表（单例）"""
    global _default_adapter_registry
    if _default_adapter_registry is None:
        _default_adapter_registry = AdapterRegistry()
        from .function_adapter import FunctionAdapter
        from .skill_adapter import SkillAdapter
        from .api_adapter import APIAdapter
        _default_adapter_registry.register(FunctionAdapter())
        _default_adapter_registry.register(SkillAdapter())
        _default_adapter_registry.register(APIAdapter())
    return _default_adapter_registry
