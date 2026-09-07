# -*- coding: utf-8 -*-
"""文档采集与清洗（阶段3·持续进化）：读取文档、去重、归一化、增量索引。

流程：
1. 读取文档内容，计算 md5 哈希；
2. 与知识库已有文件去重（相同哈希跳过）；
3. 归一化标题层级（最低级别对齐到 H1）；
4. 写入知识库目录；
5. 触发向量索引与知识图谱的增量更新。

FAIL-OPEN：索引/图谱构建失败不阻塞采集返回，仅在 status 中标注。
"""

import hashlib
import re
import sys
from pathlib import Path
from typing import Dict

# === 路径设置 ===
_THIS_DIR = Path(__file__).resolve().parent
_RAG_INFRA_DIR = _THIS_DIR.parent
if str(_RAG_INFRA_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_INFRA_DIR))

from vector_store.chunker import chunk_markdown
from vector_store.config import CHROMA_DB_PATH, COLLECTION_NAME
from knowledge_graph.entity_extractor import extract_entities

# 标题行正则
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def _md5(text: str) -> str:
    """计算文本的 md5 哈希。"""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _normalize_headings(text: str) -> str:
    """归一化标题层级：将最低标题级别对齐到 H1。

    例如文档从 ## 开始，则所有标题级别下移 1 级（## → #, ### → ##）。
    """
    lines = text.split("\n")
    # 找到最低标题级别
    min_level = 7
    for line in lines:
        m = _HEADING_RE.match(line)
        if m:
            min_level = min(min_level, len(m.group(1)))

    if min_level == 7 or min_level <= 1:
        return text  # 无标题或已从 H1 开始

    shift = min_level - 1
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m:
            new_level = len(m.group(1)) - shift
            new_level = max(1, new_level)
            lines[i] = "#" * new_level + " " + m.group(2)

    return "\n".join(lines)


def _domain_of(rel_path: Path) -> str:
    """根据相对路径推断所属域（第一级目录名）。"""
    parts = rel_path.parts
    return parts[0] if len(parts) > 1 else "root"


def _find_duplicate(knowledge_dir: Path, file_hash: str) -> bool:
    """检查知识库中是否已存在相同哈希的文件。"""
    for f in knowledge_dir.rglob("*.md"):
        try:
            text = f.read_text(encoding="utf-8")
            if _md5(text) == file_hash:
                return True
        except Exception:
            continue
    return False


def ingest_document(file_path: Path, knowledge_dir: Path) -> Dict:
    """采集文档到知识库并触发增量索引。

    Args:
        file_path: 待采集文档路径（.md）。
        knowledge_dir: 知识库根目录。

    Returns:
        dict 含以下字段：
        - status: "indexed" / "duplicate" / "failed"
        - file_hash: 文件 md5 哈希
        - chunks_indexed: 索引的分块数
        - nodes_extracted: 抽取的图谱节点数
    """
    file_path = Path(file_path)
    knowledge_dir = Path(knowledge_dir)

    # 1. 读取文档
    try:
        text = file_path.read_text(encoding="utf-8")
    except Exception:
        return {
            "status": "failed",
            "file_hash": "",
            "chunks_indexed": 0,
            "nodes_extracted": 0,
            "error": "文件读取失败",
        }

    file_hash = _md5(text)

    # 2. 去重：检查知识库中是否已有相同内容
    if _find_duplicate(knowledge_dir, file_hash):
        return {
            "status": "duplicate",
            "file_hash": file_hash,
            "chunks_indexed": 0,
            "nodes_extracted": 0,
        }

    # 3. 归一化标题层级
    text = _normalize_headings(text)

    # 4. 写入知识库（保留相对路径或使用文件名）
    try:
        rel_path = file_path.relative_to(knowledge_dir)
    except ValueError:
        rel_path = Path(file_path.name)

    dest = knowledge_dir / rel_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")

    rel_str = str(rel_path)
    domain = _domain_of(rel_path)

    # 5. 计算分块数与节点数（精确统计）
    chunks = chunk_markdown(text, rel_str, domain)
    chunks_indexed = len(chunks)

    try:
        entity_result = extract_entities(text, rel_str, domain)
        nodes_extracted = len(entity_result["nodes"])
    except Exception:
        nodes_extracted = 0

    # 6. 触发增量索引更新（FAIL-OPEN：失败不阻塞）
    index_status = "ok"
    graph_status = "ok"

    try:
        from vector_store.build_index import build_index
        build_index(knowledge_dir, db_path=CHROMA_DB_PATH,
                    collection_name=COLLECTION_NAME)
    except Exception:
        index_status = "failed"

    try:
        from knowledge_graph.build_graph import build_graph
        from knowledge_graph.schema import DEFAULT_GRAPH_PATH
        build_graph(knowledge_dir, graph_path=DEFAULT_GRAPH_PATH)
    except Exception:
        graph_status = "failed"

    return {
        "status": "indexed",
        "file_hash": file_hash,
        "chunks_indexed": chunks_indexed,
        "nodes_extracted": nodes_extracted,
        "index_status": index_status,
        "graph_status": graph_status,
        "dest_path": str(dest),
    }
