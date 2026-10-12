"""
智能决策推导器测试 — 验证 C 层 expected_decision 多样性
P1 修复：替代硬编码 CONTINUE

测试覆盖：
  1. outcome 信号推导（success→CONTINUE / failure→纠正 / partial→补充）
  2. confidence 信号推导（低→REDO / 中→INSERT_BEFORE / 高→CONTINUE）
  3. action 关键词推导（retry→REDO / supplement→INSERT_BEFORE / skip→JUMP_TO / abort→EARLY_TERMINATE）
  4. learned 关键词推导
  5. 决策多样性验证（批量案例产生 ≥3 种不同决策）
  6. FAIL-OPEN：空输入安全降级
"""
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
for _p in [_THIS_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import unittest
from unittest.mock import MagicMock
from core.decision_deriver import (
    derive_expected_decision,
    derive_expected_decision_from_case,
    derive_expected_decision_with_cdrive,
    derive_with_cdrive_reflection,
    derive_decision_distribution,
    CDRIVE_CONF_REDO,
    CDRIVE_CONF_SUPPLEMENT,
    CONTINUE,
    REDO,
    INSERT_BEFORE,
    JUMP_TO,
    EARLY_TERMINATE,
)


class TestOutcomeSignal(unittest.TestCase):
    """1. outcome 信号推导"""

    def test_success_returns_continue(self):
        d = derive_expected_decision(
            intent="test", actions=["do_something"],
            outcome="success", confidence=0.9,
        )
        self.assertEqual(d, CONTINUE)

    def test_failure_with_retry_action_returns_redo(self):
        d = derive_expected_decision(
            intent="test", actions=["retry_step"],
            outcome="failure", confidence=0.2,
        )
        self.assertEqual(d, REDO)

    def test_failure_with_supplement_action_returns_insert_before(self):
        d = derive_expected_decision(
            intent="test", actions=["supplement_info"],
            outcome="failure", confidence=0.2,
        )
        self.assertEqual(d, INSERT_BEFORE)

    def test_failure_with_skip_action_returns_jump_to(self):
        d = derive_expected_decision(
            intent="test", actions=["skip_step"],
            outcome="failure", confidence=0.2,
        )
        self.assertEqual(d, JUMP_TO)

    def test_failure_with_abort_action_returns_early_terminate(self):
        d = derive_expected_decision(
            intent="test", actions=["abort_task"],
            outcome="failure", confidence=0.2,
        )
        self.assertEqual(d, EARLY_TERMINATE)

    def test_failure_no_semantics_returns_early_terminate(self):
        d = derive_expected_decision(
            intent="test", actions=["generic_action"],
            outcome="failure", confidence=0.2,
        )
        self.assertEqual(d, EARLY_TERMINATE)

    def test_partial_with_redo_learned_returns_redo(self):
        d = derive_expected_decision(
            intent="test", actions=["generic"],
            outcome="partial", learned=["should redo this step"],
            confidence=0.2,
        )
        self.assertEqual(d, REDO)

    def test_partial_no_semantics_low_confidence_returns_redo(self):
        d = derive_expected_decision(
            intent="test", actions=["generic"],
            outcome="partial", confidence=0.2,
        )
        self.assertEqual(d, REDO)

    def test_partial_no_semantics_medium_confidence_returns_insert_before(self):
        d = derive_expected_decision(
            intent="test", actions=["generic"],
            outcome="partial", confidence=0.5,
        )
        self.assertEqual(d, INSERT_BEFORE)


class TestConfidenceSignal(unittest.TestCase):
    """2. confidence 信号推导（unknown outcome 时）"""

    def test_unknown_low_confidence_returns_redo(self):
        d = derive_expected_decision(
            intent="test", actions=["generic"],
            outcome="unknown", confidence=0.2,
        )
        self.assertEqual(d, REDO)

    def test_unknown_medium_confidence_returns_insert_before(self):
        d = derive_expected_decision(
            intent="test", actions=["generic"],
            outcome="unknown", confidence=0.5,
        )
        self.assertEqual(d, INSERT_BEFORE)

    def test_unknown_high_confidence_returns_continue(self):
        d = derive_expected_decision(
            intent="test", actions=["generic"],
            outcome="unknown", confidence=0.8,
        )
        self.assertEqual(d, CONTINUE)


class TestActionKeywords(unittest.TestCase):
    """3. action 关键词推导"""

    def test_retry_keyword_returns_redo(self):
        for kw in ["retry", "redo", "重做", "重来", "重新"]:
            d = derive_expected_decision(
                intent="test", actions=[kw],
                outcome="failure", confidence=0.2,
            )
            self.assertEqual(d, REDO, f"keyword '{kw}' should map to REDO")

    def test_supplement_keyword_returns_insert_before(self):
        for kw in ["insert", "supplement", "补充", "插入", "追加"]:
            d = derive_expected_decision(
                intent="test", actions=[kw],
                outcome="failure", confidence=0.2,
            )
            self.assertEqual(d, INSERT_BEFORE, f"keyword '{kw}' should map to INSERT_BEFORE")

    def test_skip_keyword_returns_jump_to(self):
        for kw in ["skip", "jump", "跳过", "跳转", "换路"]:
            d = derive_expected_decision(
                intent="test", actions=[kw],
                outcome="failure", confidence=0.2,
            )
            self.assertEqual(d, JUMP_TO, f"keyword '{kw}' should map to JUMP_TO")

    def test_abort_keyword_returns_early_terminate(self):
        for kw in ["abort", "terminate", "终止", "放弃", "中止"]:
            d = derive_expected_decision(
                intent="test", actions=[kw],
                outcome="failure", confidence=0.2,
            )
            self.assertEqual(d, EARLY_TERMINATE, f"keyword '{kw}' should map to EARLY_TERMINATE")


class TestLearnedKeywords(unittest.TestCase):
    """4. learned 关键词推导"""

    def test_missing_info_learned_returns_insert_before(self):
        d = derive_expected_decision(
            intent="test", actions=["generic"],
            outcome="partial", learned=["missing info about X"],
            confidence=0.5,
        )
        self.assertEqual(d, INSERT_BEFORE)

    def test_wrong_path_learned_returns_jump_to(self):
        d = derive_expected_decision(
            intent="test", actions=["generic"],
            outcome="partial", learned=["wrong path taken"],
            confidence=0.5,
        )
        self.assertEqual(d, JUMP_TO)

    def test_should_stop_learned_returns_early_terminate(self):
        d = derive_expected_decision(
            intent="test", actions=["generic"],
            outcome="partial", learned=["should stop this immediately"],
            confidence=0.5,
        )
        self.assertEqual(d, EARLY_TERMINATE)


class TestDecisionDiversity(unittest.TestCase):
    """5. 决策多样性验证"""

    def _mock_case(self, outcome, actions=None, learned=None, confidence=0.4):
        case = MagicMock()
        case.intent = "test"
        case.actions = actions or ["generic"]
        case.outcome_text = ""
        case.learned = learned or []
        case.confidence = confidence
        case.metadata = {"outcome": outcome}
        return case

    def test_batch_cases_produce_at_least_3_decision_types(self):
        cases = [
            # success → CONTINUE
            self._mock_case("success", actions=["normal"], confidence=0.9),
            # failure with retry → REDO
            self._mock_case("failure", actions=["retry_step"], confidence=0.2),
            # failure with supplement → INSERT_BEFORE
            self._mock_case("failure", actions=["supplement_info"], confidence=0.2),
            # failure with skip → JUMP_TO
            self._mock_case("failure", actions=["skip_step"], confidence=0.2),
            # failure with abort → EARLY_TERMINATE
            self._mock_case("failure", actions=["abort_task"], confidence=0.2),
            # partial low confidence → REDO
            self._mock_case("partial", confidence=0.2),
            # partial medium → INSERT_BEFORE
            self._mock_case("partial", confidence=0.5),
        ]
        dist = derive_decision_distribution(cases)
        # 至少 3 种不同决策
        non_zero = [k for k, v in dist.items() if v > 0]
        self.assertGreaterEqual(
            len(non_zero), 3,
            f"Expected ≥3 decision types, got {len(non_zero)}: {dist}",
        )

    def test_no_hardcoded_continue_only(self):
        """验证不再是全 CONTINUE"""
        cases = [
            self._mock_case("failure", actions=["retry"], confidence=0.2),
            self._mock_case("failure", actions=["abort"], confidence=0.2),
            self._mock_case("partial", confidence=0.5),
        ]
        dist = derive_decision_distribution(cases)
        # CONTINUE 应该为 0（全部是 failure/partial 且有语义信号）
        self.assertEqual(dist[CONTINUE], 0, f"Expected 0 CONTINUE, got {dist}")


class TestFailOpen(unittest.TestCase):
    """6. FAIL-OPEN：空输入安全降级"""

    def test_empty_actions_returns_continue(self):
        d = derive_expected_decision(
            intent="", actions=[], outcome="unknown",
            confidence=0.8,
        )
        self.assertEqual(d, CONTINUE)

    def test_none_learned_safe(self):
        d = derive_expected_decision(
            intent="test", actions=["generic"],
            outcome="success", learned=None, confidence=0.9,
        )
        self.assertEqual(d, CONTINUE)

    def test_empty_metadata_safe(self):
        d = derive_expected_decision(
            intent="test", actions=["generic"],
            outcome="unknown", confidence=0.8, metadata=None,
        )
        self.assertEqual(d, CONTINUE)


# ============================================================
# P2: C-Drive Agent 集成测试
# ============================================================

class TestCDriveReflectionNoDebate(unittest.TestCase):
    """P2: C-Drive 无辩论反思（c_drive_agent.py _reflect_no_debate）"""

    def test_low_confidence_returns_redo(self):
        """confidence < CDRIVE_CONF_REDO → REDO"""
        d = derive_with_cdrive_reflection(confidence=0.15)
        self.assertEqual(d, REDO)

    def test_confidence_at_redo_threshold_returns_none(self):
        """confidence = CDRIVE_CONF_REDO → 不触发 REDO"""
        d = derive_with_cdrive_reflection(confidence=CDRIVE_CONF_REDO)
        self.assertIsNone(d)

    def test_high_confidence_no_debate_returns_none(self):
        """confidence >= CDRIVE_CONF_REDO 且无辩论 → None（交由 P1 逻辑）"""
        d = derive_with_cdrive_reflection(confidence=0.5)
        self.assertIsNone(d)


class TestCDriveReflectionWithDebate(unittest.TestCase):
    """P2: C-Drive 辩论后反思（c_drive_agent.py _reflect_after_debate）"""

    def test_low_confidence_with_debate_returns_redo(self):
        """confidence < CDRIVE_CONF_REDO → REDO（优先于辩论结果）"""
        d = derive_with_cdrive_reflection(
            confidence=0.15,
            bull_confidence=0.8, bear_confidence=0.7,
        )
        self.assertEqual(d, REDO)

    def test_both_bull_bear_weak_returns_insert_before(self):
        """max(bull, bear) < CDRIVE_CONF_SUPPLEMENT → INSERT_BEFORE"""
        d = derive_with_cdrive_reflection(
            confidence=0.5,
            bull_confidence=0.2, bear_confidence=0.25,
        )
        self.assertEqual(d, INSERT_BEFORE)

    def test_bull_strong_returns_none(self):
        """max(bull, bear) >= CDRIVE_CONF_SUPPLEMENT → None（辩论后继续）"""
        d = derive_with_cdrive_reflection(
            confidence=0.5,
            bull_confidence=0.6, bear_confidence=0.2,
        )
        self.assertIsNone(d)

    def test_bear_strong_returns_none(self):
        """bear 方强 → None（辩论后继续）"""
        d = derive_with_cdrive_reflection(
            confidence=0.5,
            bull_confidence=0.1, bear_confidence=0.7,
        )
        self.assertIsNone(d)


class TestCDriveCaseIntegration(unittest.TestCase):
    """P2: 增强版 case 推导（C-Drive 优先 + P1 降级）"""

    def _mock_case_with_debate(self, confidence, bull, bear, outcome="partial"):
        case = MagicMock()
        case.intent = "test"
        case.actions = ["generic"]
        case.outcome_text = ""
        case.learned = []
        case.confidence = confidence
        case.metadata = {
            "outcome": outcome,
            "debate": {"bull_confidence": bull, "bear_confidence": bear},
        }
        return case

    def _mock_case_no_debate(self, confidence, outcome="partial", actions=None):
        case = MagicMock()
        case.intent = "test"
        case.actions = actions or ["generic"]
        case.outcome_text = ""
        case.learned = []
        case.confidence = confidence
        case.metadata = {"outcome": outcome}
        return case

    def test_case_with_debate_low_conf_returns_redo(self):
        """有 debate 元数据 + 低 confidence → REDO"""
        case = self._mock_case_with_debate(confidence=0.1, bull=0.8, bear=0.7)
        d = derive_expected_decision_with_cdrive(case)
        self.assertEqual(d, REDO)

    def test_case_with_debate_both_weak_returns_insert_before(self):
        """有 debate 元数据 + bull/bear 均弱 → INSERT_BEFORE"""
        case = self._mock_case_with_debate(confidence=0.5, bull=0.2, bear=0.25)
        d = derive_expected_decision_with_cdrive(case)
        self.assertEqual(d, INSERT_BEFORE)

    def test_case_with_debate_bull_strong_falls_to_p1(self):
        """有 debate 元数据 + bull 强 → 降级到 P1 语义推导"""
        case = self._mock_case_with_debate(
            confidence=0.8, bull=0.7, bear=0.2, outcome="success",
        )
        d = derive_expected_decision_with_cdrive(case)
        self.assertEqual(d, CONTINUE)

    def test_case_no_debate_low_conf_returns_redo(self):
        """无 debate 元数据 + 低 confidence → REDO（C-Drive 无辩论反思）"""
        case = self._mock_case_no_debate(confidence=0.15)
        d = derive_expected_decision_with_cdrive(case)
        self.assertEqual(d, REDO)

    def test_case_no_debate_high_conf_falls_to_p1(self):
        """无 debate 元数据 + 高 confidence → 降级到 P1 语义推导"""
        case = self._mock_case_no_debate(confidence=0.8, outcome="success")
        d = derive_expected_decision_with_cdrive(case)
        self.assertEqual(d, CONTINUE)

    def test_case_no_debate_failure_with_retry_falls_to_p1(self):
        """无 debate 元数据 + failure + retry → P1 推导出 REDO"""
        case = self._mock_case_no_debate(
            confidence=0.5, outcome="failure", actions=["retry_step"],
        )
        d = derive_expected_decision_with_cdrive(case)
        self.assertEqual(d, REDO)


class TestCDriveDecisionDiversity(unittest.TestCase):
    """P2: C-Drive 集成后决策多样性验证"""

    def test_cdrive_integration_provides_more_correction_signals(self):
        """C-Drive 集成应提供更多纠正决策信号"""
        cases = [
            # C-Drive: 低 confidence → REDO
            MagicMock(
                intent="test", actions=["generic"], outcome_text="",
                learned=[], confidence=0.1,
                metadata={"outcome": "unknown"},
            ),
            # C-Drive: debate 均弱 → INSERT_BEFORE
            MagicMock(
                intent="test", actions=["generic"], outcome_text="",
                learned=[], confidence=0.5,
                metadata={
                    "outcome": "partial",
                    "debate": {"bull_confidence": 0.2, "bear_confidence": 0.25},
                },
            ),
            # P1: success → CONTINUE
            MagicMock(
                intent="test", actions=["normal"], outcome_text="",
                learned=[], confidence=0.9,
                metadata={"outcome": "success"},
            ),
            # P1: failure + abort → EARLY_TERMINATE
            MagicMock(
                intent="test", actions=["abort_task"], outcome_text="",
                learned=[], confidence=0.5,
                metadata={"outcome": "failure"},
            ),
        ]
        decisions = [derive_expected_decision_with_cdrive(c) for c in cases]
        unique = set(decisions)
        self.assertGreaterEqual(
            len(unique), 3,
            f"Expected ≥3 unique decisions, got {len(unique)}: {decisions}",
        )
        # 确保不全是 CONTINUE
        self.assertIn(REDO, unique, "REDO should be present")
        self.assertIn(INSERT_BEFORE, unique, "INSERT_BEFORE should be present")
        self.assertIn(CONTINUE, unique, "CONTINUE should be present")


if __name__ == "__main__":
    unittest.main()
