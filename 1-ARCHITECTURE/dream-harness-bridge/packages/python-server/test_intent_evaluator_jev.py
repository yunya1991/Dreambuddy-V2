#!/usr/bin/env python3
"""IntentEvaluatorAgent + jev/laya 集成测试套件

测试覆盖:
    1. __init__ 支持 jev_fn/laya_fn 注入
    2. confidence >= 0.65 → 透传不评估
    3. jev choice == 原 intent → confidence 提升
    4. jev choice != 原 intent 且高置信 → confidence 降低 + clarified_intent
    5. jev choice != 原 intent 且低置信 → confidence 轻微降低
    6. jev noul < 0.5 → confidence 进一步降低
    7. jev degraded → 走规则降级
    8. jev 异常 → FAIL-OPEN 透传
    9. 无 jev_fn/laya_fn → 走现有逻辑（零回归）
    10. laya_fn 备用：jev degraded 时 fallback 到 laya
"""

from __future__ import annotations

import os
import sys
import unittest
from typing import Any, Dict
from unittest.mock import MagicMock, patch

# 将 python-server 目录加入 sys.path
SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

# 将 1-ARCHITECTURE 加入 sys.path (dreamos 的父目录)
# SERVER_DIR = .../dream-harness-bridge/packages/python-server
# ../../.. = .../1-ARCHITECTURE
ARCH_DIR = os.path.abspath(os.path.join(SERVER_DIR, "..", "..", ".."))
if ARCH_DIR not in sys.path:
    sys.path.insert(0, ARCH_DIR)

from dreamos.core.sense.evaluators.intent_evaluator_agent import IntentEvaluatorAgent, EvalResult
from dreamos.core.sense.types import IntentResult


def make_intent(intent_type: str = "TREND_FOLLOWING", confidence: float = 0.5) -> IntentResult:
    """构造测试用 IntentResult"""
    return IntentResult(
        intent_type=intent_type,
        confidence=confidence,
        rationale="test rationale",
    )


def make_jev_response(
    choice_intent: str = "TREND_FOLLOWING",
    choice_confidence: float = 0.8,
    noul: float = 0.7,
    degraded: bool = False,
) -> Dict[str, Any]:
    """构造 mock jev judge 响应"""
    if degraded:
        return {"answers": {}, "degraded": True, "reason": "test_degraded"}
    return {
        "model": "jev-latest",
        "answers": {
            "intent_classify": {
                "type": "choice",
                "choice": choice_intent,
                "confidence": choice_confidence,
            },
            "intent_correct": {
                "type": "noul",
                "noul": noul,
                "confidence": noul,
            },
        },
        "usage": {"input_tokens": 100, "output_tokens": 20},
        "degraded": False,
    }


class TestInitInjection(unittest.TestCase):
    """jev_fn/laya_fn 注入"""

    def test_init_accepts_jev_fn(self):
        jev_fn = MagicMock()
        agent = IntentEvaluatorAgent(jev_fn=jev_fn)
        self.assertIs(agent._jev_fn, jev_fn)

    def test_init_accepts_laya_fn(self):
        laya_fn = MagicMock()
        agent = IntentEvaluatorAgent(laya_fn=laya_fn)
        self.assertIs(agent._laya_fn, laya_fn)

    def test_init_no_jev_laya(self):
        agent = IntentEvaluatorAgent()
        self.assertIsNone(agent._jev_fn)
        self.assertIsNone(agent._laya_fn)


class TestHighConfidencePassthrough(unittest.TestCase):
    """高置信度透传"""

    def test_high_confidence_skip(self):
        jev_fn = MagicMock()
        agent = IntentEvaluatorAgent(jev_fn=jev_fn)
        intent = make_intent(confidence=0.7)
        result = agent.evaluate(intent, {})
        self.assertEqual(result.adjusted_confidence, 0.7)
        jev_fn.assert_not_called()


class TestJevChoiceMatch(unittest.TestCase):
    """jev choice 与原 intent 一致 → confidence 提升"""

    def test_choice_match_increases_confidence(self):
        jev_fn = MagicMock(return_value=make_jev_response(
            choice_intent="TREND_FOLLOWING",
            choice_confidence=0.8,
            noul=0.7,
        ))
        agent = IntentEvaluatorAgent(jev_fn=jev_fn)
        intent = make_intent(intent_type="TREND_FOLLOWING", confidence=0.5)
        result = agent.evaluate(intent, {"user_message": "分析BTC趋势"})
        # choice 匹配 → confidence 应提升
        self.assertGreater(result.adjusted_confidence, 0.5)
        # confidence 不超过 1.0
        self.assertLessEqual(result.adjusted_confidence, 1.0)
        jev_fn.assert_called_once()


class TestJevChoiceMismatchHighConf(unittest.TestCase):
    """jev choice != 原 intent 且高置信 → confidence 降低 + clarified_intent"""

    def test_choice_mismatch_high_conf(self):
        jev_fn = MagicMock(return_value=make_jev_response(
            choice_intent="DEEP_ANALYSIS",
            choice_confidence=0.85,
            noul=0.7,
        ))
        agent = IntentEvaluatorAgent(jev_fn=jev_fn)
        intent = make_intent(intent_type="TREND_FOLLOWING", confidence=0.5)
        result = agent.evaluate(intent, {"user_message": "深度分析BTC"})
        # choice 不匹配且高置信 → confidence 降低
        self.assertLess(result.adjusted_confidence, 0.5)
        # clarified_intent 应为 jev 的 choice
        self.assertEqual(result.clarified_intent, "DEEP_ANALYSIS")


