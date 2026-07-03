"""
DreamOS A层 — 节点选择器

职责:
    1. 根据 IntentResult 选择合适的链路 (A/C/F)
    2. 从 Registry 中选出该链路的节点
    3. 根据意图置信度和扩展节点列表决定包含哪些节点
    4. 过滤不存在或不适用的节点

选择策略:
    - 置信度高 (>=0.7): 精简模式，只选必须节点
    - 置信度中 (0.4-0.7): 标准模式，选必须 + 高优节点
    - 置信度低 (<0.4): 完整模式，选全部可用节点 + 扩展节点
"""

from __future__ import annotations

from typing import List, Optional, Dict, Any

from dreamos.shared.interfaces import Node
from dreamos.shared.state import State
from dreamos.registry.node_registry import NodeRegistry, get_default_registry

from .types import ChainSpec, NodeMeta, STANDARD_CHAINS


class NodeSelector:
    """节点选择器 — 从 Registry 中选出执行所需的节点

    用法:
        selector = NodeSelector(registry)
        metas = selector.select(
            chain="A",
            extend_nodes=["F1"],
            include_optional=True,
        )
    """

    def __init__(self, registry: Optional[NodeRegistry] = None):
        self._registry = registry or get_default_registry()

    def select(self,
               chain: str = "A",
               base_chain: Optional[List[str]] = None,
               extend_nodes: Optional[List[str]] = None,
               intent_confidence: float = 0.5,
               include_optional: Optional[bool] = None) -> List[NodeMeta]:
        """选择节点

        Args:
            chain: 主链 ID (A/C/F)
            base_chain: S 层推荐的基础链节点序列
            extend_nodes: S 层推荐的扩展节点
            intent_confidence: 意图置信度，影响选择策略
            include_optional: 是否包含可选节点 (None=自动按置信度决定)

        Returns:
            List[NodeMeta]: 选中的节点元信息列表
        """
        # 获取链路规格
        chain_spec = STANDARD_CHAINS.get(chain, STANDARD_CHAINS["A"])

        # 确定基础节点序列
        planned_ids = list(base_chain) if base_chain else list(chain_spec.node_ids)

        # 合并扩展节点
        if extend_nodes:
            for nid in extend_nodes:
                if nid not in planned_ids:
                    planned_ids.append(nid)

        # 自动决定是否包含可选节点
        if include_optional is None:
            include_optional = intent_confidence < 0.7

        if include_optional:
            for nid in chain_spec.optional_nodes:
                if nid not in planned_ids:
                    planned_ids.append(nid)

        # 从 Registry 中查找节点，构建 NodeMeta
        metas: List[NodeMeta] = []
        missing: List[str] = []

        for nid in planned_ids:
            node = self._registry.get(nid)
            if node is None:
                missing.append(nid)
                continue

            meta = NodeMeta(
                node_id=node.node_id,
                name=node.name,
                chain=node.chain,
                priority=self._determine_priority(nid, chain_spec),
                estimated_latency_ms=node.estimated_latency_ms,
                estimated_tokens=node.estimated_tokens,
                tags=list(node.tags or []),
            )
            metas.append(meta)

        return metas

    def _determine_priority(self, node_id: str, chain_spec: ChainSpec) -> int:
        """确定节点优先级

        Returns:
            0=必须, 1=高优, 2=可选
        """
        if node_id in chain_spec.node_ids:
            return 0  # 主链节点是必须的
        if node_id in chain_spec.optional_nodes:
            return 2  # 可选节点
        return 1  # 扩展节点是高优

    def get_chain_spec(self, chain: str) -> ChainSpec:
        """获取链路规格"""
        return STANDARD_CHAINS.get(chain, STANDARD_CHAINS["A"])

    def list_available(self, chain: Optional[str] = None) -> List[Dict[str, Any]]:
        """列出 Registry 中可用的节点"""
        nodes = self._registry.list_nodes(chain=chain)
        return [
            {
                "node_id": n.node_id,
                "name": n.name,
                "chain": n.chain,
                "estimated_tokens": n.estimated_tokens,
            }
            for n in nodes
        ]
