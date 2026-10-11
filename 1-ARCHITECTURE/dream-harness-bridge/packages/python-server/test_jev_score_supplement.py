#!/usr/bin/env python3
"""test_jev_score_supplement.py — 方案A 补充评分 TDD (RED)

SPEC debate-jev-integration-spec.md §5:
- JevScoreSupplement.supplement(topic, transcript, adjudication_result) -> dict
- jev score 补充客观维度(事实真实性/逻辑有效性)
- 加权融合 0.6*LLM + 0.4*jev
- 仅客观维度，主观维度保留 LLM
"""
from __future__ import annotations
import os, sys, unittest
from unittest.mock import MagicMock

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


def _make_adj():
    from adjudicator import AdjudicationResult
    return AdjudicationResult(
        topic="BTC是数字黄金",
        bull_turn_scores=[{"turn": 1}],
        bear_turn_scores=[{"turn": 1}],
        bull_total=24.0, bear_total=18.0,
        dimension_comparison={
            "fact_authenticity": {"bull": 4.0, "bear": 3.0},
            "logical_validity": {"bull": 4.0, "bear": 2.0},
            "clarity": {"bull": 4.0, "bear": 3.0},
            "emotional_appeal": {"bull": 5.0, "bear": 2.0},
        },
        winner="bull", rfd="正方领先", key_clash_points=["稀缺性"],
        rebuttal_strength={}, evidence_depth={}, timestamp="",
    )


def _make_transcript():
    return [
        {"speaker": "bull", "round": 1, "content": {"thesis": "BTC稀缺", "arguments": ["2100万"]}},
        {"speaker": "bear", "round": 1, "content": {"thesis": "BTC波动大", "arguments": ["20%"]}},
    ]


class TestImport(unittest.TestCase):
    def test_import(self):
        from jev_score_supplement import JevScoreSupplement  # noqa: F401


class TestFailOpen(unittest.TestCase):
    def test_no_jev_fn_degraded(self):
        """无 jev_fn → degraded=True，保留 LLM 评分。"""
        from jev_score_supplement import JevScoreSupplement
        s = JevScoreSupplement(jev_fn=None)
        result = s.supplement("BTC", _make_transcript(), _make_adj())
        self.assertTrue(result["degraded"])

    def test_jev_degraded(self):
        """jev degraded → 保留 LLM。"""
        from jev_score_supplement import JevScoreSupplement
        jev = MagicMock(return_value={"answers": {}, "degraded": True})
        s = JevScoreSupplement(jev_fn=jev)
        result = s.supplement("BTC", _make_transcript(), _make_adj())
        self.assertTrue(result["degraded"])


class TestSupplement(unittest.TestCase):
    def test_returns_objective_dims(self):
        """返回 fact_authenticity + logical_validity。"""
        from jev_score_supplement import JevScoreSupplement
        jev = MagicMock(return_value={
            "answers": {
                "fact_bull": {"score": 4}, "fact_bear": {"score": 3},
                "logic_bull": {"score": 5}, "logic_bear": {"score": 2},
            },
            "degraded": False})
        s = JevScoreSupplement(jev_fn=jev)
        result = s.supplement("BTC", _make_transcript(), _make_adj())
        self.assertIn("fact_authenticity", result)
        self.assertIn("logical_validity", result)
        self.assertNotIn("clarity", result)  # 主观维度不补充

    def test_score_range_1_to_5(self):
        """融合后分数在 1-5。"""
        from jev_score_supplement import JevScoreSupplement
        jev = MagicMock(return_value={
            "answers": {
                "fact_bull": {"score": 5}, "fact_bear": {"score": 1},
                "logic_bull": {"score": 5}, "logic_bear": {"score": 1},
            },
            "degraded": False})
        s = JevScoreSupplement(jev_fn=jev, jev_weight=0.4)
        result = s.supplement("BTC", _make_transcript(), _make_adj())
        for dim in ["fact_authenticity", "logical_validity"]:
            for side in ["bull", "bear"]:
                val = result[dim][side]
                self.assertGreaterEqual(val, 1.0)
                self.assertLessEqual(val, 5.0)

    def test_fusion_weights(self):
        """融合 = 0.6*LLM + 0.4*jev。"""
        from jev_score_supplement import JevScoreSupplement
        # LLM fact_bull=4, jev=5 → 0.6*4+0.4*5=4.4
        jev = MagicMock(return_value={
            "answers": {
                "fact_bull": {"score": 5}, "fact_bear": {"score": 3},
                "logic_bull": {"score": 4}, "logic_bear": {"score": 2},
            },
            "degraded": False})
        s = JevScoreSupplement(jev_fn=jev, jev_weight=0.4)
        adj = _make_adj()
        result = s.supplement("BTC", _make_transcript(), adj)
        # LLM fact_bull=4.0, jev=5 → 0.6*4 + 0.4*5 = 4.4
        self.assertAlmostEqual(result["fact_authenticity"]["bull"], 4.4, places=1)

    def test_applies_to_adjudication_result(self):
        """apply 方法更新 adjudication_result 的客观维度。"""
        from jev_score_supplement import JevScoreSupplement
        jev = MagicMock(return_value={
            "answers": {
                "fact_bull": {"score": 5}, "fact_bear": {"score": 3},
                "logic_bull": {"score": 5}, "logic_bear": {"score": 2},
            },
            "degraded": False})
        s = JevScoreSupplement(jev_fn=jev, jev_weight=0.4)
        adj = _make_adj()
        s.apply("BTC", _make_transcript(), adj)
        # LLM fact_bull=4, jev=5 → 4.4
        self.assertAlmostEqual(
            adj.dimension_comparison["fact_authenticity"]["bull"], 4.4, places=1)
        # 主观维度不变
        self.assertEqual(adj.dimension_comparison["clarity"]["bull"], 4.0)
        self.assertEqual(adj.dimension_comparison["emotional_appeal"]["bull"], 5.0)


class TestJevQuestions(unittest.TestCase):
    def test_four_score_questions(self):
        """4 个 score 问题：fact_bull/fact_bear/logic_bull/logic_bear。"""
        from jev_score_supplement import JevScoreSupplement
        jev = MagicMock(return_value={
            "answers": {
                "fact_bull": {"score": 4}, "fact_bear": {"score": 3},
                "logic_bull": {"score": 4}, "logic_bear": {"score": 2},
            },
            "degraded": False})
        s = JevScoreSupplement(jev_fn=jev)
        s.supplement("BTC", _make_transcript(), _make_adj())
        questions = jev.call_args[0][1]
        self.assertEqual(len(questions), 4)
        for q in questions.values():
            self.assertEqual(q["type"], "score")
            self.assertEqual(len(q["criteria"]), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
