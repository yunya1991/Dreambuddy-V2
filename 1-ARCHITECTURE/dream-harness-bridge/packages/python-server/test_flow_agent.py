#!/usr/bin/env python3
"""P1-2: flow-agent 测试 (RED→GREEN)
F2 节点: ETF流入/杠杆/稳定币 → SubagentOutput
图表: sankey(资金流向) + bar(柱状)
"""
from __future__ import annotations
import os, sys, unittest

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


class TestImport(unittest.TestCase):
    def test_importable(self):
        from flow_agent import FlowAgent
        from subagent_types import SubagentOutput
        self.assertIsNotNone(FlowAgent)


class TestExecute(unittest.TestCase):
    def _node_output(self):
        return {
            "indicators": {
                "etf_inflow": 150.5,  # M USD
                "leverage_ratio": 2.8,
                "stablecoin_mcap": 120e9,
                "fund_flow": 80.0,  # M USD 净流入
            },
            "rationale": ["ETF 持续流入", "杠杆温和"],
            "direction": "LONG",
            "confidence": 0.65,
        }

    def test_returns_subagent_output(self):
        from flow_agent import FlowAgent
        from subagent_types import SubagentOutput
        agent = FlowAgent()
        out = agent.execute(self._node_output())
        self.assertIsInstance(out, SubagentOutput)

    def test_module_name(self):
        from flow_agent import FlowAgent
        agent = FlowAgent()
        out = agent.execute(self._node_output())
        self.assertEqual(out.module, "flow")

    def test_signals_extracted(self):
        from flow_agent import FlowAgent
        agent = FlowAgent()
        out = agent.execute(self._node_output())
        self.assertGreater(len(out.signals), 0)
        names = [s.name for s in out.signals]
        self.assertIn("ETF流入", names)

    def test_etf_long_signal(self):
        from flow_agent import FlowAgent
        agent = FlowAgent()
        out = agent.execute(self._node_output())
        etf_sigs = [s for s in out.signals if s.name == "ETF流入"]
        self.assertEqual(len(etf_sigs), 1)
        self.assertEqual(etf_sigs[0].direction, "long")  # 150.5 > 0 → long

    def test_leverage_signal(self):
        from flow_agent import FlowAgent
        agent = FlowAgent()
        out = agent.execute(self._node_output())
        lev_sigs = [s for s in out.signals if s.name == "杠杆倍数"]
        self.assertEqual(len(lev_sigs), 1)

    def test_signal_directions_valid(self):
        from flow_agent import FlowAgent
        agent = FlowAgent()
        out = agent.execute(self._node_output())
        for s in out.signals:
            self.assertIn(s.direction, ("long", "short", "neutral"))

    def test_summary_not_empty(self):
        from flow_agent import FlowAgent
        agent = FlowAgent()
        out = agent.execute(self._node_output())
        self.assertTrue(out.summary)

    def test_sankey_chart(self):
        from flow_agent import FlowAgent
        agent = FlowAgent()
        out = agent.execute(self._node_output())
        sankeys = [c for c in out.charts if c.type == "sankey"]
        self.assertEqual(len(sankeys), 1)

    def test_bar_chart(self):
        from flow_agent import FlowAgent
        agent = FlowAgent()
        out = agent.execute(self._node_output())
        bars = [c for c in out.charts if c.type == "bar"]
        self.assertGreater(len(bars), 0)

    def test_llm_fn_injectable(self):
        from flow_agent import FlowAgent
        calls = []
        def mock_llm(prompt):
            calls.append(prompt)
            return "资金流LLM摘要"
        agent = FlowAgent(llm_fn=mock_llm)
        out = agent.execute(self._node_output())
        self.assertEqual(len(calls), 1)
        self.assertEqual(out.summary, "资金流LLM摘要")

    def test_llm_exception_fails_open(self):
        from flow_agent import FlowAgent
        def bad_llm(prompt):
            raise RuntimeError("LLM不可用")
        agent = FlowAgent(llm_fn=bad_llm)
        out = agent.execute(self._node_output())
        self.assertTrue(out.summary)

    def test_empty_input(self):
        from flow_agent import FlowAgent
        agent = FlowAgent()
        out = agent.execute({})
        self.assertEqual(out.module, "flow")

    def test_ipc_handler(self):
        from flow_agent import handle_flow_agent
        result = handle_flow_agent({"node_output": self._node_output()})
        self.assertTrue(result["ok"])

    def test_to_dict(self):
        from flow_agent import FlowAgent
        agent = FlowAgent()
        out = agent.execute(self._node_output())
        d = out.to_dict()
        self.assertIn("module", d)
        self.assertIn("signals", d)


if __name__ == "__main__":
    unittest.main()
