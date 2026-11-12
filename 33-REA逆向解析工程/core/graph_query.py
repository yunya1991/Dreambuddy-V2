"""受限图查询 DSL（SPEC-33-F T-F13）。

设计边界：
  - 只读快照既有图数据，不重新扫描、不联网、不调用模型。
  - 语法白名单：`nodes` / `edges` / `neighbors <node>`，过滤仅支持
    `field=value`（精确）与 `field~=regex`（不区分大小写的子串匹配）。
  - 任何未登记字段、非法正则、未知指令都抛 ValueError，由调用方转成
    `invalid_query` 错误码，不做静默兜底。
"""

from __future__ import annotations

import re
from typing import Any

_NODE_FIELDS = ("name", "type", "kind", "path", "language")
_EDGE_FIELDS = ("source", "target")
_MAX_DEPTH = 3
_MAX_REGEX_LEN = 200
_FILTER_RE = re.compile(r"^(?P<field>[a-z_]+)(?P<op>~=|=)(?P<value>.+)$")


def _as_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("raw") or {}
    graph = raw.get("graph") or {}
    items = raw.get("modules") or graph.get("nodes") or []
    nodes: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            nodes.append(dict(item))
        else:
            nodes.append({"name": str(item)})
    return nodes


def _as_edges(payload: dict[str, Any]) -> list[dict[str, str]]:
    raw = payload.get("raw") or {}
    graph = raw.get("graph") or {}
    edges: set[tuple[str, str]] = set()
    deps = raw.get("dependencies")
    if isinstance(deps, dict):
        for source, targets in deps.items():
            for target in targets or []:
                edges.add((str(source), str(target)))
    adjacency = graph.get("adjacency")
    if isinstance(adjacency, dict):
        for source, targets in adjacency.items():
            for target in targets or []:
                edges.add((str(source), str(target)))
    for item in raw.get("edges") or graph.get("edges") or []:
        if isinstance(item, dict) and item.get("source") and item.get("target"):
            edges.add((str(item["source"]), str(item["target"])))
    return [{"source": s, "target": t} for s, t in sorted(edges)]


def _apply_filters(
    items: list[dict[str, Any]], filters: list[str], allowed: tuple[str, ...]
) -> list[dict[str, Any]]:
    for token in filters:
        match = _FILTER_RE.match(token)
        if match is None:
            raise ValueError(f"无法解析过滤条件: {token}")
        field = match.group("field")
        if field not in allowed:
            raise ValueError(f"字段不在白名单: {field}（允许 {', '.join(allowed)}）")
        value = match.group("value")
        if match.group("op") == "=":
            items = [item for item in items if str(item.get(field) or "") == value]
            continue
        if len(value) > _MAX_REGEX_LEN:
            raise ValueError("正则过长（上限 200 字符）")
        try:
            pattern = re.compile(value, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"非法正则: {exc}") from exc
        items = [item for item in items if pattern.search(str(item.get(field) or ""))]
    return items


def run_graph_query(
    payload: dict[str, Any],
    query: str,
    *,
    cursor: int = 0,
    limit: int = 20,
) -> dict[str, Any]:
    """执行受限图查询并返回分页结果。"""
    tokens = str(query or "").split()
    if not tokens:
        raise ValueError("query 为空")
    kind = tokens[0]
    args = tokens[1:]

    if kind == "nodes":
        items = _apply_filters(_as_nodes(payload), args, _NODE_FIELDS)
    elif kind == "edges":
        items = _apply_filters(_as_edges(payload), args, _EDGE_FIELDS)
    elif kind == "neighbors":
        if not args:
            raise ValueError("neighbors 需要节点名")
        depth = 1
        node = args[0]
        for token in args[1:]:
            if not token.startswith("depth="):
                raise ValueError(f"neighbors 仅支持 depth=N，收到: {token}")
            try:
                depth = int(token.split("=", 1)[1])
            except ValueError as exc:
                raise ValueError("depth 必须为整数") from exc
            if not 1 <= depth <= _MAX_DEPTH:
                raise ValueError(f"depth 超限（1..{_MAX_DEPTH}）")
        items = _neighbors(_as_edges(payload), node, depth)
    else:
        raise ValueError(f"未知指令: {kind}（仅支持 nodes/edges/neighbors）")

    total = len(items)
    page = items[cursor : cursor + limit]
    return {
        "section": "graph",
        "query": str(query),
        "kind": kind,
        "items": page,
        "total": total,
        "next_cursor": cursor + limit if cursor + limit < total else None,
    }


def _neighbors(edges: list[dict[str, str]], node: str, depth: int) -> list[dict[str, str]]:
    """BFS 收集 depth 跳内与 node 相连的边（去重后按边字典序排序）。"""
    frontier = {node}
    seen_nodes = {node}
    collected: set[tuple[str, str]] = set()
    for _ in range(depth):
        next_frontier: set[str] = set()
        for edge in edges:
            if edge["source"] in frontier or edge["target"] in frontier:
                collected.add((edge["source"], edge["target"]))
                for side in (edge["source"], edge["target"]):
                    if side not in seen_nodes:
                        next_frontier.add(side)
        seen_nodes |= next_frontier
        frontier = next_frontier
    return [{"source": s, "target": t} for s, t in sorted(collected)]
