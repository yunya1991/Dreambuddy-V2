#!/usr/bin/env python3
"""P2-1: risk-agent 测试 (RED→GREEN)
新建域: VaR/相关性/压力测试 → SubagentOutput
图表: heatmap(热力图) + bar(矩阵柱状)
"""
from __future__ import annotations
import os, sys, unittest

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


class TestImport(unittest.TestCase):
    def test_importable(self):
        from risk_agent import RiskAgent
        from subagent_types import SubagentOutput
        self.assertIsNotNone(RiskAgent)


class TestExecute(unittest.TestCase):
    def _node_output(self):
        return {
            "indicators": {
                "var_95": 0.035,  # 95% VaR
                "var_99": 0.058,
                "correlation_btc": 0.85,
                "correlation_eth": 0.72,
                "stress_loss": 0.12,
                "max_drawdown": 0.08,
                "sharpe": 1.2,
            },
            "rationale": ["VaR 在安全范围", "BTC 相关性高"],
            "direction": "NEUTRAL",
            "confidence": 0.6,
        }

    def test_returns_subagent_output(self):
        from risk_agent import RiskAgent
        from subagent_types import SubagentOutput
        agent = RiskAgent()
        out = agent.execute(self._node_output())
        self.assertIsInstance(out, SubagentOutput)

    def test_module_name(self):
        from risk_agent import RiskAgent
        agent = RiskAgent()
        out = agent.execute(self._node_output())
        self.assertEqual(out.module, "risk")

    def test_signals_extracted(self):
        from risk_agent import RiskAgent
        agent = RiskAgent()
        out = agent.execute(self._node_output())
        self.assertGreater(len(out.signals), 0)
        names = [s.name for s in out.signals]
        self.assertIn("VaR95", names)

    def test_var_signal(self):
        from risk_agent import RiskAgent
        agent = RiskAgent()
        out = agent.execute(self._node_output())
        var_sigs = [s for s in out.signals if s.name == "VaR95"]
        self.assertEqual(len(var_sigs), 1)
        # VaR 0.035 < 0.05 → neutral (安全)
        self.assertEqual(var_sigs[0].direction, "neutral")

    def test_correlation_signal(self):
        from risk_agent import RiskAgent
        agent = RiskAgent()
        out = agent.execute(self._node_output())
        corr_sigs = [s for s in out.signals if s.name == "BTC相关性"]
        self.assertEqual(len(corr_sigs), 1)

    def test_stress_signal(self):
        from risk_agent import RiskAgent
        agent = RiskAgent()
        out = agent.execute(self._node_output())
        stress_sigs = [s for s in out.signals if s.name == "压力损失"]
        self.assertEqual(len(stress_sigs), 1)

    def test_signal_directions_valid(self):
        from risk_agent import RiskAgent
        agent = RiskAgent()
        out = agent.execute(self._node_output())
        for s in out.signals:
            self.assertIn(s.direction, ("long", "short", "neutral"))

    def test_summary_not_empty(self):
        from risk_agent import RiskAgent
        agent = RiskAgent()
        out = agent.execute(self._node_output())
        self.assertTrue(out.summary)

    def test_heatmap_chart(self):
        from risk_agent import RiskAgent
        agent = RiskAgent()
        out = agent.execute(self._node_output())
        heatmaps = [c for c in out.charts if c.type == "heatmap"]
        self.assertEqual(len(heatmaps), 1)

    def test_bar_chart(self):
        from risk_agent import RiskAgent
        agent = RiskAgent()
        out = agent.execute(self._node_output())
        bars = [c for c in out.charts if c.type == "bar"]
        self.assertGreater(len(bars), 0)

    def test_llm_fn_injectable(self):
        from risk_agent import RiskAgent
        calls = []
        def mock_llm(prompt):
            calls.append(prompt)
            return "风险LLM摘要"
        agent = RiskAgent(llm_fn=mock_llm)
        out = agent.execute(self._node_output())
        self.assertEqual(len(calls), 1)
        self.assertEqual(out.summary, "风险LLM摘要")

    def test_llm_exception_fails_open(self):
        from risk_agent import RiskAgent
        def bad_llm(prompt):
            raise RuntimeError("LLM不可用")
        agent = RiskAgent(llm_fn=bad_llm)
        out = agent.execute(self._node_output())
        self.assertTrue(out.summary)

    def test_empty_input(self):
        from risk_agent import RiskAgent
        agent = RiskAgent()
        out = agent.execute({})
        self.assertEqual(out.module, "risk")

    def test_ipc_handler(self):
        from risk_agent import handle_risk_agent
        result = handle_risk_agent({"node_output": self._node_output()})
        self.assertTrue(result["ok"])

    def test_to_dict(self):
        from risk_agent import RiskAgent
        agent = RiskAgent()
        out = agent.execute(self._node_output())
        d = out.to_dict()
        self.assertIn("module", d)
        self.assertIn("signals", d)


if __name__ == "__main__":
    unittest.main()
