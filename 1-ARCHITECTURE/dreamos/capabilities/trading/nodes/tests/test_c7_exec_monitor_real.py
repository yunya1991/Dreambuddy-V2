"""C7 执行监控节点 — 真实业务逻辑测试

验证 C7ExecMonitorNode 抽取自 ml_trade_service.py execute/monitor 路由的简化版：
- 从 state.get_result("C6").outputs["trade_plan"] 读取交易计划
- 模拟执行每笔订单 → filled_orders
- exec_status: filled/partial_filled/pending/canceled
- alerts: 滑点超限/部分成交/反向波动

简化策略（与 C0-C6 一致）：
- 不依赖交易所 API / WebSocket / 实时持仓
- 通过 state.market.market_data 获取当前价格作为成交价
- 无 market 或无 C6 上游 → FAIL-OPEN 返回 SUCCESS + 空 outputs
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from dreamos.capabilities.trading.nodes.c7_exec_monitor import C7ExecMonitorNode
from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus


# ── 测试夹具 ──────────────────────────────────────────────
def _make_trade_plan(plan: Dict[str, Dict[str, Any]] | None = None) -> Dict[str, Any]:
    if plan is None:
        plan = {
            "BTC": {
                "symbol": "BTC",
                "direction": "LONG",
                "size": 0.5,
                "entry_price": 60000.0,
                "stop_loss": 59000.0,
                "take_profit": 66000.0,
                "params": {},
            },
            "ETH": {
                "symbol": "ETH",
                "direction": "LONG",
                "size": 3.0,
                "entry_price": 3000.0,
                "stop_loss": 2950.0,
                "take_profit": 3300.0,
                "params": {},
            },
        }
    return plan


def _make_c6_outputs(trade_plan: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {
        "trade_plan": _make_trade_plan() if trade_plan is None else trade_plan,
        "changeset": {},
        "strategy_name": "Classic_LONG",
        "trace_id": "test-trace-001",
    }


def _make_state(
    c6_outputs: Dict[str, Any] | None = None,
    with_c6: bool = True,
    market_data: Dict[str, Any] | None = None,
    config: Dict[str, Any] | None = None,
    live_positions: Dict[str, Any] | None = None,
) -> State:
    state = State()
    state.config = config or {}
    if market_data is None:
        market_data = {"BTC": {"price": 60100.0}, "ETH": {"price": 3010.0}}
    state.market = {"market_data": market_data}
    if live_positions is not None:
        state.market["live_positions"] = live_positions
    if with_c6:
        state.results["C6"] = NodeResult(
            node_id="C6",
            status=NodeStatus.SUCCESS,
            confidence=0.8,
            outputs=_make_c6_outputs() if c6_outputs is None else c6_outputs,
        )
    return state


# ── 1. 契约与导入 ──────────────────────────────────────────
class TestC7Contract:
    def test_import(self):
        from dreamos.capabilities.trading.nodes.c7_exec_monitor import C7ExecMonitorNode  # noqa: F401

    def test_node_metadata(self):
        node = C7ExecMonitorNode()
        assert node.node_id == "C7"
        assert node.chain == "C"
        assert "classic" in node.tags
        assert "classic_v2" in node.tags
        assert "execution" in node.tags

    def test_is_base_node_subclass(self):
        assert isinstance(C7ExecMonitorNode(), BaseNode)


# ── 2. FAIL-OPEN 路径 ──────────────────────────────────────
class TestC7FailOpen:
    def test_no_market_returns_success_empty(self):
        node = C7ExecMonitorNode()
        state = State()
        state.market = None
        state.results["C6"] = NodeResult(node_id="C6", status=NodeStatus.SUCCESS,
                                          outputs=_make_c6_outputs())
        r = node.execute_core(state)
        assert r.status == NodeStatus.SUCCESS
        assert r.outputs["exec_status"] == "pending"
        assert r.outputs["filled_orders"] == []
        assert r.outputs["alerts"] == []
        assert r.error is not None

    def test_no_c6_upstream_returns_success_empty(self):
        node = C7ExecMonitorNode()
        state = _make_state(with_c6=False)
        r = node.execute_core(state)
        assert r.status == NodeStatus.SUCCESS
        assert r.outputs["exec_status"] == "pending"
        assert r.outputs["filled_orders"] == []
        assert r.error is not None
        assert "C6" in (r.error or "")

    def test_c6_empty_trade_plan_returns_pending(self):
        node = C7ExecMonitorNode()
        state = _make_state(c6_outputs=_make_c6_outputs(trade_plan={}))
        r = node.execute_core(state)
        assert r.status == NodeStatus.SUCCESS
        assert r.outputs["exec_status"] == "pending"
        assert r.outputs["filled_orders"] == []


# ── 3. filled_orders 生成 ─────────────────────────────────
class TestC7FilledOrders:
    def test_filled_orders_count_matches_plan(self):
        node = C7ExecMonitorNode()
        state = _make_state()
        r = node.execute_core(state)
        assert len(r.outputs["filled_orders"]) == 2

    def test_filled_order_has_required_fields(self):
        node = C7ExecMonitorNode()
        state = _make_state()
        r = node.execute_core(state)
        order = r.outputs["filled_orders"][0]
        assert isinstance(order, dict)
        for field in ("symbol", "direction", "size", "filled_price", "status"):
            assert field in order, f"missing field: {field}"

    def test_filled_order_status_is_filled(self):
        node = C7ExecMonitorNode()
        state = _make_state()
        r = node.execute_core(state)
        for order in r.outputs["filled_orders"]:
            assert order["status"] == "filled"

    def test_filled_price_from_market(self):
        node = C7ExecMonitorNode()
        state = _make_state(market_data={"BTC": {"price": 60100.0}, "ETH": {"price": 3010.0}})
        r = node.execute_core(state)
        btc_order = next(o for o in r.outputs["filled_orders"] if o["symbol"] == "BTC")
        assert btc_order["filled_price"] == 60100.0

    def test_filled_order_preserves_direction(self):
        node = C7ExecMonitorNode()
        state = _make_state()
        r = node.execute_core(state)
        btc_order = next(o for o in r.outputs["filled_orders"] if o["symbol"] == "BTC")
        assert btc_order["direction"] == "LONG"

    def test_filled_order_preserves_size(self):
        node = C7ExecMonitorNode()
        state = _make_state()
        r = node.execute_core(state)
        btc_order = next(o for o in r.outputs["filled_orders"] if o["symbol"] == "BTC")
        assert btc_order["size"] == 0.5


# ── 4. exec_status 状态机 ─────────────────────────────────
class TestC7ExecStatus:
    def test_all_filled_status(self):
        node = C7ExecMonitorNode()
        state = _make_state()
        r = node.execute_core(state)
        assert r.outputs["exec_status"] == "filled"

    def test_empty_plan_status_pending(self):
        node = C7ExecMonitorNode()
        state = _make_state(c6_outputs=_make_c6_outputs(trade_plan={}))
        r = node.execute_core(state)
        assert r.outputs["exec_status"] == "pending"

    def test_partial_fill_when_market_missing_symbol(self):
        """市场数据缺少某品种 → 该订单未成交 → partial_filled"""
        node = C7ExecMonitorNode()
        # market_data 只有 BTC，没有 ETH
        state = _make_state(market_data={"BTC": {"price": 60100.0}})
        r = node.execute_core(state)
        assert r.outputs["exec_status"] == "partial_filled"
        assert len(r.outputs["filled_orders"]) == 1  # 只有 BTC 成交


# ── 5. alerts 告警 ────────────────────────────────────────
class TestC7Alerts:
    def test_no_alerts_when_normal_execution(self):
        """正常执行无告警"""
        node = C7ExecMonitorNode()
        state = _make_state(market_data={"BTC": {"price": 60000.0}, "ETH": {"price": 3000.0}})
        r = node.execute_core(state)
        # 滑点在阈值内 → 无告警
        assert r.outputs["alerts"] == []

    def test_slippage_alert_when_price_deviates(self):
        """成交价偏离 entry_price 超过阈值 → 滑点告警"""
        node = C7ExecMonitorNode()
        # BTC entry_price=60000, 市场价 63000 → 偏离 5%
        state = _make_state(market_data={"BTC": {"price": 63000.0}, "ETH": {"price": 3000.0}})
        r = node.execute_core(state)
        alerts = r.outputs["alerts"]
        assert len(alerts) > 0
        # 至少有一个滑点相关告警
        assert any("slippage" in str(a.get("type", "")).lower() or
                   "滑点" in str(a.get("message", "")) for a in alerts)

    def test_missing_market_data_alert(self):
        """市场数据缺少品种 → missing_data 告警"""
        node = C7ExecMonitorNode()
        state = _make_state(market_data={"BTC": {"price": 60000.0}})  # 无 ETH
        r = node.execute_core(state)
        alerts = r.outputs["alerts"]
        assert len(alerts) > 0
        assert any("ETH" in str(a.get("symbol", "")) for a in alerts)


# ── 6. exec_log ───────────────────────────────────────────
class TestC7ExecLog:
    def test_exec_log_is_dict(self):
        node = C7ExecMonitorNode()
        state = _make_state()
        r = node.execute_core(state)
        assert isinstance(r.outputs.get("exec_log", {}), dict)

    def test_exec_log_contains_summary(self):
        node = C7ExecMonitorNode()
        state = _make_state()
        r = node.execute_core(state)
        log = r.outputs.get("exec_log", {})
        # 应含 total/filled/failed 统计
        assert "total" in log or "filled_count" in log or "total_orders" in log


# ── 7. 边界场景 ───────────────────────────────────────────
class TestC7EdgeCases:
    def test_single_order(self):
        node = C7ExecMonitorNode()
        plan = {"BTC": {"symbol": "BTC", "direction": "LONG", "size": 0.5,
                        "entry_price": 60000.0, "stop_loss": 59000.0,
                        "take_profit": 66000.0, "params": {}}}
        state = _make_state(c6_outputs=_make_c6_outputs(trade_plan=plan))
        r = node.execute_core(state)
        assert len(r.outputs["filled_orders"]) == 1
        assert r.outputs["exec_status"] == "filled"

    def test_short_direction_order(self):
        node = C7ExecMonitorNode()
        plan = {"BTC": {"symbol": "BTC", "direction": "SHORT", "size": 0.5,
                        "entry_price": 60000.0, "stop_loss": 61000.0,
                        "take_profit": 54000.0, "params": {}}}
        state = _make_state(c6_outputs=_make_c6_outputs(trade_plan=plan))
        r = node.execute_core(state)
        order = r.outputs["filled_orders"][0]
        assert order["direction"] == "SHORT"

    def test_slippage_threshold_configurable(self):
        """config.exec_slippage_threshold 可覆盖滑点阈值"""
        node = C7ExecMonitorNode()
        # entry_price=6060, market=6100 → 偏离 40/6060=0.66% > 0.5% 阈值 → 告警
        state = _make_state(
            market_data={"BTC": {"price": 6100.0}, "ETH": {"price": 3000.0}},
            config={"exec_slippage_threshold": 0.005},
        )
        state.results["C6"].outputs["trade_plan"]["BTC"]["entry_price"] = 6060.0
        state.market["market_data"]["BTC"]["price"] = 6100.0  # 偏离 0.66%
        r = node.execute_core(state)
        alerts = r.outputs["alerts"]
        assert len(alerts) > 0

    def test_trace_id_propagated(self):
        """C6 trace_id 应传播到 C7 exec_log"""
        node = C7ExecMonitorNode()
        state = _make_state()
        r = node.execute_core(state)
        log = r.outputs.get("exec_log", {})
        assert "trace_id" in log
        assert log["trace_id"] == "test-trace-001"
