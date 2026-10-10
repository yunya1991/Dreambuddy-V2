#!/usr/bin/env python3
"""test_adjudicator.py — 裁判评审层单元测试 (TDD RED→GREEN)

SPEC v1.2-rc1 §3 Layer 1: Adjudication
- AdjudicationResult dataclass (6维评分 + winner + rfd + key_clash_points)
- Adjudicator.adjudicate(transcript, verdict) → AdjudicationResult
- 6维: clarity/arrangement/topic_relevance/emotional_appeal (主观) + fact_authenticity/logical_validity (客观)
- 自评偏差声明 (M1): "你是独立裁判不是辩手" Prompt 框架
- FAIL-OPEN: 无 LLM 或异常时返回降级结果
- 与 Verdict 共存 (m6): 在 Verdict 之后异步执行
"""
from __future__ import annotations
import json, os, sys, unittest
from unittest.mock import MagicMock, patch

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


# ── mock LLM ──────────────────────────────────────────────────

def _make_adjudication_llm():
    """创建 mock LLM，返回6维评分 JSON。"""
    score_json = json.dumps({
        "bull": {
            "clarity": 4, "arrangement": 3, "topic_relevance": 5,
            "emotional_appeal": 3, "fact_authenticity": 4, "logical_validity": 4,
        },
        "bear": {
            "clarity": 3, "arrangement": 4, "topic_relevance": 4,
            "emotional_appeal": 2, "fact_authenticity": 3, "logical_validity": 3,
        },
        "rfd": "正方在事实真实性和话题切题维度领先，反方论点编排更优但情感诉求不足。",
        "key_clash_points": ["稀缺性vs波动性", "数字黄金定义之争"],
    })

    def llm_fn(prompt, max_tokens=600):
        return score_json
    return llm_fn


def _make_transcript():
    """创建 mock 辩论 transcript。"""
    return [
        {"speaker": "bull", "round": 1, "content": {
            "thesis": "BTC 稀缺性决定长期价值",
            "arguments": ["2100万枚上限", "减半周期", "机构采用"],
            "quote": "数字黄金不是投机",
            "confidence": 0.85,
        }, "persona": "乐观分析师"},
        {"speaker": "bear", "round": 1, "content": {
            "thesis": "BTC 波动性远超黄金",
            "arguments": ["单日波动可达20%", "与风险资产高相关"],
            "quote": "黄金一天跌20%就不是黄金了",
            "confidence": 0.72,
        }, "persona": "谨慎风控师"},
    ]


def _make_verdict():
    """创建 mock Verdict。"""
    return {
        "summary": "正方论据更充分",
        "winner": "bull",
        "key_insights": ["稀缺性是核心", "波动性需时间验证"],
        "topic_angle": "数字黄金的进化论",
    }


# ── Tests ─────────────────────────────────────────────────────

class TestImport(unittest.TestCase):
    """RED: adjudicator 模块可导入。"""

    def test_import_adjudication_result(self):
        from adjudicator import AdjudicationResult  # noqa: F401

    def test_import_adjudicator(self):
        from adjudicator import Adjudicator  # noqa: F401


class TestAdjudicationResult(unittest.TestCase):
    """AdjudicationResult dataclass 字段验证。"""

    def test_has_six_dimension_fields(self):
        """6维评分字段存在。"""
        from adjudicator import AdjudicationResult
        result = AdjudicationResult(
            topic="测试话题",
            bull_turn_scores=[],
            bear_turn_scores=[],
            bull_total=20.0,
            bear_total=18.0,
            dimension_comparison={},
            winner="bull",
            rfd="正方领先",
            key_clash_points=[],
            rebuttal_strength={},
            evidence_depth={},
            timestamp="2026-01-01T00:00:00",
        )
        self.assertEqual(result.topic, "测试话题")
        self.assertEqual(result.winner, "bull")
        self.assertEqual(result.bull_total, 20.0)
        self.assertEqual(result.bear_total, 18.0)

    def test_to_dict_serializable(self):
        """AdjudicationResult 可序列化为 JSON。"""
        from adjudicator import AdjudicationResult
        result = AdjudicationResult(
            topic="测试",
            bull_turn_scores=[{"turn": 1, "clarity": 4}],
            bear_turn_scores=[{"turn": 1, "clarity": 3}],
            bull_total=20.0,
            bear_total=18.0,
            dimension_comparison={"clarity": {"bull": 4.0, "bear": 3.0}},
            winner="bull",
            rfd="测试RFD",
            key_clash_points=["交锋点1"],
            rebuttal_strength={"bull": 4, "bear": 3},
            evidence_depth={"bull": 3, "bear": 4},
            timestamp="2026-01-01T00:00:00",
        )
        d = result.to_dict()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["winner"], "bull")
        # 可 JSON 序列化
        json.dumps(d)


