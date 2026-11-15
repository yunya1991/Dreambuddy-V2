# -*- coding: utf-8 -*-
"""embedder_bridge.py — L1 语义意图检索的 embedding 桥接（P0，SPEC-41-L1 §3.4/§3.5）

策略：in-process 优先，subprocess 回退。
- 本地 41 venv 已装 sentence-transformers，直接 in-process 调用 9-RAG-INFRA 的 Embedder
- 云端 41 venv 若缺依赖，回退 subprocess 调用 intent_embedder_bridge.py（venv-trading）
- 支持双模型：bge-small-zh-v1.5（中文，512 维）+ all-MiniLM-L6-v2（英文，384 维）
- FAIL-OPEN：任何异常返回空列表，调用方降级为纯正则
"""

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# 9-RAG-INFRA 路径（本地与云端一致的相对定位）
_HERE = Path(__file__).resolve().parent  # 41-文件索引系统/core/
_INDEX_ROOT = _HERE.parent  # 41-文件索引系统/
_WORKSPACE_ROOT = _INDEX_ROOT.parent  # dreambuddy-v2/
_RAG_INFRA = str(_WORKSPACE_ROOT / "2-KNOWLEDGE" / "9-RAG-INFRA")

# 模型配置
# 主模型 bge-base-zh-v1.5（768 维）：实测口语措辞意图区分度显著优于 bge-small
# （A 组 12 条 top1 命中 0/12 → 12/12，见 SPEC-41-L1-新闻意图检索 §8.5）。
# 可用 L1_ZH_MODEL 覆盖为本地路径/HF id；加载失败时回退 bge-small-zh-v1.5（512 维）。
ZH_MODEL = os.environ.get("L1_ZH_MODEL", "BAAI/bge-base-zh-v1.5")
ZH_MODEL_FALLBACK = os.environ.get("L1_ZH_MODEL_FALLBACK", "BAAI/bge-small-zh-v1.5")
EN_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# subprocess 桥接脚本（云端 41 venv 无 st 时使用）
_BRIDGE_SCRIPT = str(_INDEX_ROOT / "scripts" / "intent_embedder_bridge.py")

# 模块级缓存的 in-process embedder 实例
_zh_embedder = None
_en_embedder = None
_inproc_available: Optional[bool] = None  # None=未探测, True/False=结果


def _try_inproc_embedder(model_name: str):
    """尝试 in-process 加载 9-RAG-INFRA 的 Embedder。失败返回 None。"""
    global _inproc_available
    if _inproc_available is False:
        return None
    try:
        if _RAG_INFRA not in sys.path:
            sys.path.insert(0, _RAG_INFRA)
        from vector_store.embedder import Embedder

        _inproc_available = True
        return Embedder(model_name)
    except Exception as e:
        _inproc_available = False
        logger.warning("in-process embedder 不可用，回退 subprocess: %s", e)
        return None


def _get_zh_embedder():
    global _zh_embedder, _inproc_available
    if _zh_embedder is None:
        _zh_embedder = _try_inproc_embedder(ZH_MODEL)
        if _zh_embedder is None and ZH_MODEL_FALLBACK and ZH_MODEL_FALLBACK != ZH_MODEL:
            # 主模型不可用时回退（重置探测标记，否则 _try_inproc_embedder 直接短路）
            logger.warning("主向量模型 %s 加载失败，回退 %s", ZH_MODEL, ZH_MODEL_FALLBACK)
            _inproc_available = None
            _zh_embedder = _try_inproc_embedder(ZH_MODEL_FALLBACK)
    return _zh_embedder


def _get_en_embedder():
    global _en_embedder
    if _en_embedder is None:
        _en_embedder = _try_inproc_embedder(EN_MODEL)
    return _en_embedder


def embed_batch(texts: List[str], lang: str = "zh") -> List[List[float]]:
    """批量文本向量化。

    Args:
        texts: 文本列表
        lang: "zh" → bge-small-zh-v1.5 (512维), "en" → all-MiniLM-L6-v2 (384维)

    Returns:
        向量列表（每条为 float list）。失败返回 []。
    """
    if not texts:
        return []
    lang = (lang or "zh").lower()
    model = ZH_MODEL if lang == "zh" else EN_MODEL
    embedder = _get_zh_embedder() if lang == "zh" else _get_en_embedder()

    # in-process 路径
    if embedder is not None:
        try:
            vecs = embedder.embed_batch(texts)
            return [v.tolist() for v in vecs]
        except Exception as e:
            logger.warning("in-process embed 失败，回退 subprocess: %s", e)

    # subprocess 回退路径
    return _subprocess_embed(texts, model)


def _subprocess_embed(texts: List[str], model: str) -> List[List[float]]:
    """通过 subprocess 调用 intent_embedder_bridge.py。"""
    try:
        import json

        payload = json.dumps({"texts": texts, "model": model}, ensure_ascii=False)
        proc = subprocess.run(
            [sys.executable, _BRIDGE_SCRIPT],
            input=payload,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            logger.warning("embedder bridge 退出码 %d: %s", proc.returncode, proc.stderr[:200])
            return []
        result = json.loads(proc.stdout or "{}")
        return result.get("vectors", [])
    except Exception as e:
        logger.warning("subprocess embed 失败: %s", e)
        return []


def embed(text: str, lang: str = "zh") -> List[float]:
    """单条文本向量化。"""
    vecs = embed_batch([text], lang=lang)
    return vecs[0] if vecs else []


def is_inproc_available() -> bool:
    """探测 in-process embedder 是否可用（缓存结果）。"""
    global _inproc_available
    if _inproc_available is None:
        _try_inproc_embedder(ZH_MODEL)  # 触发探测
    return bool(_inproc_available)
