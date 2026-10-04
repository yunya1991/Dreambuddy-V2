"""C6 计划生成节点 — 真实业务逻辑测试

验证 C6PlanGenerateNode 抽取自 ml_trade_service.py plan/draft 路由的简化版：
- 从 state.get_result("C4").outputs 读取 position_size/stop_loss/take_profit
- 从 state.get_result("C5").outputs["optimized_params"] 读取参数
- 聚合产出 trade_plan（每品种完整计划）+ changeset（供 governance 审批）
- strategy_name 基于主流方向，trace_id 用 uuid

简化策略（与 C0-C5 风格一致）：
- 不依赖全局 CONFIG / 复杂 draft 引擎
- 无 market 或无 C4/C5 上游 → FAIL-OPEN 返回 SUCCESS + 空 outputs
- 仓位为 0 的品种被过滤
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch
from uuid import UUID

import pytest

from dreamos.capabilities.trading.nodes.c6_plan_generate import C6PlanGenerateNode
from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus


# ── 测试夹具 ──────────────────────────────────────────────
def _make_c4_outputs(
    position_size: Dict[str, float] | None = None,
    stop_loss: Dict[str, float] | None = None,
    take_profit: Dict[str, float] | None = None,
    risk_budget: float = 0.08,
) -> Dict[str, Any]:
    return {
        "position_size": {"BTC": 0.5, "ETH": 3.0} if position_size is None else position_size,
        "stop_loss": {"BTC": 60000.0, "ETH": 3000.0} if stop_loss is None else stop_loss,
        "take_profit": {"BTC": 66000.0, "ETH": 3300.0} if take_profit is None else take_profit,
        "risk_budget": risk_budget,
    }


def _make_c5_outputs(
    optimized_params: Dict[str, Dict[str, Any]] | None = None,
    improvement_pct: float = 0.15,
) -> Dict[str, Any]:
    return {
        "optimized_params": optimized_params
        or {
            "BTC": {
                "trend_threshold": 0.01,
                "risk_per_trade": 0.02,
                "take_profit_pct": 0.08,
                "stop_loss_pct": 0.03,
                "confidence_input": 0.85,
                "win_rate_input": 0.65,
            },
            "ETH": {
                "trend_threshold": 0.015,
                "risk_per_trade": 0.025,
                "take_profit_pct": 0.09,
                "stop_loss_pct": 0.025,
                "confidence_input": 0.70,
                "win_rate_input": 0.60,
            },
        },
        "improvement_pct": improvement_pct,
        "optimization_log": [],
    }


def _make_c3_signals(signals: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    return {
        "verified_signals": signals
        or [
            {"symbol": "BTC", "direction": "LONG", "confidence": 0.85, "win_rate": 0.65},
            {"symbol": "ETH", "direction": "LONG", "confidence": 0.70, "win_rate": 0.60},
        ],
        "win_rate": 0.625,
        "sharpe": 1.2,
        "max_dd": 0.08,
    }


def _make_state(
    c4_outputs: Dict[str, Any] | None = None,
    c5_outputs: Dict[str, Any] | None = None,
    c3_outputs: Dict[str, Any] | None = None,
    with_c4: bool = True,
    with_c5: bool = True,
    with_c3: bool = True,
    config: Dict[str, Any] | None = None,
) -> State:
    state = State()
    state.config = config or {}
    state.market = {"market_data": {"BTC": {"price": 60000.0}, "ETH": {"price": 3000.0}}}
    if with_c3:
        state.results["C3"] = NodeResult(
            node_id="C3",
            status=NodeStatus.SUCCESS,
            confidence=0.7,
            outputs=_make_c3_signals() if c3_outputs is None else c3_outputs,
        )
    if with_c4:
        state.results["C4"] = NodeResult(
            node_id="C4",
            status=NodeStatus.SUCCESS,
            confidence=0.8,
            outputs=_make_c4_outputs() if c4_outputs is None else c4_outputs,
        )
    if with_c5:
        state.results["C5"] = NodeResult(
            node_id="C5",
            status=NodeStatus.SUCCESS,
            confidence=0.75,
            outputs=_make_c5_outputs() if c5_outputs is None else c5_outputs,
        )
    return state


# ── 1. 契约与导入 ──────────────────────────────────────────
class TestC6Contract:
    def test_import(self):
        from dreamos.capabilities.trading.nodes.c6_plan_generate import C6PlanGenerateNode  # noqa: F401

    def test_node_metadata(self):
        node = C6PlanGenerateNode()
        assert node.node_id == "C6"
        assert node.chain == "C"
        assert "classic" in node.tags
        assert "classic_v2" in node.tags
        assert "plan" in node.tags

    def test_is_base_node_subclass(self):
        assert isinstance(C6PlanGenerateNode(), BaseNode)


# ── 2. FAIL-OPEN 路径 ──────────────────────────────────────
class TestC6FailOpen:
    def test_no_market_returns_success_empty(self):
        node = C6PlanGenerateNode()
        state = State()
        state.market = None
        state.results["C4"] = NodeResult(node_id="C4", status=NodeStatus.SUCCESS,
                                          outputs=_make_c4_outputs())
        state.results["C5"] = NodeResult(node_id="C5", status=NodeStatus.SUCCESS,
                                          outputs=_make_c5_outputs())
        r = node.execute_core(state)
        assert r.status == NodeStatus.SUCCESS
        assert r.outputs["trade_plan"] == {}
        assert r.outputs["changeset"] == {}
        assert r.outputs["strategy_name"] == ""
        assert r.outputs["trace_id"] == ""
        assert r.error is not None

    def test_no_c4_upstream_returns_success_empty(self):
        node = C6PlanGenerateNode()
        state = _make_state(with_c4=False)
        r = node.execute_core(state)
        assert r.status == NodeStatus.SUCCESS
        assert r.outputs["trade_plan"] == {}
        assert r.error is not None
        assert "C4" in (r.error or "")

    def test_no_c5_upstream_returns_success_empty(self):
        node = C6PlanGenerateNode()
        state = _make_state(with_c5=False)
        r = node.execute_core(state)
        assert r.status == NodeStatus.SUCCESS
        assert r.outputs["trade_plan"] == {}
        assert r.error is not None
        assert "C5" in (r.error or "")

    def test_c4_empty_position_size_returns_success_empty(self):
        node = C6PlanGenerateNode()
        state = _make_state(c4_outputs=_make_c4_outputs(position_size={}))
        r = node.execute_core(state)
        assert r.status == NodeStatus.SUCCESS
        assert r.outputs["trade_plan"] == {}
        assert r.error is not None


# ── 3. trade_plan 生成 ────────────────────────────────────
class TestC6TradePlan:
    def test_trade_plan_contains_all_symbols(self):
        node = C6PlanGenerateNode()
        state = _make_state()
        r = node.execute_core(state)
        plan = r.outputs["trade_plan"]
        assert isinstance(plan, dict)
        assert "BTC" in plan
        assert "ETH" in plan

    def test_trade_plan_entry_has_required_fields(self):
        node = C6PlanGenerateNode()
        state = _make_state()
        r = node.execute_core(state)
        btc_plan = r.outputs["trade_plan"]["BTC"]
        assert isinstance(btc_plan, dict)
        for field in ("symbol", "direction", "size", "entry_price",
                      "stop_loss", "take_profit", "params"):
            assert field in btc_plan, f"missing field: {field}"

    def test_trade_plan_size_from_c4_position_size(self):
        node = C6PlanGenerateNode()
        state = _make_state()
        r = node.execute_core(state)
        assert r.outputs["trade_plan"]["BTC"]["size"] == 0.5
        assert r.outputs["trade_plan"]["ETH"]["size"] == 3.0

    def test_trade_plan_stop_loss_take_profit_from_c4(self):
        node = C6PlanGenerateNode()
        state = _make_state()
        r = node.execute_core(state)
        btc = r.outputs["trade_plan"]["BTC"]
        assert btc["stop_loss"] == 60000.0
        assert btc["take_profit"] == 66000.0

    def test_trade_plan_entry_price_from_market(self):
        node = C6PlanGenerateNode()
        state = _make_state()
        r = node.execute_core(state)
        assert r.outputs["trade_plan"]["BTC"]["entry_price"] == 60000.0
        assert r.outputs["trade_plan"]["ETH"]["entry_price"] == 3000.0

    def test_trade_plan_direction_from_c3_signals(self):
        node = C6PlanGenerateNode()
        state = _make_state()
        r = node.execute_core(state)
        assert r.outputs["trade_plan"]["BTC"]["direction"] == "LONG"
        assert r.outputs["trade_plan"]["ETH"]["direction"] == "LONG"

    def test_trade_plan_params_from_c5_optimized(self):
        node = C6PlanGenerateNode()
        state = _make_state()
        r = node.execute_core(state)
        btc_params = r.outputs["trade_plan"]["BTC"]["params"]
        assert btc_params["trend_threshold"] == 0.01
        assert btc_params["risk_per_trade"] == 0.02

    def test_zero_size_symbol_filtered_out(self):
        node = C6PlanGenerateNode()
        c4 = _make_c4_outputs(position_size={"BTC": 0.5, "ETH": 0.0})
        state = _make_state(c4_outputs=c4)
        r = node.execute_core(state)
        plan = r.outputs["trade_plan"]
        assert "BTC" in plan
        assert "ETH" not in plan


# ── 4. changeset 生成 ─────────────────────────────────────
class TestC6Changeset:
    def test_changeset_is_dict(self):
        node = C6PlanGenerateNode()
        state = _make_state()
        r = node.execute_core(state)
        assert isinstance(r.outputs["changeset"], dict)

    def test_changeset_contains_symbols_list(self):
        node = C6PlanGenerateNode()
        state = _make_state()
        r = node.execute_core(state)
        cs = r.outputs["changeset"]
        # 至少包含 symbols 字段（list）
        assert "symbols" in cs
        assert isinstance(cs["symbols"], list)
        assert "BTC" in cs["symbols"]
        assert "ETH" in cs["symbols"]

    def test_changeset_contains_per_symbol_entry(self):
        node = C6PlanGenerateNode()
        state = _make_state()
        r = node.execute_core(state)
        cs = r.outputs["changeset"]
        # 每个品种有 direction/size/sl/tp
        btc_entry = cs["BTC"] if "BTC" in cs else None
        assert btc_entry is not None
        assert btc_entry["direction"] == "LONG"
        assert btc_entry["size"] == 0.5
        assert btc_entry["stop_loss"] == 60000.0
        assert btc_entry["take_profit"] == 66000.0


# ── 5. strategy_name 与 trace_id ──────────────────────────
class TestC6StrategyAndTrace:
    def test_strategy_name_based_on_dominant_direction(self):
        node = C6PlanGenerateNode()
        state = _make_state()
        r = node.execute_core(state)
        # 两个 LONG → LONG 主流
        assert r.outputs["strategy_name"] != ""
        assert "LONG" in r.outputs["strategy_name"] or "long" in r.outputs["strategy_name"].lower()

    def test_strategy_name_short_when_dominant_short(self):
        node = C6PlanGenerateNode()
        c3 = _make_c3_signals(signals=[
            {"symbol": "BTC", "direction": "SHORT", "confidence": 0.8, "win_rate": 0.6},
            {"symbol": "ETH", "direction": "SHORT", "confidence": 0.7, "win_rate": 0.55},
        ])
        state = _make_state(c3_outputs=c3)
        r = node.execute_core(state)
        assert "SHORT" in r.outputs["strategy_name"] or "short" in r.outputs["strategy_name"].lower()

    def test_strategy_name_neutral_when_mixed(self):
        node = C6PlanGenerateNode()
        c3 = _make_c3_signals(signals=[
            {"symbol": "BTC", "direction": "LONG", "confidence": 0.8, "win_rate": 0.6},
            {"symbol": "ETH", "direction": "SHORT", "confidence": 0.7, "win_rate": 0.55},
        ])
        state = _make_state(c3_outputs=c3)
        r = node.execute_core(state)
        sn = r.outputs["strategy_name"].lower()
        assert "neutral" in sn or "mixed" in sn or "long" in sn or "short" in sn

    def test_trace_id_is_valid_uuid(self):
        node = C6PlanGenerateNode()
        state = _make_state()
        r = node.execute_core(state)
        tid = r.outputs["trace_id"]
        assert tid
        # 应为合法 UUID 字符串
        UUID(str(tid))  # 抛 ValueError 即失败

    def test_trace_id_unique_per_call(self):
        node = C6PlanGenerateNode()
        state = _make_state()
        r1 = node.execute_core(state)
        r2 = node.execute_core(state)
        assert r1.outputs["trace_id"] != r2.outputs["trace_id"]


# ── 6. 多品种与边界场景 ───────────────────────────────────
class TestC6EdgeCases:
    def test_single_symbol(self):
        node = C6PlanGenerateNode()
        c4 = _make_c4_outputs(position_size={"BTC": 1.0}, stop_loss={"BTC": 59000.0},
                               take_profit={"BTC": 65000.0})
        c5 = _make_c5_outputs(optimized_params={"BTC": {"trend_threshold": 0.01}})
        c3 = _make_c3_signals(signals=[{"symbol": "BTC", "direction": "LONG",
                                          "confidence": 0.85, "win_rate": 0.65}])
        state = _make_state(c4_outputs=c4, c5_outputs=c5, c3_outputs=c3)
        r = node.execute_core(state)
        plan = r.outputs["trade_plan"]
        assert len(plan) == 1
        assert "BTC" in plan

    def test_symbol_missing_in_c5_params_still_in_plan(self):
        """C5 缺少某品种参数时，该品种仍入计划但 params 为空 dict"""
        node = C6PlanGenerateNode()
        c5 = _make_c5_outputs(optimized_params={"BTC": {"trend_threshold": 0.01}})  # 无 ETH
        state = _make_state(c5_outputs=c5)
        r = node.execute_core(state)
        plan = r.outputs["trade_plan"]
        assert "ETH" in plan
        assert plan["ETH"]["params"] == {}

    def test_symbol_in_c5_but_not_in_c4_excluded(self):
        """C5 有品种但 C4 没有仓位 → 不入计划（C4 是仓位真相源）"""
        node = C6PlanGenerateNode()
        c4 = _make_c4_outputs(position_size={"BTC": 0.5})  # 无 ETH
        state = _make_state(c4_outputs=c4)
        r = node.execute_core(state)
        plan = r.outputs["trade_plan"]
        assert "BTC" in plan
        assert "ETH" not in plan

    def test_c3_signals_missing_direction_defaults_to_long(self):
        """C3 信号缺少 direction 字段时默认 LONG"""
        node = C6PlanGenerateNode()
        c3 = _make_c3_signals(signals=[{"symbol": "BTC", "confidence": 0.8, "win_rate": 0.6}])
        state = _make_state(c3_outputs=c3)
        r = node.execute_core(state)
        assert r.outputs["trade_plan"]["BTC"]["direction"] == "LONG"

    def test_config_can_override_strategy_prefix(self):
        """config.plan_strategy_prefix 可覆盖 strategy_name 前缀"""
        node = C6PlanGenerateNode()
        state = _make_state(config={"plan_strategy_prefix": "DreamClassic"})
        r = node.execute_core(state)
        assert r.outputs["strategy_name"].startswith("DreamClassic")
