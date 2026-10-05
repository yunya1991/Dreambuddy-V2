"""
统一能力注册表 — 端到端集成测试

覆盖: 注册 → 查询 → 匹配 → 降级 → 状态同步 全链路
性能基准: 查询 < 1ms, 匹配 < 5ms

运行:
    cd 1-ARCHITECTURE
    python -m pytest dreamos/tests/test_capability_registry_e2e.py -v
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "dream-harness-bridge/packages/python-server"))

from dreamos.registry.node_registry import NodeRegistry, get_default_registry
from dreamos.registry.base import BaseNode
from dreamos.shared.capability import (
    CapabilitySpec, StrategyRequirement, CapabilityMatcher,
    ProviderType, CapabilityStatus,
)
from dreamos.shared.state import State, NodeResult, NodeStatus


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def registry() -> NodeRegistry:
    """干净的注册表"""
    reg = NodeRegistry()
    return reg


@pytest.fixture
def full_registry(registry: NodeRegistry) -> NodeRegistry:
    """包含交易所 + subagent + 子系统节点的完整注册表"""
    from dreamos.capabilities.trading.exchange_capabilities import ExchangeCapabilityProvider
    from dreamos.capabilities.trading.nodes.subsystem_adapter_nodes import (
        CS3TrendNode, AYJInferNode, CMartinV15Node,
    )
    from subagent_registry import SubagentNode, SUBAGENT_REGISTRY_CONFIG

    # 交易所
    ExchangeCapabilityProvider("OKX").register_to(registry)
    ExchangeCapabilityProvider("Hyperliquid").register_to(registry)

    # 子系统节点
    registry.register(CS3TrendNode())
    registry.register(AYJInferNode())
    registry.register(CMartinV15Node())

    # DSH subagent
    class _MockAgent:
        def execute(self, x):
            return x

    for cfg in SUBAGENT_REGISTRY_CONFIG:
        registry.register(SubagentNode(cfg, _MockAgent()))

    return registry


class _MockStrategyNode(BaseNode):
    """需要 futures + leverage>=10 的策略节点"""
    node_id = "STRAT_MOCK"
    name = "模拟策略"
    chain = "T"
    required_capabilities = ["trading.futures", "trading.leverage"]

    def execute_core(self, state: State) -> NodeResult:
        return NodeResult(
            node_id=self.node_id,
            status=NodeStatus.SUCCESS,
            direction="LONG",
            confidence=0.85,
        )


# ============================================================
# 1. 注册测试
# ============================================================

class TestRegistration:
    def test_exchange_registration(self, registry):
        from dreamos.capabilities.trading.exchange_capabilities import ExchangeCapabilityProvider
        nid = ExchangeCapabilityProvider("OKX").register_to(registry)
        assert nid == "OKX"
        caps = registry.get_node_capabilities("OKX")
        assert len(caps) >= 15
        cap_ids = [c.capability_id for c in caps]
        assert "trading.futures" in cap_ids
        assert "trading.leverage" in cap_ids
        lev = next(c for c in caps if c.capability_id == "trading.leverage")
        assert lev.properties["max"] == 125

    def test_subsystem_node_capabilities(self, registry):
        from dreamos.capabilities.trading.nodes.subsystem_adapter_nodes import CS3TrendNode
        node = CS3TrendNode()
        registry.register(node)
        caps = registry.get_node_capabilities("C_S3_TREND")
        assert len(caps) == 1
        assert caps[0].capability_id == "analysis.trend"
        assert caps[0].provider_type == ProviderType.SUBSYSTEM

    def test_subagent_capabilities(self, registry):
        from subagent_registry import SubagentNode, SUBAGENT_REGISTRY_CONFIG

        class _A:
            def execute(self, x):
                return x

        for cfg in SUBAGENT_REGISTRY_CONFIG:
            node = SubagentNode(cfg, _A())
            registry.register(node)

        caps = registry.list_node_capabilities(category="analysis")
        assert len(caps) == 8
        cap_ids = {c.capability_id for c in caps}
        assert "analysis.technical" in cap_ids
        assert "analysis.risk" in cap_ids


# ============================================================
# 2. 查询测试
# ============================================================

class TestQuery:
    def test_list_by_category(self, full_registry):
        trading = full_registry.list_node_capabilities(category="trading")
        assert len(trading) > 0
        assert all(c.category == "trading" for c in trading)

    def test_find_by_capability(self, full_registry):
        nodes = full_registry.find_nodes_by_capability("trading.futures")
        node_ids = {n.node_id for n in nodes}
        assert "OKX" in node_ids
        assert "Hyperliquid" in node_ids

    def test_node_capability_summary(self, full_registry):
        summary = full_registry.node_capability_summary()
        assert "by_category" in summary
        assert "trading" in summary["by_category"]
        assert summary["by_category"]["trading"] > 0
        assert summary["by_status"]["available"] > 0

    def test_get_node_capabilities_not_found(self, full_registry):
        caps = full_registry.get_node_capabilities("NONEXISTENT")
        assert caps == []


# ============================================================
# 3. 匹配测试
# ============================================================

class TestMatching:
    def test_okx_supports_futures_strategy(self, full_registry):
        caps = full_registry.get_node_capabilities("OKX")
        req = StrategyRequirement(
            strategy_id="v15_martin",
            required_capabilities=["trading.futures", "trading.leverage"],
            min_properties={"trading.leverage": {"max": 10}},
        )
        result = CapabilityMatcher.match(req, caps)
        assert result.is_fulfilled
        assert result.missing_required == []

    def test_okx_no_options(self, full_registry):
        caps = full_registry.get_node_capabilities("OKX")
        req = StrategyRequirement(
            strategy_id="options_strat",
            required_capabilities=["trading.options"],
        )
        result = CapabilityMatcher.match(req, caps)
        assert not result.is_fulfilled
        assert "trading.options" in result.missing_required

    def test_leverage_too_high(self, full_registry):
        caps = full_registry.get_node_capabilities("OKX")
        req = StrategyRequirement(
            strategy_id="high_lev",
            required_capabilities=["trading.leverage"],
            min_properties={"trading.leverage": {"max": 200}},
        )
        result = CapabilityMatcher.match(req, caps)
        assert not result.is_fulfilled

    def test_excluded_capability_conflict(self, full_registry):
        caps = full_registry.get_node_capabilities("OKX")
        req = StrategyRequirement(
            strategy_id="no_margin",
            required_capabilities=["trading.spot"],
            excluded_capabilities=["trading.margin"],
        )
        result = CapabilityMatcher.match(req, caps)
        assert not result.is_fulfilled
        assert "trading.margin" in result.conflicts


# ============================================================
# 4. 降级测试
# ============================================================

class TestDegradation:
    def test_missing_required_capability_degrades(self, registry):
        import dreamos.registry.node_registry as nr_mod
        nr_mod._default_registry = registry

        strat = _MockStrategyNode()
        registry.register(strat)
        state = State()

        result = strat.execute(state)
        assert result.status == NodeStatus.DEGRADED
        assert result.warnings
        assert "trading.futures" in result.warnings[0]

    def test_available_capability_succeeds(self, registry):
        import dreamos.registry.node_registry as nr_mod
        nr_mod._default_registry = registry

        from dreamos.capabilities.trading.exchange_capabilities import ExchangeCapabilityProvider
        ExchangeCapabilityProvider("OKX").register_to(registry)

        strat = _MockStrategyNode()
        registry.register(strat)
        state = State()

        result = strat.execute(state)
        assert result.status == NodeStatus.SUCCESS
        assert result.direction == "LONG"

    def test_unavailable_capability_degrades(self, registry):
        import dreamos.registry.node_registry as nr_mod
        nr_mod._default_registry = registry

        from dreamos.capabilities.trading.exchange_capabilities import ExchangeCapabilityProvider
        ExchangeCapabilityProvider("OKX").register_to(registry)

        strat = _MockStrategyNode()
        registry.register(strat)
        state = State()

        registry.update_node_capability_status("OKX", "unavailable")
        result = strat.execute(state)
        assert result.status == NodeStatus.DEGRADED

    def test_status_sync_on_failure(self, registry):
        from dreamos.capabilities.trading.nodes.subsystem_adapter_nodes import CS3TrendNode
        node = CS3TrendNode()
        registry.register(node)

        # 模拟执行失败
        fail_result = NodeResult(node_id="C_S3_TREND", status=NodeStatus.FAILED)
        node._sync_capability_status(fail_result)

        caps = registry.get_node_capabilities("C_S3_TREND")
        assert caps[0].status == CapabilityStatus.UNAVAILABLE

    def test_status_sync_on_success(self, registry):
        from dreamos.capabilities.trading.nodes.subsystem_adapter_nodes import CS3TrendNode
        node = CS3TrendNode()
        registry.register(node)

        success_result = NodeResult(node_id="C_S3_TREND", status=NodeStatus.SUCCESS)
        node._sync_capability_status(success_result)

        caps = registry.get_node_capabilities("C_S3_TREND")
        assert caps[0].status == CapabilityStatus.AVAILABLE


# ============================================================
# 5. 性能测试
# ============================================================

class TestPerformance:
    def test_query_under_1ms(self, full_registry):
        # 预热
        full_registry.list_node_capabilities()

        times = []
        for _ in range(100):
            t0 = time.perf_counter()
            full_registry.list_node_capabilities()
            times.append((time.perf_counter() - t0) * 1000)

        avg = sum(times) / len(times)
        p99 = sorted(times)[int(len(times) * 0.99)]
        print(f"\n  list_node_capabilities: avg={avg:.3f}ms, p99={p99:.3f}ms")
        assert avg < 1.0, f"平均查询耗时 {avg:.3f}ms 超过 1ms"

    def test_match_under_5ms(self, full_registry):
        caps = full_registry.get_node_capabilities("OKX")
        req = StrategyRequirement(
            strategy_id="perf_test",
            required_capabilities=["trading.futures", "trading.leverage"],
            min_properties={"trading.leverage": {"max": 10}},
        )
        # 预热
        CapabilityMatcher.match(req, caps)

        times = []
        for _ in range(100):
            t0 = time.perf_counter()
            CapabilityMatcher.match(req, caps)
            times.append((time.perf_counter() - t0) * 1000)

        avg = sum(times) / len(times)
        p99 = sorted(times)[int(len(times) * 0.99)]
        print(f"\n  CapabilityMatcher.match: avg={avg:.3f}ms, p99={p99:.3f}ms")
        assert avg < 5.0, f"平均匹配耗时 {avg:.3f}ms 超过 5ms"


# ============================================================
# 6. 回归测试 — 确保不破坏现有节点
# ============================================================

class TestBackwardCompatibility:
    def test_legacy_node_infers_capabilities(self, registry):
        """未显式声明 capabilities 的节点应自动推断"""
        class LegacyNode(BaseNode):
            node_id = "LEGACY_NODE"
            name = "遗留节点"
            chain = "C"

        node = LegacyNode()
        registry.register(node)
        caps = registry.get_node_capabilities("LEGACY_NODE")
        assert len(caps) >= 1
        # C 链节点应推断出 analysis.* 能力
        assert any(c.category == "analysis" for c in caps)

    def test_node_without_required_capabilities_passes(self, registry):
        """未声明 required_capabilities 的节点不应触发降级"""
        import dreamos.registry.node_registry as nr_mod
        nr_mod._default_registry = registry

        class SimpleNode(BaseNode):
            node_id = "SIMPLE"
            chain = "C"

            def execute_core(self, state):
                return NodeResult(node_id=self.node_id, status=NodeStatus.SUCCESS)

        node = SimpleNode()
        registry.register(node)
        state = State()
        result = node.execute(state)
        assert result.status == NodeStatus.SUCCESS
