"""
Dreambuddy OS — 节点注册表实现

NodeRegistry 是节点的唯一真相源:
    - 注册节点 (register)
    - 按 ID / chain / tag 查询
    - 支持动态注册和注销
    - 支持从 YAML 配置批量加载

设计原则:
    - 单一真相源: 一个 node_id 只能注册一次
    - 线程安全: 基本操作加锁
    - 可观测: list_nodes / summary 提供注册表视图
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional, Iterable

from dreamos.shared.interfaces import Node, Registry
from dreamos.shared.errors import ErrorCode, OSError
from dreamos.shared.capability import CapabilitySpec, CapabilityStatus, ProviderType


class NodeRegistry(Registry):
    """节点注册表 — 节点的唯一真相源

    用法:
        registry = NodeRegistry()
        registry.register(MyNode())
        node = registry.get("A0")
        a_chain_nodes = registry.list_nodes(chain="A")
    """

    def __init__(self):
        self._nodes: Dict[str, Node] = {}
        self._lock = threading.RLock()

    # ── Registry 接口实现 ───────────────────────────────

    def register(self, node: Node) -> None:
        """注册节点

        Raises:
            OSError: node_id 为空或已存在
        """
        if not node.node_id:
            raise OSError(ErrorCode.NODE_003, "节点 node_id 不能为空")

        with self._lock:
            if node.node_id in self._nodes:
                raise OSError(ErrorCode.NODE_002,
                               f"节点已存在: {node.node_id}（请先 unregister）",
                               node_id=node.node_id)
            self._nodes[node.node_id] = node

    def get(self, node_id: str) -> Optional[Node]:
        """按 ID 获取节点"""
        with self._lock:
            return self._nodes.get(node_id)

    def list_nodes(self, chain: Optional[str] = None,
                   tag: Optional[str] = None) -> List[Node]:
        """列出节点（可按 chain / tag 过滤）"""
        with self._lock:
            nodes = list(self._nodes.values())
        if chain:
            nodes = [n for n in nodes if n.chain == chain]
        if tag:
            nodes = [n for n in nodes if tag in (n.tags or [])]
        return nodes

    def unregister(self, node_id: str) -> bool:
        """注销节点"""
        with self._lock:
            if node_id in self._nodes:
                del self._nodes[node_id]
                return True
            return False

    def exists(self, node_id: str) -> bool:
        """节点是否存在"""
        with self._lock:
            return node_id in self._nodes

    # ── 扩展方法 ───────────────────────────────────────

    def register_many(self, nodes: Iterable[Node]) -> int:
        """批量注册，返回成功数量"""
        count = 0
        for node in nodes:
            try:
                self.register(node)
                count += 1
            except OSError:
                # 已存在则跳过
                pass
        return count

    def clear(self) -> int:
        """清空注册表，返回清理数量"""
        with self._lock:
            n = len(self._nodes)
            self._nodes.clear()
            return n

    def summary(self) -> Dict[str, int]:
        """注册表摘要"""
        with self._lock:
            nodes = list(self._nodes.values())
        chains: Dict[str, int] = {}
        for n in nodes:
            chains[n.chain or "?"] = chains.get(n.chain or "?", 0) + 1
        return {
            "total": len(nodes),
            **{f"chain_{k}": v for k, v in chains.items()},
        }

    # ── 能力查询 API（第3层细粒度能力）──────────────────

    def list_node_capabilities(self,
                               category: Optional[str] = None,
                               provider_type: Optional[str] = None,
                               status: Optional[str] = None) -> List[CapabilitySpec]:
        """列出所有节点声明的细粒度能力（第3层 CapabilitySpec）

        注意: 区别于第1层 CapabilityRegistry.list_capabilities()（返回 CapabilityDomain）。

        Args:
            category:      按能力域过滤 (trading/data/analysis/execution/integration)
            provider_type: 按提供者类型过滤 (node/subagent/exchange/subsystem)
            status:        按状态过滤 (available/degraded/unavailable)
        """
        with self._lock:
            nodes = list(self._nodes.values())

        caps: List[CapabilitySpec] = []
        for node in nodes:
            node_caps = getattr(node, "capabilities", None) or []
            for cap in node_caps:
                if category and cap.category != category:
                    continue
                if provider_type:
                    pt = cap.provider_type.value if isinstance(cap.provider_type, ProviderType) else str(cap.provider_type)
                    if pt != provider_type:
                        continue
                if status:
                    st = cap.status.value if isinstance(cap.status, CapabilityStatus) else str(cap.status)
                    if st != status:
                        continue
                caps.append(cap)
        return caps

    def get_node_capabilities(self, provider_id: str) -> List[CapabilitySpec]:
        """按提供者 ID 获取其声明的所有能力"""
        with self._lock:
            node = self._nodes.get(provider_id)
        if node is None:
            return []
        return list(getattr(node, "capabilities", None) or [])

    def find_nodes_by_capability(self, capability_id: str) -> List[Node]:
        """返回提供指定能力 ID 的所有节点（仅 status=available 的能力计入）"""
        with self._lock:
            nodes = list(self._nodes.values())

        matched: List[Node] = []
        for node in nodes:
            node_caps = getattr(node, "capabilities", None) or []
            for cap in node_caps:
                if cap.capability_id == capability_id and cap.status == CapabilityStatus.AVAILABLE:
                    matched.append(node)
                    break
        return matched

    def node_capability_summary(self) -> Dict[str, object]:
        """能力统计摘要（按 category / provider_type / status 分组）"""
        with self._lock:
            nodes = list(self._nodes.values())

        by_category: Dict[str, int] = {}
        by_provider_type: Dict[str, int] = {}
        by_status: Dict[str, int] = {}
        total = 0

        for node in nodes:
            for cap in (getattr(node, "capabilities", None) or []):
                total += 1
                by_category[cap.category] = by_category.get(cap.category, 0) + 1
                pt = cap.provider_type.value if isinstance(cap.provider_type, ProviderType) else str(cap.provider_type)
                by_provider_type[pt] = by_provider_type.get(pt, 0) + 1
                st = cap.status.value if isinstance(cap.status, CapabilityStatus) else str(cap.status)
                by_status[st] = by_status.get(st, 0) + 1

        return {
            "total": total,
            "by_category": by_category,
            "by_provider_type": by_provider_type,
            "by_status": by_status,
        }

    def update_node_capability_status(self,
                                      provider_id: str,
                                      status: str,
                                      reason: str = "") -> bool:
        """更新某提供者所有能力的 status

        Args:
            provider_id: 节点 ID（= capability 的 provider_id）
            status:      新状态 (available/degraded/unavailable)
            reason:      降级原因（status=degraded 时建议填写）

        Returns:
            是否更新成功（提供者不存在返回 False）
        """
        with self._lock:
            node = self._nodes.get(provider_id)
        if node is None:
            return False

        target_status = CapabilityStatus(status) if isinstance(status, str) else status
        for cap in (getattr(node, "capabilities", None) or []):
            cap.status = target_status
            if target_status == CapabilityStatus.DEGRADED:
                cap.degraded_reason = reason or cap.degraded_reason
            elif target_status == CapabilityStatus.AVAILABLE:
                cap.degraded_reason = ""
        return True

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, node_id: str) -> bool:
        return self.exists(node_id)

    def __repr__(self) -> str:
        return f"<NodeRegistry total={len(self)}>"


# ============================================================
# 全局默认注册表
# ============================================================

_default_registry: Optional[NodeRegistry] = None


def get_default_registry() -> NodeRegistry:
    """获取全局默认注册表（单例）"""
    global _default_registry
    if _default_registry is None:
        _default_registry = NodeRegistry()
    return _default_registry


def set_default_registry(registry: NodeRegistry) -> None:
    """设置全局默认注册表"""
    global _default_registry
    _default_registry = registry
