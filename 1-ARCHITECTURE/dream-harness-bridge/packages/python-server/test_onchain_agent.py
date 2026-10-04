#!/usr/bin/env python3
"""P1-3: onchain-agent 测试 (RED→GREEN)
F4 节点: 活跃地址/算力/MVRV → SubagentOutput
图表: line(折线) + heatmap(热力图)
"""
from __future__ import annotations
import os, sys, unittest

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


class TestImport(unittest.TestCase):
    def test_importable(self):
        from onchain_agent import OnchainAgent
        from subagent_types import SubagentOutput
        self.assertIsNotNone(OnchainAgent)


class TestExecute(unittest.TestCase):
    def _node_output(self):
        return {
            "indicators": {
                "active_addresses": 1.1e6,
                "hashrate": 650e12,  # TH/s
                "mvrv": 1.8,
                "exchange_inflow": 1200.0,  # BTC
                "nupl": 0.35,
            },
            "rationale": ["链上活跃度上升", "MVRV 中性偏多"],
            "direction": "LONG",
            "confidence": 0.6,
        }

    def test_returns_subagent_output(self):
        from onchain_agent import OnchainAgent
        from subagent_types import SubagentOutput
        agent = OnchainAgent()
        out = agent.execute(self._node_output())
        self.assertIsInstance(out, SubagentOutput)

    def test_module_name(self):
        from onchain_agent import OnchainAgent
        agent = OnchainAgent()
        out = agent.execute(self._node_output())
        self.assertEqual(out.module, "onchain")

    def test_signals_extracted(self):
        from onchain_agent import OnchainAgent
        agent = OnchainAgent()
        out = agent.execute(self._node_output())
        self.assertGreater(len(out.signals), 0)
        names = [s.name for s in out.signals]
        self.assertIn("MVRV", names)

    def test_mvrv_signal(self):
        from onchain_agent import OnchainAgent
        agent = OnchainAgent()
        out = agent.execute(self._node_output())
        mvrv_sigs = [s for s in out.signals if s.name == "MVRV"]
        self.assertEqual(len(mvrv_sigs), 1)
        # MVRV 1.8 in 1.5~3.0 → neutral偏多
        self.assertIn(mvrv_sigs[0].direction, ("long", "neutral"))

    def test_exchange_inflow_signal(self):
        from onchain_agent import OnchainAgent
        agent = OnchainAgent()
        out = agent.execute(self._node_output())
        inflow_sigs = [s for s in out.signals if s.name == "交易所流入"]
        self.assertEqual(len(inflow_sigs), 1)

    def test_signal_directions_valid(self):
        from onchain_agent import OnchainAgent
        agent = OnchainAgent()
        out = agent.execute(self._node_output())
        for s in out.signals:
            self.assertIn(s.direction, ("long", "short", "neutral"))

    def test_summary_not_empty(self):
        from onchain_agent import OnchainAgent
        agent = OnchainAgent()
        out = agent.execute(self._node_output())
        self.assertTrue(out.summary)

    def test_line_chart(self):
        from onchain_agent import OnchainAgent
        agent = OnchainAgent()
        out = agent.execute(self._node_output())
        lines = [c for c in out.charts if c.type == "line"]
        self.assertGreater(len(lines), 0)

    def test_heatmap_chart(self):
        from onchain_agent import OnchainAgent
        agent = OnchainAgent()
        out = agent.execute(self._node_output())
        heatmaps = [c for c in out.charts if c.type == "heatmap"]
        self.assertEqual(len(heatmaps), 1)

    def test_llm_fn_injectable(self):
        from onchain_agent import OnchainAgent
        calls = []
        def mock_llm(prompt):
            calls.append(prompt)
            return "链上LLM摘要"
        agent = OnchainAgent(llm_fn=mock_llm)
        out = agent.execute(self._node_output())
        self.assertEqual(len(calls), 1)
        self.assertEqual(out.summary, "链上LLM摘要")

    def test_llm_exception_fails_open(self):
        from onchain_agent import OnchainAgent
        def bad_llm(prompt):
            raise RuntimeError("LLM不可用")
        agent = OnchainAgent(llm_fn=bad_llm)
        out = agent.execute(self._node_output())
        self.assertTrue(out.summary)

    def test_empty_input(self):
        from onchain_agent import OnchainAgent
        agent = OnchainAgent()
        out = agent.execute({})
        self.assertEqual(out.module, "onchain")

    def test_ipc_handler(self):
        from onchain_agent import handle_onchain_agent
        result = handle_onchain_agent({"node_output": self._node_output()})
        self.assertTrue(result["ok"])

    def test_to_dict(self):
        from onchain_agent import OnchainAgent
        agent = OnchainAgent()
        out = agent.execute(self._node_output())
        d = out.to_dict()
        self.assertIn("module", d)
        self.assertIn("signals", d)


if __name__ == "__main__":
    unittest.main()
