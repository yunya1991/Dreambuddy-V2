#!/usr/bin/env python3
"""P0-3b: sentiment-agent 测试 (RED→GREEN)"""
from __future__ import annotations
import os, sys, unittest

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


class TestImport(unittest.TestCase):
    def test_importable(self):
        from sentiment_agent import SentimentAgent
        from subagent_types import SubagentOutput
        self.assertIsNotNone(SentimentAgent)


class TestExecute(unittest.TestCase):
    def _node_output(self):
        return {
            "sentiment": {"impact": "BULLISH", "score": 0.75, "fgi": 80},
            "rationale": ["新闻情绪看多"],
            "direction": "LONG", "confidence": 0.6,
        }

    def test_returns_subagent_output(self):
        from sentiment_agent import SentimentAgent
        from subagent_types import SubagentOutput
        agent = SentimentAgent()
        out = agent.execute(self._node_output())
        self.assertIsInstance(out, SubagentOutput)

    def test_module_name(self):
        from sentiment_agent import SentimentAgent
        agent = SentimentAgent()
        out = agent.execute(self._node_output())
        self.assertEqual(out.module, "sentiment")

    def test_signals_extracted(self):
        from sentiment_agent import SentimentAgent
        agent = SentimentAgent()
        out = agent.execute(self._node_output())
        self.assertGreater(len(out.signals), 0)
        names = [s.name for s in out.signals]
        self.assertIn("新闻情绪", names)

    def test_fgi_signal(self):
        from sentiment_agent import SentimentAgent
        agent = SentimentAgent()
        out = agent.execute(self._node_output())
        fgi_sigs = [s for s in out.signals if s.name == "恐惧贪婪指数"]
        self.assertEqual(len(fgi_sigs), 1)
        self.assertEqual(fgi_sigs[0].direction, "short")  # FGI=80 > 75 → short

    def test_signal_directions_valid(self):
        from sentiment_agent import SentimentAgent
        agent = SentimentAgent()
        out = agent.execute(self._node_output())
        for s in out.signals:
            self.assertIn(s.direction, ("long", "short", "neutral"))

    def test_summary_not_empty(self):
        from sentiment_agent import SentimentAgent
        agent = SentimentAgent()
        out = agent.execute(self._node_output())
        self.assertTrue(out.summary)

    def test_gauge_chart(self):
        from sentiment_agent import SentimentAgent
        agent = SentimentAgent()
        out = agent.execute(self._node_output())
        gauge = [c for c in out.charts if c.type == "gauge"]
        self.assertEqual(len(gauge), 1)

    def test_fgi_line_chart(self):
        from sentiment_agent import SentimentAgent
        agent = SentimentAgent()
        out = agent.execute(self._node_output())
        lines = [c for c in out.charts if c.type == "line"]
        self.assertGreater(len(lines), 0)

    def test_llm_fn_injectable(self):
        from sentiment_agent import SentimentAgent
        calls = []
        def mock_llm(prompt):
            calls.append(prompt)
            return "情绪LLM摘要"
        agent = SentimentAgent(llm_fn=mock_llm)
        out = agent.execute(self._node_output())
        self.assertEqual(len(calls), 1)
        self.assertEqual(out.summary, "情绪LLM摘要")

    def test_llm_exception_fails_open(self):
        from sentiment_agent import SentimentAgent
        def bad_llm(prompt):
            raise RuntimeError("LLM不可用")
        agent = SentimentAgent(llm_fn=bad_llm)
        out = agent.execute(self._node_output())
        self.assertTrue(out.summary)

    def test_empty_input(self):
        from sentiment_agent import SentimentAgent
        agent = SentimentAgent()
        out = agent.execute({})
        self.assertEqual(out.module, "sentiment")

    def test_ipc_handler(self):
        from sentiment_agent import handle_sentiment_agent
        result = handle_sentiment_agent({"node_output": self._node_output()})
        self.assertTrue(result["ok"])

    def test_to_dict(self):
        from sentiment_agent import SentimentAgent
        agent = SentimentAgent()
        out = agent.execute(self._node_output())
        d = out.to_dict()
        self.assertIn("module", d)
        self.assertIn("signals", d)


if __name__ == "__main__":
    unittest.main()
