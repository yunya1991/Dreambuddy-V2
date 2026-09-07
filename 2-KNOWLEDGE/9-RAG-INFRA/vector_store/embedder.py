# -*- coding: utf-8 -*-
"""向量化器：懒加载 bge-small-zh 模型，FAIL-OPEN 回退 TF-IDF。

设计原则：
- 懒加载：首次 embed 时才加载模型，避免启动开销；
- FAIL-OPEN：模型加载/推理失败时回退到纯 numpy 实现的哈希 TF-IDF 向量，
  保证系统在无网络/无模型环境下仍可运行；
- 哈希 TF-IDF 使用 md5 哈希到 VECTOR_DIM 维，L2 归一化，
  与 cosine 距离度量兼容，且对单条文本无状态、可复现。
"""

import hashlib
import math
import re
import threading
from collections import Counter
from typing import List

import numpy as np

try:
    from . import config
except ImportError:  # 直接以脚本运行时
    import config

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fa5]")


def _tokenize(text: str) -> List[str]:
    """中英文混合分词：中文按字，英文/数字按连续串。"""
    return _TOKEN_RE.findall(text.lower())


def _hash_term(term: str) -> int:
    """对词项做 md5 哈希（跨进程稳定），取前 4 字节为整数。"""
    digest = hashlib.md5(term.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


class Embedder:
    """向量嵌入器，支持模型路径与 TF-IDF 回退。"""

    def __init__(self, model_name: str = None):
        self.model_name = model_name or config.EMBEDDING_MODEL
        self._model = None
        self._embedder_ready = False
        self._use_tfidf_fallback = False
        self._lock = threading.Lock()

    # ---- 模型加载（懒加载 + FAIL-OPEN） ----
    def _ensure_model(self) -> None:
        if self._embedder_ready or self._use_tfidf_fallback:
            return
        with self._lock:
            if self._embedder_ready or self._use_tfidf_fallback:
                return
            try:
                from sentence_transformers import SentenceTransformer
                model = SentenceTransformer(self.model_name)
                # 试编码一句，确认模型可用
                model.encode(["自检"], normalize_embeddings=True)
                self._model = model
                self._embedder_ready = True
            except Exception:
                # FAIL-OPEN：模型不可用，回退 TF-IDF
                self._model = None
                self._embedder_ready = False
                self._use_tfidf_fallback = True

    # ---- TF-IDF 回退实现（纯 numpy，哈希到 VECTOR_DIM） ----
    def _tfidf_embed(self, text: str) -> np.ndarray:
        vec = np.zeros(config.VECTOR_DIM, dtype=np.float32)
        tokens = _tokenize(text)
        if not tokens:
            return vec
        tf = Counter(tokens)
        for term, cnt in tf.items():
            idx = _hash_term(term) % config.VECTOR_DIM
            # 子线性 TF 加权
            vec[idx] += 1.0 + math.log(cnt)
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        return vec

    # ---- 对外接口 ----
    def embed(self, text: str) -> np.ndarray:
        """单条文本向量化，返回 VECTOR_DIM 维 ndarray。"""
        self._ensure_model()
        if self._use_tfidf_fallback or self._model is None:
            return self._tfidf_embed(text)
        try:
            vec = self._model.encode([text], normalize_embeddings=True)[0]
            return np.asarray(vec, dtype=np.float32)
        except Exception:
            # 运行期推理失败也回退
            self._use_tfidf_fallback = True
            return self._tfidf_embed(text)

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        """批量文本向量化，返回 (n, VECTOR_DIM) ndarray。"""
        if not texts:
            return np.zeros((0, config.VECTOR_DIM), dtype=np.float32)
        self._ensure_model()
        if self._use_tfidf_fallback or self._model is None:
            return np.vstack([self._tfidf_embed(t) for t in texts])
        try:
            vecs = self._model.encode(
                texts, normalize_embeddings=True,
                batch_size=config.BATCH_SIZE,
            )
            return np.asarray(vecs, dtype=np.float32)
        except Exception:
            self._use_tfidf_fallback = True
            return np.vstack([self._tfidf_embed(t) for t in texts])


# 模块级共享实例（build_index / search 复用，避免重复加载模型）
_embedder = Embedder()
