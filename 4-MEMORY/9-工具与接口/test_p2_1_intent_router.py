"""P2-1 IntentRouter 记忆路由器 TDD RED 测试

SPEC: SPEC-CognitiveSystem-Evolution.md §2.4.1 + §4.3 P2-1
将 intent_engine 从纯分类器升级为记忆路由器，实现三库加权召回。

RED 契约：
  - IntentRouter 继承 CognitiveRouter ABC
  - route() 返回 RecallResult
  - code_question 类型 memory 权重最高 → fast-path 只查 memory
  - knowledge_query 类型 knowledge 权重最高 → fast-path 只查 knowledge
  - fast-path 只调用 1 个库的查询函数
  - full-path 调用 3 个库的查询函数
  - top_k 限制每库返回数
  - FAIL-OPEN：某库查询函数抛异常时其他库结果不受影响

测试用 mock 函数（lambda 返回预设结果）模拟三库查询，不依赖真实数据库。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest


# ============================================================
# 辅助：mock 三库查询函数（带调用计数）
# ============================================================

def _make_mock_fn(calls_log, tag, payload):
    """构造带调用计数的 mock 查询函数。

    Args:
        calls_log: list，每次调用追加 tag
        tag: 标识哪个库
        payload: 返回的预设结果（list of dict）

    Returns:
        fn(context, top_k) -> list[dict]
    """
    def _fn(context, top_k):
        calls_log.append(tag)
        return list(payload)  # 返回副本，避免被切片修改
    return _fn


def _make_failing_fn(calls_log, tag):
    """构造必定抛异常的 mock 函数（测试 FAIL-OPEN）。"""
    def _fn(context, top_k):
        calls_log.append(tag)
        raise RuntimeError(f"{tag} DB query failed (模拟故障)")
    return _fn


# ============================================================
# Test 1: IntentRouter 继承 CognitiveRouter ABC
# ============================================================

def test_intent_router_is_cognitive_router():
    """RED: IntentRouter 是 CognitiveRouter 的子类。"""
    from cognitive_interfaces import CognitiveRouter
    from intent_router import IntentRouter

    assert issubclass(IntentRouter, CognitiveRouter), \
        "IntentRouter 必须继承 CognitiveRouter ABC"


# ============================================================
# Test 2: route() 返回 RecallResult
# ============================================================

def test_route_returns_recall_result():
    """RED: route() 返回 RecallResult 实例。"""
    from cognitive_interfaces import RecallResult
    from intent_router import IntentRouter

    calls = []
    mem_fn = _make_mock_fn(calls, "memory", [{"id": "m1", "content": "hello"}])
    skill_fn = _make_mock_fn(calls, "skill", [{"id": "s1"}])
    know_fn = _make_mock_fn(calls, "knowledge", [{"id": "k1"}])

    router = IntentRouter(mem_fn, skill_fn, know_fn)
    intent = {"type": "general", "confidence": 0.8, "keywords": ["test"]}
    result = router.route(intent, top_k=5, route_mode="full")

    assert isinstance(result, RecallResult), \
        "route() 必须返回 RecallResult 实例"


# ============================================================
# Test 3: code_question 类型 memory 权重最高 → fast-path 只查 memory
# ============================================================

def test_route_with_code_question_weights():
    """RED: code_question 类型 memory 权重最高，fast-path 只查 memory 库。"""
    from intent_router import IntentRouter

    calls = []
    mem_fn = _make_mock_fn(calls, "memory", [{"id": "m1"}])
    skill_fn = _make_mock_fn(calls, "skill", [{"id": "s1"}])
    know_fn = _make_mock_fn(calls, "knowledge", [{"id": "k1"}])

    router = IntentRouter(mem_fn, skill_fn, know_fn)
    intent = {"type": "code_question", "confidence": 0.9, "keywords": ["python", "bug"]}
    result = router.route(intent, top_k=5, route_mode="fast")

    # fast-path 只查 memory
    assert calls == ["memory"], \
        f"code_question fast-path 应只查 memory，实际调用: {calls}"
    # memory 结果非空
    assert len(result.memories) == 1
    assert result.memories[0]["id"] == "m1"


# ============================================================
# Test 4: knowledge_query 类型 knowledge 权重最高 → fast-path 只查 knowledge
# ============================================================

def test_route_with_knowledge_query_weights():
    """RED: knowledge_query 类型 knowledge 权重最高，fast-path 只查 knowledge 库。"""
    from intent_router import IntentRouter

    calls = []
    mem_fn = _make_mock_fn(calls, "memory", [{"id": "m1"}])
    skill_fn = _make_mock_fn(calls, "skill", [{"id": "s1"}])
    know_fn = _make_mock_fn(calls, "knowledge", [{"id": "k1"}])

    router = IntentRouter(mem_fn, skill_fn, know_fn)
    intent = {"type": "knowledge_query", "confidence": 0.85, "keywords": ["market", "structure"]}
    result = router.route(intent, top_k=5, route_mode="fast")

    # fast-path 只查 knowledge
    assert calls == ["knowledge"], \
        f"knowledge_query fast-path 应只查 knowledge，实际调用: {calls}"
    assert len(result.knowledge) == 1
    assert result.knowledge[0]["id"] == "k1"


# ============================================================
# Test 5: fast-path 只调用 1 个库的查询函数
# ============================================================

def test_route_fast_path_single_db():
    """RED: fast-path 模式只调用 1 个库的查询函数（权重最高的那个）。"""
    from intent_router import IntentRouter

    calls = []
    mem_fn = _make_mock_fn(calls, "memory", [{"id": "m1"}])
    skill_fn = _make_mock_fn(calls, "skill", [{"id": "s1"}])
    know_fn = _make_mock_fn(calls, "knowledge", [{"id": "k1"}])

    router = IntentRouter(mem_fn, skill_fn, know_fn)
    # skill_match 类型 skill 权重最高 (0.6)
    intent = {"type": "skill_match", "confidence": 0.7, "keywords": ["tdd"]}
    result = router.route(intent, top_k=5, route_mode="fast")

    # fast-path 只调用 1 次
    assert len(calls) == 1, \
        f"fast-path 应只调用 1 个库的查询函数，实际调用 {len(calls)} 次: {calls}"
    # 且调用的是 skill（权重最高）
    assert calls == ["skill"], \
        f"skill_match 类型 fast-path 应查 skill 库，实际: {calls}"
    assert len(result.skills) == 1


# ============================================================
# Test 6: full-path 调用 3 个库的查询函数
# ============================================================

def test_route_full_path_three_db():
    """RED: full-path 模式调用全部 3 个库的查询函数。"""
    from intent_router import IntentRouter

    calls = []
    mem_fn = _make_mock_fn(calls, "memory", [{"id": "m1"}])
    skill_fn = _make_mock_fn(calls, "skill", [{"id": "s1"}])
    know_fn = _make_mock_fn(calls, "knowledge", [{"id": "k1"}])

    router = IntentRouter(mem_fn, skill_fn, know_fn)
    intent = {"type": "trading_decision", "confidence": 0.75, "keywords": ["entry", "signal"]}
    result = router.route(intent, top_k=5, route_mode="full")

    # full-path 调用全部 3 个库
    assert len(calls) == 3, \
        f"full-path 应调用 3 个库的查询函数，实际调用 {len(calls)} 次: {calls}"
    # 三个库都被调用
    assert set(calls) == {"memory", "skill", "knowledge"}, \
        f"full-path 应调用三库，实际: {calls}"
    # 三库结果都非空
    assert len(result.memories) == 1
    assert len(result.skills) == 1
    assert len(result.knowledge) == 1


# ============================================================
# Test 7: top_k 限制每库返回数
# ============================================================

def test_route_respects_top_k():
    """RED: top_k 限制每个库的返回结果数。"""
    from intent_router import IntentRouter

    # 构造 10 条结果的 mock
    big_payload = [{"id": f"m{i}"} for i in range(10)]
    calls = []
    mem_fn = _make_mock_fn(calls, "memory", big_payload)
    skill_fn = _make_mock_fn(calls, "skill", [{"id": f"s{i}"} for i in range(10)])
    know_fn = _make_mock_fn(calls, "knowledge", [{"id": f"k{i}"} for i in range(10)])

    router = IntentRouter(mem_fn, skill_fn, know_fn)
    intent = {"type": "general", "confidence": 0.6, "keywords": ["misc"]}
    result = router.route(intent, top_k=3, route_mode="full")

    # 每库返回不超过 top_k=3
    assert len(result.memories) <= 3, \
        f"memory 库返回应 <= top_k=3，实际 {len(result.memories)}"
    assert len(result.skills) <= 3, \
        f"skill 库返回应 <= top_k=3，实际 {len(result.skills)}"
    assert len(result.knowledge) <= 3, \
        f"knowledge 库返回应 <= top_k=3，实际 {len(result.knowledge)}"


# ============================================================
# Test 8: FAIL-OPEN — 某库查询函数抛异常时其他库结果不受影响
# ============================================================

def test_route_fail_open():
    """RED: 某库查询函数抛异常时，其他库结果不受影响（FAIL-OPEN）。"""
    from intent_router import IntentRouter

    calls = []
    # memory 正常返回
    mem_fn = _make_mock_fn(calls, "memory", [{"id": "m1"}])
    # skill 抛异常（模拟故障）
    skill_fn = _make_failing_fn(calls, "skill")
    # knowledge 正常返回
    know_fn = _make_mock_fn(calls, "knowledge", [{"id": "k1"}])

    router = IntentRouter(mem_fn, skill_fn, know_fn)
    intent = {"type": "general", "confidence": 0.6, "keywords": ["test"]}
    result = router.route(intent, top_k=5, route_mode="full")

    # 三库都被调用（skill 调了但抛异常）
    assert len(calls) == 3, \
        f"FAIL-OPEN 下三库都应被调用，实际调用 {len(calls)} 次: {calls}"
    # memory 和 knowledge 结果不受影响
    assert len(result.memories) == 1, \
        "memory 库结果应正常返回，不受 skill 故障影响"
    assert len(result.knowledge) == 1, \
        "knowledge 库结果应正常返回，不受 skill 故障影响"
    # skill 结果为空（故障 FAIL-OPEN 返回空列表）
    assert result.skills == [], \
        f"skill 库故障应 FAIL-OPEN 返回空列表，实际: {result.skills}"
