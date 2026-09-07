# -*- coding: utf-8 -*-
"""向量检索层统一配置。

所有路径均基于本文件位置自动解析为绝对路径，
确保代码在任意工作目录下均可直接运行。
"""

from pathlib import Path

# === 路径解析（基于 config.py 所在位置） ===
# config.py 位于 2-KNOWLEDGE/9-RAG-INFRA/vector_store/config.py
_THIS_DIR = Path(__file__).resolve().parent          # .../9-RAG-INFRA/vector_store
_RAG_INFRA_DIR = _THIS_DIR.parent                    # .../9-RAG-INFRA
_KNOWLEDGE_DIR = _RAG_INFRA_DIR.parent               # .../2-KNOWLEDGE

# === 嵌入模型 ===
EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
VECTOR_DIM = 512

# === ChromaDB 持久化 ===
CHROMA_DB_PATH = str(_RAG_INFRA_DIR / "chroma_db")
COLLECTION_NAME = "dreambuddy_knowledge"
DISTANCE_METRIC = "cosine"

# === 处理参数 ===
BATCH_SIZE = 100
# 单块 token 上限（粗略估计：中文字符=1 token，英文单词=1 token）
MAX_CHUNK_TOKENS = 512

# === 知识库根目录 ===
KNOWLEDGE_BASE_DIR = str(_KNOWLEDGE_DIR)
