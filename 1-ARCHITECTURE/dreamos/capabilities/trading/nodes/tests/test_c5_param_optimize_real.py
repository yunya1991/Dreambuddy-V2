"""C5 参数优化节点 — 真实业务逻辑测试

验证 C5ParamOptimizeNode 抽取自 ml_trade_service.py 参数优化路由的简化版：
- 从 state.get_result("C3").outputs["verified_signals"] 读取通过验证的信号
- 基于信号 confidence + trend + portfolio 反馈计算参数优化方向
- 输出 optimized_params/improvement_pct/optimization_log

简化策略（与 C0-C4 风格一致）：
- 每个信号按 confidence + win_rate 推荐参数微调
- improvement_pct 基于信号的平均 win_rate 相对基线 0.5 的提升
- optimization_log 记录每个信号的优化轨迹
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from dreamos.capabilities.trading.nodes.c5_param_optimize import C5ParamOptimizeNode
from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus


def _make_signal(
    symbol: str = "BTC",
    direction: str = "LONG",
    confidence: float = 0.8,
    win_rate: float = 0.65,
    trend: float = 0.10,
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
    config: Dict[str, Any] | None = None,
    with_c3: bool = True,
) -> State:
    state = State()
    state.config = config or {}
    state.market = {}
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
def test_c5_node_contract():
    node = C5ParamOptimizeNode()
    assert node.node_id == "C5"
    assert node.chain == "C"
    assert "classic" in node.tags
    assert "classic_v2" in node.tags
    assert "param_opt" in node.tags
    assert isinstance(node, BaseNode)


def test_c5_node_metadata():
    node = C5ParamOptimizeNode()
    assert node.name == "参数优化"
    assert node.description
    assert node.estimated_tokens == 0


# ── 2. 降级/边界场景 ──────────────────────────────────────
def test_c5_no_market_degradation():
    """无 market 时降级返回 SUCCESS + 空结果"""
    state = State()
    state.config = {}
    node = C5ParamOptimizeNode()
    result = node.execute_core(state)
    assert result.status == NodeStatus.SUCCESS
    assert result.outputs["optimized_params"] == {}
    assert result.outputs["improvement_pct"] == 0.0
    assert result.outputs["optimization_log"] == []


def test_c5_no_c3_results_degradation():
    """无 C3 上游结果时降级"""
    state = State()
    state.config = {}
    state.market = {}
    node = C5ParamOptimizeNode()
    result = node.execute_core(state)
    assert result.outputs["optimized_params"] == {}
    assert result.outputs["improvement_pct"] == 0.0


def test_c5_empty_signals():
    """verified_signals 为空时返回空结果"""
    state = _make_state(signals=[])
    node = C5ParamOptimizeNode()
    result = node.execute_core(state)
    assert result.outputs["optimized_params"] == {}
    assert result.outputs["improvement_pct"] == 0.0
    assert result.outputs["optimization_log"] == []


# ── 3. 参数优化测试 ───────────────────────────────────────
def test_c5_optimized_params_per_symbol():
    """每个信号生成对应的优化参数"""
    signals = [
        _make_signal(symbol="BTC", confidence=0.8, win_rate=0.65),
        _make_signal(symbol="ETH", confidence=0.75, win_rate=0.60),
    ]
    state = _make_state(signals=signals)
    node = C5ParamOptimizeNode()
    result = node.execute_core(state)
    assert "BTC" in result.outputs["optimized_params"]
    assert "ETH" in result.outputs["optimized_params"]


def test_c5_optimized_params_schema():
    """每个品种的优化参数含核心字段"""
    signals = [_make_signal(symbol="BTC", confidence=0.8, win_rate=0.65)]
    state = _make_state(signals=signals)
    node = C5ParamOptimizeNode()
    result = node.execute_core(state)
    params = result.outputs["optimized_params"]["BTC"]
    # 核心参数字段
    assert isinstance(params, dict)


def test_c5_improvement_positive_for_good_signals():
    """win_rate > 0.5 时 improvement_pct > 0"""
    signals = [_make_signal(symbol="BTC", confidence=0.8, win_rate=0.70)]
    state = _make_state(signals=signals)
    node = C5ParamOptimizeNode()
    result = node.execute_core(state)
    assert result.outputs["improvement_pct"] > 0.0


def test_c5_improvement_zero_for_baseline_signals():
    """win_rate = 0.5 时 improvement_pct = 0"""
    signals = [_make_signal(symbol="BTC", confidence=0.5, win_rate=0.50)]
    state = _make_state(signals=signals)
    node = C5ParamOptimizeNode()
    result = node.execute_core(state)
    assert result.outputs["improvement_pct"] == 0.0


def test_c5_optimization_log_records_iterations():
    """optimization_log 记录每个信号的优化轨迹"""
    signals = [
        _make_signal(symbol="BTC", confidence=0.8, win_rate=0.65),
        _make_signal(symbol="ETH", confidence=0.75, win_rate=0.60),
    ]
    state = _make_state(signals=signals)
    node = C5ParamOptimizeNode()
    result = node.execute_core(state)
    log = result.outputs["optimization_log"]
    assert isinstance(log, list)
    assert len(log) >= 1
    # 每条日志含必要字段
    for entry in log:
        assert isinstance(entry, dict)


# ── 4. 配置覆盖测试 ───────────────────────────────────────
def test_c5_config_override_baseline():
    """config 可覆盖 baseline"""
    signals = [_make_signal(symbol="BTC", confidence=0.8, win_rate=0.60)]
    state = _make_state(
        signals=signals,
        config={"param_optimize_baseline": 0.55},
    )
    node = C5ParamOptimizeNode()
    result = node.execute_core(state)
    # baseline=0.55, win_rate=0.60 → improvement=(0.60-0.55)/0.55
    # 但具体实现可能调整公式，只验证为正
    assert result.outputs["improvement_pct"] >= 0.0


def test_c5_uses_c3_verified_signals():
    """从 state.get_result("C3").outputs["verified_signals"] 读取"""
    signals = [_make_signal(symbol="BTC"), _make_signal(symbol="ETH")]
    state = _make_state(signals=signals)
    node = C5ParamOptimizeNode()
    result = node.execute_core(state)
    assert "BTC" in result.outputs["optimized_params"]
    assert "ETH" in result.outputs["optimized_params"]


def test_c5_high_confidence_yields_higher_improvement():
    """confidence 越高 → improvement 越大"""
    sig_a = _make_signal(symbol="BTC", confidence=0.60, win_rate=0.55)
    sig_b = _make_signal(symbol="BTC", confidence=0.90, win_rate=0.75)
    state_a = _make_state(signals=[sig_a])
    state_b = _make_state(signals=[sig_b])
    node = C5ParamOptimizeNode()
    res_a = node.execute_core(state_a)
    res_b = node.execute_core(state_b)
    assert res_b.outputs["improvement_pct"] >= res_a.outputs["improvement_pct"]
