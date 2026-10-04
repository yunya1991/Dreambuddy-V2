#!/usr/bin/env python3
"""P1-1: macro-agent 测试 (RED→GREEN)
F5 节点: GDP/CPI/利率/流动性 → SubagentOutput
图表: bar(柱状) + line(趋势线)
"""
from __future__ import annotations
import os, sys, unittest

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


class TestImport(unittest.TestCase):
    def test_importable(self):
        from macro_agent import MacroAgent
        from subagent_types import SubagentOutput
        self.assertIsNotNone(MacroAgent)


class TestExecute(unittest.TestCase):
    def _node_output(self):
        return {
            "indicators": {
                "gdp_yoy": 2.5,
                "cpi_yoy": 3.1,
                "interest_rate": 5.25,
                "liquidity_m2": 1.2e9,
                "unemployment": 4.1,
            },
            "rationale": ["GDP 温和增长", "CPI 仍高于目标"],
            "direction": "NEUTRAL",
            "confidence": 0.55,
        }

    def test_returns_subagent_output(self):
        from macro_agent import MacroAgent
        from subagent_types import SubagentOutput
        agent = MacroAgent()
        out = agent.execute(self._node_output())
        self.assertIsInstance(out, SubagentOutput)

    def test_module_name(self):
        from macro_agent import MacroAgent
        agent = MacroAgent()
        out = agent.execute(self._node_output())
        self.assertEqual(out.module, "macro")

    def test_signals_extracted(self):
        from macro_agent import MacroAgent
        agent = MacroAgent()
        out = agent.execute(self._node_output())
        self.assertGreater(len(out.signals), 0)
        names = [s.name for s in out.signals]
        self.assertIn("GDP同比", names)

    def test_gdp_long_signal(self):
        from macro_agent import MacroAgent
        agent = MacroAgent()
        out = agent.execute(self._node_output())
        gdp_sigs = [s for s in out.signals if s.name == "GDP同比"]
        self.assertEqual(len(gdp_sigs), 1)
        self.assertEqual(gdp_sigs[0].direction, "long")  # 2.5 > 2.0 → long

    def test_cpi_signal(self):
        from macro_agent import MacroAgent
        agent = MacroAgent()
        out = agent.execute(self._node_output())
        cpi_sigs = [s for s in out.signals if s.name == "CPI同比"]
        self.assertEqual(len(cpi_sigs), 1)

    def test_signal_directions_valid(self):
        from macro_agent import MacroAgent
        agent = MacroAgent()
        out = agent.execute(self._node_output())
        for s in out.signals:
            self.assertIn(s.direction, ("long", "short", "neutral"))

    def test_summary_not_empty(self):
        from macro_agent import MacroAgent
        agent = MacroAgent()
        out = agent.execute(self._node_output())
        self.assertTrue(out.summary)

    def test_bar_chart(self):
        from macro_agent import MacroAgent
        agent = MacroAgent()
        out = agent.execute(self._node_output())
        bars = [c for c in out.charts if c.type == "bar"]
        self.assertEqual(len(bars), 1)

    def test_trend_line_chart(self):
        from macro_agent import MacroAgent
        agent = MacroAgent()
        out = agent.execute(self._node_output())
        lines = [c for c in out.charts if c.type == "line"]
        self.assertGreater(len(lines), 0)

    def test_llm_fn_injectable(self):
        from macro_agent import MacroAgent
        calls = []
        def mock_llm(prompt):
            calls.append(prompt)
            return "宏观LLM摘要"
        agent = MacroAgent(llm_fn=mock_llm)
        out = agent.execute(self._node_output())
        self.assertEqual(len(calls), 1)
        self.assertEqual(out.summary, "宏观LLM摘要")

    def test_llm_exception_fails_open(self):
        from macro_agent import MacroAgent
        def bad_llm(prompt):
            raise RuntimeError("LLM不可用")
        agent = MacroAgent(llm_fn=bad_llm)
        out = agent.execute(self._node_output())
        self.assertTrue(out.summary)

    def test_empty_input(self):
        from macro_agent import MacroAgent
        agent = MacroAgent()
        out = agent.execute({})
        self.assertEqual(out.module, "macro")

    def test_ipc_handler(self):
        from macro_agent import handle_macro_agent
        result = handle_macro_agent({"node_output": self._node_output()})
        self.assertTrue(result["ok"])

    def test_to_dict(self):
        from macro_agent import MacroAgent
        agent = MacroAgent()
        out = agent.execute(self._node_output())
        d = out.to_dict()
        self.assertIn("module", d)
        self.assertIn("signals", d)


if __name__ == "__main__":
    unittest.main()
