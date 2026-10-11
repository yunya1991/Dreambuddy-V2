#!/usr/bin/env python3
"""test_debate_quality_gate.py — 方案C 辩论质量门控 TDD (RED)

SPEC debate-jev-integration-spec.md §3:
- DebateQualityGate.gate(topic, transcript, adjudication_result, debate_count) -> QualityGateResult
- jev noul 判断辩论质量, noul < threshold 跳过训练
- 冷启动(debate_count<20)使用 cold_start_threshold
- FAIL-OPEN: jev 不可用 → passed=True
"""
from __future__ import annotations
import os, sys, unittest
from unittest.mock import MagicMock

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


def _make_adj_result():
    from adjudicator import AdjudicationResult
    return AdjudicationResult(
        topic="BTC是数字黄金",
        bull_turn_scores=[{"turn": 1, "clarity": 4}],
        bear_turn_scores=[{"turn": 1, "clarity": 3}],
        bull_total=24.0, bear_total=18.0,
        dimension_comparison={"clarity": {"bull": 4.0, "bear": 3.0}},
        winner="bull",
        rfd="正方领先",
        key_clash_points=["稀缺性vs波动性"],
        rebuttal_strength={}, evidence_depth={},
        timestamp="2026-10-11T00:00:00",
    )


def _make_transcript():
    return [
        {"speaker": "bull", "round": 1, "content": {"thesis": "BTC稀缺", "arguments": ["2100万"]},
         "persona": "乐观"},
        {"speaker": "bear", "round": 1, "content": {"thesis": "BTC波动大", "arguments": ["20%波动"]},
         "persona": "谨慎"},
    ]


class TestImport(unittest.TestCase):
    def test_import_debate_quality_gate(self):
        from debate_quality_gate import DebateQualityGate, QualityGateResult  # noqa: F401


class TestFailOpen(unittest.TestCase):
    """HC-J1: FAIL-OPEN — jev 不可用时不阻塞训练。"""

    def test_no_jev_fn_passes(self):
        """无 jev_fn → degraded=True, passed=True。"""
        from debate_quality_gate import DebateQualityGate
        gate = DebateQualityGate(jev_fn=None)
        result = gate.gate("BTC", _make_transcript(), _make_adj_result(), 100)
        self.assertTrue(result.degraded)
        self.assertTrue(result.passed)

    def test_jev_returns_degraded_passes(self):
        """jev 返回 degraded=True → passed=True。"""
        from debate_quality_gate import DebateQualityGate
        jev = MagicMock(return_value={"answers": {}, "degraded": True, "reason": "api_error"})
        gate = DebateQualityGate(jev_fn=jev)
        result = gate.gate("BTC", _make_transcript(), _make_adj_result(), 100)
        self.assertTrue(result.degraded)
        self.assertTrue(result.passed)

    def test_jev_exception_passes(self):
        """jev 异常 → degraded=True, passed=True。"""
        from debate_quality_gate import DebateQualityGate
        jev = MagicMock(side_effect=RuntimeError("API down"))
        gate = DebateQualityGate(jev_fn=jev)
        result = gate.gate("BTC", _make_transcript(), _make_adj_result(), 100)
        self.assertTrue(result.degraded)
        self.assertTrue(result.passed)

    def test_jev_missing_noul_passes(self):
        """jev answers 无 noul 字段 → degraded=True, passed=True。"""
        from debate_quality_gate import DebateQualityGate
        jev = MagicMock(return_value={"answers": {"q1": {"type": "noul"}}, "degraded": False})
        gate = DebateQualityGate(jev_fn=jev)
        result = gate.gate("BTC", _make_transcript(), _make_adj_result(), 100)
        self.assertTrue(result.degraded)
        self.assertTrue(result.passed)