class TestAdjudicate(unittest.TestCase):
    """Adjudicator.adjudicate() 核心逻辑。"""

    def test_adjudicate_returns_result(self):
        """adjudicate 返回 AdjudicationResult。"""
        from adjudicator import Adjudicator, AdjudicationResult
        adj = Adjudicator(llm_fn=_make_adjudication_llm())
        result = adj.adjudicate(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict=_make_verdict(),
        )
        self.assertIsInstance(result, AdjudicationResult)

    def test_six_dimensions_scored(self):
        """6维评分均完成，每维 1-5 分。"""
        from adjudicator import Adjudicator
        adj = Adjudicator(llm_fn=_make_adjudication_llm())
        result = adj.adjudicate(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict=_make_verdict(),
        )
        # 6维应该都在 dimension_comparison 中
        dims = result.dimension_comparison
        for dim in ["clarity", "arrangement", "topic_relevance",
                     "emotional_appeal", "fact_authenticity", "logical_validity"]:
            self.assertIn(dim, dims, f"维度 {dim} 缺失")
            self.assertIn("bull", dims[dim])
            self.assertIn("bear", dims[dim])
            self.assertGreaterEqual(dims[dim]["bull"], 1)
            self.assertLessEqual(dims[dim]["bull"], 5)

    def test_winner_determined_by_total(self):
        """胜方由总分决定。"""
        from adjudicator import Adjudicator
        adj = Adjudicator(llm_fn=_make_adjudication_llm())
        result = adj.adjudicate(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict=_make_verdict(),
        )
        self.assertEqual(result.winner, "bull")

    def test_rfd_generated(self):
        """RFD (Reason for Decision) 已生成。"""
        from adjudicator import Adjudicator
        adj = Adjudicator(llm_fn=_make_adjudication_llm())
        result = adj.adjudicate(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict=_make_verdict(),
        )
        self.assertTrue(result.rfd)
        self.assertIsInstance(result.rfd, str)
        self.assertGreater(len(result.rfd), 10)

    def test_key_clash_points_extracted(self):
        """关键交锋点已提取。"""
        from adjudicator import Adjudicator
        adj = Adjudicator(llm_fn=_make_adjudication_llm())
        result = adj.adjudicate(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict=_make_verdict(),
        )
        self.assertIsInstance(result.key_clash_points, list)
        self.assertGreater(len(result.key_clash_points), 0)

    def test_bull_total_in_range(self):
        """总分在 6-30 范围内。"""
        from adjudicator import Adjudicator
        adj = Adjudicator(llm_fn=_make_adjudication_llm())
        result = adj.adjudicate(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict=_make_verdict(),
        )
        self.assertGreaterEqual(result.bull_total, 6)
        self.assertLessEqual(result.bull_total, 30)
        self.assertGreaterEqual(result.bear_total, 6)
        self.assertLessEqual(result.bear_total, 30)


class TestFailOpen(unittest.TestCase):
    """FAIL-OPEN: 无 LLM 或异常时不崩溃。"""

    def test_no_llm_returns_degraded(self):
        """无 LLM 时返回降级结果。"""
        from adjudicator import Adjudicator, AdjudicationResult
        adj = Adjudicator(llm_fn=None)
        result = adj.adjudicate(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict=_make_verdict(),
        )
        self.assertIsInstance(result, AdjudicationResult)
        # 降级时用 Verdict 的 winner
        self.assertEqual(result.winner, _make_verdict()["winner"])

    def test_llm_exception_returns_degraded(self):
        """LLM 抛异常时返回降级结果。"""
        from adjudicator import Adjudicator, AdjudicationResult

        def bad_llm(prompt, max_tokens=600):
            raise RuntimeError("LLM 调用失败")

        adj = Adjudicator(llm_fn=bad_llm)
        result = adj.adjudicate(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict=_make_verdict(),
        )
        self.assertIsInstance(result, AdjudicationResult)
        # FAIL-OPEN: 降级用 Verdict winner
        self.assertEqual(result.winner, "bull")

    def test_llm_returns_garbage_returns_degraded(self):
        """LLM 返回无法解析的内容时降级。"""
        from adjudicator import Adjudicator, AdjudicationResult

        def garbage_llm(prompt, max_tokens=600):
            return "这不是JSON"

        adj = Adjudicator(llm_fn=garbage_llm)
        result = adj.adjudicate(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict=_make_verdict(),
        )
        self.assertIsInstance(result, AdjudicationResult)


class TestBiasDeclaration(unittest.TestCase):
    """M1: 自评偏差声明 — Prompt 使用"独立裁判"框架。"""

    def test_prompt_contains_bias_warning(self):
        """评分 Prompt 包含自评偏差声明。"""
        from adjudicator import ADJUDICATION_PROMPT
        self.assertIn("独立裁判", ADJUDICATION_PROMPT)
        self.assertIn("不是辩手", ADJUDICATION_PROMPT)


class TestVerdictCoexistence(unittest.TestCase):
    """m6: 与 Verdict 共存 — Adjudication 在 Verdict 之后执行。"""

    def test_uses_verdict_winner_as_fallback(self):
        """FAIL-OPEN 降级时使用 Verdict 的 winner。"""
        from adjudicator import Adjudicator
        adj = Adjudicator(llm_fn=None)
        result = adj.adjudicate(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            verdict={"winner": "draw", "summary": "平局"},
        )
        self.assertEqual(result.winner, "draw")


if __name__ == "__main__":
    unittest.main(verbosity=2)
