# -*- coding: utf-8 -*-
"""intent_matcher.py — 双通道意图匹配器（P0，SPEC-41-L1 §2.1/§3.3）

通道 A（正则）：由调用方注入 regex_func（P1 集成到 l1_route_signal.detect_intent）
通道 B（语义）：embed(message) → intent_vector_store.cosine_top1()
合并：A 优先，A 未命中用 B，B 未命中返回 None
"""

import logging
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from .embedder_bridge import embed
from .intent_vector_store import IntentVectorStore, get_store

logger = logging.getLogger(__name__)

# 语义命中阈值（P2 校准：golden set 332 正例 + 30 反例 ROC）
# 中文 0.65：正则通道已 100% 覆盖 golden 正例，语义通道仅需控制反例 FPR。
#   反例最高 max_sim=0.642，阈值 0.65 时 FPR=0%（≤2% 目标），有效 TPR=100%。
#   语义兜底召回（正则漏过正例）约 88%，作为正则的安全网。
SEMANTIC_THRESHOLD_ZH = 0.65
SEMANTIC_THRESHOLD_EN = 0.50

# 语言检测：中文字符占比阈值
LANG_DETECT_ZH_RATIO = 0.30


def detect_lang(text: str) -> str:
    """语言检测：中文字符占比 ≥30% 判 zh，否则 en。"""
    if not text:
        return "zh"
    zh_count = sum(1 for c in text if "\u4e00" <= c <= "\u9fa5")
    return "zh" if zh_count / len(text) >= LANG_DETECT_ZH_RATIO else "en"


@dataclass
class MatchResult:
    intent: Optional[str]
    channel: str  # "regex" | "semantic" | "none"
    score: float = 0.0
    lang: str = "zh"
    semantic_top3: List[Tuple[str, float]] = field(default_factory=list)


class IntentMatcher:
    """双通道意图匹配器。"""

    def __init__(
        self,
        store: Optional[IntentVectorStore] = None,
        regex_func: Optional[Callable[[str], Optional[str]]] = None,
        threshold_zh: float = SEMANTIC_THRESHOLD_ZH,
        threshold_en: float = SEMANTIC_THRESHOLD_EN,
    ):
        self.store = store or get_store()
        self.regex_func = regex_func
        self.threshold_zh = threshold_zh
        self.threshold_en = threshold_en

    # ---- 语义匹配 ----
    def semantic_match(self, message: str, lang: str = "auto") -> Optional[Tuple[str, float]]:
        """纯语义匹配：返回 (intent_id, cosine_similarity) 或 None。"""
        if not message:
            return None
        lang = detect_lang(message) if lang == "auto" else lang
        threshold = self.threshold_zh if lang == "zh" else self.threshold_en

        query_vec = embed(message, lang=lang)
        if not query_vec:
            return None
        top1 = self.store.top1(query_vec, lang=lang)
        if top1 and top1[1] >= threshold:
            return top1
        return None

    def semantic_topk(
        self, message: str, lang: str = "auto", k: int = 3
    ) -> List[Tuple[str, float]]:
        """返回 top-K 语义候选（调试用）。"""
        if not message:
            return []
        lang = detect_lang(message) if lang == "auto" else lang
        query_vec = embed(message, lang=lang)
        if not query_vec:
            return []
        return self.store.search(query_vec, lang=lang, top_k=k)

    # ---- 正则匹配 ----
    def regex_match(self, message: str) -> Optional[str]:
        """纯正则匹配：调用注入的 regex_func。"""
        if not message or not self.regex_func:
            return None
        try:
            return self.regex_func(message)
        except Exception as e:
            logger.warning("regex_func 异常: %s", e)
            return None

    # ---- 双通道合并 ----
    def match(self, message: str, lang: str = "auto") -> MatchResult:
        """双通道匹配：正则优先，正则未命中走语义。"""
        if not message:
            return MatchResult(intent=None, channel="none")

        # 通道 A：正则
        regex_intent = self.regex_match(message)
        if regex_intent:
            return MatchResult(intent=regex_intent, channel="regex", score=1.0)

        # 通道 B：语义
        resolved_lang = detect_lang(message) if lang == "auto" else lang
        top3 = self.semantic_topk(message, lang=resolved_lang, k=3)
        semantic = self.semantic_match(message, lang=resolved_lang)
        if semantic:
            return MatchResult(
                intent=semantic[0],
                channel="semantic",
                score=semantic[1],
                lang=resolved_lang,
                semantic_top3=top3,
            )

        return MatchResult(intent=None, channel="none", lang=resolved_lang, semantic_top3=top3)
