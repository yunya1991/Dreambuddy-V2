"""
辩论引擎集成测试 — P3
验证 should_run_debate / is_high_value / run_debate_for_case / enrich_case_with_debate

测试覆盖：
  1. should_run_debate 触发条件
  2. is_high_value 高价值判断
  3. FAIL-OPEN：辩论引擎不可用时降级
  4. enrich_case_with_debate 注入元数据
"""
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
for _p in [_THIS_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import unittest
from unittest.mock import MagicMock, patch
from core.debate_integration import (
    should_run_debate,
    is_high_value,
    run_debate_for_case,
    enrich_case_with_debate,
    DEBATE_CONFIDENCE_THRESHOLD,
    DEBATE_OUTCOMES,
    HIGH_VALUE_KEYWORDS,
)


class TestShouldRunDebate(unittest.TestCase):
    """1. should_run_debate 触发条件"""

    def test_low_confidence_triggers_debate(self):
        self.assertTrue(should_run_debate(confidence=0.2, outcome="success"))

    def test_high_confidence_success_does_not_trigger(self):
        self.assertFalse(should_run_debate(confidence=0.8, outcome="success"))

    def test_failure_triggers_debate(self):
        self.assertTrue(should_run_debate(confidence=0.9, outcome="failure"))

    def test_partial_triggers_debate(self):
        self.assertTrue(should_run_debate(confidence=0.9, outcome="partial"))

    def test_high_value_keyword_triggers_debate(self):
        self.assertTrue(
            should_run_debate(confidence=0.9, outcome="success", intent="架构重构")
        )

    def test_english_high_value_keyword_triggers(self):
        self.assertTrue(
            should_run_debate(
                confidence=0.9, outcome="success", intent="migration plan",
            )
        )

    def test_no_trigger_safe_default(self):
        self.assertFalse(should_run_debate(confidence=0.8, outcome="success", intent="test"))


class TestIsHighValue(unittest.TestCase):
    """2. is_high_value 高价值判断"""

    def test_high_value_keywords_in_intent(self):
        for kw in HIGH_VALUE_KEYWORDS:
            self.assertTrue(is_high_value(intent=f"task about {kw}"))

    def test_high_value_keywords_in_learned(self):
        self.assertTrue(is_high_value(intent="task", learned=["核心逻辑需要重构"]))

    def test_low_value_returns_false(self):
        self.assertFalse(is_high_value(intent="simple task", learned=["minor fix"]))

    def test_empty_returns_false(self):
        self.assertFalse(is_high_value(intent="", learned=[]))


class TestFailOpen(unittest.TestCase):
    """3. FAIL-OPEN：辩论引擎不可用时降级"""

    def _mock_case(self, confidence=0.2, outcome="failure", intent="critical task"):
        case = MagicMock()
        case.intent = intent
        case.actions = ["do_something"]
        case.outcome_text = ""
        case.learned = []
        case.confidence = confidence
        case.metadata = {"outcome": outcome}
        return case

    def test_debate_engine_not_available_returns_none(self):
        """辩论引擎不可用时返回 None（FAIL-OPEN）"""
        case = self._mock_case()
        with patch("core.debate_integration._load_debate_engine", return_value=None):
            result = run_debate_for_case(case)
        self.assertIsNone(result)

    def test_no_debate_needed_returns_none(self):
        """不需要辩论时返回 None"""
        case = self._mock_case(confidence=0.9, outcome="success", intent="simple")
        result = run_debate_for_case(case)
        self.assertIsNone(result)

    def test_debate_exception_returns_none(self):
        """辩论执行异常时返回 None（FAIL-OPEN）"""
        case = self._mock_case()
        mock_engine = MagicMock()
        mock_engine.run_fast = MagicMock(side_effect=Exception("test error"))
        with patch("core.debate_integration._load_debate_engine", return_value=mock_engine):
            result = run_debate_for_case(case)
        self.assertIsNone(result)


class TestEnrichCaseWithDebate(unittest.TestCase):
    """4. enrich_case_with_debate 注入元数据"""

    def test_enrich_injects_debate_metadata(self):
        """成功执行辩论后注入 metadata['debate']"""
        case = MagicMock()
        case.intent = "critical architecture migration"
        case.actions = ["do_something"]
        case.outcome_text = ""
        case.learned = []
        case.confidence = 0.2
        case.metadata = {"outcome": "failure"}

        mock_engine = MagicMock()
        mock_engine.run_fast = MagicMock(return_value={
            "bull_thesis": "bull says go",
            "bull_confidence": 0.7,
            "bear_thesis": "bear says stop",
            "bear_confidence": 0.3,
        })
        with patch("core.debate_integration._load_debate_engine", return_value=mock_engine):
            with patch("core.debate_integration.asyncio.run", return_value={
                "bull_thesis": "bull says go",
                "bull_confidence": 0.7,
                "bear_thesis": "bear says stop",
                "bear_confidence": 0.3,
            }):
                enriched = enrich_case_with_debate(case)

        self.assertIn("debate", case.metadata)
        self.assertEqual(case.metadata["debate"]["bull_confidence"], 0.7)
        self.assertEqual(case.metadata["debate"]["bear_confidence"], 0.3)

    def test_enrich_engine_not_available_no_change(self):
        """引擎不可用时不修改 case"""
        case = MagicMock()
        case.intent = "test"
        case.actions = ["do"]
        case.confidence = 0.2
        case.metadata = {"outcome": "failure"}

        with patch("core.debate_integration._load_debate_engine", return_value=None):
            enrich_case_with_debate(case)

        self.assertNotIn("debate", case.metadata)

    def test_enrich_no_debate_needed_no_change(self):
        """不需要辩论时不修改 case"""
        case = MagicMock()
        case.intent = "simple"
        case.actions = ["do"]
        case.confidence = 0.9
        case.metadata = {"outcome": "success"}

        result = enrich_case_with_debate(case)
        self.assertNotIn("debate", case.metadata)


class TestFullIntegrationChain(unittest.TestCase):
    """P3 完整集成链路验证"""

    def test_p3_to_p2_to_p1_chain(self):
        """P3(辩论) → P2(C-Drive) → P1(语义) 完整降级链"""
        from core.decision_deriver import derive_expected_decision_with_cdrive

        # 模拟复杂案例
        case = MagicMock()
        case.intent = "critical architecture decision"
        case.actions = ["do_migration"]
        case.outcome_text = ""
        case.learned = ["核心逻辑需要重构"]
        case.confidence = 0.15  # 极低 confidence
        case.metadata = {"outcome": "failure"}

        # P3: 注入辩论元数据
        mock_engine = MagicMock()
        with patch("core.debate_integration._load_debate_engine", return_value=mock_engine):
            with patch("core.debate_integration.asyncio.run", return_value={
                "bull_confidence": 0.2,
                "bear_confidence": 0.15,
                "bull_thesis": "bull",
                "bear_thesis": "bear",
            }):
                enrich_case_with_debate(case)

        # 此时 case 应有 debate 元数据
        self.assertIn("debate", case.metadata)

        # P2: C-Drive 应基于低 confidence 返回 REDO
        decision = derive_expected_decision_with_cdrive(case)
        self.assertEqual(decision, "REDO")

    def test_p3_failopen_falls_to_p2_p1(self):
        """P3 引擎不可用 → 降级到 P2 → P1"""
        from core.decision_deriver import derive_expected_decision_with_cdrive

        case = MagicMock()
        case.intent = "test"
        case.actions = ["retry_step"]
        case.outcome_text = ""
        case.learned = []
        case.confidence = 0.5
        case.metadata = {"outcome": "failure"}

        # P3: 引擎不可用
        with patch("core.debate_integration._load_debate_engine", return_value=None):
            enrich_case_with_debate(case)

        # 无 debate 元数据
        self.assertNotIn("debate", case.metadata)

        # P2/P1: 应基于 action 关键词 "retry" 返回 REDO
        decision = derive_expected_decision_with_cdrive(case)
        self.assertEqual(decision, "REDO")


if __name__ == "__main__":
    unittest.main()