class TestGateLogic(unittest.TestCase):
    """门控逻辑：noul >= threshold 放行，否则阻止。"""

    def test_noul_above_threshold_passes(self):
        """noul=0.8 >= 0.55 → passed=True。"""
        from debate_quality_gate import DebateQualityGate
        jev = MagicMock(return_value={
            "answers": {"q1": {"noul": 0.8}}, "degraded": False})
        gate = DebateQualityGate(jev_fn=jev, threshold=0.55)
        result = gate.gate("BTC", _make_transcript(), _make_adj_result(), 100)
        self.assertFalse(result.degraded)
        self.assertTrue(result.passed)
        self.assertAlmostEqual(result.noul, 0.8)

    def test_noul_below_threshold_blocks(self):
        """noul=0.3 < 0.55 → passed=False。"""
        from debate_quality_gate import DebateQualityGate
        jev = MagicMock(return_value={
            "answers": {"q1": {"noul": 0.3}}, "degraded": False})
        gate = DebateQualityGate(jev_fn=jev, threshold=0.55)
        result = gate.gate("BTC", _make_transcript(), _make_adj_result(), 100)
        self.assertFalse(result.passed)

    def test_noul_at_threshold_passes(self):
        """noul == threshold → passed=True（边界）。"""
        from debate_quality_gate import DebateQualityGate
        jev = MagicMock(return_value={
            "answers": {"q1": {"noul": 0.55}}, "degraded": False})
        gate = DebateQualityGate(jev_fn=jev, threshold=0.55)
        result = gate.gate("BTC", _make_transcript(), _make_adj_result(), 100)
        self.assertTrue(result.passed)


class TestColdStart(unittest.TestCase):
    """HC-J4: 冷启动阶段使用低阈值。"""

    def test_cold_start_uses_low_threshold(self):
        """debate_count=5 < 20 → 使用 cold_start_threshold=0.35。"""
        from debate_quality_gate import DebateQualityGate
        # noul=0.4: 正常阈值0.55会阻止, 冷启动0.35会放行
        jev = MagicMock(return_value={
            "answers": {"q1": {"noul": 0.4}}, "degraded": False})
        gate = DebateQualityGate(jev_fn=jev, threshold=0.55,
                                 cold_start_threshold=0.35)
        result = gate.gate("BTC", _make_transcript(), _make_adj_result(), 5)
        self.assertTrue(result.passed, "冷启动应使用低阈值放行")

    def test_normal_uses_high_threshold(self):
        """debate_count=100 >= 20 → 使用正常 threshold=0.55。"""
        from debate_quality_gate import DebateQualityGate
        jev = MagicMock(return_value={
            "answers": {"q1": {"noul": 0.4}}, "degraded": False})
        gate = DebateQualityGate(jev_fn=jev, threshold=0.55,
                                 cold_start_threshold=0.35)
        result = gate.gate("BTC", _make_transcript(), _make_adj_result(), 100)
        self.assertFalse(result.passed, "正常阶段应使用高阈值阻止")


class TestJevCall(unittest.TestCase):
    """jev 调用参数正确性。"""

    def test_jev_receives_state_and_questions(self):
        """jev_fn 接收 state(dict) 和 questions(dict)。"""
        from debate_quality_gate import DebateQualityGate
        jev = MagicMock(return_value={
            "answers": {"q1": {"noul": 0.9}}, "degraded": False})
        gate = DebateQualityGate(jev_fn=jev)
        gate.gate("BTC是数字黄金", _make_transcript(), _make_adj_result(), 100)
        jev.assert_called_once()
        state, questions = jev.call_args[0]
        self.assertIsInstance(state, dict)
        self.assertIn("topic", state)
        self.assertIn("winner", state)
        self.assertIsInstance(questions, dict)
        q = list(questions.values())[0]
        self.assertEqual(q["type"], "noul")
        self.assertIn("instructions", q)

    def test_state_contains_clash_points(self):
        """state 包含 key_clash_points。"""
        from debate_quality_gate import DebateQualityGate
        jev = MagicMock(return_value={
            "answers": {"q1": {"noul": 0.9}}, "degraded": False})
        gate = DebateQualityGate(jev_fn=jev)
        gate.gate("BTC", _make_transcript(), _make_adj_result(), 100)
        state = jev.call_args[0][0]
        self.assertIn("key_clash_points", state)


