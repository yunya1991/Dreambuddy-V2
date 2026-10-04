#!/usr/bin/env python3
"""E2E 集成测试: C-Drive-Agent → subagent 路由 → 多 subagent 聚合

测试链路:
  1. C-Drive-Agent 低置信度 → SUPPLEMENT 决策 → 路由到 subagent module
  2. subagent module → 对应 Agent.execute() → SubagentOutput
  3. 多 subagent 输出聚合 → 统一摘要 + 信号合并 + 图表收集
  4. 高置信度场景 → 跳过四步循环 (HC-2)
  5. FAIL-OPEN: 无 llm_fn / 无 cognitive_adapter → 不阻塞
"""
from __future__ import annotations
import os, sys, unittest
from dataclasses import dataclass
from typing import Any, Dict, List

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from c_drive_agent import CDriveAgent, CDriveAction, CDriveDecision
from subagent_types import SubagentOutput, Signal, ChartSpec


# ============================================================
# 辅助: subagent 聚合器 (E2E 测试核心)
# ============================================================

def aggregate_subagent_outputs(outputs: List[SubagentOutput]) -> Dict[str, Any]:
    """聚合多个 subagent 输出为统一摘要

    用于 C-Drive-Agent SUPPLEMENT 后的多 subagent 结果合并
    """
    if not outputs:
        return {"summaries": [], "all_signals": [], "all_charts": [],
                "modules": [], "total_signals": 0,
                "consensus_direction": "neutral",
                "long_count": 0, "short_count": 0,
                "total_charts": 0}

    summaries = [o.summary for o in outputs]
    all_signals: List[Signal] = []
    all_charts: List[ChartSpec] = []
    modules = [o.module for o in outputs]

    for o in outputs:
        all_signals.extend(o.signals)
        all_charts.extend(o.charts)

    # 多数投票方向
    long_n = sum(1 for s in all_signals if s.direction == "long")
    short_n = sum(1 for s in all_signals if s.direction == "short")
    if long_n > short_n:
        consensus = "long"
    elif short_n > long_n:
        consensus = "short"
    else:
        consensus = "neutral"

    return {
        "summaries": summaries,
        "all_signals": [s.to_dict() for s in all_signals],
        "all_charts": [c.to_dict() for c in all_charts],
        "modules": modules,
        "total_signals": len(all_signals),
        "total_charts": len(all_charts),
        "consensus_direction": consensus,
        "long_count": long_n,
        "short_count": short_n,
    }


# ============================================================
# 辅助: 模拟节点结果
# ============================================================

@dataclass
class MockNodeResult:
    """模拟 DreamOS 节点执行结果"""
    confidence: float
    direction: str
    status: str = "SUCCESS"
    outputs: dict = None
    error: str = None

    def __post_init__(self):
        if self.outputs is None:
            self.outputs = {}


def make_signals(directions: List[str], conf: float = 0.6) -> List[Dict[str, Any]]:
    """生成模拟信号列表"""
    return [{"name": f"sig_{i}", "value": i, "direction": d, "confidence": conf}
            for i, d in enumerate(directions)]


# ============================================================
# 测试类
# ============================================================

class TestE2EHighConfidenceSkip(unittest.TestCase):
    """HC-2: 高置信度 > 0.75 → 跳过四步循环"""

    def test_high_confidence_skips_loop(self):
        agent = CDriveAgent()
        result = MockNodeResult(confidence=0.85, direction="LONG")
        decision = agent.run(node_id="C1", result=result, state=None)
        self.assertEqual(decision.action, CDriveAction.CONTINUE)
        self.assertEqual(decision.steps_executed, ["skip"])
        self.assertIn("跳过", decision.reason)


