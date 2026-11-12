"""确定性 Personalized PageRank 与一跳/多跳邻域排序（SPEC-33-F §2.2）。

约束：
  - 零随机性：节点按字典序处理，初始向量均匀分布，teleport 只落在种子集。
  - 固定参数默认值 damping=0.85 / max_iter=50 / tol=1e-8（SPEC 硬性要求）。
  - 仅依赖标准库，不引入 networkx（Q2 决策）。
"""

from __future__ import annotations

from collections import deque
from typing import Any, Iterable

DEFAULT_DAMPING = 0.85
DEFAULT_MAX_ITER = 50
DEFAULT_TOL = 1e-8
DEFAULT_HOPS = 2


def personalized_pagerank(
    adjacency: dict[str, Iterable[str]],
    seeds: Iterable[str],
    damping: float = DEFAULT_DAMPING,
    max_iter: int = DEFAULT_MAX_ITER,
    tol: float = DEFAULT_TOL,
) -> dict[str, float]:
    """在邻接表上计算带种子偏置的 PageRank（确定性）。

    Args:
        adjacency: {节点: [出边节点...]}，出边可以指向未作为 key 的节点
        seeds: 种子节点（teleport 集），为空或全部不在图内时退化为均匀 teleport

    Returns:
        {节点: 归一化分数}，节点按字典序，分数保留 6 位小数
    """
    node_set: set[str] = set()
    out_edges: dict[str, list[str]] = {}
    for src, dsts in adjacency.items():
        node_set.add(src)
        cleaned = sorted({str(d) for d in dsts})
        out_edges[str(src)] = cleaned
        node_set.update(cleaned)
    nodes = sorted(node_set)
    if not nodes:
        return {}

    seed_list = sorted({str(s) for s in seeds if str(s) in node_set})
    if not seed_list:
        seed_list = list(nodes)
    teleport = {n: (1.0 / len(seed_list) if n in seed_list else 0.0) for n in nodes}

    n = len(nodes)
    rank = dict.fromkeys(nodes, 1.0 / n)
    for _ in range(max(1, int(max_iter))):
        new_rank = {node: (1.0 - damping) * teleport[node] for node in nodes}
        dangling_mass = 0.0
        for node in nodes:
            outs = out_edges.get(node) or []
            if outs:
                share = damping * rank[node] / len(outs)
                for dst in outs:
                    new_rank[dst] += share
            else:
                dangling_mass += rank[node]
        if dangling_mass:
            share = damping * dangling_mass / n
            for node in nodes:
                new_rank[node] += share
        delta = sum(abs(new_rank[node] - rank[node]) for node in nodes)
        rank = new_rank
        if delta < tol:
            break

    total = sum(rank.values()) or 1.0
    return {node: round(rank[node] / total, 6) for node in nodes}


def _undirected(adjacency: dict[str, Iterable[str]]) -> dict[str, set[str]]:
    neighbors: dict[str, set[str]] = {}
    for src, dsts in adjacency.items():
        neighbors.setdefault(str(src), set()).update(str(d) for d in dsts)
        for dst in dsts:
            neighbors.setdefault(str(dst), set()).add(str(src))
    return neighbors


def bounded_hop_distances(
    adjacency: dict[str, Iterable[str]],
    seeds: Iterable[str],
    hops: int = DEFAULT_HOPS,
) -> dict[str, int]:
    """从种子出发的双向 BFS（仅 import 图双向邻域），返回 {节点: 最小跳数}。"""
    neighbors = _undirected(adjacency)
    dist: dict[str, int] = {}
    queue: deque[tuple[str, int]] = deque()
    for seed in sorted({str(s) for s in seeds}):
        if seed in dist:
            continue
        if seed not in neighbors and seed not in adjacency:
            continue
        dist[seed] = 0
        queue.append((seed, 0))
    while queue:
        node, d = queue.popleft()
        if d >= hops:
            continue
        for nb in sorted(neighbors.get(node, ())):
            if nb not in dist:
                dist[nb] = d + 1
                queue.append((nb, d + 1))
    return dist


def rank_neighborhood(
    adjacency: dict[str, Iterable[str]],
    seeds: Iterable[str],
    hops: int = DEFAULT_HOPS,
    damping: float = DEFAULT_DAMPING,
    max_iter: int = DEFAULT_MAX_ITER,
    tol: float = DEFAULT_TOL,
) -> list[dict[str, Any]]:
    """按 PPR 分数降序返回 hops 跳内节点（分数相同按跳数、节点名排序）。"""
    seed_list = sorted({str(s) for s in seeds})
    scores = personalized_pagerank(adjacency, seed_list, damping, max_iter, tol)
    dist = bounded_hop_distances(adjacency, seed_list, hops)
    ranked = [{"module": node, "score": scores.get(node, 0.0), "hop": dist[node]} for node in dist]
    ranked.sort(key=lambda item: (-item["score"], item["hop"], item["module"]))
    return ranked


def edges_within(adjacency: dict[str, Iterable[str]], kept: Iterable[str]) -> list[dict[str, str]]:
    """返回 kept 集合内部的边（按 source/target 字典序，保证确定性）。"""
    kept_set = set(kept)
    edges: list[dict[str, str]] = []
    for src in sorted(adjacency):
        if src not in kept_set:
            continue
        for dst in sorted({str(d) for d in adjacency[src]}):
            if dst in kept_set:
                edges.append({"source": src, "target": dst})
    return edges
