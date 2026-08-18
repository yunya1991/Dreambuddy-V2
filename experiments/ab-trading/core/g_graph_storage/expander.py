#!/usr/bin/env python3
"""
G层 - 图展开器

位置: experiments/ab-trading/core/g_graph_storage/expander.py

职责：
1. 正向展开 - B→A→C 三层展开
2. 从 Blueprint 展开为 Architecture
3. 从 Architecture 展开为 Chronicle
4. 支持增量展开

展开方向：
  正向展开: G.B → G.A → G.C
  回溯压缩: G.C → G.A → G.B
"""

import time
import copy
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from .types import (
    BlueprintGraph,
    ArchitectureGraph,
    ChronicleGraph,
    BNode,
    ANode,
    CNode,
    BEdge,
    AEdge,
    CEdge,
    NodeType,
    NodeStatus,
    ComponentType,
    NodeMetadata,
    NodeId,
    _gen_id,
)


# ============================================================
# 图展开器
# ============================================================

class GraphExpander:
    """图展开器

    实现正向展开：G.B → G.A → G.C
    """

    def __init__(self):
        pass

    def expand_blueprint_to_architecture(
        self,
        blueprint: BlueprintGraph,
    ) -> ArchitectureGraph:
        """
        B→A 展开：从 Blueprint 展开为 Architecture

        将每个 B 节点展开为对应的执行步骤
        """
        arch = ArchitectureGraph(
            blueprint_id=blueprint.id,
            name=f"{blueprint.name}_arch",
        )

        # 创建入口节点
        entry_id = "entry"
        entry_node = ANode(
            id=entry_id,
            name="入口",
            type=NodeType.STEP,
            metadata=NodeMetadata(status=NodeStatus.PENDING),
        )
        arch.add_node(entry_node)
        arch.entry_node_id = entry_id

        # 遍历 Blueprint 的节点
        current_parent = entry_id

        # 获取 B 节点映射
        b_nodes_ordered = self._get_bfs_order(blueprint)

        # 为每个 B 节点创建对应的 A 节点
        prev_id = entry_id
        for bnode in b_nodes_ordered:
            anode_id = f"a_{bnode.id}"
            anode = ANode(
                id=anode_id,
                name=bnode.name,
                type=NodeType.STEP,
                parent_bnode_id=bnode.id,
                metadata=copy.deepcopy(bnode.metadata),
                requires=[prev_id] if prev_id else [],
            )
            arch.add_node(anode)

            # 创建边
            if prev_id:
                edge = AEdge(
                    source=prev_id,
                    target=anode_id,
                    data_flow_type="control",
                )
                arch.add_edge(edge)

            prev_id = anode_id

        return arch

    def expand_architecture_to_chronicle(
        self,
        architecture: ArchitectureGraph,
        execution_id: Optional[str] = None,
    ) -> ChronicleGraph:
        """
        A→C 展开：从 Architecture 展开为 Chronicle

        为每个 A 节点创建执行记录
        """
        exec_id = execution_id or _gen_id("exec")

        chronicle = ChronicleGraph(
            architecture_id=architecture.id,
            execution_id=exec_id,
        )

        # 按拓扑顺序创建 C 节点
        topo_order = architecture.topological_sort()

        prev_id = None
        for anode_id in topo_order:
            anode = architecture.get_node(anode_id)
            if not anode:
                continue

            cnode = CNode(
                id=f"c_{anode.id}",
                architecture_node_id=anode.id,
                execution_id=exec_id,
                metadata=copy.deepcopy(anode.metadata),
            )
            chronicle.add_node(cnode)

            # 创建边
            if prev_id:
                edge = CEdge(
                    source=prev_id,
                    target=cnode.id,
                    data_keys=["previous_output"],
                )
                chronicle.add_edge(edge)

            prev_id = cnode.id

        return chronicle

    def expand_full(
        self,
        blueprint: BlueprintGraph,
        execution_id: Optional[str] = None,
    ) -> tuple[ArchitectureGraph, ChronicleGraph]:
        """
        完整展开：B → A → C

        Returns:
            (ArchitectureGraph, ChronicleGraph)
        """
        arch = self.expand_blueprint_to_architecture(blueprint)
        chronicle = self.expand_architecture_to_chronicle(arch, execution_id)
        return arch, chronicle

    def _get_bfs_order(self, blueprint: BlueprintGraph) -> List[BNode]:
        """BFS 遍历 Blueprint 节点"""
        if not blueprint.root_id:
            return list(blueprint.nodes.values())

        visited = set()
        order = []
        queue = [blueprint.root_id]

        while queue:
            node_id = queue.pop(0)
            if node_id in visited:
                continue
            visited.add(node_id)

            node = blueprint.get_node(node_id)
            if node:
                order.append(node)
                # 子节点入队
                for child_id in node.children:
                    if child_id not in visited:
                        queue.append(child_id)

        return order