class TestE2ESupplementRouting(unittest.TestCase):
    """C-Drive-Agent SUPPLEMENT → subagent 路由"""

    def test_low_confidence_triggers_supplement(self):
        """置信度 < 0.50 + Bull/Bear 均弱 → SUPPLEMENT"""
        agent = CDriveAgent(llm_fn=None)  # 规则辩论
        result = MockNodeResult(confidence=0.35, direction="NEUTRAL")
        # 低置信度信号 → Bull/Bear avg=0.1 < 0.30 → SUPPLEMENT
        decision = agent.run(
            node_id="F5", result=result, state=None,
            signals=make_signals(["long", "short"], conf=0.1),
            intent_type="deep_analysis",
        )
        self.assertEqual(decision.action, CDriveAction.SUPPLEMENT)
        self.assertIsNotNone(decision.supplement_module)

    def test_supplement_routes_f5_to_macro(self):
        agent = CDriveAgent(llm_fn=None)
        result = MockNodeResult(confidence=0.35, direction="NEUTRAL")
        decision = agent.run(
            node_id="F5", result=result, state=None,
            signals=make_signals(["long", "short"], conf=0.1),
        )
        self.assertEqual(decision.supplement_module, "macro")

    def test_supplement_routes_f2_to_flow(self):
        agent = CDriveAgent(llm_fn=None)
        result = MockNodeResult(confidence=0.35, direction="NEUTRAL")
        decision = agent.run(
            node_id="F2", result=result, state=None,
            signals=make_signals(["long", "short"], conf=0.1),
        )
        self.assertEqual(decision.supplement_module, "flow")

    def test_supplement_routes_c1_to_technical(self):
        agent = CDriveAgent(llm_fn=None)
        result = MockNodeResult(confidence=0.35, direction="NEUTRAL")
        decision = agent.run(
            node_id="C1", result=result, state=None,
            signals=make_signals(["long", "short"], conf=0.1),
        )
        self.assertEqual(decision.supplement_module, "technical")

    def test_supplement_routes_f4_to_onchain(self):
        agent = CDriveAgent(llm_fn=None)
        result = MockNodeResult(confidence=0.35, direction="NEUTRAL")
        decision = agent.run(
            node_id="F4", result=result, state=None,
            signals=make_signals(["long", "short"], conf=0.1),
        )
        self.assertEqual(decision.supplement_module, "onchain")

    def test_supplement_routes_f3_to_valuation(self):
        agent = CDriveAgent(llm_fn=None)
        result = MockNodeResult(confidence=0.35, direction="NEUTRAL")
        decision = agent.run(
            node_id="F3", result=result, state=None,
            signals=make_signals(["long", "short"], conf=0.1),
        )
        self.assertEqual(decision.supplement_module, "valuation")


