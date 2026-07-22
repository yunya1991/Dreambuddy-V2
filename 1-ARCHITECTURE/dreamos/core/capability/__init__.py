"""
Dream OS — 能力域管理内核组件

提供能力域的注册、发现、路由等核心能力，是操作系统内核连接业务能力的标准接口。

核心组件:
    - CapabilityRegistry: 能力域注册表，管理多个能力域的生命周期
    - CapabilityRouter: 意图路由，根据意图选择最优能力域

设计原则:
    - 内核层只管理能力域的"元信息"和"路由"，不耦合具体业务
    - 能力域通过标准接口（register/can_handle/info）与内核交互
    - 支持动态发现和热插拔
"""

from __future__ import annotations

from .registry import CapabilityRegistry, CapabilityDomain
from .router import CapabilityRouter, RoutingResult

__all__ = [
    "CapabilityRegistry",
    "CapabilityDomain",
    "CapabilityRouter",
    "RoutingResult",
]
