"""
RED 测试 — C1 品种筛选节点真实业务逻辑

从 ml_trade_service.py L12053 _build_universe_stage_a 抽取的逻辑：
- Stage A 硬过滤：流动性 / 数据完整性 / carry risk
- Relax 阶梯：候选数 < target_min 时按 0.5^step 降低 turnover、按 2^step 放宽 gap、按 0.5^step 降低 age
- Fallback：无候选时返回 ["BTC", "ETH", "SOL"] 中有价格的

断言：
1. 候选池含高流动性币种（BTC/ETH/SOL）
2. 无价格的币种被拒（rejected 含 reasons=["no_price"]）
3. 低 turnover 的币种被拒
4. 高 gap_rate 的币种被拒
5. 新上市（age 太小）的币种被拒
6. filter_log 含 relax 步骤记录（candidates < target_min 时触发）
7. 无候选时返回 fallback
8. state.config 可覆盖默认阈值
"""

from __future__ import annotations

import pytest

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus


# ── 测试 fixtures ──────────────────────────────────────────

def _make_market_data(candidates_spec):
    """构造 state.market 测试数据

    candidates_spec: list[dict] 每项形如
        {"name": "BTC", "px": 50000.0, "turnover": 100000, "gap": 0.01, "jump": 0.02, "age": 365}
    """
    universe = [{"name": c["name"], "szDecimals": 3} for c in candidates_spec]
    mids = {c["name"]: c.get("px", 0.0) for c in candidates_spec}
    stats = {
        c["name"]: {
            "median_turnover": c.get("turnover", 0.0),
            "gap_rate": c.get("gap", 1.0),
            "jump_rate": c.get("jump", 0.0),
            "age_days": c.get("age", 0.0),
        }
        for c in candidates_spec
    }
    return {"universe": universe, "mids": mids, "stats": stats}


# ── 基础契约测试 ──────────────────────────────────────────

def test_c1_importable():
    """断言 C1 节点可导入"""
    from dreamos.capabilities.trading.nodes.c1_symbol_filter import C1SymbolFilterNode
    assert C1SymbolFilterNode is not None


def test_c1_metadata():
    """断言 node_id/chain/name 正确"""
    from dreamos.capabilities.trading.nodes.c1_symbol_filter import C1SymbolFilterNode
    node = C1SymbolFilterNode()
    assert node.node_id == "C1"
    assert node.chain == "C"
    assert node.name == "品种筛选"


def test_c1_tags_has_classic_v2():
    """断言 tags 包含 classic 和 classic_v2"""
    from dreamos.capabilities.trading.nodes.c1_symbol_filter import C1SymbolFilterNode
    node = C1SymbolFilterNode()
    assert "classic" in node.tags
    assert "classic_v2" in node.tags


# ── 真实业务逻辑测试 ──────────────────────────────────────

def test_c1_filter_returns_candidates_for_valid_market():
    """正常市场：高流动性币种应入选 candidates"""
    from dreamos.capabilities.trading.nodes.c1_symbol_filter import C1SymbolFilterNode
    market = _make_market_data([
        {"name": "BTC", "px": 50000.0, "turnover": 100000, "gap": 0.01, "jump": 0.02, "age": 365},
        {"name": "ETH", "px": 3000.0, "turnover": 80000, "gap": 0.015, "jump": 0.03, "age": 300},
        {"name": "SOL", "px": 100.0, "turnover": 60000, "gap": 0.02, "jump": 0.04, "age": 200},
    ])
    state = State(market=market)
    node = C1SymbolFilterNode()
    result = node.execute_core(state)

    assert isinstance(result, NodeResult)
    assert result.node_id == "C1"
    assert result.status == NodeStatus.SUCCESS
    assert isinstance(result.outputs["candidates"], list)
    assert "BTC" in result.outputs["candidates"]
    assert "ETH" in result.outputs["candidates"]
    assert "SOL" in result.outputs["candidates"]