class TestE2ESubagentExecution(unittest.TestCase):
    """SUPPLEMENT 路由后 → subagent execute() → SubagentOutput"""

    def _macro_node_output(self):
        return {
            "indicators": {"gdp_yoy": 2.5, "cpi_yoy": 3.1,
                           "interest_rate": 5.25, "liquidity_m2": 1.2e9},
            "rationale": ["GDP 温和增长"],
            "direction": "NEUTRAL", "confidence": 0.55,
        }

    def test_macro_agent_execute(self):
        from macro_agent import MacroAgent
        agent = MacroAgent()
        out = agent.execute(self._macro_node_output())
        self.assertEqual(out.module, "macro")
        self.assertGreater(len(out.signals), 0)

    def test_flow_agent_execute(self):
        from flow_agent import FlowAgent
        agent = FlowAgent()
        out = agent.execute({
            "indicators": {"etf_inflow": 150, "leverage_ratio": 2.8,
                           "stablecoin_mcap": 120e9, "fund_flow": 80},
            "direction": "LONG", "confidence": 0.65,
        })
        self.assertEqual(out.module, "flow")
        self.assertGreater(len(out.signals), 0)

    def test_onchain_agent_execute(self):
        from onchain_agent import OnchainAgent
        agent = OnchainAgent()
        out = agent.execute({
            "indicators": {"active_addresses": 1.1e6, "hashrate": 650e12,
                           "mvrv": 1.8, "exchange_inflow": 1200, "nupl": 0.35},
            "direction": "LONG", "confidence": 0.6,
        })
        self.assertEqual(out.module, "onchain")
        self.assertGreater(len(out.signals), 0)

    def test_valuation_agent_execute(self):
        from valuation_agent import ValuationAgent
        agent = ValuationAgent()
        out = agent.execute({
            "indicators": {"nvt": 45, "stock_to_flow": 59,
                           "market_cap_dominance": 52, "price": 95000},
            "direction": "NEUTRAL", "confidence": 0.5,
        })
        self.assertEqual(out.module, "valuation")
        self.assertGreater(len(out.signals), 0)

    def test_risk_agent_execute(self):
        from risk_agent import RiskAgent
        agent = RiskAgent()
        out = agent.execute({
            "indicators": {"var_95": 0.035, "var_99": 0.058,
                           "correlation_btc": 0.85, "stress_loss": 0.12},
            "direction": "NEUTRAL", "confidence": 0.6,
        })
        self.assertEqual(out.module, "risk")
        self.assertGreater(len(out.signals), 0)

    def test_portfolio_agent_execute(self):
        from portfolio_agent import PortfolioAgent
        agent = PortfolioAgent()
        out = agent.execute({
            "indicators": {
                "positions": [{"symbol": "BTC", "weight": 0.45, "pnl_pct": 0.08}],
                "drift": 0.05, "rebalance_needed": True, "total_weight": 1.0,
            },
            "direction": "NEUTRAL", "confidence": 0.55,
        })
        self.assertEqual(out.module, "portfolio")
        self.assertGreater(len(out.signals), 0)


class TestE2EAggregation(unittest.TestCase):
    """多 subagent 输出聚合"""

    def test_aggregate_empty(self):
        result = aggregate_subagent_outputs([])
        self.assertEqual(result["total_signals"], 0)
        self.assertEqual(result["consensus_direction"], "neutral")

    def test_aggregate_single(self):
        from macro_agent import MacroAgent
        out = MacroAgent().execute({
            "indicators": {"gdp_yoy": 2.5, "cpi_yoy": 3.1},
        })
        result = aggregate_subagent_outputs([out])
        self.assertEqual(len(result["modules"]), 1)
        self.assertEqual(result["modules"][0], "macro")

    def test_aggregate_multi_module(self):
        from macro_agent import MacroAgent
        from flow_agent import FlowAgent
        from onchain_agent import OnchainAgent

        macro_out = MacroAgent().execute({
            "indicators": {"gdp_yoy": 2.5, "cpi_yoy": 3.1}})
        flow_out = FlowAgent().execute({
            "indicators": {"etf_inflow": 150, "leverage_ratio": 2.8}})
        onchain_out = OnchainAgent().execute({
            "indicators": {"mvrv": 1.8, "active_addresses": 1.1e6}})

        result = aggregate_subagent_outputs([macro_out, flow_out, onchain_out])
        self.assertEqual(len(result["modules"]), 3)
        self.assertIn("macro", result["modules"])
        self.assertIn("flow", result["modules"])
        self.assertIn("onchain", result["modules"])
        self.assertGreater(result["total_signals"], 3)

    def test_aggregate_consensus_direction(self):
        """多数投票方向"""
        from macro_agent import MacroAgent
        # GDP > 2.0 → long, CPI > 1 < 5 → neutral → 多 long 信号
        out = MacroAgent().execute({
            "indicators": {"gdp_yoy": 3.0, "cpi_yoy": 2.0,
                           "interest_rate": 0.5, "liquidity_m2": 1e9}})
        result = aggregate_subagent_outputs([out])
        # 至少有 long 信号
        self.assertGreater(result["long_count"], 0)

    def test_aggregate_charts_collected(self):
        from macro_agent import MacroAgent
        from valuation_agent import ValuationAgent

        macro_out = MacroAgent().execute({
            "indicators": {"gdp_yoy": 2.5, "cpi_yoy": 3.1}})
        val_out = ValuationAgent().execute({
            "indicators": {"nvt": 45, "stock_to_flow": 59,
                           "market_cap_dominance": 52, "price": 95000}})

        result = aggregate_subagent_outputs([macro_out, val_out])
        self.assertGreater(result["total_charts"], 0)


