"""
Dreambuddy OS — Adapters 适配器层

提供:
    - BaseAdapter:       适配器基类
    - AdapterRegistry:   适配器注册表（多适配器分发）
    - FunctionAdapter:   函数适配器（本地函数 → Node）
    - SkillAdapter:      SKILL 适配器（SKILL.md → Node）
    - APIAdapter:        API 适配器（HTTP API → Node）
    - get_default_adapter_registry: 获取默认适配器注册表
"""

from .base import BaseAdapter, AdapterRegistry, get_default_adapter_registry
from .function_adapter import FunctionAdapter, FunctionNode
from .skill_adapter import SkillAdapter, SkillNode, parse_skill_metadata
from .api_adapter import APIAdapter, APINode

__all__ = [
    "BaseAdapter", "AdapterRegistry", "get_default_adapter_registry",
    "FunctionAdapter", "FunctionNode",
    "SkillAdapter", "SkillNode", "parse_skill_metadata",
    "APIAdapter", "APINode",
]
