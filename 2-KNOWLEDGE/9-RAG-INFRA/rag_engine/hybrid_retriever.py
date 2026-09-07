# -*- coding: utf-8 -*-
"""混合检索器（阶段3）：三路召回 + 合并去重 + 重排序。

三路召回（默认权重）：
- 向量检索 0.4：语义相似度检索（ChromaDB）
- 图谱检索 0.3：知识图谱邻域检索（NetworkX）
- 关键词检索 0.3：BM25 全文检索（Whoosh）

每路检索独立 FAIL-OPEN：任一路失败跳过，不阻塞其余路。
合并后按 (source_file, heading) 去重，再经 reranker 多信号重排序。
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional

# === 路径设置 ===
_THIS_DIR = Path(__file__).resolve().parent
_RAG_INFRA_DIR = _THIS_DIR.parent
if str(_RAG_INFRA_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_INFRA_DIR))

from .keyword_search import keyword_search
from .reranker import rerank

# 默认三路召回权重
DEFAULT_RETRIEVAL_WEIGHTS = {
    "vector": 0.4,
    "graph": 0.3,
    "keyword": 0.3,
}


def _vector_recall(query: str, top_k: int, db_path=None) -> List[Dict]:
    """向量检索召回。FAIL-OPEN：失败返回空列表。"""
    try:
        from vector_store.search import search as vector_search
        results = vector_search(query, top_k=top_k, db_path=db_path)
        for r in results:
            r["retrieval_method"] = "vector"
            r["vector_score"] = r.get("score", 0)
        return results
    except Exception:
        return []


def _graph_recall(query: str, top_k: int, graph_path=None) -> List[Dict]:
    """图谱检索召回：从查询中匹配实体节点，BFS 检索邻域。

    将自然语言查询与图谱节点名称做子串匹配，命中后转换为分块格式。
    FAIL-OPEN：图谱不存在或加载失败返回空列表。
    """
    try:
        from knowledge_graph.graph_search import graph_search, _load_graph
        from knowledge_graph.schema import DEFAULT_GRAPH_PATH
    except ImportError:
        return []

    gp = graph_path or DEFAULT_GRAPH_PATH
    graph = _load_graph(gp)
    if graph is None:
        return []

    # 在图谱中查找名称出现在查询中的节点（子串匹配，双向兼容）
    candidates = []
    for nid, data in graph.nodes(data=True):
        name = data.get("name", "")
        if name and len(name) >= 2 and name in query:
            candidates.append(name)
        # 反向匹配：查询中的关键词出现在节点名称中
        elif name and len(name) >= 2 and query in name:
            candidates.append(name)

    if not candidates:
        return []

    results: List[Dict] = []
    seen_keys = set()

    for name in candidates[:10]:  # 限制候选数量
        try:
            r = graph_search(name, hops=2, graph_path=gp)
        except Exception:
            continue

        if r["center_node"] is None:
            continue

        center = r["center_node"]
        center_files = center.get("source_files") or []
        source_file = center_files[0] if center_files else ""

        # 中心节点作为结果
        key = (source_file, center["name"])
        if key not in seen_keys:
            seen_keys.add(key)
            results.append({
                "content": f"{center['name']}（{center['type']}）",
                "source_file": source_file,
                "domain": "",
                "heading": center["name"],
                "score": 1.0,
                "graph_score": 1.0,
                "retrieval_method": "graph",
            })

        # 邻居节点作为结果
        for nb in r["neighbors"]:
            nb_data = graph.nodes.get(nb["id"], {})
            nb_files = nb_data.get("source_files") or []
            nb_source = nb_files[0] if nb_files else source_file
            nb_domain = nb_data.get("domain", "")

            nb_key = (nb_source, nb["name"])
            if nb_key in seen_keys:
                continue
            seen_keys.add(nb_key)

            # 得分按跳数衰减：1 跳=0.6，2 跳=0.4
            score = round(1.0 / (nb["hops"] + 1), 4)
            results.append({
                "content": f"{nb['name']}（{nb['type']}）— 关系: {nb['relation']} → {center['name']}",
                "source_file": nb_source,
                "domain": nb_domain,
                "heading": nb["name"],
                "score": score,
                "graph_score": score,
                "retrieval_method": "graph",
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def _keyword_recall(query: str, top_k: int, index_path=None) -> List[Dict]:
    """关键词检索召回。FAIL-OPEN：失败返回空列表。"""
    try:
        results = keyword_search(query, top_k=top_k, index_path=index_path)
        for r in results:
            r["retrieval_method"] = "keyword"
            r["keyword_score"] = r.get("score", 0)
        return results
    except Exception:
        return []


def _merge_and_dedup(*result_lists: List[Dict]) -> List[Dict]:
    """合并多路检索结果，按 (source_file, heading) 去重。

    被多路命中的结果合并各路得分，保留最高分与最长内容。
    """
    merged: Dict[tuple, Dict] = {}

    for results in result_lists:
        for r in results:
            key = (r.get("source_file", ""), r.get("heading", ""))
            method = r.get("retrieval_method", "")

            if key in merged:
                existing = merged[key]
                # 记录该路的得分信号
                if method == "vector":
                    existing["vector_score"] = r.get("score", 0)
                elif method == "graph":
                    existing["graph_score"] = r.get("score", 0)
                elif method == "keyword":
                    existing["keyword_score"] = r.get("score", 0)

                # 保留最高分
                if r.get("score", 0) > existing.get("score", 0):
                    existing["score"] = r["score"]
                # 保留最长内容
                if len(r.get("content", "")) > len(existing.get("content", "")):
                    existing["content"] = r["content"]
                # 合并域信息（优先非空）
                if not existing.get("domain") and r.get("domain"):
                    existing["domain"] = r["domain"]
                # 记录命中方法
                methods = existing.get("retrieval_methods", [])
                if method and method not in methods:
                    methods.append(method)
                existing["retrieval_methods"] = methods
            else:
                entry = dict(r)
                # 初始化各路得分信号
                if "vector_score" not in entry:
                    entry["vector_score"] = r.get("score", 0) if method == "vector" else None
                if "graph_score" not in entry:
                    entry["graph_score"] = r.get("score", 0) if method == "graph" else None
                if "keyword_score" not in entry:
                    entry["keyword_score"] = r.get("score", 0) if method == "keyword" else None
                entry["retrieval_methods"] = [method] if method else []
                merged[key] = entry

    return list(merged.values())


def hybrid_search(query: str, top_k: int = 10,
                  weights: Optional[Dict] = None,
                  db_path: Optional[str] = None,
                  index_path: Optional[Path] = None,
                  graph_path: Optional[Path] = None) -> List[Dict]:
    """三路混合检索 + 重排序。

    Args:
        query: 查询文本。
        top_k: 最终返回结果数上限。
        weights: 三路召回权重，默认 {vector: 0.4, graph: 0.3, keyword: 0.3}。
        db_path: ChromaDB 路径（向量检索），默认 config.CHROMA_DB_PATH。
        index_path: Whoosh 索引目录（关键词检索），默认 DEFAULT_INDEX_PATH。
        graph_path: 图谱持久化路径，默认 DEFAULT_GRAPH_PATH。

    Returns:
        重排序后的结果列表（降序），每项含 final_score / rerank_signals。
        每路独立 FAIL-OPEN，单路失败不影响其余路。
    """
    if not query or not query.strip():
        return []

    w = dict(DEFAULT_RETRIEVAL_WEIGHTS)
    if weights:
        w.update(weights)

    # 三路召回（各路独立 FAIL-OPEN）
    vec_results = _vector_recall(query, top_k, db_path=db_path)
    graph_results = _graph_recall(query, top_k, graph_path=graph_path)
    kw_results = _keyword_recall(query, top_k, index_path=index_path)

    # 合并去重
    merged = _merge_and_dedup(vec_results, graph_results, kw_results)

    # 重排序
    ranked = rerank(query, merged)

    return ranked[:top_k]


def search_with_feedback(query: str, top_k: int = 10,
                         weights: Optional[Dict] = None,
                         db_path: Optional[str] = None,
                         index_path: Optional[Path] = None,
                         graph_path: Optional[Path] = None,
                         enable_record: bool = True,
                         enable_boost: bool = True,
                         enable_annotate: bool = True,
                         weight_path: Optional[Path] = None,
                         map_path: Optional[Path] = None) -> Dict:
    """认知闭环检索：hybrid_search + 权重反哺 + 质量标注 + 记忆记录。

    在 hybrid_search 基础上叠加桥接层，形成完整闭环：
    1. apply_boost_to_results：读取 verify 反哺的 boost 因子，调整 final_score 重排序；
    2. annotate_chunk：对每个结果自动标注域/标签/质量分，quality<0.5 降权10%
       （FIX-EV-1 接入，低质量信号注入重排序，FAIL-OPEN）；
    3. record_retrieval_as_memory：将检索结果 record 为 C 级记忆，
       持久化 memory_id ↔ source_file/heading 映射，供后续 verify 反哺。

    所有桥接环节 FAIL-OPEN：认知系统不可用、标注缺失、映射写入失败等异常
    均不阻塞检索，仅降级为普通 hybrid_search 结果。

    Args:
        query: 查询文本。
        top_k / weights / db_path / index_path / graph_path: 同 hybrid_search。
        enable_record: 是否记录检索结果为 C 级记忆，默认 True。
        enable_boost: 是否应用 boost 权重反哺，默认 True。
        enable_annotate: 是否调用 annotate_chunk 注入质量标注与降权，默认 True。
        weight_path: 权重反馈文件路径，默认 bridge/weight_feedback.json。
        map_path: 映射表路径，默认 bridge/retrieval_memory_map.jsonl。

    Returns:
        {results: list, memory_mappings: list, boost_applied: bool,
         annotations_applied: bool, record_done: bool}
    """
    # 基础检索（不修改 hybrid_search，保持字节等价）
    results = hybrid_search(
        query, top_k=top_k, weights=weights,
        db_path=db_path, index_path=index_path, graph_path=graph_path)

    boost_applied = False
    annotations_applied = False
    record_done = False
    memory_mappings: List = []

    # 1. 应用权重反哺（FAIL-OPEN）
    if enable_boost and results:
        try:
            from bridge.weight_feedback import apply_boost_to_results
            results = apply_boost_to_results(results, weight_path)
            boost_applied = True
        except Exception:
            # 桥接缺失或异常，保持原结果
            pass

    # 2. FIX-EV-1：annotate_chunk 自动标注 + 低质量降权（FAIL-OPEN）
    #    位置在 boost 之后、record 之前：确保 annotation 携带最终 score
    #    进入 rerank_signals，低质量降权也影响 record 记忆写入的 score 映射
    if enable_annotate and results:
        try:
            from evolution.annotate import annotate_chunk
            QUALITY_THRESHOLD = 0.5
            QUALITY_PENALTY = 0.9
            any_applied = False
            for r in results:
                # annotate_chunk 返回的是**已修改的整个 chunk**，
                # annotation 信息存放在 r["annotation"] 字典中
                # （domain/tags/quality 三个子键）
                annotated_r = annotate_chunk(dict(r))
                if annotated_r is None:
                    continue

                # 从返回 chunk 中取出 annotation 字典，回写到 r
                # （保持 r 引用与原 results 列表的关联）
                annotation = annotated_r.get("annotation")
                if not annotation or not isinstance(annotation, dict):
                    continue
                r["annotation"] = annotation
                any_applied = True

                # 低质量降权：quality.overall < 阈值 → final_score 乘 0.9
                q_overall = None
                try:
                    q = annotation.get("quality") or {}
                    q_overall = q.get("overall")
                except Exception:
                    q_overall = None

                if (q_overall is not None
                        and isinstance(q_overall, (int, float))
                        and q_overall < QUALITY_THRESHOLD):
                    current = r.get("final_score", r.get("score", 0))
                    try:
                        new_score = max(0.0, round(float(current) * QUALITY_PENALTY, 6))
                    except (TypeError, ValueError):
                        new_score = current
                    r["final_score"] = new_score

                    # 写信号到 rerank_signals（确保字典存在）
                    if "rerank_signals" not in r or not isinstance(r.get("rerank_signals"), dict):
                        r["rerank_signals"] = {}
                    r["rerank_signals"]["quality_penalty"] = QUALITY_PENALTY
                    r["rerank_signals"]["quality_overall"] = q_overall
                else:
                    # 非低质量也记录 quality_overall 信号便于审计
                    if "rerank_signals" not in r or not isinstance(r.get("rerank_signals"), dict):
                        r["rerank_signals"] = {}
                    if q_overall is not None:
                        r["rerank_signals"]["quality_overall"] = q_overall

            # 如果有降权发生或 annotation 写入导致排序变化，重新按 final_score 降序
            if any_applied:
                try:
                    results.sort(
                        key=lambda x: x.get("final_score", x.get("score", 0)),
                        reverse=True)
                except Exception:
                    pass
                annotations_applied = True
        except Exception:
            # annotate 整个链路 FAIL-OPEN：import 错误、annotate_chunk 抛异常等
            # 都不阻塞检索；annotations_applied 保持 False
            annotations_applied = False

    # 3. 记录检索结果为 C 级记忆（FAIL-OPEN）
    if enable_record and results:
        try:
            from bridge.memory_bridge import record_retrieval_as_memory
            memory_mappings = record_retrieval_as_memory(
                query, results, map_path=map_path)
            record_done = bool(memory_mappings)
        except Exception:
            # 认知系统不可用，跳过记录
            pass

    return {
        "results": results,
        "memory_mappings": memory_mappings,
        "boost_applied": boost_applied,
        "annotations_applied": annotations_applied,
        "record_done": record_done,
    }


if __name__ == "__main__":
    import json

    q = "BCRM推理模型"
    for r in hybrid_search(q, top_k=5):
        print(json.dumps(r, ensure_ascii=False))
