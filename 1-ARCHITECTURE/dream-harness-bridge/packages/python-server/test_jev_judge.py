#!/usr/bin/env python3
"""jev_judge.py 测试套件

测试覆盖:
    1. 功能开关关闭 → degraded=True
    2. 缺少 API Key → degraded=True
    3. 输入校验（空 questions / 无效 type / choice 缺 criteria / score 缺 criteria / 超限）
    4. 字段过滤（reward/direction/action/position 等禁止字段被剔除）
    5. FAIL-OPEN（API 异常 → degraded=True）
    6. 成功路径（mock _call_jev_api）

HC-9 验证: 不出现交易判断逻辑
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# 将 python-server 目录加入 sys.path
SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

import jev_judge


class TestJevJudgeDisabled(unittest.TestCase):
    """功能开关关闭时的行为"""

    def test_disabled_returns_degraded(self):
        with patch.object(jev_judge, "ENABLE_JEV_JUDGE", False):
            result = jev_judge.judge("state", {"q": {"type": "noul", "instructions": "test"}})
            self.assertTrue(result["degraded"])
            self.assertEqual(result["reason"], "jev_judge_disabled")
            self.assertEqual(result["answers"], {})


class TestJevJudgeMissingKey(unittest.TestCase):
    """缺少 API Key 时的行为"""

    def test_missing_key_returns_degraded(self):
        with patch.object(jev_judge, "ENABLE_JEV_JUDGE", True), \
             patch.object(jev_judge, "TYPESAFE_API_KEY", ""):
            result = jev_judge.judge("state", {"q": {"type": "noul", "instructions": "test"}})
            self.assertTrue(result["degraded"])
            self.assertEqual(result["reason"], "missing TYPESAFE_API_KEY")


class TestJevJudgeValidation(unittest.TestCase):
    """输入校验"""

    def setUp(self):
        # 开启开关 + 设置 key，只测校验逻辑
        self.enabled_patch = patch.object(jev_judge, "ENABLE_JEV_JUDGE", True)
        self.key_patch = patch.object(jev_judge, "TYPESAFE_API_KEY", "test-key")
        self.enabled_patch.start()
        self.key_patch.start()

    def tearDown(self):
        self.enabled_patch.stop()
        self.key_patch.stop()

    def test_empty_questions(self):
        result = jev_judge.judge("state", {})
        self.assertTrue(result["degraded"])
        self.assertIn("invalid_questions", result["reason"])

    def test_non_dict_questions(self):
        result = jev_judge.judge("state", "not a dict")
        self.assertTrue(result["degraded"])

    def test_invalid_type(self):
        questions = {"q": {"type": "invalid", "instructions": "test"}}
        result = jev_judge.judge("state", questions)
        self.assertTrue(result["degraded"])
        self.assertIn("invalid type", result["reason"])

    def test_missing_instructions(self):
        questions = {"q": {"type": "noul"}}
        result = jev_judge.judge("state", questions)
        self.assertTrue(result["degraded"])
        self.assertIn("instructions", result["reason"])

    def test_choice_missing_criteria(self):
        questions = {"q": {"type": "choice", "instructions": "test"}}
        result = jev_judge.judge("state", questions)
        self.assertTrue(result["degraded"])
        self.assertIn("criteria", result["reason"])

    def test_choice_empty_criteria(self):
        questions = {"q": {"type": "choice", "instructions": "test", "criteria": {}}}
        result = jev_judge.judge("state", questions)
        self.assertTrue(result["degraded"])

    def test_choice_too_many_options(self):
        with patch.object(jev_judge, "MAX_CHOICE_OPTIONS", 2):
            criteria = {f"opt{i}": f"desc{i}" for i in range(5)}
            questions = {"q": {"type": "choice", "instructions": "test", "criteria": criteria}}
            result = jev_judge.judge("state", questions)
            self.assertTrue(result["degraded"])
            self.assertIn("max is", result["reason"])

    def test_score_missing_criteria(self):
        questions = {"q": {"type": "score", "instructions": "test"}}
        result = jev_judge.judge("state", questions)
        self.assertTrue(result["degraded"])
        self.assertIn("criteria", result["reason"])

    def test_score_empty_criteria(self):
        questions = {"q": {"type": "score", "instructions": "test", "criteria": []}}
        result = jev_judge.judge("state", questions)
        self.assertTrue(result["degraded"])

    def test_score_too_many_levels(self):
        with patch.object(jev_judge, "MAX_SCORE_LEVELS", 3):
            criteria = [f"level{i}" for i in range(5)]
            questions = {"q": {"type": "score", "instructions": "test", "criteria": criteria}}
            result = jev_judge.judge("state", questions)
            self.assertTrue(result["degraded"])
            self.assertIn("max is", result["reason"])


class TestJevJudgeFieldFiltering(unittest.TestCase):
    """HC-5/HC-9 字段过滤：禁止字段被剔除"""

    def test_forbidden_fields_stripped(self):
        """reward/direction/action/position 等字段必须被剔除"""
        mock_response = {
            "model": "jev-1.13.0",
            "answers": {
                "q1": {
                    "type": "noul",
                    "noul": 0.92,
                    "reward": 0.5,          # HC-5: 禁止
                    "direction": "long",     # HC-9: 禁止
                    "action": "buy",         # HC-9: 禁止
                    "position": 1.0,         # HC-9: 禁止
                    "size": 100,             # HC-9: 禁止
                },
            },
            "usage": {"input_tokens": 100, "output_tokens": 10},
        }

        with patch.object(jev_judge, "ENABLE_JEV_JUDGE", True), \
             patch.object(jev_judge, "TYPESAFE_API_KEY", "test-key"), \
             patch.object(jev_judge, "_call_jev_api", return_value=mock_response):
            result = jev_judge.judge("state", {"q1": {"type": "noul", "instructions": "test"}})

            self.assertFalse(result["degraded"])
            ans = result["answers"]["q1"]
            # 禁止字段必须被剔除
            self.assertNotIn("reward", ans)
            self.assertNotIn("direction", ans)
            self.assertNotIn("action", ans)
            self.assertNotIn("position", ans)
            self.assertNotIn("size", ans)
            self.assertNotIn("position_delta", ans)
            self.assertNotIn("target_weight", ans)
            self.assertNotIn("notional", ans)
            # 合法字段保留
            self.assertEqual(ans["type"], "noul")
            self.assertEqual(ans["noul"], 0.92)


class TestJevJudgeFailOpen(unittest.TestCase):
    """FAIL-OPEN：API 异常时降级"""

    def test_exception_returns_degraded(self):
        with patch.object(jev_judge, "ENABLE_JEV_JUDGE", True), \
             patch.object(jev_judge, "TYPESAFE_API_KEY", "test-key"), \
             patch.object(jev_judge, "_call_jev_api", side_effect=Exception("boom")):
            result = jev_judge.judge("state", {"q": {"type": "noul", "instructions": "test"}})
            self.assertTrue(result["degraded"])
            self.assertIn("Exception", result["reason"])
            self.assertEqual(result["answers"], {})


class TestJevJudgeSuccess(unittest.TestCase):
    """成功路径"""

    def test_noul_success(self):
        mock_response = {
            "model": "jev-1.13.0",
            "answers": {
                "is_urgent": {"type": "noul", "noul": 0.92},
            },
            "usage": {"input_tokens": 420, "output_tokens": 71},
        }

        with patch.object(jev_judge, "ENABLE_JEV_JUDGE", True), \
             patch.object(jev_judge, "TYPESAFE_API_KEY", "test-key"), \
             patch.object(jev_judge, "_call_jev_api", return_value=mock_response):
            result = jev_judge.judge(
                "Help! My payouts have been failing for 3 days.",
                {"is_urgent": {"type": "noul", "instructions": "Does this convey urgency?"}},
            )

            self.assertFalse(result["degraded"])
            self.assertEqual(result["model"], "jev-1.13.0")
            self.assertEqual(result["answers"]["is_urgent"]["noul"], 0.92)
            self.assertEqual(result["usage"]["input_tokens"], 420)

    def test_choice_and_score_success(self):
        mock_response = {
            "model": "jev-1.13.0",
            "answers": {
                "team": {
                    "type": "choice",
                    "choice": "technical",
                    "confidence": 0.82,
                    "probabilities": {"billing": 0.08, "technical": 0.85, "sales": 0.07},
                },
                "anger": {
                    "type": "score",
                    "score": 1.6,
                    "legend": {"0": "calm", "1": "upset", "2": "angry"},
                    "probabilities": {"0": 0.05, "1": 0.30, "2": 0.65},
                    "confidence": 0.78,
                },
            },
            "usage": {},
        }

        questions = {
            "team": {
                "type": "choice",
                "instructions": "Which team?",
                "criteria": {"billing": "payments", "technical": "bugs", "sales": "pricing"},
            },
            "anger": {
                "type": "score",
                "instructions": "How angry?",
                "criteria": ["calm", "upset", "angry"],
            },
        }

        with patch.object(jev_judge, "ENABLE_JEV_JUDGE", True), \
             patch.object(jev_judge, "TYPESAFE_API_KEY", "test-key"), \
             patch.object(jev_judge, "_call_jev_api", return_value=mock_response):
            result = jev_judge.judge("state", questions)

            self.assertFalse(result["degraded"])
            self.assertEqual(result["answers"]["team"]["choice"], "technical")
            self.assertEqual(result["answers"]["anger"]["score"], 1.6)


class TestHandleJevJudge(unittest.TestCase):
    """IPC handler 入口"""

    def test_handle_passes_params(self):
        with patch.object(jev_judge, "judge", return_value={"degraded": True}) as mock_judge:
            result = jev_judge.handle_jev_judge({"state": "s", "questions": {"q": {"type": "noul", "instructions": "t"}}})
            mock_judge.assert_called_once_with("s", {"q": {"type": "noul", "instructions": "t"}})
            self.assertEqual(result, {"degraded": True})

    def test_handle_defaults_empty_questions(self):
        with patch.object(jev_judge, "judge", return_value={"degraded": True}) as mock_judge:
            jev_judge.handle_jev_judge({"state": "s"})
            mock_judge.assert_called_once_with("s", {})


class TestHC9Compliance(unittest.TestCase):
    """HC-9: 源码不包含交易判断逻辑"""

    def test_no_trading_keywords(self):
        """grep 源码，禁止出现交易判断关键字"""
        import re

        src_path = os.path.join(SERVER_DIR, "jev_judge.py")
        with open(src_path, "r", encoding="utf-8") as f:
            src = f.read()

        # 禁止的交易判断模式（在条件判断中使用）
        forbidden_patterns = [
            r"if\s+rsi\b",
            r"if\s+position\b",
            r"if\s+pnl\b",
            r"if\s+direction\b",
            r"if\s+price\b",
            r"reward\s*=",
        ]

        for pattern in forbidden_patterns:
            matches = re.findall(pattern, src)
            self.assertEqual(
                len(matches), 0,
                f"HC-9 违规: 发现交易判断模式 '{pattern}'"
            )


if __name__ == "__main__":
    unittest.main()
