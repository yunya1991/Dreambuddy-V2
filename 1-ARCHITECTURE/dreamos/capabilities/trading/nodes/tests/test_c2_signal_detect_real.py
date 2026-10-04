"""C2 信号识别节点 — 真实业务逻辑测试

验证 C2SignalDetectNode 抽取自 ml_trade_service.py 信号路由的简化版：
- 从 state.get_result("C1").outputs["candidates"] 读取候选币种
- 基于 state.market["market_data"] 中每个币种的 trend/rsi/momentum 生成信号
- 输出 signals list[dict] / signal_count / dominant_direction

简化策略（与 C0/C1 风格一致）：
- trend > +threshold → LONG signal
- trend < -threshold → SHORT signal
- |trend| <= threshold → 跳过（不生成信号）
- 同时综合 rsi/momentum 做置信度调整
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

import pytest

from dreamos.capabilities.trading.nodes.c2_signal_detect import C2SignalDetectNode
from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus


# ── 测试夹具 ────────────────────────────────────────────────
def _make_state(
    candidates: List[str] | None = None,
    market_data: Dict[str, Dict[str, Any]] | None = None,
    config: Dict[str, Any] | None = None,
    with_c1: bool = True,
) -> State:
    """构造带 C1 上游结果的 State"""
    state = State()
    state.config = config or {}
    state.market = {"market_data": market_data or {}}
    if with_c1:
        state.results["C1"] = NodeResult(
            node_id="C1",
            status=NodeStatus.SUCCESS,
            confidence=0.7,
            outputs={
                "candidates": candidates or [],
                "filter_log": [],
                "rejected": [],
                "symbols_total": len(candidates or []),
                "mids_total": len(candidates or []),
            },
        )
    return state


# ── 1. 契约测试 ────────────────────────────────────────────
def test_c2_node_contract():
    node = C2SignalDetectNode()
    assert node.node_id == "C2"
    assert node.chain == "C"
    assert "classic" in node.tags
    assert "classic_v2" in node.tags
    assert "signal" in node.tags
    assert isinstance(node, BaseNode)


def test_c2_node_metadata():
    node = C2SignalDetectNode()
    assert node.name == "信号识别"
    assert node.description  # 非空
    assert node.estimated_tokens == 0
    assert node.estimated_latency_ms == 0


# ── 2. 降级/边界场景 ──────────────────────────────────────
def test_c2_no_market_degradation():
    """无 market 时降级返回 SUCCESS + 空 signals（FAIL-OPEN）"""
    state = State()
    state.config = {}
    # 不设置 market
    node = C2SignalDetectNode()
    result = node.execute_core(state)
    assert result.status == NodeStatus.SUCCESS
    assert result.outputs["signals"] == []
    assert result.outputs["signal_count"] == 0
    assert result.outputs["dominant_direction"] == "NEUTRAL"


def test_c2_no_c1_results_degradation():
    """无 C1 上游结果时降级返回 SUCCESS + 空 signals"""
    state = State()
    state.config = {}
    state.market = {"market_data": {"BTC": {"trend": 0.10}}}
    node = C2SignalDetectNode()
    result = node.execute_core(state)
    assert result.status == NodeStatus.SUCCESS
    assert result.outputs["signals"] == []
    assert result.outputs["signal_count"] == 0


def test_c2_empty_candidates():
    """candidates 为空时返回空 signals"""
    state = _make_state(candidates=[], market_data={"BTC": {"trend": 0.10}})
    node = C2SignalDetectNode()
    result = node.execute_core(state)
    assert result.outputs["signals"] == []
    assert result.outputs["signal_count"] == 0
    assert result.outputs["dominant_direction"] == "NEUTRAL"


def test_c2_no_market_data_for_coin():
    """candidates 有币种但 market_data 缺该币种数据时跳过该币种"""
    state = _make_state(
        candidates=["BTC", "ETH"],
        market_data={"BTC": {"trend": 0.10}},  # 缺 ETH
    )
    node = C2SignalDetectNode()
    result = node.execute_core(state)
    # 只 BTC 有数据，应生成 BTC 的信号
    assert result.outputs["signal_count"] == 1
    assert result.outputs["signals"][0]["symbol"] == "BTC"


# ── 3. 信号生成测试 ────────────────────────────────────────
def test_c2_long_signal():
    """trend > +threshold 生成 LONG signal"""
    state = _make_state(
        candidates=["BTC"],
        market_data={"BTC": {"trend": 0.10, "rsi": 60, "momentum": 0.05}},
    )
    node = C2SignalDetectNode()
    result = node.execute_core(state)
    assert result.outputs["signal_count"] == 1
    sig = result.outputs["signals"][0]
    assert sig["symbol"] == "BTC"
    assert sig["direction"] == "LONG"
    assert 0.0 < sig["confidence"] <= 1.0
    assert "strategy" in sig
    assert "layer" in sig


def test_c2_short_signal():
    """trend < -threshold 生成 SHORT signal"""
    state = _make_state(
        candidates=["BTC"],
        market_data={"BTC": {"trend": -0.10, "rsi": 40, "momentum": -0.05}},
    )
    node = C2SignalDetectNode()
    result = node.execute_core(state)
    assert result.outputs["signal_count"] == 1
    sig = result.outputs["signals"][0]
    assert sig["symbol"] == "BTC"
    assert sig["direction"] == "SHORT"
    assert 0.0 < sig["confidence"] <= 1.0


def test_c2_hold_skip():
    """|trend| <= threshold 时不生成 signal（NEUTRAL 区间）"""
    state = _make_state(
        candidates=["BTC"],
        market_data={"BTC": {"trend": 0.001, "rsi": 50, "momentum": 0.0}},
    )
    node = C2SignalDetectNode()
    result = node.execute_core(state)
    assert result.outputs["signal_count"] == 0
    assert result.outputs["signals"] == []


def test_c2_signal_schema():
    """每个 signal 必须含 symbol/direction/confidence/strategy/layer"""
    state = _make_state(
        candidates=["BTC", "ETH"],
        market_data={
            "BTC": {"trend": 0.10, "rsi": 65, "momentum": 0.05},
            "ETH": {"trend": -0.10, "rsi": 35, "momentum": -0.05},
        },
    )
    node = C2SignalDetectNode()
    result = node.execute_core(state)
    for sig in result.outputs["signals"]:
        assert "symbol" in sig
        assert "direction" in sig
        assert "confidence" in sig
        assert "strategy" in sig
        assert "layer" in sig
        assert sig["direction"] in ("LONG", "SHORT")


# ── 4. dominant_direction 测试 ────────────────────────────
def test_c2_dominant_direction_long():
    """多数 LONG 信号 → dominant_direction=LONG"""
    state = _make_state(
        candidates=["BTC", "ETH", "SOL"],
        market_data={
            "BTC": {"trend": 0.10},
            "ETH": {"trend": 0.08},
            "SOL": {"trend": -0.10},
        },
    )
    node = C2SignalDetectNode()
    result = node.execute_core(state)
    assert result.outputs["dominant_direction"] == "LONG"


def test_c2_dominant_direction_short():
    """多数 SHORT 信号 → dominant_direction=SHORT"""
    state = _make_state(
        candidates=["BTC", "ETH", "SOL"],
        market_data={
            "BTC": {"trend": -0.10},
            "ETH": {"trend": -0.08},
            "SOL": {"trend": 0.10},
        },
    )
    node = C2SignalDetectNode()
    result = node.execute_core(state)
    assert result.outputs["dominant_direction"] == "SHORT"


def test_c2_dominant_direction_neutral_no_signals():
    """无信号 → dominant_direction=NEUTRAL"""
    state = _make_state(
        candidates=["BTC"],
        market_data={"BTC": {"trend": 0.001}},
    )
    node = C2SignalDetectNode()
    result = node.execute_core(state)
    assert result.outputs["dominant_direction"] == "NEUTRAL"


def test_c2_dominant_direction_neutral_tie():
    """LONG/SHORT 数量相等 → NEUTRAL"""
    state = _make_state(
        candidates=["BTC", "ETH"],
        market_data={
            "BTC": {"trend": 0.10},
            "ETH": {"trend": -0.10},
        },
    )
    node = C2SignalDetectNode()
    result = node.execute_core(state)
    assert result.outputs["dominant_direction"] == "NEUTRAL"


def test_c2_signal_count_matches():
    """signal_count 与 len(signals) 一致"""
    state = _make_state(
        candidates=["BTC", "ETH", "SOL", "XRP"],
        market_data={
            "BTC": {"trend": 0.10},
            "ETH": {"trend": -0.10},
            "SOL": {"trend": 0.001},  # NEUTRAL 不生成
            "XRP": {"trend": 0.08},
        },
    )
    node = C2SignalDetectNode()
    result = node.execute_core(state)
    assert result.outputs["signal_count"] == len(result.outputs["signals"])
    assert result.outputs["signal_count"] == 3


# ── 5. 配置覆盖测试 ────────────────────────────────────────
def test_c2_config_override_trend_threshold():
    """config 可覆盖 trend_threshold"""
    state = _make_state(
        candidates=["BTC"],
        market_data={"BTC": {"trend": 0.03}},  # 默认阈值 0.01 → LONG
        config={"signal_detect_trend_threshold": 0.05},  # 提高阈值 → NEUTRAL
    )
    node = C2SignalDetectNode()
    result = node.execute_core(state)
    assert result.outputs["signal_count"] == 0


def test_c2_uses_c1_candidates_from_state():
    """从 state.get_result("C1").outputs["candidates"] 读取候选"""
    state = _make_state(
        candidates=["BTC", "ETH"],
        market_data={
            "BTC": {"trend": 0.10},
            "ETH": {"trend": 0.08},
            "SOL": {"trend": 0.10},  # SOL 不在 candidates，应被忽略
        },
    )
    node = C2SignalDetectNode()
    result = node.execute_core(state)
    symbols = [s["symbol"] for s in result.outputs["signals"]]
    assert "SOL" not in symbols
    assert "BTC" in symbols
    assert "ETH" in symbols


def test_c2_confidence_increases_with_momentum():
    """momentum 与 trend 同向时置信度提升"""
    state_a = _make_state(
        candidates=["BTC"],
        market_data={"BTC": {"trend": 0.10, "momentum": 0.0, "rsi": 50}},
    )
    state_b = _make_state(
        candidates=["BTC"],
        market_data={"BTC": {"trend": 0.10, "momentum": 0.05, "rsi": 65}},
    )
    node = C2SignalDetectNode()
    res_a = node.execute_core(state_a)
    res_b = node.execute_core(state_b)
    assert res_b.outputs["signals"][0]["confidence"] >= res_a.outputs["signals"][0]["confidence"]
