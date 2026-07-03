"""
Dreambuddy OS — 节点注册装饰器

提供便捷的节点注册方式:
    - @register_node: 类装饰器，自动实例化并注册到默认注册表
    - @node_metadata: 元信息装饰器，设置 node_id/name/chain/tags

用法:
    @register_node
    class A0Node(BaseNode):
        node_id = "A0"
        name = "矛盾论分析"
        chain = "A"

        def execute_core(self, state):
            return NodeResult(...)

或带参数:
    @register_node(chain="A", tags=["research"])
    class A0Node(BaseNode):
        ...
"""

from __future__ import annotations

from typing import Any, Type, Optional, List

from .base import BaseNode
from .node_registry import get_default_registry


def register_node(cls: Optional[Type[BaseNode]] = None, *,
                  chain: Optional[str] = None,
                  tags: Optional[List[str]] = None,
                  registry=None):
    """类装饰器 — 自动注册节点

    Args:
        cls: 被装饰的类（BaseNode 子类）
        chain: 可选，覆盖类的 chain 属性
        tags: 可选，覆盖类的 tags 属性
        registry: 可选，目标注册表（默认全局注册表）

    用法:
        @register_node
        class A0Node(BaseNode): ...

        @register_node(chain="A", tags=["research"])
        class A0Node(BaseNode): ...
    """
    def _decorate(klass: Type[BaseNode]) -> Type[BaseNode]:
        # 覆盖元信息
        if chain is not None:
            klass.chain = chain
        if tags is not None:
            klass.tags = tags
        # 实例化并注册
        instance = klass()
        target_registry = registry or get_default_registry()
        target_registry.register(instance)
        return klass

    if cls is not None:
        # 无参调用: @register_node
        return _decorate(cls)
    # 带参调用: @register_node(chain="A")
    return _decorate


def node_metadata(node_id: str = "", name: str = "",
                  description: str = "", chain: str = "",
                  tags: Optional[List[str]] = None,
                  estimated_tokens: int = 0):
    """类装饰器 — 设置节点元信息（不自动注册）

    Args:
        node_id: 节点 ID
        name: 显示名
        description: 描述
        chain: 所属链 (A/C/F/G/T)
        tags: 标签列表
        estimated_tokens: 预估 token 消耗

    用法:
        @node_metadata(node_id="A0", name="矛盾论", chain="A", tags=["research"])
        class A0Node(BaseNode):
            def execute_core(self, state):
                ...
    """
    def decorator(cls: Type[BaseNode]) -> Type[BaseNode]:
        if node_id:
            cls.node_id = node_id
        if name:
            cls.name = name
        if description:
            cls.description = description
        if chain:
            cls.chain = chain
        if tags is not None:
            cls.tags = tags
        if estimated_tokens:
            cls.estimated_tokens = estimated_tokens
        return cls
    return decorator
