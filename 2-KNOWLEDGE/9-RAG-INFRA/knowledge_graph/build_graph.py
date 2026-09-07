# -*- coding: utf-8 -*-
"""构建知识图谱：扫描知识库 Markdown，抽取实体关系，构建 NetworkX 有向图并持久化。

图引擎：NetworkX（纯 Python，无外部服务依赖）。
持久化：pickle 格式（DiGraph 可直接序列化）。
接口设计兼容后续替换为 Neo4j：节点/关系类型以字符串标识，
节点属性扁平存储，便于映射到图数据库的 label 与 property。

FAIL-OPEN：单个文件抽取失败不阻塞整体构建。
"""

import pickle
import time
from pathlib import Path
from typing import Dict

import networkx as nx

try:
    from .schema import DEFAULT_GRAPH_PATH, GRAPH_DB_DIR
    from .entity_extractor import extract_entities
except ImportError:  # 直接以脚本运行时
    from schema import DEFAULT_GRAPH_PATH, GRAPH_DB_DIR
    from entity_extractor import extract_entities


def _domain_of(rel_path: Path) -> str:
    """根据相对路径推断所属域（第一级目录名），无子目录则为 root。"""
    parts = rel_path.parts
    return parts[0] if len(parts) > 1 else "root"


def _add_node_to_graph(graph: nx.DiGraph, node: Dict) -> None:
    """将单个节点加入图，跨文件去重并累积 source_files。"""
    nid = node["id"]
    if nid in graph:
        # 已存在：合并来源文件列表
        existing = graph.nodes[nid]
        files = existing.get("source_files") or []
        if node.get("source_file") and node["source_file"] not in files:
            files.append(node["source_file"])
        existing["source_files"] = files
        # 补全可能缺失的属性
        for k, v in node.items():
            if k in ("id", "source_file"):
                continue
            if k not in existing or existing[k] in (None, ""):
                existing[k] = v
    else:
        data = {k: v for k, v in node.items() if k != "id" and k != "source_file"}
        data["source_files"] = [node["source_file"]] if node.get("source_file") else []
        graph.add_node(nid, **data)


def _add_edge_to_graph(graph: nx.DiGraph, edge: Dict) -> None:
    """将边加入图，附带关系类型与来源文件。"""
    src, tgt = edge["source"], edge["target"]
    # 确保端点存在（防止孤立边）
    if src not in graph:
        graph.add_node(src, name=src.split(":", 1)[-1],
                       type=src.split(":", 1)[0], source_files=[])
    if tgt not in graph:
        graph.add_node(tgt, name=tgt.split(":", 1)[-1],
                       type=tgt.split(":", 1)[0], source_files=[])
    rel = edge["relation"]
    if graph.has_edge(src, tgt):
        # 已存在同方向边：合并关系类型集合
        rels = graph[src][tgt].get("relations") or []
        if rel not in rels:
            rels.append(rel)
        graph[src][tgt]["relations"] = rels
    else:
        graph.add_edge(src, tgt, relation=rel,
                       relations=[rel],
                       source_file=edge.get("source_file", ""))


def build_graph(knowledge_dir, graph_path=None) -> Dict:
    """扫描知识库构建知识图谱并持久化。

    Args:
        knowledge_dir: 知识库根目录（递归扫描 .md）。
        graph_path: 图谱持久化路径（pickle），默认 DEFAULT_GRAPH_PATH。

    Returns:
        统计字典：total_files / total_nodes / total_edges /
        node_by_type / edge_by_type / failed_files / duration_sec。
    """
    start = time.time()
    knowledge_dir = Path(knowledge_dir)
    graph_path = Path(graph_path) if graph_path else DEFAULT_GRAPH_PATH

    graph = nx.DiGraph()
    md_files = sorted(knowledge_dir.rglob("*.md"))

    stats = {
        "total_files": len(md_files),
        "total_nodes": 0,
        "total_edges": 0,
        "node_by_type": {},
        "edge_by_type": {},
        "failed_files": 0,
        "duration_sec": 0.0,
    }

    for f in md_files:
        rel = f.relative_to(knowledge_dir)
        rel_str = str(rel)
        domain = _domain_of(rel)
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            stats["failed_files"] += 1
            continue

        try:
            result = extract_entities(text, rel_str, domain)
            for node in result["nodes"]:
                _add_node_to_graph(graph, node)
            for edge in result["edges"]:
                _add_edge_to_graph(graph, edge)
        except Exception:
            # FAIL-OPEN：单文件抽取失败不阻塞整体
            stats["failed_files"] += 1

    # 持久化（pickle 序列化 DiGraph）
    try:
        graph_path.parent.mkdir(parents=True, exist_ok=True)
        with open(graph_path, "wb") as fp:
            pickle.dump(graph, fp)
    except Exception:
        # 持久化失败不阻塞统计返回（FAIL-OPEN）
        pass

    # 统计节点/边按类型分布
    node_by_type: Dict[str, int] = {}
    for _n, data in graph.nodes(data=True):
        t = data.get("type", "Unknown")
        node_by_type[t] = node_by_type.get(t, 0) + 1

    edge_by_type: Dict[str, int] = {}
    for _u, _v, data in graph.edges(data=True):
        for rel in (data.get("relations") or [data.get("relation")]):
            if rel:
                edge_by_type[rel] = edge_by_type.get(rel, 0) + 1

    stats["total_nodes"] = graph.number_of_nodes()
    stats["total_edges"] = graph.number_of_edges()
    stats["node_by_type"] = node_by_type
    stats["edge_by_type"] = edge_by_type
    stats["duration_sec"] = round(time.time() - start, 2)
    stats["graph_path"] = str(graph_path)
    return stats


if __name__ == "__main__":
    import sys
    import json

    # 默认知识库根目录 = 9-RAG-INFRA 的上一级（即项目下的 2-KNOWLEDGE）
    _default = str(Path(__file__).resolve().parent.parent.parent / "2-KNOWLEDGE")
    target = sys.argv[1] if len(sys.argv) > 1 else _default
    out = sys.argv[2] if len(sys.argv) > 2 else None
    result = build_graph(target, out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
