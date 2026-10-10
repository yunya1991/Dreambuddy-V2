#!/usr/bin/env python3
"""test_c_drive_debate_v2.py — _bull_bear_debate v2 feature flag 测试 (TDD)

SPEC v2.0-rc3 第 6.7 节：
- config: c_drive.debate_engine: "v1" | "v2"（默认 "v1"）
- v2 出错时自动 fallback 到 v1
- 连续 3 次异常 → 切回 v1 + 告警
"""
from __future__ import annotations
import json, os, sys, unittest
from unittest.mock import MagicMock, patch

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


def _mock_llm(prompt, *args, **kwargs):
    """返回有效 JSON 的 mock LLM。"""
    return json.dumps({
        "thesis": "测试论点",
        "arguments": ["论据1"],
        "quote": "金句",
        "confidence": 0.75,
    })


class TestDebateV1Default(unittest.TestCase):
    """默认 v1 模式，行为不变。"""

    def test_v1_uses_llm_debate(self):
        """v1 模式使用 _llm_based_debate。"""
        from c_drive_agent import CDriveAgent, CDriveAction
        agent = CDriveAgent(llm_fn=_mock_llm)
        # 默认 debate_engine_version = "v1"
        self.assertEqual(agent._debate_engine_version, "v1")
        result = agent._bull_bear_debate(
            signals=[{"name": "RSI超卖", "direction": "long", "confidence": 0.8}],
            direction="LONG",
        )
        self.assertIn("bull_argument", result)
        self.assertIn("bear_argument", result)
        self.assertIn("bull_confidence", result)
        self.assertIn("bear_confidence", result)


class TestDebateV2Mode(unittest.TestCase):
    """v2 模式调用 DebateEngine。"""

    def test_v2_returns_expected_format(self):
        """v2 模式返回 v1 兼容格式。"""
        from c_drive_agent import CDriveAgent
        agent = CDriveAgent(
            llm_fn=_mock_llm,
            config={"debate_engine": "v2"},
        )
        self.assertEqual(agent._debate_engine_version, "v2")
        result = agent._bull_bear_debate(
            signals=[{"name": "RSI", "direction": "long", "confidence": 0.8}],
            direction="LONG",
        )
        # v2 输出映射到 v1 格式
        self.assertIn("bull_argument", result)
        self.assertIn("bear_argument", result)
        self.assertIn("bull_confidence", result)
        self.assertIn("bear_confidence", result)

    def test_v2_failure_fallback_to_v1(self):
        """v2 异常时 fallback 到 v1。"""
        from c_drive_agent import CDriveAgent
        # v2 会因 DebateEngine 异常而 fallback
        bad_llm = lambda p, *a, **kw: (_ for _ in ()).throw(Exception("LLM error"))
        agent = CDriveAgent(
            llm_fn=bad_llm,
            config={"debate_engine": "v2"},
        )
        # v2 异常 → fallback 到 rule-based (v1)
        result = agent._bull_bear_debate(
            signals=[{"name": "RSI", "direction": "long", "confidence": 0.8}],
            direction="LONG",
        )
        # 应该返回有效结果（rule-based fallback）
        self.assertIn("bull_argument", result)
        self.assertIn("bear_argument", result)

    def test_v2_consecutive_errors_rollback(self):
        """连续 3 次异常后切回 v1。"""
        from c_drive_agent import CDriveAgent
        bad_llm = lambda p, *a, **kw: (_ for _ in ()).throw(Exception("error"))
        agent = CDriveAgent(
            llm_fn=bad_llm,
            config={"debate_engine": "v2"},
        )
        # 触发 3 次异常
        for _ in range(3):
            agent._bull_bear_debate(
                signals=[{"name": "RSI", "direction": "long", "confidence": 0.8}],
                direction="LONG",
            )
        # 第 4 次应该直接用 v1（不再尝试 v2）
        self.assertEqual(agent._debate_engine_version, "v1")
        self.assertGreaterEqual(agent._debate_error_count, 3)

    def test_v2_success_resets_error_count(self):
        """v2 成功时重置错误计数。"""
        from c_drive_agent import CDriveAgent
        agent = CDriveAgent(
            llm_fn=_mock_llm,
            config={"debate_engine": "v2"},
        )
        agent._debate_error_count = 2  # 预置 2 次错误
        agent._bull_bear_debate(
            signals=[{"name": "RSI", "direction": "long", "confidence": 0.8}],
            direction="LONG",
        )
        self.assertEqual(agent._debate_error_count, 0)


if __name__ == "__main__":
    unittest.main()
