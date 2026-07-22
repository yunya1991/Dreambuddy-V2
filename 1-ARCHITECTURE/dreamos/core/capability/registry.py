"""
Dream OS — 能力域注册表 (CapabilityRegistry)

管理多个能力域的注册、发现、查询，是内核与业务能力之间的"设备管理器"。

类比:
    - 操作系统: 设备管理器 / 驱动注册表
    - 微服务: 服务注册中心（如 Consul/Eureka）
    - 插件系统: Plugin Registry

设计原则:
    - 单一真相源: 一个 capability_id 只能注册一次
    - 懒加载: 能力域节点按需注册，避免启动时全部加载
    - 可观测: 支持列表查询、健康检查、统计信息
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import threading
from typing import Dict, List, Optional, Any, Protocol

from dreamos.registry import NodeRegistry


class CapabilityDomain(Protocol):
    """能力域接口协议

    任何能力域都必须实现此接口，才能被 CapabilityRegistry 管理。
    内核通过此协议与能力域交互，不依赖具体实现。
    """

    capability_id: str
    name: str
    description: str
    version: str
    supported_intents: List[str]
    tags: List[str]

    def register(self, registry: Optional[NodeRegistry] = None) -> int:
        """将能力域的节点注册到内核注册表"""
        ...

    def can_handle(self, intent_type: str, keywords: Optional[List[str]] = None) -> float:
        """判断能否处理给定意图，返回匹配置信度 (0.0 ~ 1.0)"""
        ...

    def info(self) -> Dict[str, Any]:
        """返回能力域元信息"""
        ...


class CapabilityRegistry:
    """能力域注册表 — 多能力域的统一管理器

    用法:
        registry = CapabilityRegistry()

        # 手动注册
        from dreamos.capabilities.trading import TradingCapability
        registry.register(TradingCapability())

        # 自动发现
        registry.discover_and_register("dreamos.capabilities")

        # 查询
        cap = registry.get("trading")
        all_caps = registry.list_capabilities()

        # 根据意图选择
        candidates = registry.find_by_intent("TREND_FOLLOWING")
    """

    def __init__(self):
        self._capabilities: Dict[str, CapabilityDomain] = {}
        self._lock = threading.RLock()
        self._node_registry: Optional[NodeRegistry] = None

    # ── 注册与注销 ────────────────────────────────

    def register(self, capability: CapabilityDomain) -> bool:
        """注册能力域

        Args:
            capability: 能力域实例，必须实现 CapabilityDomain 协议

        Returns:
            是否注册成功（已存在则返回 False）
        """
        cap_id = capability.capability_id
        with self._lock:
            if cap_id in self._capabilities:
                return False
            self._capabilities[cap_id] = capability

        # 自动将能力域节点注册到节点注册表
        if self._node_registry is not None:
            try:
                capability.register(registry=self._node_registry)
            except Exception:
                pass  # 允许注册失败（能力域可能不依赖节点）

        return True

    def unregister(self, capability_id: str) -> bool:
        """注销能力域"""
        with self._lock:
            if capability_id in self._capabilities:
                del self._capabilities[capability_id]
                return True
            return False

    def get(self, capability_id: str) -> Optional[CapabilityDomain]:
        """按 ID 获取能力域"""
        with self._lock:
            return self._capabilities.get(capability_id)

    def list_capabilities(self) -> List[CapabilityDomain]:
        """列出所有已注册的能力域"""
        with self._lock:
            return list(self._capabilities.values())

    def list_ids(self) -> List[str]:
        """列出所有能力域 ID"""
        with self._lock:
            return list(self._capabilities.keys())

    # ── 节点注册表关联 ────────────────────────────

    def attach_node_registry(self, registry: NodeRegistry) -> None:
        """关联内核节点注册表

        关联后，新注册的能力域会自动将其节点注册到 NodeRegistry。
        """
        self._node_registry = registry

    def register_all_nodes(self) -> int:
        """将所有已注册能力域的节点注册到 NodeRegistry

        Returns:
            注册的节点总数
        """
        if self._node_registry is None:
            raise RuntimeError("未关联 NodeRegistry，请先调用 attach_node_registry()")

        total = 0
        for cap in self.list_capabilities():
            try:
                count = cap.register(registry=self._node_registry)
                total += count
            except Exception:
                pass
        return total

    # ── 意图匹配 ──────────────────────────────────

    def find_by_intent(self, intent_type: str,
                       keywords: Optional[List[str]] = None) -> List[tuple]:
        """根据意图类型查找匹配的能力域

        Returns:
            按匹配置信度降序排列的 (capability, score) 列表
        """
        results: List[tuple] = []
        for cap in self.list_capabilities():
            score = cap.can_handle(intent_type, keywords=keywords)
            if score > 0:
                results.append((cap, score))

        # 按置信度降序排列
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def best_match(self, intent_type: str,
                   keywords: Optional[List[str]] = None) -> Optional[tuple]:
        """查找最匹配的能力域

        Returns:
            (capability, score) 或 None
        """
        matches = self.find_by_intent(intent_type, keywords=keywords)
        return matches[0] if matches else None

    # ── 自动发现 ──────────────────────────────────

    def discover_and_register(self, package_path: str) -> int:
        """自动发现并注册指定包路径下的能力域

        扫描规则:
            - 遍历 package_path 下的所有子包
            - 查找实现 CapabilityDomain 协议的类
            - 实例化并注册

        Args:
            package_path: Python 包路径，如 "dreamos.capabilities"

        Returns:
            发现并注册的能力域数量
        """
        count = 0
        try:
            package = importlib.import_module(package_path)
            package_dir = getattr(package, "__path__", [None])[0]
            if not package_dir:
                return 0
        except ImportError:
            return 0

        for _, module_name, is_pkg in pkgutil.iter_modules([package_dir]):
            if not is_pkg:
                continue

            full_module = f"{package_path}.{module_name}"
            try:
                module = importlib.import_module(full_module)
            except Exception:
                continue

            # 查找模块中实现 CapabilityDomain 的类
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if name == "CapabilityDomain":
                    continue
                # 简单启发式: 有 capability_id 和 register 方法
                if hasattr(obj, "capability_id") and hasattr(obj, "register"):
                    try:
                        instance = obj()
                        if self.register(instance):
                            count += 1
                    except Exception:
                        pass

        return count

    # ── 统计与可观测性 ────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """注册表摘要"""
        with self._lock:
            caps = list(self._capabilities.values())

        return {
            "total_capabilities": len(caps),
            "capability_ids": [c.capability_id for c in caps],
            "capabilities": [
                {
                    "id": c.capability_id,
                    "name": c.name,
                    "version": c.version,
                    "supported_intents": len(getattr(c, "supported_intents", [])),
                }
                for c in caps
            ],
        }

    def __len__(self) -> int:
        return len(self._capabilities)

    def __contains__(self, capability_id: str) -> bool:
        return capability_id in self._capabilities

    def __repr__(self) -> str:
        return f"<CapabilityRegistry total={len(self)} ids={self.list_ids()}>"


# ============================================================
# 全局默认能力域注册表（单例）
# ============================================================

_default_cap_registry: Optional[CapabilityRegistry] = None


def get_default_capability_registry() -> CapabilityRegistry:
    """获取全局默认能力域注册表"""
    global _default_cap_registry
    if _default_cap_registry is None:
        _default_cap_registry = CapabilityRegistry()
    return _default_cap_registry
