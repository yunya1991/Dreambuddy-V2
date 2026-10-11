"""P2-3 Agentic RAG 路由 — 智能检索决策 TDD RED 测试

SPEC: SPEC-CognitiveSystem-Evolution.md §2.4.3 + §4.3 P2-3
借鉴 arXiv:2501.09136 Agentic RAG 综述：从 pipeline 转向 routing。

三维度智能检索决策：
  1. 是否检索 — 高置信度 + 缓存命中 → 跳过检索
  2. 检索什么 — 按权重选择 DB 子集（跳过低权重 DB）
  3. 何时停止 — 置信度达标即停，不再过度检索

RED 契约：
  - route_mode="agentic" 触发 Agentic RAG 路由
  - 低权重 DB 被跳过（knowledge_query memory_w=0.1 < 阈值）
  - 置信度达标即停（高置信度只查 1 库）
  - 高置信度 + 缓存命中 → 第二次 0 次查询
  - 按权重降序查询
  - FAIL-OPEN：异常不崩溃
  - 非 dict intent 安全降级
  - clear_result_cache() 清空结果缓存
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest


# ============================================================
# 辅助：mock 三库查询函数（复用 P2-1/P2-2 模式）
# ============================================================

def _make_mock_fn(calls_log, tag, payload):
    """构造带调用计数的 mock 查询函数。"""
    def _fn(context, top_k):
        calls_log.append(tag)
        return list(payload)
    return _fn


def _make_router(calls, mem_payload=None, skill_payload=None, know_payload=None):
    """构造测试用 IntentRouter + 调用日志。"""
    from intent_router import IntentRouter
    mem_fn = _make_mock_fn(calls, "memory", mem_payload or [{"id": "m1"}])
    skill_fn = _make_mock_fn(calls, "skill", skill_payload or [{"id": "s1"}])
    know_fn = _make_mock_fn(calls, "knowledge", know_payload or [{"id": "k1"}])
    return IntentRouter(mem_fn, skill_fn, know_fn)


# ============================================================
# Test 1: 低权重 DB 被跳过
# ============================================================

def test_agentic_skips_low_weight_db():
    """RED: knowledge_query weights (0.1, 0.2, 0.7), memory(0.1) 低于阈值被跳过。"""
    calls = []
    router = _make_router(calls)
    intent = {"type": "knowledge_query", "confidence": 0.3, "keywords": ["test"]}
    router.route(intent, top_k=5, route_mode="agentic")

    assert "memory" not in calls, \
        f"memory(权重0.1) 低于阈值应被跳过，实际查询: {calls}"
    assert len(calls) >= 1, \
        f"至少应查 1 个 DB，实际 {len(calls)} 次: {calls}"


# ============================================================
# Test 2: 置信度达标即停（高置信度只查 1 库）
# ============================================================

def test_agentic_stops_early_on_high_confidence():
    """RED: knowledge_query confidence=0.9 → 查 knowledge 后达标即停（1 次调用）。"""
    calls = []
    router = _make_router(calls, know_payload=[{"id": "k1"}])
    intent = {"type": "knowledge_query", "confidence": 0.9, "keywords": ["test"]}
    router.route(intent, top_k=5, route_mode="agentic")

    assert len(calls) == 1, \
        f"高置信度应查 1 库即停，实际 {len(calls)} 次: {calls}"
    assert calls[0] == "knowledge", \
        f"应先查最高权重 knowledge(0.7)，实际: {calls}"


# ============================================================
# Test 3: 低置信度查多个 DB
# ============================================================

def test_agentic_queries_multiple_when_low_confidence():
    """RED: general confidence=0.5 → 不达阈值，查多个 DB。"""
    calls = []
    router = _make_router(calls)
    intent = {"type": "general", "confidence": 0.5, "keywords": ["test"]}
    router.route(intent, top_k=5, route_mode="agentic")

    assert len(calls) >= 2, \
        f"低置信度应查多个 DB，实际 {len(calls)} 次: {calls}"


# ============================================================
# Test 4: 高置信度 + 缓存命中 → 跳过检索
# ============================================================

def test_agentic_cache_hit_skips_retrieval():
    """RED: 高置信度重复 intent → 第二次命中缓存，0 次额外查询。"""
    calls = []
    router = _make_router(calls)
    intent = {"type": "knowledge_query", "confidence": 0.9, "keywords": ["test"]}

    # 第一次：查询 + 缓存结果
    router.route(intent, top_k=5, route_mode="agentic")
    first_call_count = len(calls)
    assert first_call_count >= 1, "第一次应查询"

    # 第二次：缓存命中，0 次额外查询
    router.route(intent, top_k=5, route_mode="agentic")
    assert len(calls) == first_call_count, \
        f"第二次应命中缓存 0 次查询，实际多调了 {len(calls) - first_call_count} 次"


# ============================================================
# Test 5: 按权重降序查询
# ============================================================

def test_agentic_respects_weight_ordering():
    """RED: trading_decision (0.5, 0.3, 0.2) → 先查 memory(最高权重)。"""
    calls = []
    router = _make_router(calls)
    intent = {"type": "trading_decision", "confidence": 0.3, "keywords": ["entry"]}
    router.route(intent, top_k=5, route_mode="agentic")

    assert calls[0] == "memory", \
        f"应先查 memory(权重0.5)，实际首查: {calls[0]}"


# ============================================================
# Test 6: FAIL-OPEN — 某库异常不崩溃
# ============================================================

def test_agentic_failopen_on_exception():
    """RED: memory 查询抛异常 → _safe_call 返回空，不崩溃，其他库继续。"""
    from intent_router import IntentRouter

    def boom_fn(context, top_k):
        raise RuntimeError("boom")

    calls = []
    skill_fn = _make_mock_fn(calls, "skill", [{"id": "s1"}])
    know_fn = _make_mock_fn(calls, "knowledge", [{"id": "k1"}])
    router = IntentRouter(boom_fn, skill_fn, know_fn)
    intent = {"type": "general", "confidence": 0.3, "keywords": ["test"]}

    result = router.route(intent, top_k=5, route_mode="agentic")

    assert result is not None, "FAIL-OPEN 不应崩溃"
    assert "skill" in calls or "knowledge" in calls, \
        f"memory 异常不应阻塞 skill/knowledge 查询，实际: {calls}"


# ============================================================
# Test 7: 非 dict intent 安全降级
# ============================================================

def test_agentic_non_dict_intent_safe():
    """RED: 非 dict intent → agentic 不崩溃，安全降级。"""
    calls = []
    router = _make_router(calls)
    # 传 list 而非 dict — agentic 应安全降级
    result = router.route([0.1, 0.9], top_k=5, route_mode="agentic")

    assert result is not None, "非 dict intent 不应崩溃"


# ============================================================
# Test 8: clear_result_cache() 清空结果缓存
# ============================================================

def test_agentic_clear_result_cache():
    """RED: agentic 路由后 _result_cache 非空，clear_result_cache() 清空。"""
    router = _make_router([])
    intent = {"type": "knowledge_query", "confidence": 0.9, "keywords": ["test"]}
    router.route(intent, top_k=5, route_mode="agentic")

    assert len(router._result_cache) >= 1, \
        "agentic 路由后应缓存结果"

    router.clear_result_cache()
    assert len(router._result_cache) == 0, \
        "clear_result_cache() 后 _result_cache 应为空"
