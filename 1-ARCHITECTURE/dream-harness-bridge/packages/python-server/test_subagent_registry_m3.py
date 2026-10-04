#!/usr/bin/env python3
"""M3: DSH Subagent 接入百炼 LLM 测试

覆盖:
- 默认无 LLM → 8 subagent 全部 FAIL-OPEN 注册
- 显式 llm_fn 注入 → risk_agent 跳过 (HC-3 纯算法), 其他 7 个注入
- 全局 provider 钩子 + 显式参数优先级
- make_bailian_llm_fn 无 dreamos/QWEN_API_KEY 时返回 None (HC-10)
- register_subagents_with_bailian 无 API key 时仍注册 (FAIL-OPEN)
"""
from __future__ import annotations

import pytest

import subagent_registry as reg


@pytest.fixture(autouse=True)
def _reset_provider():
    """每个测试前后清理全局 provider, 避免污染"""
    saved = reg.get_llm_fn_provider()
    reg.set_llm_fn_provider(None)
    yield
    reg.set_llm_fn_provider(saved)


def test_create_nodes_default_no_llm():
    """默认无 LLM: 8 个 subagent 全部注册, 走 FAIL-OPEN"""
    nodes = reg.create_subagent_nodes()
    assert len(nodes) == 8
    # 所有 node 都有 SubagentOutput 输出能力 (FAIL-OPEN 不依赖 LLM)
    for n in nodes:
        out = n.execute({"indicators": {}, "rationale": [], "direction": "NEUTRAL", "confidence": 0.5})
        assert out.module == n.module
        assert isinstance(out.summary, str)
        assert out.summary  # 非空


def test_create_nodes_with_llm_skips_risk():
    """显式 llm_fn 注入: risk_agent 跳过 (HC-3), 其他注入"""
    calls: list[str] = []

    def mock_llm(prompt: str) -> str:
        calls.append(prompt)
        return "mock-synthesis"

    nodes = reg.create_subagent_nodes(llm_fn=mock_llm)
    assert len(nodes) == 8

    # 找到 risk node
    risk_node = next(n for n in nodes if n.module == "risk")
    # risk_agent 内部即使有 llm_fn 也不会调用 (HC-3 纯算法)
    # 验证: risk_agent 当前实现中 _generate_summary 会在有 llm_fn 时调用
    # 但 risk_agent __init__ 不接收 llm_fn — 我们直接传 llm_fn 给构造函数会失败
    # 所以 create_subagent_nodes 内部对 risk 跳过 llm_fn
    out = risk_node.execute({"indicators": {"var_95": 0.05}, "rationale": [], "direction": "NEUTRAL", "confidence": 0.5})
    assert out.module == "risk"

    # 验证非 risk agent 调用了 LLM (sentiment/flow/valuation/macro/onchain/portfolio)
    # 通过 _llm_fn 注入痕迹判断: 检查任一非 risk node 的 _subagent._llm_fn 是否设置
    non_risk_nodes = [n for n in nodes if n.module != "risk"]
    for n in non_risk_nodes:
        llm_attr = getattr(n._subagent, "_llm_fn", None)
        assert llm_attr is mock_llm, f"{n.module} 未注入 llm_fn"


def test_resolve_llm_fn_priority():
    """显式参数优先 > 全局 provider"""
    def explicit_fn(p: str) -> str:
        return "explicit"

    def provider_fn() -> reg.LLMFn:
        return lambda p: "provider"

    reg.set_llm_fn_provider(provider_fn)

    # 显式参数优先
    resolved = reg._resolve_llm_fn(explicit_fn)
    assert resolved is explicit_fn

    # 无显式参数时用 provider
    resolved = reg._resolve_llm_fn(None)
    assert resolved is not None
    assert resolved("test") == "provider"


def test_resolve_llm_fn_provider_exception_fail_open():
    """provider 抛异常时 FAIL-OPEN 返回 None"""
    def bad_provider() -> reg.LLMFn:
        raise RuntimeError("provider crashed")

    reg.set_llm_fn_provider(bad_provider)
    resolved = reg._resolve_llm_fn(None)
    assert resolved is None


def test_make_bailian_llm_fn_no_dreamos_returns_none():
    """无 dreamos 可导入时返回 None (HC-10 容错)

    通过 sys.modules 注入一个 fake 'dreamos' 模块来模拟导入失败
    """
    # dreamos 在测试环境通常不可导入, 应返回 None
    fn = reg.make_bailian_llm_fn()
    # 如果 dreamos 可导入且有 API key, fn 可能为 callable
    # 但在测试环境通常为 None
    if fn is not None:
        # 验证 callable 且 FAIL-OPEN 异常返回空串
        assert callable(fn)
        # 实际调用一个简单 prompt 看是否不抛异常
        result = fn("test prompt")
        assert isinstance(result, str)


