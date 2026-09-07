# -*- coding: utf-8 -*-
"""语义检索：向量化 query，从 ChromaDB 查询并按域/分数过滤。"""

from typing import Dict, List, Optional

import chromadb

try:
    from . import config
    from .embedder import _embedder
except ImportError:  # 直接以脚本运行时
    import config
    from embedder import _embedder


def search(query: str, top_k: int = 5,
           domain_filter: Optional[List[str]] = None,
           score_threshold: float = 0.3,
           db_path: str = None,
           collection_name: str = None) -> List[Dict]:
    """对 query 进行语义检索，返回排序后的结果列表。

    Args:
        query: 查询文本。空查询返回空列表。
        top_k: 返回结果数上限。
        domain_filter: 仅保留这些域（如 ["1-TRADING"]），None 表示不过滤。
        score_threshold: 相似度下限（cosine 相似度，0~1），低于则丢弃。
        db_path: ChromaDB 路径，默认 config.CHROMA_DB_PATH。
        collection_name: 集合名，默认 config.COLLECTION_NAME。

    Returns:
        每项含 content / source_file / domain / heading / score / tags。
    """
    if not query or not query.strip():
        return []

    db_path = db_path or config.CHROMA_DB_PATH
    collection_name = collection_name or config.COLLECTION_NAME

    client = chromadb.PersistentClient(path=db_path)
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": config.DISTANCE_METRIC},
    )

    if collection.count() == 0:
        return []

    query_emb = _embedder.embed(query)
    where = None
    if domain_filter:
        where = {"domain": {"$in": list(domain_filter)}}

    try:
        res = collection.query(
            query_embeddings=[query_emb.tolist()],
            n_results=top_k,
            where=where,
        )
    except Exception:
        return []  # FAIL-OPEN：查询失败返回空

    results: List[Dict] = []
    ids = res.get("ids", [[]])[0]
    dists = res.get("distances", [[]])[0]
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]

    for _id, dist, doc, meta in zip(ids, dists, docs, metas):
        # cosine 距离 → 相似度：score = 1 - distance
        score = 1.0 - float(dist)
        if score < score_threshold:
            continue
        tags_str = meta.get("tags", "") if meta else ""
        tags = [t for t in tags_str.split(",") if t] if tags_str else []
        results.append({
            "content": doc,
            "source_file": meta.get("source_file", "") if meta else "",
            "domain": meta.get("domain", "") if meta else "",
            "heading": meta.get("heading", "") if meta else "",
            "score": round(score, 4),
            "tags": tags,
        })

    return results


if __name__ == "__main__":
    import json
    import sys

    q = sys.argv[1] if len(sys.argv) > 1 else "BCRM推理模型"
    for r in search(q):
        print(json.dumps(r, ensure_ascii=False))
