#!/usr/bin/env python3
"""一键重建 RAG 索引。

- dreambuddy_index：INDEX.md + SKILL registry 的元数据语义索引（Chroma）
- dreambuddy_knowledge：知识库 Markdown 分块向量索引（Chroma）
- keyword_index：BM25 关键词索引（Whoosh；不可用时纯 Python BM25 回退）

用法：
    python 2-KNOWLEDGE/9-RAG-INFRA/scripts/rebuild_indexes.py
    python .../rebuild_indexes.py --skip-meta   # 只重建分块/关键词
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_RAG_INFRA_DIR = Path(__file__).resolve().parents[1]
if str(_RAG_INFRA_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_INFRA_DIR))

from index_query_service import IndexQueryService  # noqa: E402
from rag_engine.keyword_search import build_keyword_index  # noqa: E402
from vector_store import build_index as build_vector_index  # noqa: E402
from vector_store.config import KNOWLEDGE_BASE_DIR  # noqa: E402


def _reset_chroma() -> dict:
    """删除 Chroma 集合与哈希账本，确保不残留已删除文件的旧块。"""
    import chromadb
    from vector_store.config import CHROMA_DB_PATH, COLLECTION_NAME

    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    removed = []
    for name in (COLLECTION_NAME, "dreambuddy_index"):
        try:
            client.delete_collection(name)
            removed.append(name)
        except Exception:
            pass
    hash_file = Path(CHROMA_DB_PATH) / "_file_hashes.json"
    if hash_file.exists():
        hash_file.unlink()
    return {"removed_collections": removed, "removed_hashes": True}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reset", action="store_true", help="先删除 Chroma 集合与哈希账本，再全量重建"
    )
    parser.add_argument("--skip-meta", action="store_true", help="跳过 dreambuddy_index 元数据索引")
    parser.add_argument(
        "--skip-chunks", action="store_true", help="跳过 dreambuddy_knowledge 分块索引"
    )
    parser.add_argument("--skip-keyword", action="store_true", help="跳过 BM25 关键词索引")
    args = parser.parse_args()

    results = {}
    if args.reset:
        results["reset"] = _reset_chroma()
    if not args.skip_meta:
        results["meta_index"] = {
            "entries": IndexQueryService().build_index(),
        }
    if not args.skip_chunks:
        results["chroma_chunks"] = build_vector_index(KNOWLEDGE_BASE_DIR, force=True)
    if not args.skip_keyword:
        results["keyword_index"] = build_keyword_index(KNOWLEDGE_BASE_DIR)

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
