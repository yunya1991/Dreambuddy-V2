#!/usr/bin/env python3
"""test_adjudication_validator.py — 方案B 评审校验 TDD (RED)

SPEC debate-jev-integration-spec.md §4:
- AdjudicationValidator.validate(topic, transcript, adjudication_result) -> ValidationResult
- jev noul 校验评分合理性
- jev choice 校验胜方一致性
- 评分不合理 → 警告不覆盖
- 胜方不一致 → 取 jev 建议胜方
"""
from __future__ import annotations
import os, sys, unittest
from unittest.mock import MagicMock

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


def _make_adj(winner="bull", bull_total=24.0, bear_total=18.0):
    from adjudicator import AdjudicationResult
    return AdjudicationResult(
        topic="BTC是数字黄金",
        bull_turn_scores=[{"turn": 1, "clarity": 4}],
        bear_turn_scores=[{"turn": 1, "clarity": 3}],
        bull_total=bull_total, bear_total=bear_total,
        dimension_comparison={"clarity": {"bull": 4.0, "bear": 3.0}},
        winner=winner,
        rfd="正方在论证清晰度领先",
        key_clash_points=["稀缺性vs波动性"],
        rebuttal_strength={}, evidence_depth={},
        timestamp="2026-10-11T00:00:00",
    )


def _make_transcript():
    return [
        {"speaker": "bull", "round": 1, "content": {"thesis": "BTC稀缺", "arguments": ["2100万"]}},
        {"speaker": "bear", "round": 1, "content": {"thesis": "BTC波动大", "arguments": ["20%"]}},
    ]


class TestImport(unittest.TestCase):
    def test_import(self):
        from adjudication_validator import AdjudicationValidator, ValidationResult  # noqa: F401


class TestFailOpen(unittest.TestCase):
    def test_no_jev_fn_degraded(self):
        """无 jev_fn → degraded=True，评分不变。"""
        from adjudication_validator import AdjudicationValidator
        v = AdjudicationValidator(jev_fn=None)
        adj = _make_adj()
        result = v.validate("BTC", _make_transcript(), adj)
        self.assertTrue(result.degraded)
        self.assertTrue(result.score_reasonable)
        self.assertTrue(result.winner_consistent)

    def test_jev_degraded(self):
        """jev 返回 degraded → 不影响评分。"""
        from adjudication_validator import AdjudicationValidator
        jev = MagicMock(return_value={"answers": {}, "degraded": True})
        v = AdjudicationValidator(jev_fn=jev)
        adj = _make_adj()
        result = v.validate("BTC", _make_transcript(), adj)
        self.assertTrue(result.degraded)

    def test_jev_exception(self):
        """jev 异常 → degraded=True。"""
        from adjudication_validator import AdjudicationValidator
        jev = MagicMock(side_effect=RuntimeError("down"))
        v = AdjudicationValidator(jev_fn=jev)
        result = v.validate("BTC", _make_transcript(), _make_adj())
        self.assertTrue(result.degraded)


class TestScoreValidation(unittest.TestCase):
    def test_score_reasonable(self):
        """noul>=0.5 → score_reasonable=True。"""
        from adjudication_validator import AdjudicationValidator
        jev = MagicMock(return_value={
            "answers": {"score_q": {"noul": 0.8}, "winner_q": {"choice": "bull"}},
            "degraded": False})
        v = AdjudicationValidator(jev_fn=jev)
        adj = _make_adj()
        result = v.validate("BTC", _make_transcript(), adj)
        self.assertTrue(result.score_reasonable)

    def test_score_unreasonable(self):
        """noul<0.5 → score_reasonable=False。"""
        from adjudication_validator import AdjudicationValidator
        jev = MagicMock(return_value={
            "answers": {"score_q": {"noul": 0.2}, "winner_q": {"choice": "bull"}},
            "degraded": False})
        v = AdjudicationValidator(jev_fn=jev)
        adj = _make_adj()
        result = v.validate("BTC", _make_transcript(), adj)
        self.assertFalse(result.score_reasonable)

    def test_unreasonable_does_not_override_scores(self):
        """评分不合理时不覆盖 LLM 评分。"""
        from adjudication_validator import AdjudicationValidator
        jev = MagicMock(return_value={
            "answers": {"score_q": {"noul": 0.1}, "winner_q": {"choice": "bull"}},
            "degraded": False})
        v = AdjudicationValidator(jev_fn=jev)
        adj = _make_adj(bull_total=24.0)
        v.validate("BTC", _make_transcript(), adj)
        # 评分不变
        self.assertEqual(adj.bull_total, 24.0)


class TestWinnerConsistency(unittest.TestCase):
    def test_winner_consistent(self):
        """jev choice 与 LLM winner 一致。"""
        from adjudication_validator import AdjudicationValidator
        jev = MagicMock(return_value={
            "answers": {"score_q": {"noul": 0.8}, "winner_q": {"choice": "bull"}},
            "degraded": False})
        v = AdjudicationValidator(jev_fn=jev)
        adj = _make_adj(winner="bull")
        result = v.validate("BTC", _make_transcript(), adj)
        self.assertTrue(result.winner_consistent)
        self.assertEqual(adj.winner, "bull")

    def test_winner_inconsistent_overrides(self):
        """胜方不一致 → 取 jev 建议胜方。"""
        from adjudication_validator import AdjudicationValidator
        jev = MagicMock(return_value={
            "answers": {"score_q": {"noul": 0.8}, "winner_q": {"choice": "bear"}},
            "degraded": False})
        v = AdjudicationValidator(jev_fn=jev)
        adj = _make_adj(winner="bull")
        result = v.validate("BTC", _make_transcript(), adj)
        self.assertFalse(result.winner_consistent)
        self.assertEqual(adj.winner, "bear")
        self.assertEqual(result.suggested_winner, "bear")


class TestJevCall(unittest.TestCase):
    def test_two_questions(self):
        """jev 接收两个问题：noul(评分) + choice(胜方)。"""
        from adjudication_validator import AdjudicationValidator
        jev = MagicMock(return_value={
            "answers": {"score_q": {"noul": 0.8}, "winner_q": {"choice": "bull"}},
            "degraded": False})
        v = AdjudicationValidator(jev_fn=jev)
        v.validate("BTC", _make_transcript(), _make_adj())
        questions = jev.call_args[0][1]
        types = {q["type"] for q in questions.values()}
        self.assertIn("noul", types)
        self.assertIn("choice", types)


if __name__ == "__main__":
    unittest.main(verbosity=2)
