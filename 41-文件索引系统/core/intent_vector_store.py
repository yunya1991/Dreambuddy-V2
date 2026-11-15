# -*- coding: utf-8 -*-
"""intent_vector_store.py — 意图向量存储与 cosine 检索（P0，SPEC-41-L1 §3.5）

存储：intent_units/{intent_id}/vector.json → {"zh": [512 floats], "en": [384 floats]}
检索：暴力 cosine similarity（21 意图，无需向量数据库），返回 top-K 候选。
"""

import json
import logging
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_INDEX_ROOT = Path(__file__).resolve().parent.parent  # 41-文件索引系统/
UNITS_DIR = _INDEX_ROOT / "intent_units"


def _cosine(a: List[float], b: List[float]) -> float:
    """余弦相似度。向量已 L2 归一化时退化为点积。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class IntentVectorStore:
    """意图向量存储与检索。"""

    def __init__(self, units_dir: Optional[Path] = None):
        self.units_dir = Path(units_dir) if units_dir else UNITS_DIR
        self._vectors: Dict[str, Dict[str, Optional[List[float]]]] = {}  # intent → {zh, en}
        self._loaded = False

    # ---- 加载 ----
    def load(self) -> None:
        """加载所有意图的向量文件。"""
        self._vectors.clear()
        if not self.units_dir.exists():
            logger.warning("intent_units 目录不存在: %s", self.units_dir)
            self._loaded = True
            return
        for intent_dir in sorted(self.units_dir.iterdir()):
            if not intent_dir.is_dir():
                continue
            vec_file = intent_dir / "vector.json"
            if not vec_file.exists():
                continue
            try:
                data = json.loads(vec_file.read_text(encoding="utf-8"))
                self._vectors[intent_dir.name] = {
                    "zh": data.get("zh"),
                    "en": data.get("en"),
                }
            except Exception as e:
                logger.warning("加载 %s 失败: %s", vec_file, e)
        self._loaded = True
        logger.info("已加载 %d 个意图向量", len(self._vectors))

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    # ---- 检索 ----
    def search(
        self,
        query_vector: List[float],
        lang: str = "zh",
        top_k: int = 3,
        exclude_intents: Optional[List[str]] = None,
    ) -> List[Tuple[str, float]]:
        """语义检索：返回 top-K (intent_id, cosine_similarity)。

        exclude_intents: 排除指定意图（uplift 度量时用，模拟"无该意图规则"）。
        """
        self._ensure_loaded()
        lang = (lang or "zh").lower()
        excluded = set(exclude_intents or [])
        results: List[Tuple[str, float]] = []
        for intent_id, vecs in self._vectors.items():
            if intent_id in excluded:
                continue
            vec = vecs.get(lang)
            if not vec:
                continue
            sim = _cosine(query_vector, vec)
            results.append((intent_id, sim))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def top1(self, query_vector: List[float], lang: str = "zh") -> Optional[Tuple[str, float]]:
        """返回 top-1 命中。"""
        results = self.search(query_vector, lang=lang, top_k=1)
        return results[0] if results else None

    def similarity_to(
        self, intent_id: str, query_vector: List[float], lang: str = "zh"
    ) -> Optional[float]:
        """返回查询向量与指定意图向量的 cosine 相似度。意图不存在返回 None。"""
        self._ensure_loaded()
        vecs = self._vectors.get(intent_id)
        if not vecs:
            return None
        vec = vecs.get(lang)
        if not vec:
            return None
        return _cosine(query_vector, vec)

    # ---- 元信息 ----
    @property
    def intent_ids(self) -> List[str]:
        self._ensure_loaded()
        return list(self._vectors.keys())

    def has_vector(self, intent_id: str, lang: str = "zh") -> bool:
        self._ensure_loaded()
        vecs = self._vectors.get(intent_id, {})
        return bool(vecs.get(lang))

    # ---- 写入（构建时用） ----
    def save_vector(
        self, intent_id: str, zh: Optional[List[float]], en: Optional[List[float]]
    ) -> None:
        """保存意图向量到 intent_units/{intent_id}/vector.json。"""
        intent_dir = self.units_dir / intent_id
        intent_dir.mkdir(parents=True, exist_ok=True)
        data = {"zh": zh, "en": en}
        (intent_dir / "vector.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        self._vectors[intent_id] = {"zh": zh, "en": en}
        self._loaded = True


# 模块级共享实例
_store: Optional[IntentVectorStore] = None


def get_store() -> IntentVectorStore:
    global _store
    if _store is None:
        _store = IntentVectorStore()
    return _store