def test_c1_filter_rejects_no_price():
    """无价格的币种应被拒，rejected 含 reasons=["no_price"]"""
    from dreamos.capabilities.trading.nodes.c1_symbol_filter import C1SymbolFilterNode
    market = _make_market_data([
        {"name": "BTC", "px": 50000.0, "turnover": 100000, "gap": 0.01, "jump": 0.02, "age": 365},
        {"name": "DEAD", "px": 0.0, "turnover": 0, "gap": 1.0, "jump": 0.0, "age": 0},
    ])
    state = State(market=market)
    result = C1SymbolFilterNode().execute_core(state)

    rejected = result.outputs["rejected"]
    assert isinstance(rejected, list)
    # 找到 DEAD 的拒绝记录
    dead_rej = [r for r in rejected if r.get("coin") == "DEAD"]
    assert len(dead_rej) == 1
    assert "no_price" in dead_rej[0].get("reasons", [])
    assert "DEAD" not in result.outputs["candidates"]


def test_c1_filter_rejects_low_turnover():
    """低 turnover 的币种应被拒"""
    from dreamos.capabilities.trading.nodes.c1_symbol_filter import C1SymbolFilterNode
    market = _make_market_data([
        {"name": "BTC", "px": 50000.0, "turnover": 100000, "gap": 0.01, "jump": 0.02, "age": 365},
        {"name": "LOWLIQ", "px": 0.5, "turnover": 100, "gap": 0.01, "jump": 0.02, "age": 365},
    ])
    state = State(market=market)
    result = C1SymbolFilterNode().execute_core(state)

    assert "LOWLIQ" not in result.outputs["candidates"]
    lowliq_rej = [r for r in result.outputs["rejected"] if r.get("coin") == "LOWLIQ"]
    assert len(lowliq_rej) == 1
    assert any("low_turnover" in reason for reason in lowliq_rej[0].get("reasons", []))


def test_c1_filter_rejects_high_gap():
    """高 gap_rate 的币种应被拒"""
    from dreamos.capabilities.trading.nodes.c1_symbol_filter import C1SymbolFilterNode
    market = _make_market_data([
        {"name": "BTC", "px": 50000.0, "turnover": 100000, "gap": 0.01, "jump": 0.02, "age": 365},
        {"name": "GAPPY", "px": 1.0, "turnover": 100000, "gap": 0.5, "jump": 0.02, "age": 365},
    ])
    state = State(market=market)
    result = C1SymbolFilterNode().execute_core(state)

    assert "GAPPY" not in result.outputs["candidates"]
    gappy_rej = [r for r in result.outputs["rejected"] if r.get("coin") == "GAPPY"]
    assert len(gappy_rej) == 1
    assert any("high_gap" in reason for reason in gappy_rej[0].get("reasons", []))


def test_c1_filter_rejects_too_young():
    """age 太小的币种（age > 0 且 < min_age_shadow）应被拒"""
    from dreamos.capabilities.trading.nodes.c1_symbol_filter import C1SymbolFilterNode
    market = _make_market_data([
        {"name": "BTC", "px": 50000.0, "turnover": 100000, "gap": 0.01, "jump": 0.02, "age": 365},
        {"name": "NEWBIE", "px": 1.0, "turnover": 100000, "gap": 0.01, "jump": 0.02, "age": 5},
    ])
    state = State(market=market)
    result = C1SymbolFilterNode().execute_core(state)

    assert "NEWBIE" not in result.outputs["candidates"]
    newbie_rej = [r for r in result.outputs["rejected"] if r.get("coin") == "NEWBIE"]
    assert len(newbie_rej) == 1
    assert any("too_young" in reason for reason in newbie_rej[0].get("reasons", []))


