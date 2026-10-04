"""C8 绩效归因节点 — 真实业务逻辑测试

验证 C8PerfAttributionNode 抽取自 ml_trade_service.py attribution/performance 路由的简化版：
- 从 state.config.closed_trades 或 state.market.closed_trades 读取已平仓交易
- pnl_attribution 按品种/方向分解盈亏
- lessons 基于盈亏生成经验教训字符串
- memory_feedback 结构化数据供认知记忆系统 record

简化策略（与 C0-C7 一致）：
- 不依赖数据库 / 全局 CONFIG / 复杂归因引擎
- 基于 closed_trades 的 pnl 字段做简单聚合
- 无 closed_trades → FAIL-OPEN 返回 SUCCESS + 空 outputs
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from dreamos.capabilities.trading.nodes.c8_perf_attribution import C8PerfAttributionNode
from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus


# ── 测试夹具 ──────────────────────────────────────────────
def _make_closed_trade(
    symbol: str = "BTC",
    direction: str = "LONG",
    entry_price: float = 60000.0,
    exit_price: float = 65000.0,
    size: float = 0.5,
    pnl: float | None = None,
) -> Dict[str, Any]:
    if pnl is None:
        if direction == "LONG":
            pnl = (exit_price - entry_price) * size
        else:
            pnl = (entry_price - exit_price) * size
    return {
        "symbol": symbol,
        "direction": direction,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "size": size,
        "pnl": pnl,
    }


def _make_closed_trades(trades: List[Dict[str, Any]] | None = None) -> List[Dict[str, Any]]:
    if trades is None:
        return [
            _make_closed_trade("BTC", "LONG", 60000.0, 65000.0, 0.5),  # +2500
            _make_closed_trade("ETH", "LONG", 3000.0, 3300.0, 3.0),   # +900
        ]
    return trades


def _make_c7_outputs(exec_log: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {
        "exec_status": "filled",
        "filled_orders": [],
        "alerts": [],
        "exec_log": exec_log or {"total": 2, "filled_count": 2, "failed_count": 0, "trace_id": "trace-001"},
    }


def _make_state(
    closed_trades: List[Dict[str, Any]] | None = None,
    with_c7: bool = True,
    config: Dict[str, Any] | None = None,
    trades_in: str = "config",  # "config" or "market"
) -> State:
    state = State()
    state.config = config or {}
    state.market = {}
    trades = _make_closed_trades() if closed_trades is None else closed_trades
    if trades_in == "config":
        state.config["closed_trades"] = trades
    else:
        state.market["closed_trades"] = trades
    if with_c7:
        state.results["C7"] = NodeResult(
            node_id="C7",
            status=NodeStatus.SUCCESS,
            confidence=0.9,
            outputs=_make_c7_outputs(),
        )
    return state


# ── 1. 契约与导入 ──────────────────────────────────────────
class TestC8Contract:
    def test_import(self):
        from dreamos.capabilities.trading.nodes.c8_perf_attribution import C8PerfAttributionNode  # noqa: F401

    def test_node_metadata(self):
        node = C8PerfAttributionNode()
        assert node.node_id == "C8"
        assert node.chain == "C"
        assert "classic" in node.tags
        assert "classic_v2" in node.tags
        assert "attribution" in node.tags
        assert "memory" in node.tags

    def test_is_base_node_subclass(self):
        assert isinstance(C8PerfAttributionNode(), BaseNode)


# ── 2. FAIL-OPEN 路径 ──────────────────────────────────────
class TestC8FailOpen:
    def test_no_c7_upstream_returns_success_empty(self):
        node = C8PerfAttributionNode()
        state = _make_state(with_c7=False)
        state.config["closed_trades"] = _make_closed_trades()
        r = node.execute_core(state)
        assert r.status == NodeStatus.SUCCESS
        assert r.outputs["pnl_attribution"] == {}
        assert r.outputs["lessons"] == []
        assert r.error is not None
        assert "C7" in (r.error or "")

    def test_no_closed_trades_returns_success_empty(self):
        node = C8PerfAttributionNode()
        state = _make_state()
        state.config.pop("closed_trades", None)
        state.market.pop("closed_trades", None)
        r = node.execute_core(state)
        assert r.status == NodeStatus.SUCCESS
        assert r.outputs["pnl_attribution"] == {}
        assert r.outputs["lessons"] == []
        assert r.error is not None

    def test_empty_closed_trades_returns_success_empty(self):
        node = C8PerfAttributionNode()
        state = _make_state(closed_trades=[])
        r = node.execute_core(state)
        assert r.status == NodeStatus.SUCCESS
        assert r.outputs["pnl_attribution"] == {}
        assert r.outputs["lessons"] == []


# ── 3. pnl_attribution 生成 ───────────────────────────────
class TestC8PnlAttribution:
    def test_pnl_attribution_is_dict(self):
        node = C8PerfAttributionNode()
        state = _make_state()
        r = node.execute_core(state)
        assert isinstance(r.outputs["pnl_attribution"], dict)

    def test_pnl_attribution_has_total_pnl(self):
        node = C8PerfAttributionNode()
        state = _make_state()
        r = node.execute_core(state)
        attr = r.outputs["pnl_attribution"]
        assert "total_pnl" in attr
        # BTC: +2500, ETH: +900 → total = 3400
        assert attr["total_pnl"] == pytest.approx(3400.0)

    def test_pnl_attribution_by_symbol(self):
        node = C8PerfAttributionNode()
        state = _make_state()
        r = node.execute_core(state)
        attr = r.outputs["pnl_attribution"]
        assert "by_symbol" in attr
        assert attr["by_symbol"]["BTC"] == pytest.approx(2500.0)
        assert attr["by_symbol"]["ETH"] == pytest.approx(900.0)

    def test_pnl_attribution_by_direction(self):
        node = C8PerfAttributionNode()
        state = _make_state()
        r = node.execute_core(state)
        attr = r.outputs["pnl_attribution"]
        assert "by_direction" in attr
        assert attr["by_direction"]["LONG"] == pytest.approx(3400.0)

    def test_pnl_attribution_trade_count(self):
        node = C8PerfAttributionNode()
        state = _make_state()
        r = node.execute_core(state)
        attr = r.outputs["pnl_attribution"]
        assert attr.get("trade_count") == 2

    def test_pnl_attribution_win_rate(self):
        node = C8PerfAttributionNode()
        state = _make_state()
        r = node.execute_core(state)
        attr = r.outputs["pnl_attribution"]
        assert "win_rate" in attr
        # 2 笔都盈利 → win_rate = 1.0
        assert attr["win_rate"] == pytest.approx(1.0)


# ── 4. lessons 生成 ───────────────────────────────────────
class TestC8Lessons:
    def test_lessons_is_list_of_strings(self):
        node = C8PerfAttributionNode()
        state = _make_state()
        r = node.execute_core(state)
        lessons = r.outputs["lessons"]
        assert isinstance(lessons, list)
        assert all(isinstance(s, str) for s in lessons)

    def test_lessons_not_empty_when_trades_exist(self):
        node = C8PerfAttributionNode()
        state = _make_state()
        r = node.execute_core(state)
        assert len(r.outputs["lessons"]) > 0

    def test_lessons_contain_winning_insight_when_all_win(self):
        node = C8PerfAttributionNode()
        state = _make_state()
        r = node.execute_core(state)
        lessons_text = " ".join(r.outputs["lessons"]).lower()
        assert "win" in lessons_text or "盈利" in lessons_text or "胜" in lessons_text

    def test_lessons_contain_losing_insight_when_all_lose(self):
        node = C8PerfAttributionNode()
        trades = [
            _make_closed_trade("BTC", "LONG", 60000.0, 59000.0, 0.5),   # -500
            _make_closed_trade("ETH", "LONG", 3000.0, 2900.0, 3.0),     # -300
        ]
        state = _make_state(closed_trades=trades)
        r = node.execute_core(state)
        lessons_text = " ".join(r.outputs["lessons"]).lower()
        assert "loss" in lessons_text or "亏损" in lessons_text or "止损" in lessons_text


# ── 5. memory_feedback 生成 ──────────────────────────────
class TestC8MemoryFeedback:
    def test_memory_feedback_is_dict(self):
        node = C8PerfAttributionNode()
        state = _make_state()
        r = node.execute_core(state)
        assert isinstance(r.outputs["memory_feedback"], dict)

    def test_memory_feedback_contains_summary(self):
        node = C8PerfAttributionNode()
        state = _make_state()
        r = node.execute_core(state)
        fb = r.outputs["memory_feedback"]
        assert "total_pnl" in fb or "summary" in fb

    def test_memory_feedback_trace_id_from_c7(self):
        node = C8PerfAttributionNode()
        state = _make_state()
        r = node.execute_core(state)
        fb = r.outputs["memory_feedback"]
        assert fb.get("trace_id") == "trace-001"

    def test_memory_feedback_contains_tags(self):
        node = C8PerfAttributionNode()
        state = _make_state()
        r = node.execute_core(state)
        fb = r.outputs["memory_feedback"]
        assert "tags" in fb
        assert isinstance(fb["tags"], list)


# ── 6. 边界场景 ───────────────────────────────────────────
class TestC8EdgeCases:
    def test_single_trade(self):
        node = C8PerfAttributionNode()
        trades = [_make_closed_trade("BTC", "LONG", 60000.0, 65000.0, 0.5)]
        state = _make_state(closed_trades=trades)
        r = node.execute_core(state)
        assert r.outputs["pnl_attribution"]["trade_count"] == 1
        assert r.outputs["pnl_attribution"]["total_pnl"] == pytest.approx(2500.0)

    def test_short_trade_pnl(self):
        node = C8PerfAttributionNode()
        trades = [_make_closed_trade("BTC", "SHORT", 60000.0, 55000.0, 0.5)]  # +2500
        state = _make_state(closed_trades=trades)
        r = node.execute_core(state)
        assert r.outputs["pnl_attribution"]["total_pnl"] == pytest.approx(2500.0)
        assert r.outputs["pnl_attribution"]["by_direction"]["SHORT"] == pytest.approx(2500.0)

    def test_mixed_win_loss(self):
        node = C8PerfAttributionNode()
        trades = [
            _make_closed_trade("BTC", "LONG", 60000.0, 65000.0, 0.5),  # +2500 win
            _make_closed_trade("ETH", "LONG", 3000.0, 2900.0, 3.0),    # -300 loss
        ]
        state = _make_state(closed_trades=trades)
        r = node.execute_core(state)
        attr = r.outputs["pnl_attribution"]
        assert attr["total_pnl"] == pytest.approx(2200.0)
        assert attr["win_rate"] == pytest.approx(0.5)

    def test_closed_trades_from_market(self):
        """closed_trades 也可从 state.market 读取"""
        node = C8PerfAttributionNode()
        state = _make_state(trades_in="market")
        # 清除 config 中的 closed_trades
        state.config.pop("closed_trades", None)
        r = node.execute_core(state)
        assert r.outputs["pnl_attribution"]["trade_count"] == 2

    def test_trade_missing_pnl_computed_from_prices(self):
        """交易缺少 pnl 字段时从 entry/exit/size 计算"""
        node = C8PerfAttributionNode()
        trade = _make_closed_trade("BTC", "LONG", 60000.0, 65000.0, 0.5)
        trade.pop("pnl")
        state = _make_state(closed_trades=[trade])
        r = node.execute_core(state)
        assert r.outputs["pnl_attribution"]["total_pnl"] == pytest.approx(2500.0)
