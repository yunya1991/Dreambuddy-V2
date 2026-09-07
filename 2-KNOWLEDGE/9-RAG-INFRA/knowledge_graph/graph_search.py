# -*- coding: utf-8 -*-
"""图谱检索：从持久化图谱加载，BFS 搜索实体邻域。

支持多跳检索与关系类型过滤。FAIL-OPEN：实体不存在返回空结果，
图谱不存在或加载失败返回空。
"""

import pickle
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional

import networkx as nx

try:
    from .schema import DEFAULT_GRAPH_PATH
except ImportError:  # 直接以脚本运行时
    from schema import DEFAULT_GRAPH_PATH


def _load_graph(graph_path) -> Optional[nx.DiGraph]:
    """加载持久化图谱，失败返回 None（FAIL-OPEN）。"""
    graph_path = Path(graph_path) if graph_path else DEFAULT_GRAPH_PATH
    if not graph_path.exists():
        return None
    try:
        with open(graph_path, "rb") as fp:
            obj = pickle.load(fp)
        if isinstance(obj, nx.DiGraph):
            return obj
        return None
    except Exception:
        return None


def _find_center(graph: nx.DiGraph, entity: str) -> Optional[str]:
    """按名称定位中心节点：先精确匹配，再忽略大小写。"""
    if not entity:
        return None
    # 精确名称匹配
    for nid, data in graph.nodes(data=True):
        if data.get("name") == entity:
            return nid
    # 忽略大小写匹配
    ent_lower = entity.lower()
    for nid, data in graph.nodes(data=True):
        name = data.get("name", "")
        if name and name.lower() == ent_lower:
            return nid
    # 退化：按节点 id 末段匹配（如传入 "11-易经推理系统" 命中 Module:11-易经推理系统）
    for nid in graph.nodes:
        if nid.endswith(":" + entity) or nid == entity:
            return nid
    return None


def _adjacent(graph: nx.DiGraph, node: str):
    """生成 (邻居, 关系, 方向) 三元组：out 方向 + in 方向。"""
    # 出边：node -> nbr
    for nbr, data in graph[node].items():
        rels = data.get("relations") or [data.get("relation")]
        for rel in rels:
            if rel:
                yield nbr, rel, "out"
    # 入边：nbr -> node
    for nbr, data in graph.pred[node].items():
        rels = data.get("relations") or [data.get("relation")]
        for rel in rels:
            if rel:
                yield nbr, rel, "in"


def graph_search(entity: str, hops: int = 2,
                 relation_filter: Optional[List[str]] = None,
                 graph_path=None) -> Dict:
    """在图谱中 BFS 检索实体的多跳邻域。

    Args:
        entity: 中心实体名称（如 "11-易经推理系统"）。
        hops: BFS 搜索跳数（默认 2）。
        relation_filter: 仅遍历/返回这些关系类型，None 表示不过滤。
        graph_path: 图谱持久化路径，默认 DEFAULT_GRAPH_PATH。

    Returns:
        {"center_node": {...}|None, "neighbors": [...], "paths": [...]}
        - center_node: 中心节点信息（实体不存在则为 None）
        - neighbors: 邻居列表，每项含 node/type/name/relation/direction/hops
        - paths: 到各邻居的节点路径（id 序列）
        图谱不存在或实体不存在时返回空结构（FAIL-OPEN）。
    """
    empty = {"center_node": None, "neighbors": [], "paths": []}

    graph = _load_graph(graph_path)
    if graph is None:
        return empty  # FAIL-OPEN：图谱不存在

    center = _find_center(graph, entity)
    if center is None:
        return empty  # FAIL-OPEN：实体不存在

    center_data = graph.nodes[center]
    center_node = {
        "id": center,
        "name": center_data.get("name", center),
        "type": center_data.get("type", ""),
        "source_files": center_data.get("source_files", []),
    }

    # BFS（按跳数扩展，考虑出入双向）
    dist = {center: 0}
    paths = {center: [center]}
    neighbors: List[Dict] = []
    visited_edges = set()  # 去重同一 (邻居, 关系) 组合
    queue = deque([center])

    while queue:
        cur = queue.popleft()
        if dist[cur] >= hops:
            continue
        for nbr, rel, direction in _adjacent(graph, cur):
            if relation_filter and rel not in relation_filter:
                continue
            # 未访问过的邻居入队
            if nbr not in dist:
                dist[nbr] = dist[cur] + 1
                paths[nbr] = paths[cur] + [nbr]
                nbr_data = graph.nodes[nbr]
                key = (nbr, rel)
                if key not in visited_edges:
                    visited_edges.add(key)
                    neighbors.append({
                        "id": nbr,
                        "name": nbr_data.get("name", nbr),
                        "type": nbr_data.get("type", ""),
                        "relation": rel,
                        "direction": direction,
                        "hops": dist[nbr],
                    })
                if dist[nbr] < hops:
                    queue.append(nbr)
            elif dist[nbr] > dist[cur] + 1:
                dist[nbr] = dist[cur] + 1
                paths[nbr] = paths[cur] + [nbr]

    # 路径输出（排除中心节点自身的平凡路径）
    out_paths = [
        {"path": paths[nid], "hops": dist[nid]}
        for nid in paths if nid != center
    ]

    return {
        "center_node": center_node,
        "neighbors": neighbors,
        "paths": out_paths,
    }


if __name__ == "__main__":
    import sys
    import json

    q = sys.argv[1] if len(sys.argv) > 1 else "11-易经推理系统"
    h = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    result = graph_search(q, hops=h)
    print(json.dumps(result, ensure_ascii=False, indent=2))