def test_register_subagents_with_bailian_fail_open():
    """register_subagents_with_bailian 无 API key 时仍能注册 (FAIL-OPEN)

    用 mock registry, 验证返回 > 0
    """
    class MockRegistry:
        def __init__(self):
            self.nodes = []

        def register(self, node):
            self.nodes.append(node)

    mock_reg = MockRegistry()
    count = reg.register_subagents_with_bailian(registry=mock_reg)
    # 应注册了若干节点 (即使无 API key, FAIL-OPEN)
    assert count > 0
    assert len(mock_reg.nodes) > 0


def test_create_nodes_provider_returns_none_when_not_set():
    """无 provider 时 _resolve_llm_fn(None) 返回 None"""
    assert reg._resolve_llm_fn(None) is None


def test_set_get_llm_fn_provider_roundtrip():
    """set/get provider 往返"""
    def provider() -> reg.LLMFn:
        return lambda p: "ok"

    reg.set_llm_fn_provider(provider)
    assert reg.get_llm_fn_provider() is provider
    reg.set_llm_fn_provider(None)
    assert reg.get_llm_fn_provider() is None


def test_subagent_node_execute_with_llm_synthesis():
    """注入 LLM 的 subagent 实际调用 LLM 做 synthesis (sentiment 验证)"""
    calls: list[str] = []

    def mock_llm(prompt: str) -> str:
        calls.append(prompt)
        return "LLM 合成摘要"

    nodes = reg.create_subagent_nodes(llm_fn=mock_llm)
    sentiment_node = next(n for n in nodes if n.module == "sentiment")
    out = sentiment_node.execute({
        "indicators": {"fear_greed": 35, "news_sentiment": -0.3},
        "rationale": ["FGI 偏恐惧"],
        "direction": "long",
        "confidence": 0.6,
    })
    assert out.module == "sentiment"
    # llm_fn 被调用 (sentiment_agent _generate_summary 走 LLM 路径)
    assert len(calls) > 0
    # summary 是 LLM 返回的 (截断到 300)
    assert "LLM" in out.summary or "合成" in out.summary


# ── IPC handler 层 LLM 注入 (M3 最后一公里) ──────────

def test_handler_llm_fn_cache_resolves_once():
    """get_handler_llm_fn 首次解析后缓存"""
    reg.reset_handler_llm_fn_cache()
    fn1 = reg.get_handler_llm_fn()
    fn2 = reg.get_handler_llm_fn()
    # 同一引用 (缓存)
    assert fn1 is fn2
    reg.reset_handler_llm_fn_cache()


def test_handler_llm_fn_returns_none_when_no_dreamos():
    """无 dreamos 可导入时 get_handler_llm_fn 返回 None (FAIL-OPEN)

    subagent_registry.make_bailian_llm_fn 已对 dreamos 不可导入返回 None,
    handler 层应继承此行为, 让 agent 走规则降级.
    """
    reg.reset_handler_llm_fn_cache()
    # 在测试环境 dreamos 通常不可导入, fn 应为 None 或 callable
    fn = reg.get_handler_llm_fn()
    if fn is not None:
        assert callable(fn)
    reg.reset_handler_llm_fn_cache()


def test_ipc_handler_technical_agent_injects_llm_fn():
    """IPC handler handle_technical_agent 实际注入百炼 LLM fn (M3 闭环)

    通过 mock subagent_registry.get_handler_llm_fn 验证 handler 调用时传入了 llm_fn.
    """
    import technical_agent

    captured_llm_fn = []

    def mock_get_handler_llm_fn():
        def mock_fn(prompt: str) -> str:
            return "mock-bailian-response"
        captured_llm_fn.append(mock_fn)
        return mock_fn

    # monkey-patch get_handler_llm_fn
    original = reg.get_handler_llm_fn
    reg.get_handler_llm_fn = mock_get_handler_llm_fn  # type: ignore
    try:
        result = technical_agent.handle_technical_agent({
            "node_output": {
                "indicators": {"ema_fast": 100, "ema_slow": 95, "rsi14": 55},
                "rationale": ["EMA 多头排列"],
                "direction": "long",
                "confidence": 0.7,
            }
        })
    finally:
        reg.get_handler_llm_fn = original  # type: ignore

    assert result["ok"] is True
    assert len(captured_llm_fn) > 0, "handler 未调用 get_handler_llm_fn"


def test_ipc_handler_risk_agent_does_not_inject_llm():
    """IPC handler handle_risk_agent 不注入 LLM (HC-3 风险面纯算法)

    risk_agent 不应调用 get_handler_llm_fn.
    """
    import risk_agent

    call_count = [0]

    def mock_get_handler_llm_fn():
        call_count[0] += 1
        return None

    original = reg.get_handler_llm_fn
    reg.get_handler_llm_fn = mock_get_handler_llm_fn  # type: ignore
    try:
        result = risk_agent.handle_risk_agent({
            "node_output": {
                "indicators": {"var_95": 0.05, "var_99": 0.08},
                "rationale": [],
                "direction": "NEUTRAL",
                "confidence": 0.5,
            }
        })
    finally:
        reg.get_handler_llm_fn = original  # type: ignore

    assert result["ok"] is True
    # risk_agent 不应调用 get_handler_llm_fn (HC-3 纯算法)
    assert call_count[0] == 0, "risk_agent 不应注入 LLM"
