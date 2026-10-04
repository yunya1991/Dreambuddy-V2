"""C3 回测验证节点 — 真实业务逻辑测试

验证 C3BacktestVerifyNode 抽取自 ml_trade_service.py 回测路由的简化版：
- 从 state.get_result("C2").outputs["signals"] 读取待验证信号
- 基于 signal confidence + trend/momentum 同向性 + 历史样本模拟胜率
- 过滤低质信号，输出 verified_signals/win_rate/sharpe/max_dd

简化策略（与 C0/C1/C2 风格一致）：
- 每个 signal 的 confidence 作为基础胜率
- trend 方向强度 + momentum 同向加成调整胜率
- 累积盈亏 → 计算 sharpe / max_dd
- 过滤 confidence < threshold 的信号（默认 0.55）
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from dreamos.capabilities.trading.nodes.c3_backtest_verify import C3BacktestVerifyNode
from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus


def _make_signal(
    symbol: str = "BTC",
    direction: str = "LONG",
    confidence: float = 0.7,
    trend: float = 0.10,
    rsi: float = 60.0,
    momentum: float = 0.05,
) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "direction": direction,
        "confidence": confidence,
        "strategy": "trend_momentum",
        "layer": "trend",
        "trend": trend,
        "rsi": rsi,
        "momentum": momentum,
    }


def _make_state(
    signals: List[Dict[str, Any]] | None = None,
    config: Dict[str, Any] | None = None,
    with_c2: bool = True,
) -> State:
    state = State()
    state.config = config or {}
    state.market = {}
    if with_c2:
        state.results["C2"] = NodeResult(
            node_id="C2",
            status=NodeStatus.SUCCESS,
            confidence=0.7,
            outputs={
                "signals": signals or [],
                "signal_count": len(signals or []),
                "dominant_direction": "LONG" if signals else "NEUTRAL",
            },
        )
    return state


# ── 1. 契约测试 ────────────────────────────────────────────
def test_c3_node_contract():
    node = C3BacktestVerifyNode()
    assert node.node_id == "C3"
    assert node.chain == "C"
    assert "classic" in node.tags
    assert "classic_v2" in node.tags
    assert "backtest" in node.tags
    assert isinstance(node, BaseNode)


def test_c3_node_metadata():
    node = C3BacktestVerifyNode()
    assert node.name == "回测验证"
    assert node.description
    assert node.estimated_tokens == 0


# ── 2. 降级/边界场景 ──────────────────────────────────────
def test_c3_no_market_degradation():
    """无 market 时降级返回 SUCCESS + 空结果"""
    state = State()
    state.config = {}
    node = C3BacktestVerifyNode()
    result = node.execute_core(state)
    assert result.status == NodeStatus.SUCCESS
    assert result.outputs["verified_signals"] == []
    assert result.outputs["win_rate"] == 0.0
    assert result.outputs["sharpe"] == 0.0
    assert result.outputs["max_dd"] == 0.0


def test_c3_no_c2_results_degradation():
    """无 C2 上游结果时降级"""
    state = State()
    state.config = {}
    state.market = {}
    node = C3BacktestVerifyNode()
    result = node.execute_core(state)
    assert result.outputs["verified_signals"] == []
    assert result.outputs["win_rate"] == 0.0


def test_c3_empty_signals():
    """C2 signals 为空时返回空结果"""
    state = _make_state(signals=[])
    node = C3BacktestVerifyNode()
    result = node.execute_core(state)
    assert result.outputs["verified_signals"] == []
    assert result.outputs["win_rate"] == 0.0
    assert result.outputs["sharpe"] == 0.0
    assert result.outputs["max_dd"] == 0.0


# ── 3. 信号验证测试 ───────────────────────────────────────
def test_c3_low_confidence_filtered():
    """confidence < 阈值的信号被过滤"""
    signals = [
        _make_signal(symbol="BTC", confidence=0.40),  # 低于默认 0.55
        _make_signal(symbol="ETH", confidence=0.80),
    ]
    state = _make_state(signals=signals)
    node = C3BacktestVerifyNode()
    result = node.execute_core(state)
    symbols = [s["symbol"] for s in result.outputs["verified_signals"]]
    assert "BTC" not in symbols
    assert "ETH" in symbols


def test_c3_high_confidence_passed():
    """高 confidence + 强 trend 的信号通过验证"""
    signals = [_make_signal(symbol="BTC", confidence=0.80, trend=0.15, momentum=0.08)]
    state = _make_state(signals=signals)
    node = C3BacktestVerifyNode()
    result = node.execute_core(state)
    assert len(result.outputs["verified_signals"]) == 1


def test_c3_verified_signal_schema():
    """验证后的 signal 含原字段 + win_rate"""
    signals = [_make_signal(symbol="BTC", confidence=0.80, trend=0.15)]
    state = _make_state(signals=signals)
    node = C3BacktestVerifyNode()
    result = node.execute_core(state)
    vs = result.outputs["verified_signals"][0]
    assert "symbol" in vs
    assert "direction" in vs
    assert "confidence" in vs
    assert "win_rate" in vs  # 新增字段


def test_c3_win_rate_range():
    """win_rate 在 [0, 1] 区间"""
    signals = [
        _make_signal(symbol="BTC", confidence=0.80, trend=0.15),
        _make_signal(symbol="ETH", confidence=0.70, trend=0.10),
    ]
    state = _make_state(signals=signals)
    node = C3BacktestVerifyNode()
    result = node.execute_core(state)
    assert 0.0 <= result.outputs["win_rate"] <= 1.0


def test_c3_sharpe_reasonable():
    """sharpe 为合理数值（可能为负表示亏损）"""
    signals = [_make_signal(symbol="BTC", confidence=0.80, trend=0.15)]
    state = _make_state(signals=signals)
    node = C3BacktestVerifyNode()
    result = node.execute_core(state)
    # sharpe 可正可负，但应该是有限数值
    assert isinstance(result.outputs["sharpe"], (int, float))


def test_c3_max_dd_non_negative():
    """max_dd >= 0"""
    signals = [_make_signal(symbol="BTC", confidence=0.80, trend=0.15)]
    state = _make_state(signals=signals)
    node = C3BacktestVerifyNode()
    result = node.execute_core(state)
    assert result.outputs["max_dd"] >= 0.0


# ── 4. 配置覆盖测试 ───────────────────────────────────────
def test_c3_config_override_confidence_threshold():
    """config 可覆盖 confidence 阈值"""
    signals = [_make_signal(symbol="BTC", confidence=0.50)]
    state = _make_state(
        signals=signals,
        config={"backtest_confidence_threshold": 0.40},  # 降低阈值
    )
    node = C3BacktestVerifyNode()
    result = node.execute_core(state)
    assert len(result.outputs["verified_signals"]) == 1


def test_c3_uses_c2_signals_from_state():
    """从 state.get_result("C2").outputs["signals"] 读取"""
    signals = [
        _make_signal(symbol="BTC", confidence=0.80),
        _make_signal(symbol="ETH", confidence=0.70),
        _make_signal(symbol="SOL", confidence=0.90),
    ]
    state = _make_state(signals=signals)
    node = C3BacktestVerifyNode()
    result = node.execute_core(state)
    symbols = [s["symbol"] for s in result.outputs["verified_signals"]]
    assert set(symbols) == {"BTC", "ETH", "SOL"}


def test_c3_momentum_aligned_enhances_win_rate():
    """momentum 与 trend 同向时 win_rate 提升"""
    sig_a = _make_signal(symbol="BTC", confidence=0.70, trend=0.10, momentum=0.0)
    sig_b = _make_signal(symbol="BTC", confidence=0.70, trend=0.10, momentum=0.08)
    state_a = _make_state(signals=[sig_a])
    state_b = _make_state(signals=[sig_b])
    node = C3BacktestVerifyNode()
    res_a = node.execute_core(state_a)
    res_b = node.execute_core(state_b)
    assert res_b.outputs["win_rate"] >= res_a.outputs["win_rate"]


def test_c3_short_signal_validated():
    """SHORT 信号同样可被验证"""
    signals = [_make_signal(symbol="BTC", direction="SHORT", confidence=0.80, trend=-0.15, momentum=-0.08)]
    state = _make_state(signals=signals)
    node = C3BacktestVerifyNode()
    result = node.execute_core(state)
    assert len(result.outputs["verified_signals"]) == 1
    assert result.outputs["verified_signals"][0]["direction"] == "SHORT"


# ── 5. backtrader 可选增强测试 ──────────────────────────────
def test_c3_backtrader_enhance_fail_open():
    """无 backtest_klines 时 outputs["backtest_source"]=="simplified"

    场景：C3 节点未在 state.config 中提供 backtest_klines，
    应继续使用简化模拟结果，outputs 标记 source="simplified"。
    这是 FAIL-OPEN 设计：backtrader 未启用时不应破坏主流程。
    """
    signals = [_make_signal(symbol="BTC", confidence=0.80, trend=0.15)]
    state = _make_state(signals=signals)  # config 不含 backtest_klines
    node = C3BacktestVerifyNode()
    result = node.execute_core(state)
    assert result.status == NodeStatus.SUCCESS
    # backtest_source 字段应存在且为 "simplified"
    assert result.outputs.get("backtest_source") == "simplified"
    # 简化结果字段仍然存在
    assert "verified_signals" in result.outputs
    assert "win_rate" in result.outputs


def test_c3_backtrader_enhance_with_klines():
    """有 backtest_klines 时 outputs["backtest_source"] in ("backtrader","simplified")

    场景：state.config["backtest_klines"] 提供了 K 线数据，
    C3 节点尝试调用 backtrader 适配器增强结果。
    - 若 backtrader 已安装且成功 → source="backtrader"
    - 若 backtrader 未安装或失败 → 降级 source="simplified"（FAIL-OPEN）
    两种情况都应返回 SUCCESS，不破坏主流程。
    """
    signals = [_make_signal(symbol="BTC", confidence=0.80, trend=0.15)]
    # 提供 K 线数据（最小骨架，可能因 backtrader 未安装而降级）
    fake_klines = [
        {"date": "2026-09-01", "open": 100, "high": 105, "low": 95, "close": 102, "volume": 1000},
        {"date": "2026-09-02", "open": 102, "high": 108, "low": 101, "close": 107, "volume": 1200},
    ]
    state = _make_state(
        signals=signals,
        config={"backtest_klines": fake_klines},
    )
    node = C3BacktestVerifyNode()
    result = node.execute_core(state)
    assert result.status == NodeStatus.SUCCESS
    # backtest_source 字段应存在，值为 "backtrader" 或 "simplified"（取决于 backtrader 是否可用）
    assert result.outputs.get("backtest_source") in ("backtrader", "simplified")
    # 无论 source 为何，outputs 都应包含核心字段
    assert "verified_signals" in result.outputs
    assert "win_rate" in result.outputs
    assert "sharpe" in result.outputs
    assert "max_dd" in result.outputs
