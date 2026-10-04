#!/usr/bin/env python3
"""P2-2: portfolio-agent 测试 (RED→GREEN)
新建域: 仓位分布/再平衡 → SubagentOutput
图表: pie(饼图) + bar(柱状)
"""
from __future__ import annotations
import os, sys, unittest

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


class TestImport(unittest.TestCase):
    def test_importable(self):
        from portfolio_agent import PortfolioAgent
        from subagent_types import SubagentOutput
        self.assertIsNotNone(PortfolioAgent)


class TestExecute(unittest.TestCase):
    def _node_output(self):
        return {
            "indicators": {
                "positions": [
                    {"symbol": "BTC", "weight": 0.45, "pnl_pct": 0.08},
                    {"symbol": "ETH", "weight": 0.30, "pnl_pct": 0.05},
                    {"symbol": "SOL", "weight": 0.15, "pnl_pct": -0.02},
                    {"symbol": "USDC", "weight": 0.10, "pnl_pct": 0.0},
                ],
                "total_weight": 1.0,
                "rebalance_needed": True,
                "drift": 0.05,
                "target_weight": {"BTC": 0.40, "ETH": 0.30, "SOL": 0.20, "USDC": 0.10},
            },
            "rationale": ["BTC 超配", "SOL 低配"],
            "direction": "NEUTRAL",
            "confidence": 0.55,
        }

    def test_returns_subagent_output(self):
        from portfolio_agent import PortfolioAgent
        from subagent_types import SubagentOutput
        agent = PortfolioAgent()
        out = agent.execute(self._node_output())
        self.assertIsInstance(out, SubagentOutput)

    def test_module_name(self):
        from portfolio_agent import PortfolioAgent
        agent = PortfolioAgent()
        out = agent.execute(self._node_output())
        self.assertEqual(out.module, "portfolio")

    def test_signals_extracted(self):
        from portfolio_agent import PortfolioAgent
        agent = PortfolioAgent()
        out = agent.execute(self._node_output())
        self.assertGreater(len(out.signals), 0)
        names = [s.name for s in out.signals]
        self.assertIn("漂移度", names)

    def test_drift_signal(self):
        from portfolio_agent import PortfolioAgent
        agent = PortfolioAgent()
        out = agent.execute(self._node_output())
        drift_sigs = [s for s in out.signals if s.name == "漂移度"]
        self.assertEqual(len(drift_sigs), 1)
        # drift 0.05 > 0.03 → short (需再平衡)
        self.assertEqual(drift_sigs[0].direction, "short")

    def test_rebalance_signal(self):
        from portfolio_agent import PortfolioAgent
        agent = PortfolioAgent()
        out = agent.execute(self._node_output())
        rebal_sigs = [s for s in out.signals if s.name == "再平衡需求"]
        self.assertEqual(len(rebal_sigs), 1)

    def test_signal_directions_valid(self):
        from portfolio_agent import PortfolioAgent
        agent = PortfolioAgent()
        out = agent.execute(self._node_output())
        for s in out.signals:
            self.assertIn(s.direction, ("long", "short", "neutral"))

    def test_summary_not_empty(self):
        from portfolio_agent import PortfolioAgent
        agent = PortfolioAgent()
        out = agent.execute(self._node_output())
        self.assertTrue(out.summary)

    def test_pie_chart(self):
        from portfolio_agent import PortfolioAgent
        agent = PortfolioAgent()
        out = agent.execute(self._node_output())
        pies = [c for c in out.charts if c.type == "pie"]
        self.assertEqual(len(pies), 1)

    def test_bar_chart(self):
        from portfolio_agent import PortfolioAgent
        agent = PortfolioAgent()
        out = agent.execute(self._node_output())
        bars = [c for c in out.charts if c.type == "bar"]
        self.assertGreater(len(bars), 0)

    def test_llm_fn_injectable(self):
        from portfolio_agent import PortfolioAgent
        calls = []
        def mock_llm(prompt):
            calls.append(prompt)
            return "组合LLM摘要"
        agent = PortfolioAgent(llm_fn=mock_llm)
        out = agent.execute(self._node_output())
        self.assertEqual(len(calls), 1)
        self.assertEqual(out.summary, "组合LLM摘要")

    def test_llm_exception_fails_open(self):
        from portfolio_agent import PortfolioAgent
        def bad_llm(prompt):
            raise RuntimeError("LLM不可用")
        agent = PortfolioAgent(llm_fn=bad_llm)
        out = agent.execute(self._node_output())
        self.assertTrue(out.summary)

    def test_empty_input(self):
        from portfolio_agent import PortfolioAgent
        agent = PortfolioAgent()
        out = agent.execute({})
        self.assertEqual(out.module, "portfolio")

    def test_ipc_handler(self):
        from portfolio_agent import handle_portfolio_agent
        result = handle_portfolio_agent({"node_output": self._node_output()})
        self.assertTrue(result["ok"])

    def test_to_dict(self):
        from portfolio_agent import PortfolioAgent
        agent = PortfolioAgent()
        out = agent.execute(self._node_output())
        d = out.to_dict()
        self.assertIn("module", d)
        self.assertIn("signals", d)


if __name__ == "__main__":
    unittest.main()
