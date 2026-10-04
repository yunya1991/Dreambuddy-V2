"""C0-C8 串行流水线 — 真实业务逻辑端到端测试

构造完整 market+config，9 节点串行执行，验证：
1. 每个节点输出非空且契约正确
2. 数据在节点间正确传递（C0→C1→...→C8）
3. 最终 C8 产出 pnl_attribution + lessons + memory_feedback
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from dreamos.capabilities.trading.nodes.c0_env_scan import C0EnvScanNode
from dreamos.capabilities.trading.nodes.c1_symbol_filter import C1SymbolFilterNode
from dreamos.capabilities.trading.nodes.c2_signal_detect import C2SignalDetectNode
from dreamos.capabilities.trading.nodes.c3_backtest_verify import C3BacktestVerifyNode
from dreamos.capabilities.trading.nodes.c4_risk_assess import C4RiskAssessNode
from dreamos.capabilities.trading.nodes.c5_param_optimize import C5ParamOptimizeNode
from dreamos.capabilities.trading.nodes.c6_plan_generate import C6PlanGenerateNode
from dreamos.capabilities.trading.nodes.c7_exec_monitor import C7ExecMonitorNode
from dreamos.capabilities.trading.nodes.c8_perf_attribution import C8PerfAttributionNode
from dreamos.shared.state import State, NodeResult, NodeStatus


def _make_market() -> Dict[str, Any]:
    """构造完整 market dict 覆盖 C0-C8 所有输入需求"""
    coins = ["BTC", "ETH", "SOL", "BNB"]
    prices = {"BTC": 60000.0, "ETH": 3000.0, "SOL": 150.0, "BNB": 500.0}
    return {
        # C0 环境扫描
        "btc_trend": 0.05,
        "btc_volatility": 0.08,
        "eth_trend": 0.03,
        "eth_volatility": 0.06,
        # C1 品种筛选
        "universe": [{"name": c, "szDecimals": 3} for c in coins],
        "mids": prices,
        "stats": {
            c: {
                "median_turnover": 1000000.0,
                "gap_rate": 0.01,
                "jump_rate": 0.02,
                "age_days": 365.0,
            }
            for c in coins
        },
        # C2/C4/C7 市场数据
        "market_data": {
            "BTC": {"price": 60000.0, "trend": 0.05, "rsi": 62.0, "momentum": 0.03},
            "ETH": {"price": 3000.0, "trend": 0.03, "rsi": 58.0, "momentum": 0.02},
            "SOL": {"price": 150.0, "trend": 0.08, "rsi": 65.0, "momentum": 0.04},
            "BNB": {"price": 500.0, "trend": -0.02, "rsi": 45.0, "momentum": -0.01},
        },
        # C4 组合状态
        "portfolio_state": {
            "capital": 100000.0,
            "existing_positions": {},
        },
    }


def _make_config() -> Dict[str, Any]:
    """构造 config，含 C8 closed_trades"""
    return {
        # C8 已平仓交易（模拟 C7 执行后的结果）
        "closed_trades": [
            {"symbol": "BTC", "direction": "LONG", "entry_price": 60000.0,
             "exit_price": 65000.0, "size": 0.5, "pnl": 2500.0},
            {"symbol": "ETH", "direction": "LONG", "entry_price": 3000.0,
             "exit_price": 3300.0, "size": 3.0, "pnl": 900.0},
        ],
    }


def _run_pipeline(state: State) -> list:
    """串行执行 C0→C8"""
    nodes = [
        C0EnvScanNode(), C1SymbolFilterNode(), C2SignalDetectNode(),
        C3BacktestVerifyNode(), C4RiskAssessNode(), C5ParamOptimizeNode(),
        C6PlanGenerateNode(), C7ExecMonitorNode(), C8PerfAttributionNode(),
    ]
    results = []
    for node in nodes:
        result = node.execute(state)
        state.update(node.node_id, result)
        results.append(result)
    return results


class TestClassicPipelineRealE2E:
    """9 节点串行真实业务逻辑 E2E"""

    def setup_method(self):
        self.state = State()
        self.state.market = _make_market()
        self.state.config = _make_config()
        self.results = _run_pipeline(self.state)

    # ── 整体流程 ──────────────────────────────────────────
    def test_all_nine_nodes_executed(self):
        assert len(self.results) == 9

    def test_all_nodes_success(self):
        for r in self.results:
            assert r.status == NodeStatus.SUCCESS, f"{r.node_id} 非 SUCCESS: {r.status}"

    def test_state_contains_nine_results(self):
        assert len(self.state.results) == 9

    def test_trace_has_nine_steps(self):
        assert len(self.state.trace) == 9

    # ── C0 环境扫描 ────────────────────────────────────────
    def test_c0_outputs_env_state_regime(self):
        c0 = self.state.get_result("C0").outputs
        assert c0.get("env_state")
        assert c0.get("regime") in ("bull", "bear", "range")
        assert "macro_flags" in c0

    # ── C1 品种筛选 ────────────────────────────────────────
    def test_c1_outputs_candidates_non_empty(self):
        c1 = self.state.get_result("C1").outputs
        assert isinstance(c1.get("candidates"), list)
        assert len(c1["candidates"]) > 0
        assert c1.get("symbols_total", 0) > 0

    def test_c1_candidates_subset_of_universe(self):
        c1 = self.state.get_result("C1").outputs
        universe_names = {c["name"] for c in self.state.market["universe"]}
        for sym in c1["candidates"]:
            assert sym in universe_names

    # ── C2 信号识别 ────────────────────────────────────────
    def test_c2_outputs_signals(self):
        c2 = self.state.get_result("C2").outputs
        assert isinstance(c2.get("signals"), list)
        assert c2.get("signal_count", 0) >= 0
        assert c2.get("dominant_direction") in ("LONG", "SHORT", "NEUTRAL", "")

    def test_c2_signals_have_symbol_and_direction(self):
        c2 = self.state.get_result("C2").outputs
        for sig in c2.get("signals", []):
            assert "symbol" in sig
            assert "direction" in sig

    # ── C3 回测验证 ────────────────────────────────────────
    def test_c3_outputs_verified_signals(self):
        c3 = self.state.get_result("C3").outputs
        assert isinstance(c3.get("verified_signals"), list)
        assert "win_rate" in c3
        assert "sharpe" in c3
        assert "max_dd" in c3

    # ── C4 风险评估 ────────────────────────────────────────
    def test_c4_outputs_position_and_sl_tp(self):
        c4 = self.state.get_result("C4").outputs
        assert isinstance(c4.get("position_size"), dict)
        assert isinstance(c4.get("stop_loss"), dict)
        assert isinstance(c4.get("take_profit"), dict)
        assert "risk_budget" in c4

    # ── C5 参数优化 ────────────────────────────────────────
    def test_c5_outputs_optimized_params(self):
        c5 = self.state.get_result("C5").outputs
        assert isinstance(c5.get("optimized_params"), dict)
        assert "improvement_pct" in c5
        assert isinstance(c5.get("optimization_log"), list)

    # ── C6 计划生成 ────────────────────────────────────────
    def test_c6_outputs_trade_plan_and_changeset(self):
        c6 = self.state.get_result("C6").outputs
        assert isinstance(c6.get("trade_plan"), dict)
        assert isinstance(c6.get("changeset"), dict)
        assert c6.get("strategy_name")
        assert c6.get("trace_id")

    def test_c6_trade_plan_entries_have_full_fields(self):
        c6 = self.state.get_result("C6").outputs
        for sym, plan in c6["trade_plan"].items():
            assert "direction" in plan
            assert "size" in plan
            assert "stop_loss" in plan
            assert "take_profit" in plan

    # ── C7 执行监控 ────────────────────────────────────────
    def test_c7_outputs_exec_status_and_orders(self):
        c7 = self.state.get_result("C7").outputs
        assert c7.get("exec_status") in ("filled", "partial_filled", "pending", "canceled")
        assert isinstance(c7.get("filled_orders"), list)
        assert isinstance(c7.get("alerts"), list)

    def test_c7_trace_id_propagated_from_c6(self):
        c6 = self.state.get_result("C6").outputs
        c7 = self.state.get_result("C7").outputs
        assert c7["exec_log"]["trace_id"] == c6["trace_id"]

    # ── C8 绩效归因 ────────────────────────────────────────
    def test_c8_outputs_pnl_attribution(self):
        c8 = self.state.get_result("C8").outputs
        attr = c8.get("pnl_attribution", {})
        assert "total_pnl" in attr
        assert "by_symbol" in attr
        assert "by_direction" in attr
        assert attr.get("trade_count") == 2

    def test_c8_pnl_attribution_total_matches(self):
        c8 = self.state.get_result("C8").outputs
        attr = c8["pnl_attribution"]
        # closed_trades: BTC +2500, ETH +900 → total 3400
        assert attr["total_pnl"] == pytest.approx(3400.0)

    def test_c8_lessons_non_empty(self):
        c8 = self.state.get_result("C8").outputs
        assert len(c8.get("lessons", [])) > 0

    def test_c8_memory_feedback_has_trace_id(self):
        c8 = self.state.get_result("C8").outputs
        fb = c8.get("memory_feedback", {})
        c6_trace = self.state.get_result("C6").outputs["trace_id"]
        assert fb.get("trace_id") == c6_trace

    # ── 数据传递链路 ────────────────────────────────────────
    def test_data_flows_c1_to_c2(self):
        """C1 candidates 被 C2 消费"""
        c1 = self.state.get_result("C1").outputs
        c2 = self.state.get_result("C2").outputs
        # C2 的信号应来自 C1 的 candidates
        c2_symbols = {s["symbol"] for s in c2.get("signals", [])}
        if c2_symbols:  # 有信号时
            assert c2_symbols.issubset(set(c1["candidates"]))

    def test_data_flows_c4_c5_to_c6(self):
        """C4 position_size + C5 optimized_params 被 C6 聚合"""
        c4 = self.state.get_result("C4").outputs
        c6 = self.state.get_result("C6").outputs
        # C6 trade_plan 的品种应来自 C4 position_size 的品种
        c4_symbols = set(c4["position_size"].keys())
        c6_symbols = set(c6["trade_plan"].keys())
        assert c6_symbols.issubset(c4_symbols)

    def test_data_flows_c6_to_c7(self):
        """C6 trade_plan 被 C7 执行"""
        c6 = self.state.get_result("C6").outputs
        c7 = self.state.get_result("C7").outputs
        # C7 filled_orders 应来自 C6 trade_plan
        c6_symbols = set(c6["trade_plan"].keys())
        c7_filled_symbols = {o["symbol"] for o in c7.get("filled_orders", [])}
        assert c7_filled_symbols.issubset(c6_symbols)

    def test_data_flows_c7_to_c8(self):
        """C7 trace_id 被 C8 引用"""
        c7 = self.state.get_result("C7").outputs
        c8 = self.state.get_result("C8").outputs
        assert c8["memory_feedback"]["trace_id"] == c7["exec_log"]["trace_id"]
