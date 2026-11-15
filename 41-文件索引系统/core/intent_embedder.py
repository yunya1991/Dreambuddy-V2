# -*- coding: utf-8 -*-
"""intent_embedder.py — 意图向量构建（P0，SPEC-41-L1 §2.2/§3.2）

从 intent_units/{intent}/examples_zh.jsonl + examples_en.jsonl 构建意图向量：
1. 每条例句加前缀：{intent_id} ({category})\nKeywords: ...\n\n{example}
2. embed 后取均值，得到该意图的语义质心
3. 保存到 vector.json

前缀策略 A/B 验证：use_prefix=True/False 对比 golden set top-1 准确率。
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from .embedder_bridge import embed_batch
from .intent_vector_store import IntentVectorStore

logger = logging.getLogger(__name__)


def _detect_lang(text: str) -> str:
    """语言检测：中文字符占比 ≥30% 判 zh，否则 en。"""
    if not text:
        return "zh"
    zh_count = sum(1 for c in text if "\u4e00" <= c <= "\u9fa5")
    return "zh" if zh_count / len(text) >= 0.30 else "en"


def _build_prefix(intent_id: str, category: str, keywords: List[str]) -> str:
    """构建例句前缀（分块前缀策略）。"""
    kw = ", ".join(keywords[:5]) if keywords else ""
    return f"{intent_id} ({category})\nKeywords: {kw}\n\n"


def _load_examples(intent_dir: Path, lang: str) -> List[str]:
    """加载某意图某语言的正例句。"""
    fname = f"examples_{lang}.jsonl"
    fpath = intent_dir / fname
    if not fpath.exists():
        return []
    examples = []
    for line in fpath.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            msg = obj.get("message", "").strip()
            if msg:
                examples.append(msg)
        except json.JSONDecodeError:
            examples.append(line)
    return examples


def _load_intent_meta(intent_dir: Path) -> Dict:
    """加载意图元数据 intent.yaml。"""
    ypath = intent_dir / "intent.yaml"
    if not ypath.exists():
        return {"id": intent_dir.name, "category": "general", "keywords": []}
    # 简易 YAML 解析（避免引入 pyyaml 依赖）
    meta = {"id": intent_dir.name, "category": "general", "keywords": []}
    for line in ypath.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("category:"):
            meta["category"] = line.split(":", 1)[1].strip()
        elif line.startswith("keywords:"):
            rest = line.split(":", 1)[1].strip()
            if rest:
                meta["keywords"] = [k.strip() for k in rest.split(",") if k.strip()]
    return meta


def build_intent_vector(
    intent_id: str,
    store: Optional[IntentVectorStore] = None,
    use_prefix: bool = False,
    min_examples: int = 5,
) -> Dict[str, Optional[List[float]]]:
    """构建单个意图的 zh/en 向量。

    Args:
        intent_id: 意图 ID
        store: 向量存储（None 则用默认）
        use_prefix: 是否使用分块前缀策略（A/B 验证用）
        min_examples: 最少正例句数，不足则该语言向量为 None

    Returns:
        {"zh": [512 floats] or None, "en": [384 floats] or None}
    """
    store = store or IntentVectorStore()
    intent_dir = store.units_dir / intent_id
    if not intent_dir.exists():
        logger.warning("意图目录不存在: %s", intent_dir)
        return {"zh": None, "en": None}

    meta = _load_intent_meta(intent_dir)
    category = meta.get("category", "general")
    keywords = meta.get("keywords", [])
    prefix = _build_prefix(intent_id, category, keywords) if use_prefix else ""

    result: Dict[str, Optional[List[float]]] = {"zh": None, "en": None}

    for lang in ("zh", "en"):
        examples = _load_examples(intent_dir, lang)
        if len(examples) < min_examples:
            logger.info(
                "[%s] %s 正例句不足 (%d < %d)，跳过", intent_id, lang, len(examples), min_examples
            )
            continue
        # 加前缀
        prefixed = [prefix + ex for ex in examples] if use_prefix else examples
        # embed 取均值
        vecs = embed_batch(prefixed, lang=lang)
        if not vecs:
            logger.warning("[%s] %s embed 返回空", intent_id, lang)
            continue
        dim = len(vecs[0])
        centroid = [sum(v[i] for v in vecs) / len(vecs) for i in range(dim)]
        # L2 归一化
        norm = sum(x * x for x in centroid) ** 0.5
        if norm > 0:
            centroid = [x / norm for x in centroid]
        result[lang] = centroid
        logger.info("[%s] %s 向量构建完成 (%d 例句, %d 维)", intent_id, lang, len(examples), dim)

    store.save_vector(intent_id, result["zh"], result["en"])
    return result


def build_all(
    store: Optional[IntentVectorStore] = None,
    use_prefix: bool = False,
    min_examples: int = 5,
) -> Dict[str, Dict[str, Optional[List[float]]]]:
    """构建所有意图的向量。"""
    store = store or IntentVectorStore()
    store.units_dir.mkdir(parents=True, exist_ok=True)
    results: Dict[str, Dict[str, Optional[List[float]]]] = {}
    for intent_dir in sorted(store.units_dir.iterdir()):
        if not intent_dir.is_dir():
            continue
        intent_id = intent_dir.name
        results[intent_id] = build_intent_vector(
            intent_id, store=store, use_prefix=use_prefix, min_examples=min_examples
        )
    return results
