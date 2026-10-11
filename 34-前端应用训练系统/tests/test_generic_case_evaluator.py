"""GenericCaseEvaluator 单元测试。

测试:
  1. 四维评分各维度正确
  2. INGEST/DEFERRED/SKIP 决策阈值正确
  3. FAIL-OPEN：TDR 不可用时 novelty=0.5
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# sys.path 注入
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ADAPTERS_DIR = os.path.join(os.path.dirname(_THIS_DIR), "adapters")
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)
_SCRIPTS_DIR = os.path.join(_PROJECT_ROOT, "scripts")

for _p in [_THIS_DIR, _ADAPTERS_DIR, _34_DIR, _SCRIPTS_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from generic_case_evaluator import GenericCaseEvaluator
from interfaces.case_evaluator import IngestDecision


class GenericCaseEvaluatorTest(unittest.TestCase):

    def _make_case(self, **kwargs):
        """创建测试案例 dict。"""
        defaults = {
            "intent": "test_feature",
            "actions": ["action1"],
            "learned": ["lesson1"],
            "quality": "B",
            "outcome": "success",
        }
        defaults.update(kwargs)
        return defaults

    def test_significance_success_with_learned(self):
        """success + learned → significance 高分。"""
        evaluator = GenericCaseEvaluator()
        case = self._make_case(outcome="success", learned=["l1"])
        score = evaluator._assess_significance(case)
        self.assertGreaterEqual(score, 0.7)

    def test_significance_failure_no_learned(self):
        """failure + no learned → significance 低分。"""
        evaluator = GenericCaseEvaluator()
        case = self._make_case(outcome="failure", learned=[])
        score = evaluator._assess_significance(case)
        self.assertLess(score, 0.3)

    def test_anomaly_failure_quality_c(self):
        """failure + quality=C → anomaly 高分。"""
        evaluator = GenericCaseEvaluator()
        case = self._make_case(outcome="failure", quality="C", known_gaps=["gap1"])
        score = evaluator._assess_anomaly(case)
        self.assertGreaterEqual(score, 0.7)

    def test_anomaly_success_quality_a(self):
        """success + quality=A → anomaly 低分。"""
        evaluator = GenericCaseEvaluator()
        case = self._make_case(outcome="success", quality="A")
        score = evaluator._assess_anomaly(case)
        self.assertLess(score, 0.3)

    def test_reproducibility_with_evidence(self):
        """有验收证据 + learned + actions + code_path → reproducibility 高分。"""
        evaluator = GenericCaseEvaluator()
        case = self._make_case(
            learned=["l1"],
            actions=["a1"],
            acceptance_evidence={"passed": True},
            code_path="/tmp/test",
        )
        score = evaluator._assess_reproducibility(case)
        self.assertGreaterEqual(score, 0.9)

    def test_reproducibility_empty(self):
        """无验收证据 → reproducibility 低分。"""
        evaluator = GenericCaseEvaluator()
        case = self._make_case(learned=[], actions=[])
        score = evaluator._assess_reproducibility(case)
        self.assertLess(score, 0.3)

    def test_decision_ingest(self):
        """高分案例 → INGEST。"""
        evaluator = GenericCaseEvaluator()
        # mock TDR retrieve 返回空（高新颖性）
        evaluator._tdr_retrieve = MagicMock(return_value={"ok": True, "scores": []})
        case = self._make_case(
            outcome="success", quality="B", learned=["l1"],
            actions=["a1"], known_gaps=["gap1"],
            acceptance_evidence={"passed": True}, code_path="/tmp/test",
        )
        result = evaluator.evaluate(case)
        self.assertEqual(result.decision, IngestDecision.INGEST)

    def test_decision_skip(self):
        """低分案例 → SKIP。"""
        evaluator = GenericCaseEvaluator()
        # mock TDR retrieve 返回高相似度（低新颖性）
        evaluator._tdr_retrieve = MagicMock(return_value={"ok": True, "scores": [0.9]})
        case = self._make_case(
            outcome="success", quality="A", learned=[],
            actions=[], known_gaps=[],
        )
        result = evaluator.evaluate(case)
        self.assertEqual(result.decision, IngestDecision.SKIP)

    def test_fail_open_tdr_unavailable(self):
        """TDR 不可用时 novelty=0.5（中性）。"""
        evaluator = GenericCaseEvaluator()
        with patch.object(evaluator, '_get_tdr_retrieve', return_value=None):
            case = self._make_case()
            score = evaluator._assess_novelty(case)
            self.assertEqual(score, 0.5)


if __name__ == "__main__":
    unittest.main()
