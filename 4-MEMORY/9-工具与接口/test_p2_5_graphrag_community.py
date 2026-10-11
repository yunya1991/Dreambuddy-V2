"""P2-5 GraphRAG 社区检测 TDD RED 测试

借鉴 GraphRAG (Microsoft ~30K★)，对知识库实体关系图做：
  1. 社区检测（Leiden/greedy_modularity 风格）
  2. 分层摘要（每社区生成摘要）
  3. 社区内实体聚合查询

RED 契约:
  1. graphrag_community 模块不存在 → ImportError
  2. GraphRAGCommunity 类不存在
  3. detect_communities() 不存在
  4. summarize_communities() 不存在
  5. query_community() 不存在
  6. CognitiveLoopEntry 无 graphrag 属性

参考: SPEC-CognitiveSystem-Evolution.md §4.3 P2-5
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


class TestGraphRAGCommunityCore:
    """GraphRAG 社区检测核心能力。"""

    def test_import_graphrag(self):
        """RED: graphrag_community 模块可导入。"""
        from graphrag_community import GraphRAGCommunity  # noqa: F401

    def test_detect_communities_two_groups(self):
        """RED: 两个明显社区的图应被正确分组。"""
        import networkx as nx

        from graphrag_community import GraphRAGCommunity

        g = nx.Graph()
        # 社区 A: 1-2-3 紧密连接
        g.add_edges_from([(1, 2), (2, 3), (1, 3)])
        # 社区 B: 4-5-6 紧密连接
        g.add_edges_from([(4, 5), (5, 6), (4, 6)])
        # 弱连接
        g.add_edge(3, 4)

        gr = GraphRAGCommunity()
        communities = gr.detect_communities(g)

        assert len(communities) >= 2
        # 社区 1 应包含 1,2,3
        community_sets = [set(c) for c in communities]
        found_a = any({1, 2, 3}.issubset(c) for c in community_sets)
        found_b = any({4, 5, 6}.issubset(c) for c in community_sets)
        assert found_a and found_b

    def test_detect_communities_returns_list_of_sets(self):
        """RED: detect_communities() 返回社区列表（每个是节点集合）。"""
        import networkx as nx

        from graphrag_community import GraphRAGCommunity

        g = nx.Graph()
        g.add_edges_from([(1, 2), (2, 3), (3, 1)])
        gr = GraphRAGCommunity()
        communities = gr.detect_communities(g)

        assert isinstance(communities, list)
        assert len(communities) >= 1
        assert all(isinstance(c, (set, frozenset, list)) for c in communities)

    def test_summarize_communities(self):
        """RED: summarize_communities() 为每个社区生成摘要。"""
        import networkx as nx

        from graphrag_community import GraphRAGCommunity

        g = nx.Graph()
        g.add_node(1, name="马丁策略", type="Strategy")
        g.add_node(2, name="止盈止损", type="Risk")
        g.add_node(3, name="马丁加仓", type="Strategy")
        g.add_edges_from([(1, 2), (2, 3), (1, 3)])

        gr = GraphRAGCommunity()
        communities = gr.detect_communities(g)
        summaries = gr.summarize_communities(g, communities)

        assert isinstance(summaries, dict)
        assert len(summaries) == len(communities)
        # 每个摘要应含 community_id 和节点信息
        for cid, summary in summaries.items():
            assert "community_id" in summary
            assert "size" in summary
            assert "entities" in summary

    def test_query_community(self):
        """RED: query_community() 返回指定社区的实体列表。"""
        import networkx as nx

        from graphrag_community import GraphRAGCommunity

        g = nx.Graph()
        g.add_node(1, name="马丁")
        g.add_node(2, name="止盈")
        g.add_edges_from([(1, 2)])

        gr = GraphRAGCommunity()
        communities = gr.detect_communities(g)
        gr.summarize_communities(g, communities)

        # 查询第一个社区
        first_cid = list(gr.communities.keys())[0]
        entities = gr.query_community(first_cid)
        assert len(entities) >= 1

    def test_hierarchical_summary(self):
        """RED: hierarchical_summary() 生成分层摘要结构。"""
        import networkx as nx

        from graphrag_community import GraphRAGCommunity

        g = nx.Graph()
        g.add_edges_from([(1, 2), (2, 3), (4, 5), (5, 6)])

        gr = GraphRAGCommunity()
        communities = gr.detect_communities(g)
        gr.summarize_communities(g, communities)

        hierarchy = gr.hierarchical_summary()
        assert isinstance(hierarchy, dict)
        assert "communities" in hierarchy

    def test_failopen_empty_graph(self):
        """RED: 空图 → FAIL-OPEN 返回空列表。"""
        import networkx as nx

        from graphrag_community import GraphRAGCommunity

        g = nx.Graph()
        gr = GraphRAGCommunity()
        communities = gr.detect_communities(g)
        assert communities == []

    def test_failopen_none_graph(self):
        """RED: None 图 → FAIL-OPEN 返回空列表。"""
        from graphrag_community import GraphRAGCommunity

        gr = GraphRAGCommunity()
        communities = gr.detect_communities(None)
        assert communities == []

    def test_community_stats(self):
        """RED: stats() 返回社区统计信息。"""
        import networkx as nx

        from graphrag_community import GraphRAGCommunity

        g = nx.Graph()
        g.add_edges_from([(1, 2), (2, 3), (4, 5)])
        gr = GraphRAGCommunity()
        gr.detect_communities(g)
        stats = gr.stats()

        assert "num_communities" in stats
        assert "total_nodes" in stats


class TestCognitiveLoopEntryGraphRAG:
    """CognitiveLoopEntry P2-5 集成点。"""

    def test_graphrag_attribute_exists(self):
        """RED: CognitiveLoopEntry 应有 graphrag 属性。"""
        from cognitive_loop_entry import CognitiveLoopEntry

        import inspect

        src = inspect.getsource(CognitiveLoopEntry.__init__)
        assert "graphrag" in src
        assert "GraphRAGCommunity" in src
