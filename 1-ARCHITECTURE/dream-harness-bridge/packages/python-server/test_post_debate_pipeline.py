#!/usr/bin/env python3
"""test_post_debate_pipeline.py — 辩论后三层管道集成测试 (TDD RED→GREEN)

SPEC v1.2-rc1 §2.2: Verdict 之后异步执行 Layer1→2→3
- run_post_debate_pipeline(topic, transcript, verdict) → dict
- HC1 FAIL-OPEN: 任一层异常不阻塞
- HC10 异步执行: 不阻塞主流程
- HC11 延迟预算: Layer1-3 总延迟 <10s
"""
from __future__ import annotations
import json, os, sys, unittest
from unittest.mock import MagicMock, patch

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


def _make_transcript():
    return [
        {"speaker": "bull", "round": 1, "content": {
            "thesis": "BTC 稀缺性决定长期价值",
            "arguments": ["2100万枚上限", "减半周期"],
            "quote": "数字黄金",
            "confidence": 0.85,
        }, "persona": "乐观分析师"},
        {"speaker": "bear", "round": 1, "content": {
            "thesis": "BTC 波动性远超黄金",
            "arguments": ["单日波动可达20%"],
            "quote": "不是黄金",
            "confidence": 0.72,
        }, "persona": "谨慎风控师"},
    ]


def _make_verdict():
    return {"summary": "正方领先", "winner": "bull",
            "key_insights": [], "topic_angle": ""}


def _make_llm():
    """mock LLM for adjudication + reflection + strategy extraction."""
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
        "bear_strategies": ["counter-example"],
        "confidence": 0.8,
    })
    refl_json = json.dumps({
        "review": {"turn_points": [], "key_pivot": "第1轮", "rfd_summary": "正方领先"},
        "strategy_analysis": {"evidence-heavy": {"used_by": "bull", "effect": 4}},
        "gaps": {"evidence_gaps": [], "dropped_args": [], "unused_tactics": []},
        "recommendations": ["增加数据"],
        "persona_suggestions": {"bull": "加强", "bear": "强化"},
    })

    def llm_fn(prompt, max_tokens=600):
        if "分析以下辩论论点" in prompt:
            return strat_json
        if "独立裁判" in prompt:
            return adj_json
        return refl_json
    return llm_fn


class TestImport(unittest.TestCase):
    def test_import_run_post_debate_pipeline(self):
        from c_drive_agent import run_post_debate_pipeline  # noqa: F401


class TestPipelineExecution(unittest.TestCase):
    """三层管道顺序执行。"""

    def test_pipeline_returns_result(self):
        """管道返回包含三层结果的 dict。"""
        from c_drive_agent import run_post_debate_pipeline
        result = run_post_debate_pipeline(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict=_make_verdict(),
            llm_fn=_make_llm(),
        )
        self.assertIsInstance(result, dict)
        self.assertIn("adjudication", result)
        self.assertIn("reflection", result)
        self.assertIn("training", result)

    def test_pipeline_layer1_adjudication(self):
        """Layer 1 产出 AdjudicationResult。"""
        from c_drive_agent import run_post_debate_pipeline
        result = run_post_debate_pipeline(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict=_make_verdict(),
            llm_fn=_make_llm(),
        )
        adj = result["adjudication"]
        self.assertIn("winner", adj)
        self.assertIn("bull_total", adj)

    def test_pipeline_layer2_reflection(self):
        """Layer 2 产出 ReflectionReport。"""
        from c_drive_agent import run_post_debate_pipeline
        result = run_post_debate_pipeline(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict=_make_verdict(),
            llm_fn=_make_llm(),
        )
        refl = result["reflection"]
        self.assertIn("strategy_tags", refl)
        self.assertIn("recommendations", refl)

    def test_pipeline_layer3_training(self):
        """Layer 3 更新训练参数。"""
        from c_drive_agent import run_post_debate_pipeline
        result = run_post_debate_pipeline(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict=_make_verdict(),
            llm_fn=_make_llm(),
            bull_persona="乐观分析师",
            bear_persona="谨慎风控师",
        )
        train = result["training"]
        self.assertIn("bayesian_updated", train)
        self.assertIn("elo_updated", train)
        self.assertIn("cbr_ingested", train)


class TestFailOpen(unittest.TestCase):
    """FAIL-OPEN: 任一层异常不阻塞。"""

    def test_no_llm_returns_degraded(self):
        """无 LLM 时返回降级结果。"""
        from c_drive_agent import run_post_debate_pipeline
        result = run_post_debate_pipeline(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict=_make_verdict(),
            llm_fn=None,
        )
        self.assertIsInstance(result, dict)
        # 降级时仍有结构
        self.assertIn("adjudication", result)

    def test_llm_exception_returns_degraded(self):
        """LLM 异常时返回降级结果。"""
        from c_drive_agent import run_post_debate_pipeline

        def bad_llm(prompt, max_tokens=600):
            raise RuntimeError("LLM 失败")

        result = run_post_debate_pipeline(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict=_make_verdict(),
            llm_fn=bad_llm,
        )
        self.assertIsInstance(result, dict)
        # 降级时 winner 用 verdict 兜底
        self.assertEqual(result["adjudication"]["winner"], "bull")


class TestPersonasPassed(unittest.TestCase):
    """Persona 名称传入管道用于 Elo 更新。"""

    def test_personas_from_transcript(self):
        """无显式传入时从 transcript 提取 persona。"""
        from c_drive_agent import run_post_debate_pipeline
        result = run_post_debate_pipeline(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),  # transcript 含 persona
            verdict=_make_verdict(),
            llm_fn=_make_llm(),
        )
        # 无异常即通过
        self.assertIn("training", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