class TestJevChoiceMismatchLowConf(unittest.TestCase):
    """jev choice != 原 intent 且低置信 → confidence 轻微降低"""

    def test_choice_mismatch_low_conf(self):
        jev_fn = MagicMock(return_value=make_jev_response(
            choice_intent="DEEP_ANALYSIS",
            choice_confidence=0.4,
            noul=0.7,
        ))
        agent = IntentEvaluatorAgent(jev_fn=jev_fn)
        intent = make_intent(intent_type="TREND_FOLLOWING", confidence=0.5)
        result = agent.evaluate(intent, {"user_message": "分析BTC"})
        # choice 不匹配但低置信 → confidence 轻微降低（降幅小于高置信场景）
        self.assertLessEqual(result.adjusted_confidence, 0.5)
        # clarified_intent 不应设置（jev 置信度不足）
        self.assertIsNone(result.clarified_intent)


class TestJevNoulLow(unittest.TestCase):
    """jev noul < 0.5 → confidence 进一步降低"""

    def test_noul_low_reduces_confidence(self):
        jev_fn = MagicMock(return_value=make_jev_response(
            choice_intent="TREND_FOLLOWING",
            choice_confidence=0.8,
            noul=0.3,  # 低 noul
        ))
        agent = IntentEvaluatorAgent(jev_fn=jev_fn)
        intent = make_intent(intent_type="TREND_FOLLOWING", confidence=0.5)
        result = agent.evaluate(intent, {"user_message": "分析BTC趋势"})
        # noul 低 → confidence 应低于 choice 匹配但 noul 正常的场景
        # choice 匹配本应提升，但 noul<0.5 抵消甚至降低
        self.assertLess(result.adjusted_confidence, 0.6)


class TestJevDegraded(unittest.TestCase):
    """jev degraded → 走规则降级"""

    def test_degraded_falls_back_to_rule(self):
        jev_fn = MagicMock(return_value=make_jev_response(degraded=True))
        agent = IntentEvaluatorAgent(jev_fn=jev_fn)
        intent = make_intent(confidence=0.5)
        result = agent.evaluate(intent, {})
        # degraded → 走规则降级，confidence 不变或轻微调整（无 recall 时透传）
        self.assertEqual(result.adjusted_confidence, 0.5)


class TestJevException(unittest.TestCase):
    """jev 异常 → FAIL-OPEN 透传"""

    def test_exception_fail_open(self):
        jev_fn = MagicMock(side_effect=Exception("boom"))
        agent = IntentEvaluatorAgent(jev_fn=jev_fn)
        intent = make_intent(confidence=0.5)
        result = agent.evaluate(intent, {})
        # 异常 → FAIL-OPEN 透传原 confidence
        self.assertEqual(result.adjusted_confidence, 0.5)


class TestNoJevFn(unittest.TestCase):
    """无 jev_fn/laya_fn → 走现有逻辑（零回归）"""

    def test_no_jev_fn_uses_rule_based(self):
        agent = IntentEvaluatorAgent()
        intent = make_intent(confidence=0.5)
        result = agent.evaluate(intent, {})
        # 无 jev_fn 且无 llm_fn → 规则降级，无 recall 时透传
        self.assertEqual(result.adjusted_confidence, 0.5)


class TestLayaFallback(unittest.TestCase):
    """laya_fn 备用：jev degraded 时 fallback 到 laya"""

    def test_jev_degraded_fallback_to_laya(self):
        jev_fn = MagicMock(return_value=make_jev_response(degraded=True))
        laya_fn = MagicMock(return_value=make_jev_response(
            choice_intent="TREND_FOLLOWING",
            choice_confidence=0.75,
            noul=0.6,
        ))
        agent = IntentEvaluatorAgent(jev_fn=jev_fn, laya_fn=laya_fn)
        intent = make_intent(intent_type="TREND_FOLLOWING", confidence=0.5)
        result = agent.evaluate(intent, {"user_message": "分析BTC趋势"})
        # jev degraded → laya 被调用
        laya_fn.assert_called_once()
        # laya choice 匹配 → confidence 提升
        self.assertGreater(result.adjusted_confidence, 0.5)


class TestConfidenceClamped(unittest.TestCase):
    """confidence 必须 clamp 到 [0, 1]"""

    def test_confidence_not_exceeds_one(self):
        jev_fn = MagicMock(return_value=make_jev_response(
            choice_intent="TREND_FOLLOWING",
            choice_confidence=0.99,
            noul=0.99,
        ))
        agent = IntentEvaluatorAgent(jev_fn=jev_fn)
        intent = make_intent(intent_type="TREND_FOLLOWING", confidence=0.64)
        result = agent.evaluate(intent, {"user_message": "x"})
        self.assertLessEqual(result.adjusted_confidence, 1.0)
        self.assertGreaterEqual(result.adjusted_confidence, 0.0)


if __name__ == "__main__":
    unittest.main()
