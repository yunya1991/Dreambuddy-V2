"""P2-2 L2A 条件访问 — 自动路由决策 TDD RED 测试

SPEC: SPEC-CognitiveSystem-Evolution.md §2.4.2 + §4.3 P2-2
80% 场景走 fast-path，20% 复杂场景走 full-path。

RED 契约：
  - route_mode="auto" 自动决定 fast/full
  - confidence >= 0.7 → fast（高置信度）
  - confidence < 0.4 → full（低置信度）
  - 0.4 ≤ confidence < 0.7 → 按 intent 类型分流
  - 规则缓存复用决策
  - 显式 route_mode 覆盖 auto
  - 非 dict intent → 默认 fast（鲁棒性）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest


# ============================================================
# 辅助：mock 三库查询函数（复用 P2-1 模式）
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
# Test 1: 高置信度 → fast-path（只查 1 个库）
# ============================================================

def test_auto_high_confidence_uses_fast():
    """RED: confidence=0.9 → auto 选 fast，只查 1 个库。"""
    calls = []
    router = _make_router(calls)
    intent = {"type": "general", "confidence": 0.9, "keywords": ["test"]}
    router.route(intent, top_k=5, route_mode="auto")

    assert len(calls) == 1, \
        f"高置信度 auto 应走 fast-path（1 库），实际调用 {len(calls)} 次: {calls}"


# ============================================================
# Test 2: 低置信度 → full-path（查 3 个库）
# ============================================================

def test_auto_low_confidence_uses_full():
    """RED: confidence=0.2 → auto 选 full，查 3 个库。"""
    calls = []
    router = _make_router(calls)
    intent = {"type": "general", "confidence": 0.2, "keywords": ["test"]}
    router.route(intent, top_k=5, route_mode="auto")

    assert len(calls) == 3, \
        f"低置信度 auto 应走 full-path（3 库），实际调用 {len(calls)} 次: {calls}"
    assert set(calls) == {"memory", "skill", "knowledge"}, \
        f"full-path 应查三库，实际: {calls}"


# ============================================================
# Test 3: 中置信度 + 简单类型 → fast
# ============================================================

def test_auto_mid_confidence_simple_type_fast():
    """RED: confidence=0.5 + code_question → fast（简单场景）。"""
    calls = []
    router = _make_router(calls)
    intent = {"type": "code_question", "confidence": 0.5, "keywords": ["python"]}
    router.route(intent, top_k=5, route_mode="auto")

    assert len(calls) == 1, \
        f"code_question 中置信度应走 fast（1 库），实际 {len(calls)} 次: {calls}"


# ============================================================
# Test 4: 中置信度 + 复杂类型 → full
# ============================================================

def test_auto_mid_confidence_complex_type_full():
    """RED: confidence=0.5 + trading_decision → full（复杂场景）。"""
    calls = []
    router = _make_router(calls)
    intent = {"type": "trading_decision", "confidence": 0.5, "keywords": ["entry"]}
    router.route(intent, top_k=5, route_mode="auto")

    assert len(calls) == 3, \
        f"trading_decision 中置信度应走 full（3 库），实际 {len(calls)} 次: {calls}"


# ============================================================
# Test 5: 规则缓存复用决策
# ============================================================

def test_auto_cache_reuses_decision():
    """RED: 相同 intent 调两次，第二次命中缓存。"""
    calls = []
    router = _make_router(calls)
    intent = {"type": "general", "confidence": 0.55, "keywords": ["x"]}

    # 第一次调用 → 决策写入缓存
    router.route(intent, top_k=5, route_mode="auto")
    cache_after_first = dict(router._route_cache)
    assert len(cache_after_first) >= 1, \
        "第一次 auto 调用后 _route_cache 应有至少 1 条记录"

    # 第二次调用 → 缓存命中（cache 不增长）
    router.route(intent, top_k=5, route_mode="auto")
    assert len(router._route_cache) == len(cache_after_first), \
        "相同 intent 第二次调用应命中缓存，cache 不应增长"

    # clear_route_cache 清空
    router.clear_route_cache()
    assert len(router._route_cache) == 0, \
        "clear_route_cache() 后 _route_cache 应为空"


# ============================================================
# Test 6: 未知类型 + 中置信度 → 默认 fast（80% 目标）
# ============================================================

def test_auto_default_is_fast():
    """RED: 未知 intent 类型 + 中置信度 → 默认 fast。"""
    calls = []
    router = _make_router(calls)
    intent = {"type": "unknown_type_xyz", "confidence": 0.5, "keywords": ["?"]}
    router.route(intent, top_k=5, route_mode="auto")

    assert len(calls) == 1, \
        f"未知类型中置信度应默认走 fast（1 库），实际 {len(calls)} 次: {calls}"


# ============================================================
# Test 7: 显式 route_mode 覆盖 auto
# ============================================================

def test_auto_explicit_mode_overrides():
    """RED: route_mode='full' + 高置信度 → 仍走 full（显式覆盖）。"""
    calls = []
    router = _make_router(calls)
    intent = {"type": "general", "confidence": 0.95, "keywords": ["x"]}
    # auto 下高置信度会选 fast，但显式 full 应覆盖
    router.route(intent, top_k=5, route_mode="full")

    assert len(calls) == 3, \
        f"显式 route_mode='full' 应覆盖 auto 逻辑走 full（3 库），实际 {len(calls)} 次: {calls}"


# ============================================================
# Test 8: 非 dict intent → 默认 fast（鲁棒性）
# ============================================================

def test_auto_non_dict_intent_defaults_fast():
    """RED: intent_vector 非 dict（如 list）→ auto 默认 fast 不崩溃。"""
    calls = []
    router = _make_router(calls)
    # 传 list 而非 dict — auto 应安全降级为 fast
    router.route([0.1, 0.9], top_k=5, route_mode="auto")

    # 不崩溃 + 只查 1 库（fast 默认）
    assert len(calls) == 1, \
        f"非 dict intent auto 应安全降级为 fast（1 库），实际 {len(calls)} 次: {calls}"
