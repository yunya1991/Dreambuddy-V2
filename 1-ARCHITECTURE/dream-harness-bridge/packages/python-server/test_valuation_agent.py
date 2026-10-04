#!/usr/bin/env python3
"""P1-4: valuation-agent 测试 (RED→GREEN)
F3 节点: NVT/StockFlow → SubagentOutput
图表: scatter(散点) + line(回归线)
"""
from __future__ import annotations
import os, sys, unittest

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


class TestImport(unittest.TestCase):
    def test_importable(self):
        from valuation_agent import ValuationAgent
        from subagent_types import SubagentOutput
        self.assertIsNotNone(ValuationAgent)


class TestExecute(unittest.TestCase):
    def _node_output(self):
        return {
            "indicators": {
                "nvt": 45.0,
                "stock_to_flow": 59.0,
                "market_cap_dominance": 52.0,
                "pi_cycle_top": 120000.0,
                "pi_cycle_bottom": 30000.0,
                "price": 95000.0,
            },
            "rationale": ["NVT 偏高", "StockFlow 接近历史均值"],
            "direction": "NEUTRAL",
            "confidence": 0.5,
        }

    def test_returns_subagent_output(self):
        from valuation_agent import ValuationAgent
        from subagent_types import SubagentOutput
        agent = ValuationAgent()
        out = agent.execute(self._node_output())
        self.assertIsInstance(out, SubagentOutput)

    def test_module_name(self):
        from valuation_agent import ValuationAgent
        agent = ValuationAgent()
        out = agent.execute(self._node_output())
        self.assertEqual(out.module, "valuation")

    def test_signals_extracted(self):
        from valuation_agent import ValuationAgent
        agent = ValuationAgent()
        out = agent.execute(self._node_output())
        self.assertGreater(len(out.signals), 0)
        names = [s.name for s in out.signals]
        self.assertIn("NVT", names)

    def test_nvt_signal(self):
        from valuation_agent import ValuationAgent
        agent = ValuationAgent()
        out = agent.execute(self._node_output())
        nvt_sigs = [s for s in out.signals if s.name == "NVT"]
        self.assertEqual(len(nvt_sigs), 1)
        # NVT 45 > 30 → short (估值偏高)
        self.assertEqual(nvt_sigs[0].direction, "short")

    def test_stock_to_flow_signal(self):
        from valuation_agent import ValuationAgent
        agent = ValuationAgent()
        out = agent.execute(self._node_output())
        stf_sigs = [s for s in out.signals if s.name == "StockFlow"]
        self.assertEqual(len(stf_sigs), 1)

    def test_signal_directions_valid(self):
        from valuation_agent import ValuationAgent
        agent = ValuationAgent()
        out = agent.execute(self._node_output())
        for s in out.signals:
            self.assertIn(s.direction, ("long", "short", "neutral"))

    def test_summary_not_empty(self):
        from valuation_agent import ValuationAgent
        agent = ValuationAgent()
        out = agent.execute(self._node_output())
        self.assertTrue(out.summary)

    def test_scatter_chart(self):
        from valuation_agent import ValuationAgent
        agent = ValuationAgent()
        out = agent.execute(self._node_output())
        scatters = [c for c in out.charts if c.type == "scatter"]
        self.assertEqual(len(scatters), 1)

    def test_regression_line_chart(self):
        from valuation_agent import ValuationAgent
        agent = ValuationAgent()
        out = agent.execute(self._node_output())
        lines = [c for c in out.charts if c.type == "line"]
        self.assertGreater(len(lines), 0)

    def test_llm_fn_injectable(self):
        from valuation_agent import ValuationAgent
        calls = []
        def mock_llm(prompt):
            calls.append(prompt)
            return "估值LLM摘要"
        agent = ValuationAgent(llm_fn=mock_llm)
        out = agent.execute(self._node_output())
        self.assertEqual(len(calls), 1)
        self.assertEqual(out.summary, "估值LLM摘要")

    def test_llm_exception_fails_open(self):
        from valuation_agent import ValuationAgent
        def bad_llm(prompt):
            raise RuntimeError("LLM不可用")
        agent = ValuationAgent(llm_fn=bad_llm)
        out = agent.execute(self._node_output())
        self.assertTrue(out.summary)

    def test_empty_input(self):
        from valuation_agent import ValuationAgent
        agent = ValuationAgent()
        out = agent.execute({})
        self.assertEqual(out.module, "valuation")

    def test_ipc_handler(self):
        from valuation_agent import handle_valuation_agent
        result = handle_valuation_agent({"node_output": self._node_output()})
        self.assertTrue(result["ok"])

    def test_to_dict(self):
        from valuation_agent import ValuationAgent
        agent = ValuationAgent()
        out = agent.execute(self._node_output())
        d = out.to_dict()
        self.assertIn("module", d)
        self.assertIn("signals", d)


if __name__ == "__main__":
    unittest.main()
