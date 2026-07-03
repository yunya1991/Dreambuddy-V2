"""
Dreambuddy OS — Registry 注册表层

提供:
    - BaseNode:        节点基类（带计时/错误处理）
    - NodeRegistry:    节点注册表实现
    - register_node:   装饰器，自动注册
    - node_metadata:   装饰器，设置元信息
    - get_default_registry: 获取全局默认注册表

扩展功能:
    - RegistryLoader:      从 YAML/配置批量加载节点
    - RegistryExtension:   版本管理 + 依赖检查
    - VersionedNodeMixin:  版本化节点 mixin
    - parse_version / compare_versions / satisfies_requirement

"""

from .base import BaseNode
from .node_registry import NodeRegistry, get_default_registry, set_default_registry
from .decorators import register_node, node_metadata
from .loader import RegistryLoader, load_from_yaml
from .version_manager import (
    RegistryExtension, VersionedNodeMixin,
    parse_version, compare_versions, satisfies_requirement,
    DependencyCheckResult,
)

__all__ = [
    # core
    "BaseNode",
    "NodeRegistry",
    "register_node",
    "node_metadata",
    "get_default_registry",
    "set_default_registry",
    # loader
    "RegistryLoader",
    "load_from_yaml",
    # version & dependency
    "RegistryExtension",
    "VersionedNodeMixin",
    "parse_version",
    "compare_versions",
    "satisfies_requirement",
    "DependencyCheckResult",
]
