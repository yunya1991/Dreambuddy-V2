"""C4 风险评估节点 — 真实业务逻辑测试

验证 C4RiskAssessNode 抽取自 ml_trade_service.py 风险路由的简化版：
- 从 state.get_result("C3").outputs["verified_signals"] 读取通过验证的信号
- 基于 signal confidence + portfolio_state 计算仓位/止损/止盈/风险预算
- 输出 position_size/stop_loss/take_profit/risk_budget

简化策略（与 C0-C3 风格一致）：
- 仓位 = (资金 * 单笔风险比) / (入场价 * |止损比例|)
- 止损价 = 入场价 * (1 - 止损比例 * direction_sign)
- 止盈价 = 入场价 * (1 + 止盈比例 * direction_sign)
- 风险预算 = sum(仓位 * 入场价 * 止损比例) / 资金
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from dreamos.capabilities.trading.nodes.c4_risk_assess import C4RiskAssessNode
from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus


def _make_signal(
    symbol: str = "BTC",
    direction: str = "LONG",
    confidence: float = 0.8,
    trend: float = 0.10,
    win_rate: float = 0.65,
) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "direction": direction,
        "confidence": confidence,
        "strategy": "trend_momentum",
        "layer": "trend",
        "trend": trend,
        "rsi": 60.0,
        "momentum": 0.05,
        "win_rate": win_rate,
    }


def _make_state(
    signals: List[Dict[str, Any]] | None = None,
    market_data: Dict[str, Dict[str, Any]] | None = None,
    portfolio_state: Dict[str, Any] | None = None,
    config: Dict[str, Any] | None = None,
    with_c3: bool = True,
) -> State:
    state = State()
    state.config = config or {}
    state.market = {
        "market_data": market_data or {},
        "portfolio_state": portfolio_state or {"capital": 10000.0, "existing_positions": {}},
    }
    if with_c3:
        state.results["C3"] = NodeResult(
            node_id="C3",
            status=NodeStatus.SUCCESS,
            confidence=0.7,
            outputs={
                "verified_signals": signals or [],
                "win_rate": 0.65,
                "sharpe": 1.2,
                "max_dd": 0.05,
            },
        )
    return state


# ── 1. 契约测试 ────────────────────────────────────────────
def test_c4_node_contract():
    node = C4RiskAssessNode()
    assert node.node_id == "C4"
    assert node.chain == "C"
    assert "classic" in node.tags
    assert "classic_v2" in node.tags
    assert "risk" in node.tags
    assert isinstance(node, BaseNode)


def test_c4_node_metadata():
    node = C4RiskAssessNode()
    assert node.name == "风险评估"
    assert node.description
    assert node.estimated_tokens == 0


# ── 2. 降级/边界场景 ──────────────────────────────────────
def test_c4_no_market_degradation():
    """无 market 时降级返回 SUCCESS + 空结果"""
    state = State()
    state.config = {}
    node = C4RiskAssessNode()
    result = node.execute_core(state)
    assert result.status == NodeStatus.SUCCESS
    assert result.outputs["position_size"] == {}
    assert result.outputs["stop_loss"] == {}
    assert result.outputs["take_profit"] == {}
    assert result.outputs["risk_budget"] == 0.0


def test_c4_no_c3_results_degradation():
    """无 C3 上游结果时降级"""
    state = State()
    state.config = {}
    state.market = {"portfolio_state": {"capital": 10000.0}}
    node = C4RiskAssessNode()
    result = node.execute_core(state)
    assert result.outputs["position_size"] == {}
    assert result.outputs["risk_budget"] == 0.0


def test_c4_empty_signals():
    """verified_signals 为空时返回空结果"""
    state = _make_state(signals=[])
    node = C4RiskAssessNode()
    result = node.execute_core(state)
    assert result.outputs["position_size"] == {}
    assert result.outputs["risk_budget"] == 0.0


# ── 3. 仓位/止损止盈测试 ─────────────────────────────────
def test_c4_position_size_long():
    """LONG 信号的仓位计算"""
    signals = [_make_signal(symbol="BTC", direction="LONG", confidence=0.8)]
    market_data = {"BTC": {"price": 50000.0, "atr": 500.0}}
    state = _make_state(signals=signals, market_data=market_data)
    node = C4RiskAssessNode()
    result = node.execute_core(state)
    assert "BTC" in result.outputs["position_size"]
    assert result.outputs["position_size"]["BTC"] > 0


def test_c4_stop_loss_long():
    """LONG 信号止损价低于入场价"""
    signals = [_make_signal(symbol="BTC", direction="LONG")]
    market_data = {"BTC": {"price": 50000.0}}
    state = _make_state(signals=signals, market_data=market_data)
    node = C4RiskAssessNode()
    result = node.execute_core(state)
    assert "BTC" in result.outputs["stop_loss"]
    assert result.outputs["stop_loss"]["BTC"] < 50000.0


def test_c4_take_profit_long():
    """LONG 信号止盈价高于入场价"""
    signals = [_make_signal(symbol="BTC", direction="LONG")]
    market_data = {"BTC": {"price": 50000.0}}
    state = _make_state(signals=signals, market_data=market_data)
    node = C4RiskAssessNode()
    result = node.execute_core(state)
    assert "BTC" in result.outputs["take_profit"]
    assert result.outputs["take_profit"]["BTC"] > 50000.0


def test_c4_stop_loss_short():
    """SHORT 信号止损价高于入场价"""
    signals = [_make_signal(symbol="BTC", direction="SHORT")]
    market_data = {"BTC": {"price": 50000.0}}
    state = _make_state(signals=signals, market_data=market_data)
    node = C4RiskAssessNode()
    result = node.execute_core(state)
    assert result.outputs["stop_loss"]["BTC"] > 50000.0


def test_c4_take_profit_short():
    """SHORT 信号止盈价低于入场价"""
    signals = [_make_signal(symbol="BTC", direction="SHORT")]
    market_data = {"BTC": {"price": 50000.0}}
    state = _make_state(signals=signals, market_data=market_data)
    node = C4RiskAssessNode()
    result = node.execute_core(state)
    assert result.outputs["take_profit"]["BTC"] < 50000.0


# ── 4. 风险预算测试 ───────────────────────────────────────
def test_c4_risk_budget_range():
    """risk_budget 在 [0, 1] 区间"""
    signals = [
        _make_signal(symbol="BTC"),
        _make_signal(symbol="ETH"),
    ]
    market_data = {
        "BTC": {"price": 50000.0},
        "ETH": {"price": 3000.0},
    }
    state = _make_state(signals=signals, market_data=market_data)
    node = C4RiskAssessNode()
    result = node.execute_core(state)
    assert 0.0 <= result.outputs["risk_budget"] <= 1.0


def test_c4_risk_budget_scales_with_positions():
    """多信号时 risk_budget 应反映总风险占用"""
    signals_one = [_make_signal(symbol="BTC")]
    signals_two = [_make_signal(symbol="BTC"), _make_signal(symbol="ETH")]
    market_data = {"BTC": {"price": 50000.0}, "ETH": {"price": 3000.0}}
    state_one = _make_state(signals=signals_one, market_data=market_data)
    state_two = _make_state(signals=signals_two, market_data=market_data)
    node = C4RiskAssessNode()
    res_one = node.execute_core(state_one)
    res_two = node.execute_core(state_two)
    assert res_two.outputs["risk_budget"] >= res_one.outputs["risk_budget"]


# ── 5. 配置覆盖测试 ───────────────────────────────────────
def test_c4_config_override_risk_per_trade():
    """config 可覆盖单笔风险比例"""
    signals = [_make_signal(symbol="BTC")]
    market_data = {"BTC": {"price": 50000.0}}
    state_a = _make_state(signals=signals, market_data=market_data, config={"risk_per_trade": 0.01})
    state_b = _make_state(signals=signals, market_data=market_data, config={"risk_per_trade": 0.05})
    node = C4RiskAssessNode()
    res_a = node.execute_core(state_a)
    res_b = node.execute_core(state_b)
    # 更高风险比例 → 更大仓位
    assert res_b.outputs["position_size"]["BTC"] >= res_a.outputs["position_size"]["BTC"]


def test_c4_config_override_stop_loss_pct():
    """config 可覆盖止损比例"""
    signals = [_make_signal(symbol="BTC", direction="LONG")]
    market_data = {"BTC": {"price": 50000.0}}
    state_a = _make_state(signals=signals, market_data=market_data, config={"risk_stop_loss_pct": 0.02})
    state_b = _make_state(signals=signals, market_data=market_data, config={"risk_stop_loss_pct": 0.05})
    node = C4RiskAssessNode()
    res_a = node.execute_core(state_a)
    res_b = node.execute_core(state_b)
    # 更大止损比例 → 止损价离入场价更远（即更低）
    assert res_b.outputs["stop_loss"]["BTC"] <= res_a.outputs["stop_loss"]["BTC"]


def test_c4_uses_c3_verified_signals():
    """从 state.get_result("C3").outputs["verified_signals"] 读取"""
    signals = [_make_signal(symbol="BTC"), _make_signal(symbol="ETH")]
    market_data = {"BTC": {"price": 50000.0}, "ETH": {"price": 3000.0}}
    state = _make_state(signals=signals, market_data=market_data)
    node = C4RiskAssessNode()
    result = node.execute_core(state)
    assert "BTC" in result.outputs["position_size"]
    assert "ETH" in result.outputs["position_size"]


def test_c4_skip_signal_without_price():
    """market_data 缺价格时跳过该信号"""
    signals = [_make_signal(symbol="BTC"), _make_signal(symbol="ETH")]
    market_data = {"BTC": {"price": 50000.0}}  # 缺 ETH
    state = _make_state(signals=signals, market_data=market_data)
    node = C4RiskAssessNode()
    result = node.execute_core(state)
    assert "BTC" in result.outputs["position_size"]
    assert "ETH" not in result.outputs["position_size"]
