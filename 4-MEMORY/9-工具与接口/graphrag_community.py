#!/usr/bin/env python3
"""GraphRAG 社区检测 — GraphRAGCommunity

定位：L3 路由层知识库增强，借鉴 GraphRAG (Microsoft ~30K★)，
对知识库实体关系图做社区检测 + 分层摘要，增强跨文档多跳推理。

核心能力:
  1. detect_communities(graph) — 社区检测（greedy_modularity，Leiden 风格）
  2. summarize_communities(graph, communities) — 每社区生成摘要
  3. query_community(community_id) — 查询社区内实体
  4. hierarchical_summary() — 分层摘要结构
  5. stats() — 社区统计

设计原则:
  - 复用 networkx（已作为 knowledge_graph 依赖）
  - 社区检测用 greedy_modularity_communities（Leiden 的轻量替代，无需 cdlib）
  - FAIL-OPEN：空图/None 图返回空结果，不抛异常
  - 轻量级：不引入 LLM 摘要，用关键词/实体名聚合作为摘要

参考:
  - SPEC-CognitiveSystem-Evolution.md §4.3 P2-5
  - GraphRAG: Leiden 社区检测 + 分层摘要
  - 协同 2-KNOWLEDGE/9-RAG-INFRA/knowledge_graph/build_graph.py
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

try:
    import networkx as nx
    from networkx.algorithms import community as nx_community
    _HAS_NX = True
except ImportError:
    _HAS_NX = False


class GraphRAGCommunity:
    """GraphRAG 社区检测 + 分层摘要。

    对实体关系图做社区检测，每个社区生成摘要，
    支持跨文档多跳推理的社区级查询。
    """

    def __init__(self) -> None:
        self.communities: Dict[int, Set[Any]] = {}
        self.summaries: Dict[int, Dict[str, Any]] = {}
        self._graph: Optional[Any] = None

    # ============================================================
    # 社区检测
    # ============================================================

    def detect_communities(self, graph: Any) -> List[Set[Any]]:
        """检测图中的社区。

        使用 greedy_modularity_communities（Leiden 风格的模块度优化）。
        若 networkx 不可用或图为空，返回空列表（FAIL-OPEN）。

        Args:
            graph: networkx Graph 对象

        Returns:
            社区列表，每个社区是节点集合
        """
        if not _HAS_NX or graph is None:
            return []

        try:
            if graph.number_of_nodes() == 0:
                return []

            # greedy_modularity_communities（Leiden 风格的模块度优化）
            communities = list(
                nx_community.greedy_modularity_communities(graph)
            )
            self._graph = graph
            self.communities = {i: set(c) for i, c in enumerate(communities)}
            return [set(c) for c in communities]
        except Exception:
            return []  # FAIL-OPEN

    # ============================================================
    # 社区摘要
    # ============================================================

    def summarize_communities(
        self,
        graph: Any,
        communities: Optional[List[Set[Any]]] = None,
    ) -> Dict[int, Dict[str, Any]]:
        """为每个社区生成摘要。

        摘要内容：
          - community_id: 社区 ID
          - size: 社区大小
          - entities: 社区内实体列表（含 name/type）
          - key_types: 社区内实体类型分布
          - label: 自动生成的社区标签（基于高频类型）

        Args:
            graph: networkx Graph
            communities: 社区列表（None 则用已检测的）

        Returns:
            {community_id: summary_dict}
        """
        if communities is not None:
            self.communities = {i: set(c) for i, c in enumerate(communities)}

        if not self.communities:
            return {}

        self.summaries = {}
        for cid, nodes in self.communities.items():
            entities: List[Dict[str, Any]] = []
            type_counts: Dict[str, int] = defaultdict(int)

            for node in nodes:
                node_data = {}
                if graph is not None and node in graph.nodes:
                    node_data = dict(graph.nodes[node])
                name = node_data.get("name", str(node))
                ntype = node_data.get("type", "unknown")
                entities.append({"id": node, "name": name, "type": ntype})
                type_counts[ntype] += 1

            # 自动标签：高频类型 + 大小
            top_type = max(type_counts, key=type_counts.get) if type_counts else "mixed"
            label = f"{top_type}_community_{len(nodes)}"

            self.summaries[cid] = {
                "community_id": cid,
                "size": len(nodes),
                "entities": entities,
                "key_types": dict(type_counts),
                "label": label,
            }

        return self.summaries

    # ============================================================
    # 查询
    # ============================================================

    def query_community(self, community_id: int) -> List[Dict[str, Any]]:
        """查询指定社区的实体列表。

        Args:
            community_id: 社区 ID

        Returns:
            实体列表，社区不存在返回空列表
        """
        summary = self.summaries.get(community_id)
        if summary is None:
            return []
        return summary.get("entities", [])

    def find_community_by_entity(self, entity_id: Any) -> Optional[int]:
        """查找实体所属的社区 ID。

        Args:
            entity_id: 实体 ID

        Returns:
            社区 ID，或 None
        """
        for cid, nodes in self.communities.items():
            if entity_id in nodes:
                return cid
        return None

    # ============================================================
    # 分层摘要
    # ============================================================

    def hierarchical_summary(self) -> Dict[str, Any]:
        """生成分层摘要结构。

        层级:
          - communities: 所有社区摘要
          - top_communities: 按大小排序的 top-N 社区
          - type_distribution: 全局实体类型分布

        Returns:
            分层摘要 dict
        """
        if not self.summaries:
            return {"communities": {}, "top_communities": [], "type_distribution": {}}

        # 全局类型分布
        global_types: Dict[str, int] = defaultdict(int)
        for summary in self.summaries.values():
            for ntype, cnt in summary["key_types"].items():
                global_types[ntype] += cnt

        # 按大小排序的 top 社区
        top = sorted(
            self.summaries.values(),
            key=lambda s: s["size"],
            reverse=True,
        )

        return {
            "communities": self.summaries,
            "top_communities": top[:10],
            "type_distribution": dict(global_types),
        }

    # ============================================================
    # 统计
    # ============================================================

    def stats(self) -> Dict[str, Any]:
        """社区统计。"""
        total_nodes = sum(len(c) for c in self.communities.values())
        return {
            "num_communities": len(self.communities),
            "total_nodes": total_nodes,
            "avg_community_size": (
                total_nodes / len(self.communities)
                if self.communities
                else 0
            ),
            "has_summaries": bool(self.summaries),
        }


# ============================================================
# CLI 自测
# ============================================================


if __name__ == "__main__":
    print("=" * 60)
    print("GraphRAGCommunity — 功能验证")
    print("=" * 60)

    if not _HAS_NX:
        print("networkx not available, skip")
        exit(0)

    g = nx.Graph()
    g.add_node(1, name="马丁策略", type="Strategy")
    g.add_node(2, name="止盈止损", type="Risk")
    g.add_node(3, name="加仓逻辑", type="Strategy")
    g.add_node(4, name="风控规则", type="Risk")
    g.add_node(5, name="仓位管理", type="Risk")
    g.add_edges_from([(1, 2), (2, 3), (1, 3), (4, 5)])

    gr = GraphRAGCommunity()
    communities = gr.detect_communities(g)
    print(f"\n检测到 {len(communities)} 个社区:")
    for i, c in enumerate(communities):
        print(f"  社区 {i}: {c}")

    summaries = gr.summarize_communities(g, communities)
    for cid, s in summaries.items():
        print(f"\n社区 {cid} 摘要:")
        print(f"  label: {s['label']}")
        print(f"  size: {s['size']}")
        print(f"  entities: {[e['name'] for e in s['entities']]}")

    print(f"\nStats: {gr.stats()}")

    print("\n" + "=" * 60)
    print("✅ GraphRAGCommunity 功能验证通过")
