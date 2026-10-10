#!/usr/bin/env python3
"""test_debate_ipc.py — handle_debate IPC 路由测试 (TDD RED→GREEN)

SPEC v2.0-rc3 第 6.3 节：C-Drive 对外暴露 4 个辩论 IPC 接口。
- action=recall: 检索历史辩论记忆
- action=record: 存储辩论经验
- action=verify: 验证辩论预测
- action=run: C-Drive 自驱动辩论
"""
from __future__ import annotations
import json, os, sys, unittest
from unittest.mock import MagicMock, patch

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


def _mock_llm(prompt, max_tokens=600):
    """返回有效 JSON 的 mock LLM。"""
    return json.dumps({
        "thesis": "测试论点",
        "arguments": ["论据1", "论据2"],
        "quote": "金句",
        "confidence": 0.8,
    })


class TestImport(unittest.TestCase):
    def test_importable(self):
        from c_drive_agent import handle_debate  # noqa: F401


class TestRecallAction(unittest.TestCase):
    """action=recall: 检索历史辩论记忆。"""

    def test_returns_memories(self):
        from c_drive_agent import handle_debate
        with patch("c_drive_agent._load_cognitive_adapter") as mock_load:
            cog = MagicMock()
            cog.recall.return_value = [
                {"content": '{"thesis": "BTC稀缺性"}', "quality": "B",
                 "quality_score": 0.5, "verified": True}
            ]
            mock_load.return_value = cog
            result = handle_debate({
                "action": "recall",
                "context": "BTC 多空辩论论据",
                "top_k": 5,
            })
        self.assertTrue(result["ok"])
        self.assertIn("memories", result)

    def test_fail_open_no_cognitive(self):
        """无 cognitive_adapter 时 FAIL-OPEN。"""
        from c_drive_agent import handle_debate
        with patch("c_drive_agent._load_cognitive_adapter", return_value=None):
            result = handle_debate({
                "action": "recall",
                "context": "BTC",
            })
        self.assertTrue(result["ok"])
        self.assertEqual(result["memories"], [])


class TestRecordAction(unittest.TestCase):
    """action=record: 存储辩论经验。"""

    def test_returns_memory_id(self):
        from c_drive_agent import handle_debate
        with patch("c_drive_agent._load_cognitive_adapter") as mock_load:
            cog = MagicMock()
            cog.record.return_value = "VM-test-001"
            mock_load.return_value = cog
            result = handle_debate({
                "action": "record",
                "content": json.dumps({"thesis": "BTC稀缺性", "side": "bull"}),
                "quality": "B",
                "tags": "debate,argument-pattern,BTC,多空",
            })
        self.assertTrue(result["ok"])
        self.assertEqual(result["memory_id"], "VM-test-001")

    def test_default_quality_and_tags(self):
        """无 quality/tags 时使用默认值。"""
        from c_drive_agent import handle_debate
        with patch("c_drive_agent._load_cognitive_adapter") as mock_load:
            cog = MagicMock()
            cog.record.return_value = "VM-002"
            mock_load.return_value = cog
            result = handle_debate({
                "action": "record",
                "content": "test",
            })
        self.assertTrue(result["ok"])
        # 验证 record 被调用
        self.assertTrue(cog.record.called)


class TestVerifyAction(unittest.TestCase):
    """action=verify: 验证辩论预测。"""

    def test_verify_success(self):
        from c_drive_agent import handle_debate
        with patch("c_drive_agent._load_cognitive_adapter") as mock_load:
            cog = MagicMock()
            cog.verify.return_value = True
            mock_load.return_value = cog
            result = handle_debate({
                "action": "verify",
                "memory_id": "VM-001",
                "success": True,
            })
        self.assertTrue(result["ok"])


class TestRunAction(unittest.TestCase):
    """action=run: C-Drive 自驱动辩论。"""

    def test_run_fast(self):
        from c_drive_agent import handle_debate
        with patch("c_drive_agent._load_cognitive_adapter", return_value=None), \
             patch("c_drive_agent._make_synthesizer_llm_fn", return_value=_mock_llm):
            result = handle_debate({
                "action": "run",
                "topic": "BTC 是数字黄金",
                "mode": "fast",
            })
        self.assertTrue(result["ok"])
        self.assertIn("result", result)
        self.assertIn("bull_thesis", result["result"])

    def test_run_deep(self):
        from c_drive_agent import handle_debate
        with patch("c_drive_agent._load_cognitive_adapter", return_value=None), \
             patch("c_drive_agent._make_synthesizer_llm_fn", return_value=_mock_llm):
            result = handle_debate({
                "action": "run",
                "topic": "BTC 是数字黄金",
                "mode": "deep",
            })
        self.assertTrue(result["ok"])
        self.assertIn("result", result)
        self.assertIn("transcript", result["result"])

    def test_run_default_mode_is_fast(self):
        """无 mode 参数时默认 fast。"""
        from c_drive_agent import handle_debate
        with patch("c_drive_agent._load_cognitive_adapter", return_value=None), \
             patch("c_drive_agent._make_synthesizer_llm_fn", return_value=_mock_llm):
            result = handle_debate({
                "action": "run",
                "topic": "测试",
            })
        self.assertTrue(result["ok"])
        self.assertIn("bull_thesis", result["result"])


class TestUnknownAction(unittest.TestCase):
    """未知 action 返回错误。"""

    def test_unknown_action(self):
        from c_drive_agent import handle_debate
        result = handle_debate({"action": "unknown"})
        self.assertFalse(result["ok"])
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