class TestE2EFullPipeline(unittest.TestCase):
    """完整管道: C-Drive-Agent 决策 → subagent 路由 → execute → 聚合"""

    def test_full_pipeline_supplement_to_aggregation(self):
        """端到端: 低置信度 → SUPPLEMENT → macro-agent → 聚合"""
        # Step 1: C-Drive-Agent 决策
        agent = CDriveAgent(llm_fn=None)
        result = MockNodeResult(confidence=0.35, direction="NEUTRAL")
        decision = agent.run(
            node_id="F5", result=result, state=None,
            signals=make_signals(["long", "short"], conf=0.1),
            intent_type="deep_analysis",
        )
        self.assertEqual(decision.action, CDriveAction.SUPPLEMENT)
        self.assertEqual(decision.supplement_module, "macro")

        # Step 2: 根据 supplement_module 路由到 subagent
        from macro_agent import MacroAgent
        subagent = MacroAgent()
        node_output = {
            "indicators": {"gdp_yoy": 2.5, "cpi_yoy": 3.1,
                           "interest_rate": 5.25, "liquidity_m2": 1.2e9},
            "rationale": ["GDP 温和增长"],
            "direction": "NEUTRAL", "confidence": 0.55,
        }
        sub_output = subagent.execute(node_output)
        self.assertEqual(sub_output.module, "macro")

        # Step 3: 聚合
        agg = aggregate_subagent_outputs([sub_output])
        self.assertGreater(agg["total_signals"], 0)
        self.assertIn("macro", agg["modules"])

    def test_full_pipeline_multi_node_aggregation(self):
        """多节点低置信度 → 多 subagent → 聚合"""
        agent = CDriveAgent(llm_fn=None)

        # 模拟 3 个节点低置信度结果
        node_specs = [
            ("F5", "macro", "macro_agent", "MacroAgent",
             {"indicators": {"gdp_yoy": 2.5, "cpi_yoy": 3.1,
                             "interest_rate": 5.25}}),
            ("F2", "flow", "flow_agent", "FlowAgent",
             {"indicators": {"etf_inflow": 150, "leverage_ratio": 2.8,
                             "stablecoin_mcap": 120e9, "fund_flow": 80}}),
            ("F4", "onchain", "onchain_agent", "OnchainAgent",
             {"indicators": {"active_addresses": 1.1e6, "hashrate": 650e12,
                             "mvrv": 1.8, "exchange_inflow": 1200}}),
        ]

        outputs = []
        for node_id, expected_mod, import_mod, class_name, node_output in node_specs:
            result = MockNodeResult(confidence=0.35, direction="NEUTRAL")
            decision = agent.run(
                node_id=node_id, result=result, state=None,
                signals=make_signals(["long", "short"], conf=0.1),
            )
            self.assertEqual(decision.action, CDriveAction.SUPPLEMENT)
            self.assertEqual(decision.supplement_module, expected_mod)

            # 动态导入 subagent
            module = __import__(import_mod)
            agent_class = getattr(module, class_name)
            sub_out = agent_class().execute(node_output)
            self.assertEqual(sub_out.module, expected_mod)
            outputs.append(sub_out)

        # 聚合
        agg = aggregate_subagent_outputs(outputs)
        self.assertEqual(len(agg["modules"]), 3)
        self.assertGreater(agg["total_signals"], 5)
        self.assertGreater(agg["total_charts"], 2)

    def test_pipeline_high_confidence_no_supplement(self):
        """高置信度 → CONTINUE → 无 subagent 调用"""
        agent = CDriveAgent(llm_fn=None)
        result = MockNodeResult(confidence=0.90, direction="LONG")
        decision = agent.run(node_id="F5", result=result, state=None)
        self.assertEqual(decision.action, CDriveAction.CONTINUE)
        self.assertIsNone(decision.supplement_module)


