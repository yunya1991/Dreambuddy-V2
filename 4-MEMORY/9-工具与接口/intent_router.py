"""IntentRouter — 记忆路由器：Intent-Engine → 三库加权召回

SPEC: SPEC-CognitiveSystem-Evolution.md §2.4.1 + §4.3 P2-1

将 intent_engine 从纯分类器升级为记忆路由器，实现三库
（记忆库 + SKILL 库 + 知识库）加权召回。

核心设计（轻量级，代码驱动，无 ML 依赖）：
  - intent 类型 → 权重映射表（INTENT_WEIGHTS）
  - fast-path（默认）：只查权重最高的单库（低延迟）
  - full-path（显式）：三库加权召回（高召回率）
  - FAIL-OPEN：某库查询函数抛异常时返回空列表，不阻塞其他库

架构：
    intent_engine.recognize(task) → IntentResult{type, confidence, keywords}
                                            ↓
                               IntentRouter.route(intent_result)
                                            ↓
                        ┌───────────────────┼───────────────────┐
                        ↓                   ↓                   ↓
                  memory_recall      skill_search       knowledge_rag
                  (weight: w1)       (weight: w2)       (weight: w3)
                        ↓                   ↓                   ↓
                        └───────────────────┼───────────────────┘
                                            ↓
                                  RecallResult{
                                    memories, skills, knowledge,
                                    confidence
                                  }
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from cognitive_interfaces import CognitiveRouter, RecallResult


# ============================================================
# 权重映射表：intent_type → (memory_w, skill_w, knowledge_w)
# ============================================================

INTENT_WEIGHTS: Dict[str, Tuple[float, float, float]] = {
    "code_question":     (0.6, 0.3, 0.1),
    "knowledge_query":   (0.1, 0.2, 0.7),
    "skill_match":       (0.2, 0.6, 0.2),
    "trading_decision":  (0.5, 0.3, 0.2),
    "bug_investigation": (0.5, 0.2, 0.3),
    "general":           (0.4, 0.3, 0.3),
}

# 三库名称 → 权重在 tuple 中的索引
_DB_INDEX: Dict[str, int] = {"memory": 0, "skill": 1, "knowledge": 2}


class IntentRouter(CognitiveRouter):
    """记忆路由器 — 接收 intent_vector，路由到记忆/SKILL/知识三库，
    按权重聚合召回结果，输出统一 RecallResult。

    实现 CognitiveRouter ABC（§3.5 M6）。轻量级路由，无 ML 依赖。

    Args:
        memory_recall_fn: 记忆库查询函数 fn(context, top_k) -> list[dict]
        skill_search_fn: SKILL 库查询函数 fn(context, top_k) -> list[dict]
        knowledge_rag_fn: 知识库 RAG 查询函数 fn(context, top_k) -> list[dict]
    """

    def __init__(
        self,
        memory_recall_fn: Callable[[str, int], List[Dict[str, Any]]],
        skill_search_fn: Callable[[str, int], List[Dict[str, Any]]],
        knowledge_rag_fn: Callable[[str, int], List[Dict[str, Any]]],
    ) -> None:
        self._memory_recall = memory_recall_fn
        self._skill_search = skill_search_fn
        self._knowledge_rag = knowledge_rag_fn

    def route(
        self,
        intent_vector: Any,
        databases: Optional[dict] = None,
        top_k: int = 5,
        route_mode: str = "fast",
    ) -> RecallResult:
        """路由 intent_vector 到三库，返回加权召回结果。

        对齐 CognitiveRouter ABC 的 route(self, intent_vector, databases) 签名，
        额外支持 top_k 和 route_mode 参数（增量扩展，向后兼容）。

        Args:
            intent_vector: 意图向量（intent_engine 产出的 dict，
                含 type/confidence/keywords 等字段）
            databases: 三库句柄 dict（ABC 契约参数，此处保留兼容，
                实际查询函数在 __init__ 注入，默认 None）
            top_k: 每库返回结果上限
            route_mode: "fast"（单库，默认）或 "full"（三库加权）

        Returns:
            RecallResult 含三库召回结果 + 综合置信度
        """
        intent_result: Dict[str, Any] = intent_vector or {}
        intent_type = intent_result.get("type", "general")
        intent_confidence = float(intent_result.get("confidence", 0.5))

        # 权重查表（未知类型回退 general）
        mem_w, skill_w, know_w = INTENT_WEIGHTS.get(
            intent_type, INTENT_WEIGHTS["general"]
        )

        # 从 intent_result 派生查询 context 字符串
        keywords = intent_result.get("keywords", [])
        context = intent_result.get("context", "")
        if not context:
            context = " ".join(keywords) if keywords else str(intent_type)

        # 查询函数分发表
        db_fns = {
            "memory": self._memory_recall,
            "skill": self._skill_search,
            "knowledge": self._knowledge_rag,
        }
        weights = {"memory": mem_w, "skill": skill_w, "knowledge": know_w}

        if route_mode != "full":
            # ---------- fast-path：只查权重最高的单库 ----------
            best_db = max(weights, key=lambda k: weights[k])
            best_w = weights[best_db]
            results = self._safe_call(db_fns[best_db], context, top_k)
            results = results[:top_k]

            # 构造 RecallResult（只填命中库，其余为空）
            kwargs = {"memories": [], "skills": [], "knowledge": []}
            if best_db == "memory":
                kwargs["memories"] = results
            elif best_db == "skill":
                kwargs["skills"] = results
            else:
                kwargs["knowledge"] = results
            # fast-path 置信度 = intent 置信度 × 最高权重（单库召回降信）
            kwargs["confidence"] = round(intent_confidence * best_w, 4)
            return RecallResult(**kwargs)

        # ---------- full-path：三库加权召回 ----------
        memories = self._safe_call(self._memory_recall, context, top_k)[:top_k]
        skills = self._safe_call(self._skill_search, context, top_k)[:top_k]
        knowledge = self._safe_call(self._knowledge_rag, context, top_k)[:top_k]

        # 加权置信度：按各库权重 × 召回命中率（非空即命中）
        total_w = mem_w + skill_w + know_w
        hit_w = 0.0
        if memories:
            hit_w += mem_w
        if skills:
            hit_w += skill_w
        if knowledge:
            hit_w += know_w
        confidence = round(intent_confidence * (hit_w / total_w), 4) if total_w > 0 else 0.0

        return RecallResult(
            memories=memories,
            skills=skills,
            knowledge=knowledge,
            confidence=confidence,
        )

    @staticmethod
    def _safe_call(
        fn: Callable[[str, int], List[Dict[str, Any]]],
        context: str,
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """FAIL-OPEN 包装：查询函数抛异常时返回空列表，不阻塞其他库。

        Args:
            fn: 查询函数 fn(context, top_k) -> list[dict]
            context: 查询上下文字符串
            top_k: 返回上限

        Returns:
            查询结果列表；异常时返回空列表
        """
        try:
            result = fn(context, top_k)
            return list(result) if result else []
        except Exception:
            return []
