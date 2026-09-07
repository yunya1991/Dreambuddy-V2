# -*- coding: utf-8 -*-
"""构建向量索引：扫描 Markdown 知识库，分块+向量化后写入 ChromaDB。

增量更新策略：
- 计算每个 .md 文件的 md5 哈希，与索引侧记文件对比；
- 哈希不变则跳过；变化或新增则删除该文件旧块并重新写入；
- force=True 时强制全量重建。
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Dict

import chromadb

try:
    from . import config
    from .chunker import chunk_markdown
    from .embedder import _embedder
except ImportError:  # 直接以脚本运行时
    import config
    from chunker import chunk_markdown
    from embedder import _embedder

_HASH_SIDE_FILE = "_file_hashes.json"  # 文件哈希记录（存于 db 目录）


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _load_hashes(db_path: str) -> Dict[str, str]:
    p = Path(db_path) / _HASH_SIDE_FILE
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_hashes(db_path: str, hashes: Dict[str, str]) -> None:
    p = Path(db_path)
    p.mkdir(parents=True, exist_ok=True)
    (p / _HASH_SIDE_FILE).write_text(
        json.dumps(hashes, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _to_chroma_meta(meta: Dict, file_hash: str) -> Dict:
    """将分块元数据转换为 ChromaDB 兼容的扁平原始值（tags 序列化为字符串）。"""
    return {
        "source_file": str(meta.get("source_file", "")),
        "domain": str(meta.get("domain", "")),
        "chunk_type": str(meta.get("chunk_type", "")),
        "heading": str(meta.get("heading", "")),
        "heading_level": int(meta.get("heading_level", 0)),
        "position": int(meta.get("position", 0)),
        "tags": ",".join(meta.get("tags", [])),
        "file_hash": file_hash,
    }


def build_index(knowledge_dir, force: bool = False,
                db_path: str = None, collection_name: str = None) -> Dict:
    """扫描知识库构建/增量更新向量索引。

    Args:
        knowledge_dir: 知识库根目录（递归扫描 .md）。
        force: True 强制全量重建。
        db_path: ChromaDB 持久化路径，默认 config.CHROMA_DB_PATH。
        collection_name: 集合名，默认 config.COLLECTION_NAME。

    Returns:
        统计字典：total_files / total_chunks / new_chunks /
        updated_chunks / failed_chunks / duration_sec。
    """
    start = time.time()
    knowledge_dir = Path(knowledge_dir)
    db_path = db_path or config.CHROMA_DB_PATH
    collection_name = collection_name or config.COLLECTION_NAME

    client = chromadb.PersistentClient(path=db_path)
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": config.DISTANCE_METRIC},
    )

    hashes = _load_hashes(db_path)
    md_files = sorted(knowledge_dir.rglob("*.md"))

    stats = {
        "total_files": len(md_files),
        "total_chunks": collection.count(),
        "new_chunks": 0,
        "updated_chunks": 0,
        "failed_chunks": 0,
        "duration_sec": 0.0,
    }

    for f in md_files:
        rel = f.relative_to(knowledge_dir)
        rel_str = str(rel)
        # 域 = 相对路径的第一级目录
        parts = rel.parts
        domain = parts[0] if len(parts) > 1 else "root"

        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            stats["failed_chunks"] += 1
            continue

        file_hash = _md5(text)
        existing = hashes.get(rel_str)
        if existing == file_hash and not force:
            continue  # 未变更，跳过

        try:
            chunks = chunk_markdown(text, rel_str, domain)
            if not chunks:
                # 空文件/无内容，仍记录哈希避免重复处理
                hashes[rel_str] = file_hash
                continue

            # 删除该文件旧块（首次构建为空操作）
            try:
                collection.delete(where={"source_file": rel_str})
            except Exception:
                pass  # FAIL-OPEN：删除失败不阻塞

            contents = [c["content"] for c in chunks]
            embs = _embedder.embed_batch(contents)
            ids = [f"{rel_str}::{c['metadata']['position']}" for c in chunks]
            metas = [_to_chroma_meta(c["metadata"], file_hash) for c in chunks]

            collection.upsert(
                ids=ids,
                documents=contents,
                embeddings=embs.tolist(),
                metadatas=metas,
            )

            if existing is None:
                stats["new_chunks"] += len(chunks)
            else:
                stats["updated_chunks"] += len(chunks)
            hashes[rel_str] = file_hash
        except Exception:
            # FAIL-OPEN：单文件失败不阻塞整体
            stats["failed_chunks"] += 1

    _save_hashes(db_path, hashes)
    stats["total_chunks"] = collection.count()
    stats["duration_sec"] = round(time.time() - start, 2)
    return stats


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else config.KNOWLEDGE_BASE_DIR
    force_flag = "--force" in sys.argv
    result = build_index(target, force=force_flag)
    print(json.dumps(result, ensure_ascii=False, indent=2))