class TestConfig(unittest.TestCase):
    """阈值可配置。"""

    def test_custom_threshold(self):
        """自定义 threshold=0.7。"""
        from debate_quality_gate import DebateQualityGate
        jev = MagicMock(return_value={
            "answers": {"q1": {"noul": 0.65}}, "degraded": False})
        gate = DebateQualityGate(jev_fn=jev, threshold=0.7)
        result = gate.gate("BTC", _make_transcript(), _make_adj_result(), 100)
        self.assertFalse(result.passed)


class TestPipelineIntegration(unittest.TestCase):
    """质量门控集成到 run_post_debate_pipeline。"""

    def _make_llm(self):
        import json
        adj_json = json.dumps({
            "bull": {d: 4 for d in ["clarity", "arrangement", "topic_relevance",
                                     "emotional_appeal", "fact_authenticity", "logical_validity"]},
            "bear": {d: 3 for d in ["clarity", "arrangement", "topic_relevance",
                                     "emotional_appeal", "fact_authenticity", "logical_validity"]},
            "rfd": "正方领先",
            "key_clash_points": ["稀缺性vs波动性"],
        })
        strat_json = json.dumps({
            "bull_strategies": ["evidence-heavy"],
            "bear_strategies": ["disadvantage"],
            "confidence": 0.8,
        })
        refl_json = json.dumps({
            "review": {"key_pivot": "第1轮"},
            "strategy_analysis": {"evidence-heavy": {"effect": 4}},
            "gaps": {"evidence_gaps": [], "dropped_args": [], "unused_tactics": []},
            "recommendations": ["增加数据"],
            "persona_suggestions": {},
        })
        def llm_fn(prompt, max_tokens=600):
            if "分析以下辩论论点" in prompt:
                return strat_json
            if "独立裁判" in prompt:
                return adj_json
            return refl_json
        return llm_fn

    def test_gate_disabled_normal_training(self):
        """门控关闭时正常训练。"""
        from c_drive_agent import run_post_debate_pipeline
        result = run_post_debate_pipeline(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict={"summary": "正方领先", "winner": "bull", "key_insights": [], "topic_angle": ""},
            llm_fn=self._make_llm(),
            enable_quality_gate=False,
        )
        self.assertTrue(result["training"]["bayesian_updated"])
        self.assertNotIn("quality_gated", result["training"])

    def test_gate_enabled_blocks_low_quality(self):
        """门控开启且 noul 低时跳过训练。"""
        from c_drive_agent import run_post_debate_pipeline
        # jev 返回低 noul
        jev = MagicMock(return_value={
            "answers": {"q1": {"noul": 0.2}}, "degraded": False})
        result = run_post_debate_pipeline(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict={"summary": "正方领先", "winner": "bull", "key_insights": [], "topic_angle": ""},
            llm_fn=self._make_llm(),
            jev_fn=jev,
            debate_count=100,
            enable_quality_gate=True,
        )
        self.assertTrue(result["training"].get("quality_gated"))
        self.assertFalse(result["training"]["bayesian_updated"])

    def test_gate_enabled_high_noul_passes(self):
        """门控开启且 noul 高时正常训练。"""
        from c_drive_agent import run_post_debate_pipeline
        jev = MagicMock(return_value={
            "answers": {"q1": {"noul": 0.9}}, "degraded": False})
        result = run_post_debate_pipeline(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict={"summary": "正方领先", "winner": "bull", "key_insights": [], "topic_angle": ""},
            llm_fn=self._make_llm(),
            jev_fn=jev,
            debate_count=100,
            enable_quality_gate=True,
        )
        self.assertFalse(result["training"].get("quality_gated", False))
        self.assertTrue(result["training"]["bayesian_updated"])

    def test_gate_degraded_passes(self):
        """jev 降级时门控放行。"""
        from c_drive_agent import run_post_debate_pipeline
        jev = MagicMock(return_value={"answers": {}, "degraded": True})
        result = run_post_debate_pipeline(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict={"summary": "正方领先", "winner": "bull", "key_insights": [], "topic_angle": ""},
            llm_fn=self._make_llm(),
            jev_fn=jev,
            debate_count=100,
            enable_quality_gate=True,
        )
        self.assertFalse(result["training"].get("quality_gated", False))
        self.assertTrue(result["training"]["bayesian_updated"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