def test_c1_filter_log_records_relax_steps():
    """filter_log 应记录 relax 步骤（candidates < target_min 时触发）"""
    from dreamos.capabilities.trading.nodes.c1_symbol_filter import C1SymbolFilterNode
    market = _make_market_data([
        {"name": "BTC", "px": 50000.0, "turnover": 100000, "gap": 0.01, "jump": 0.02, "age": 365},
        {"name": "ETH", "px": 3000.0, "turnover": 80000, "gap": 0.015, "jump": 0.03, "age": 300},
    ])
    # target_min=10 但只有 2 个候选，应触发 relax
    state = State(market=market, config={"universe_stage_a_target_min_candidates": 10})
    result = C1SymbolFilterNode().execute_core(state)

    filter_log = result.outputs["filter_log"]
    assert isinstance(filter_log, list)
    assert len(filter_log) >= 1
    # 第 0 步必有
    step0 = filter_log[0]
    assert "step" in step0
    assert "min_turnover" in step0
    assert "max_gap" in step0
    assert "min_age_shadow" in step0


def test_c1_filter_fallback_to_btc_eth_sol():
    """无候选时返回 fallback [BTC, ETH, SOL] 中有价格的"""
    from dreamos.capabilities.trading.nodes.c1_symbol_filter import C1SymbolFilterNode
    market = _make_market_data([
        {"name": "DEAD1", "px": 0.0, "turnover": 0, "gap": 1.0, "jump": 0.0, "age": 0},
        {"name": "DEAD2", "px": 0.0, "turnover": 0, "gap": 1.0, "jump": 0.0, "age": 0},
    ])
    # 显式塞入 BTC/ETH/SOL 的价格但 universe 不包含它们
    market["mids"]["BTC"] = 50000.0
    market["mids"]["ETH"] = 3000.0
    state = State(market=market)
    result = C1SymbolFilterNode().execute_core(state)

    candidates = result.outputs["candidates"]
    # 应至少包含 BTC/ETH 中有价格的
    assert "BTC" in candidates
    assert "ETH" in candidates


def test_c1_config_overrides_default_thresholds():
    """state.config 应可覆盖默认阈值"""
    from dreamos.capabilities.trading.nodes.c1_symbol_filter import C1SymbolFilterNode
    market = _make_market_data([
        {"name": "BTC", "px": 50000.0, "turnover": 100000, "gap": 0.01, "jump": 0.02, "age": 365},
        {"name": "LOWLIQ", "px": 1.0, "turnover": 2000, "gap": 0.01, "jump": 0.02, "age": 365},
    ])
    # 默认 min_turnover=50000，LOWLIQ turnover=2000 会被拒
    state_default = State(market=market)
    result_default = C1SymbolFilterNode().execute_core(state_default)
    assert "LOWLIQ" not in result_default.outputs["candidates"]

    # 覆盖 min_turnover=1000，LOWLIQ 应通过
    state_override = State(
        market=market,
        config={"filter_min_turnover_7d": 1000.0},
    )
    result_override = C1SymbolFilterNode().execute_core(state_override)
    assert "LOWLIQ" in result_override.outputs["candidates"]


def test_c1_empty_market_returns_empty_candidates():
    """空 universe 应返回空 candidates（或 fallback）"""
    from dreamos.capabilities.trading.nodes.c1_symbol_filter import C1SymbolFilterNode
    state = State(market={"universe": [], "mids": {}, "stats": {}})
    result = C1SymbolFilterNode().execute_core(state)

    assert isinstance(result.outputs["candidates"], list)
    assert result.status == NodeStatus.SUCCESS


def test_c1_no_market_returns_failed_or_pending():
    """无 market 数据时应降级处理（FAILED 或 SUCCESS+空 candidates）"""
    from dreamos.capabilities.trading.nodes.c1_symbol_filter import C1SymbolFilterNode
    state = State()  # market=None
    result = C1SymbolFilterNode().execute_core(state)

    # 应不抛异常，返回合理状态
    assert isinstance(result, NodeResult)
    assert result.node_id == "C1"
    # SUCCESS with empty candidates 或 FAILED 都可接受
    assert result.status in (NodeStatus.SUCCESS, NodeStatus.FAILED, NodeStatus.DEGRADED)
