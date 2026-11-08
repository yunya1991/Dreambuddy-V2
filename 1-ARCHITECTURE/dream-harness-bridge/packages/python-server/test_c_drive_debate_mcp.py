"""C-Drive → agent.debate.mcp 迁移测试（feature flag / 灰度 / 回滚）。"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import patch

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


def _mock_llm(prompt, *args, **kwargs):
    return json.dumps({
        "thesis": "本地论点",
        "arguments": ["论据1"],
        "quote": "金句",
        "confidence": 0.7,
    })


SIGNALS = [
    {"name": "RSI", "direction": "long", "confidence": 0.8},
    {"name": "资金流", "direction": "short", "confidence": 0.6},
]


class FakeMCPClient:
    calls: list[dict] = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def run(self, topic, mode="fast", background="", **kwargs):
        type(self).calls.append({
            "topic": topic, "mode": mode, "background": background,
            **kwargs,
        })
        return {
            "transcript": [
                {"speaker": "bull", "round": 1,
                 "content": {"thesis": "MCP 多方", "confidence": 0.82}},
                {"speaker": "bear", "round": 1,
                 "content": {"thesis": "MCP 空方", "confidence": 0.41}},
            ],
            "verdict": {
                "signal": {
                    "direction": "long", "confidence": 0.78,
                    "risk_flags": ["high_volatility"],
                },
                "risks": [],
            },
        }


class FailingMCPClient(FakeMCPClient):
    def run(self, *args, **kwargs):
        raise RuntimeError("mcp unavailable")


class TestCDriveDebateMCP(unittest.TestCase):

    def test_flag_enabled_uses_mcp(self):
        from c_drive_agent import CDriveAgent

        FakeMCPClient.calls = []
        with patch.dict(os.environ, {
            "DEBATE_MCP_ENABLED": "true",
            "DEBATE_MCP_GRAY_PERCENT": "100",
        }):
            with patch("debate_mcp_client.DebateMCPClient", FakeMCPClient):
                agent = CDriveAgent(llm_fn=_mock_llm)
                result = agent._bull_bear_debate(SIGNALS, "LONG")

        self.assertEqual(result["bull_argument"], "MCP 多方")
        self.assertEqual(result["bear_argument"], "MCP 空方")
        self.assertAlmostEqual(result["bull_confidence"], 0.82)
        self.assertAlmostEqual(result["bear_confidence"], 0.41)
        self.assertEqual(result["signal"]["direction"], "long")
        self.assertEqual(result["risk_flags"], ["high_volatility"])
        self.assertEqual(len(FakeMCPClient.calls), 1)
        self.assertEqual(FakeMCPClient.calls[0]["mode"], "fast")
        self.assertEqual(FakeMCPClient.calls[0]["profile"], "signal")
        self.assertTrue(FakeMCPClient.calls[0]["research"])
        self.assertIn("l1_signal", FakeMCPClient.calls[0]["research_sources"])
        self.assertIn("signals", FakeMCPClient.calls[0]["background"])

    def test_flag_disabled_uses_local(self):
        from c_drive_agent import CDriveAgent

        FakeMCPClient.calls = []
        with patch.dict(os.environ, {
            "DEBATE_MCP_ENABLED": "false",
        }):
            with patch("debate_mcp_client.DebateMCPClient", FakeMCPClient):
                agent = CDriveAgent(llm_fn=_mock_llm)
                result = agent._bull_bear_debate(SIGNALS, "LONG")

        self.assertIn("bull_argument", result)
        self.assertEqual(FakeMCPClient.calls, [])

    def test_gray_zero_disables_mcp(self):
        from c_drive_agent import CDriveAgent

        FakeMCPClient.calls = []
        with patch.dict(os.environ, {
            "DEBATE_MCP_ENABLED": "true",
            "DEBATE_MCP_GRAY_PERCENT": "0",
        }):
            with patch("debate_mcp_client.DebateMCPClient", FakeMCPClient):
                agent = CDriveAgent(llm_fn=_mock_llm)
                agent._bull_bear_debate(SIGNALS, "LONG")

        self.assertEqual(FakeMCPClient.calls, [])

    def test_mcp_failure_falls_back_to_local(self):
        from c_drive_agent import CDriveAgent

        with patch.dict(os.environ, {
            "DEBATE_MCP_ENABLED": "true",
            "DEBATE_MCP_GRAY_PERCENT": "100",
        }):
            with patch("debate_mcp_client.DebateMCPClient", FailingMCPClient):
                agent = CDriveAgent(llm_fn=_mock_llm)
                result = agent._bull_bear_debate(SIGNALS, "LONG")

        self.assertIn("bull_argument", result)
        self.assertEqual(agent._debate_mcp_error_count, 1)
        self.assertTrue(agent._debate_mcp_enabled)

    def test_consecutive_errors_rollback_flag(self):
        from c_drive_agent import CDriveAgent

        with patch.dict(os.environ, {
            "DEBATE_MCP_ENABLED": "true",
            "DEBATE_MCP_GRAY_PERCENT": "100",
            "DEBATE_MCP_MAX_ERRORS": "2",
        }):
            with patch("debate_mcp_client.DebateMCPClient", FailingMCPClient):
                agent = CDriveAgent(llm_fn=_mock_llm)
                agent._bull_bear_debate(SIGNALS, "LONG")
                agent._bull_bear_debate(SIGNALS, "LONG")

        self.assertEqual(agent._debate_mcp_error_count, 2)
        self.assertFalse(agent._debate_mcp_enabled)

    def test_reflect_after_debate_carries_signal_fields(self):
        from c_drive_agent import CDriveAgent

        agent = CDriveAgent(llm_fn=_mock_llm)
        decision = agent._reflect_after_debate(
            "node", 0.6, [],
            {
                "bull_confidence": 0.74,
                "bear_confidence": 0.60,
                "signal": {"direction": "long", "confidence": 0.65},
                "risk_flags": ["period_mismatch"],
            },
        )
        self.assertEqual(decision.signal["direction"], "long")
        self.assertEqual(decision.risk_flags, ["period_mismatch"])
        self.assertEqual(decision.to_dict()["signal"]["confidence"], 0.65)

    def test_handle_debate_run_uses_mcp_when_enabled(self):
        from c_drive_agent import handle_debate

        FakeMCPClient.calls = []
        with patch.dict(os.environ, {"DEBATE_MCP_ENABLED": "true"}):
            with patch("debate_mcp_client.DebateMCPClient", FakeMCPClient):
                result = handle_debate({
                    "action": "run", "topic": "测试", "mode": "fast",
                })

        self.assertTrue(result["ok"])
        self.assertEqual(result["via"], "agent.debate.mcp")
        self.assertEqual(FakeMCPClient.calls[0]["topic"], "测试")
        self.assertEqual(FakeMCPClient.calls[0]["profile"], "signal")
        self.assertTrue(FakeMCPClient.calls[0]["research"])
        self.assertIn("l1_cycle", FakeMCPClient.calls[0]["research_sources"])


if __name__ == "__main__":
    unittest.main()