class TestE2EFailOpen(unittest.TestCase):
    """FAIL-OPEN: 无依赖 → 不阻塞"""

    def test_no_cognitive_adapter(self):
        """无 cognitive_adapter → recall 跳过, 不阻塞"""
        agent = CDriveAgent(llm_fn=None)  # 无 cognitive_adapter
        result = MockNodeResult(confidence=0.40, direction="NEUTRAL")
        decision = agent.run(
            node_id="F5", result=result, state=None,
            signals=make_signals(["long", "short"], conf=0.1),
        )
        # 应正常返回决策, 不抛异常
        self.assertIsInstance(decision, CDriveDecision)

    def test_no_llm_fn_rule_debate(self):
        """无 llm_fn → 规则辩论降级"""
        agent = CDriveAgent(llm_fn=None)
        result = MockNodeResult(confidence=0.40, direction="NEUTRAL")
        decision = agent.run(
            node_id="F5", result=result, state=None,
            signals=make_signals(["long", "short"]),
        )
        # 规则辩论应产生 bull/bear argument
        self.assertIsNotNone(decision.bull_argument)
        self.assertIsNotNone(decision.bear_argument)

    def test_no_jev_fn_skip_jeval(self):
        """无 jev_judge_fn → jeval 跳过, 不阻塞"""
        agent = CDriveAgent(llm_fn=None, jev_judge_fn=None)
        result = MockNodeResult(confidence=0.40, direction="NEUTRAL")
        decision = agent.run(
            node_id="F5", result=result, state=None,
            signals=make_signals(["long", "short"], conf=0.1),
        )
        # jeval_noul 应为 None
        self.assertIsNone(decision.jeval_noul)


class TestE2EIPCIntegration(unittest.TestCase):
    """IPC handler 端到端"""

    def test_c_drive_agent_ipc(self):
        from c_drive_agent import handle_c_drive_agent
        result = handle_c_drive_agent({
            "node_id": "F5",
            "confidence": 0.35,
            "direction": "NEUTRAL",
            "signals": make_signals(["long", "short"], conf=0.1),
            "intent_type": "deep_analysis",
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["decision"]["action"], "supplement")

    def test_macro_agent_ipc(self):
        from macro_agent import handle_macro_agent
        result = handle_macro_agent({"node_output": {
            "indicators": {"gdp_yoy": 2.5, "cpi_yoy": 3.1}}})
        self.assertTrue(result["ok"])
        self.assertEqual(result["output"]["module"], "macro")

    def test_full_ipc_pipeline(self):
        """IPC 全链路: C-Drive-Agent → subagent → 聚合"""
        from c_drive_agent import handle_c_drive_agent
        from macro_agent import handle_macro_agent

        # Step 1: C-Drive-Agent IPC
        cd_result = handle_c_drive_agent({
            "node_id": "F5", "confidence": 0.35,
            "direction": "NEUTRAL",
            "signals": make_signals(["long", "short"], conf=0.1),
        })
        self.assertTrue(cd_result["ok"])
        module = cd_result["decision"]["supplement_module"]
        self.assertEqual(module, "macro")

        # Step 2: Subagent IPC
        sub_result = handle_macro_agent({"node_output": {
            "indicators": {"gdp_yoy": 2.5, "cpi_yoy": 3.1}}})
        self.assertTrue(sub_result["ok"])

        # Step 3: 聚合
        sub_output = SubagentOutput(
            module=sub_result["output"]["module"],
            summary=sub_result["output"]["summary"],
            signals=[Signal(**s) for s in sub_result["output"]["signals"]],
            charts=[ChartSpec(**c) for c in sub_result["output"]["charts"]],
        )
        agg = aggregate_subagent_outputs([sub_output])
        self.assertGreater(agg["total_signals"], 0)


if __name__ == "__main__":
    unittest.main()
