# -*- coding: utf-8 -*-
"""BM25 关键词检索（阶段3）：基于 Whoosh 倒排索引的全文检索。

中文分词采用与 embedder 一致的策略：中文字符按字、英文/数字按连续串切分。
FAIL-OPEN：Whoosh 不可用或索引不存在时返回空列表，不阻塞混合检索。
"""

import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional

# === 路径设置：确保可导入同级包 ===
_THIS_DIR = Path(__file__).resolve().parent          # .../9-RAG-INFRA/rag_engine
_RAG_INFRA_DIR = _THIS_DIR.parent                    # .../9-RAG-INFRA
if str(_RAG_INFRA_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_INFRA_DIR))

from vector_store.chunker import chunk_markdown

# 默认关键词索引目录
DEFAULT_INDEX_PATH = _RAG_INFRA_DIR / "keyword_index"

# 中文分词正则（与 embedder 一致）
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fa5]")

# 尝试导入 Whoosh
try:
    from whoosh.analysis import Tokenizer, Token
    from whoosh.fields import Schema, TEXT, STORED
    from whoosh.index import create_in, exists_in, open_dir
    from whoosh.qparser import QueryParser, OrGroup
    from whoosh import scoring
    _WHOOSH_AVAILABLE = True
except ImportError:
    _WHOOSH_AVAILABLE = False


class ChineseTokenizer(Tokenizer):
    """中文分词器：中文字符按字切分，英文/数字按连续串切分。"""

    def __call__(self, value, positions=False, chars=False,
                 keeporiginal=False, removestops=True,
                 start_pos=0, start_char=0, tokenize=True, mode="", **kwargs):
        t = Token(positions=positions, chars=chars,
                  removestops=removestops, mode=mode)
        pos = start_pos
        for m in _TOKEN_RE.finditer(value):
            t.text = m.group(0).lower()
            t.boost = 1.0
            if positions:
                t.pos = pos
                pos += 1
            if chars:
                t.startchar = start_char + m.start()
                t.endchar = start_char + m.end()
            yield t


def _make_schema() -> "Schema":
    """构造 Whoosh 索引 schema。"""
    return Schema(
        content=TEXT(analyzer=ChineseTokenizer(), stored=True),
        source_file=TEXT(stored=True),
        domain=TEXT(stored=True),
        heading=TEXT(analyzer=ChineseTokenizer(), stored=True),
        position=STORED,
    )


def build_keyword_index(knowledge_dir, index_path: Optional[Path] = None) -> Dict:
    """扫描知识库 Markdown，分块后构建 Whoosh BM25 倒排索引。

    Args:
        knowledge_dir: 知识库根目录（递归扫描 .md）。
        index_path: 索引持久化目录，默认 DEFAULT_INDEX_PATH。

    Returns:
        统计字典：status / total_files / total_docs / index_path。
    """
    knowledge_dir = Path(knowledge_dir)
    index_path = Path(index_path) if index_path else DEFAULT_INDEX_PATH

    if not _WHOOSH_AVAILABLE:
        return {"status": "whoosh_unavailable", "total_files": 0, "total_docs": 0}

    # 清理旧索引后重建（关键词索引轻量，全量重建开销可接受）
    if index_path.exists():
        shutil.rmtree(index_path)
    index_path.mkdir(parents=True, exist_ok=True)

    ix = create_in(str(index_path), _make_schema())
    writer = ix.writer()

    md_files = sorted(knowledge_dir.rglob("*.md"))
    total_docs = 0

    for f in md_files:
        rel = f.relative_to(knowledge_dir)
        rel_str = str(rel)
        parts = rel.parts
        domain = parts[0] if len(parts) > 1 else "root"
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue  # FAIL-OPEN：单文件读取失败跳过

        try:
            chunks = chunk_markdown(text, rel_str, domain)
            for chunk in chunks:
                meta = chunk["metadata"]
                writer.add_document(
                    content=chunk["content"],
                    source_file=meta["source_file"],
                    domain=meta["domain"],
                    heading=meta["heading"],
                    position=meta["position"],
                )
                total_docs += 1
        except Exception:
            continue  # FAIL-OPEN：单文件分块失败跳过

    writer.commit()

    return {
        "status": "ok",
        "total_files": len(md_files),
        "total_docs": total_docs,
        "index_path": str(index_path),
    }


def keyword_search(query: str, top_k: int = 5,
                   index_path: Optional[Path] = None) -> List[Dict]:
    """BM25 关键词检索。

    Args:
        query: 查询文本。空查询返回空列表。
        top_k: 返回结果数上限。
        index_path: 索引目录，默认 DEFAULT_INDEX_PATH。

    Returns:
        每项含 content / source_file / domain / heading / score。
        索引不存在或查询失败返回空列表（FAIL-OPEN）。
    """
    if not _WHOOSH_AVAILABLE or not query or not query.strip():
        return []

    index_path = Path(index_path) if index_path else DEFAULT_INDEX_PATH
    if not index_path.exists():
        return []  # FAIL-OPEN：索引不存在

    try:
        ix = open_dir(str(index_path))
    except Exception:
        return []  # FAIL-OPEN：索引打开失败

    # 使用 OrGroup 提升召回率（任一词命中即返回，按 BM25 排序）
    parser = QueryParser("content", ix.schema, group=OrGroup)
    try:
        q = parser.parse(query)
    except Exception:
        return []  # FAIL-OPEN：查询解析失败

    results: List[Dict] = []
    try:
        with ix.searcher(weighting=scoring.BM25F) as searcher:
            hits = searcher.search(q, limit=top_k)
            for hit in hits:
                results.append({
                    "content": hit["content"],
                    "source_file": hit["source_file"],
                    "domain": hit["domain"],
                    "heading": hit.get("heading", ""),
                    "score": float(hit.score),
                })
    except Exception:
        return []  # FAIL-OPEN：检索失败

    return results


if __name__ == "__main__":
    import json
    from vector_store.config import KNOWLEDGE_BASE_DIR

    build_keyword_index(KNOWLEDGE_BASE_DIR)
    q = "BCRM推理模型"
    for r in keyword_search(q):
        print(json.dumps(r, ensure_ascii=False))
