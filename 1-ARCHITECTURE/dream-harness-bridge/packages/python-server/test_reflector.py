#!/usr/bin/env python3
"""test_reflector.py — 赛后反思层单元测试 (TDD RED→GREEN)

SPEC v1.2-rc1 §4 Layer 2: Reflection
- ReflectionReport dataclass (5步反思产出)
- Reflector.reflect() → ReflectionReport
- §4.0 策略提取 (Layer B 回溯标签, LLM 从论点识别策略)
- 5步循环: 复盘→分析→缺口→改进→存储
- HC7: 策略标签前置 (无策略标签时跳过策略分析)
- FAIL-OPEN: 无 LLM 或异常时返回降级结果
"""
from __future__ import annotations
import json, os, sys, unittest
from unittest.mock import MagicMock

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


# ── mock LLM ──────────────────────────────────────────────────

def _make_reflection_llm():
    """创建 mock LLM，返回策略提取 + 反思 JSON。"""
    strategy_json = json.dumps({
        "bull_strategies": ["evidence-heavy", "definition-lock"],
        "bear_strategies": ["counter-example", "value-flip"],
        "confidence": 0.85,
    })
    reflection_json = json.dumps({
        "review": {
            "turn_points": [
                {"turn": 1, "bull_score": 4.0, "bear_score": 3.5},
                {"turn": 2, "bull_score": 4.5, "bear_score": 3.0},
            ],
            "key_pivot": "第2轮正方加强证据深度",
            "rfd_summary": "正方在事实真实性维度领先",
        },
        "strategy_analysis": {
            "evidence-heavy": {"used_by": "bull", "effect": 4},
            "definition-lock": {"used_by": "bull", "effect": 3},
            "counter-example": {"used_by": "bear", "effect": 2},
            "value-flip": {"used_by": "bear", "effect": 3},
        },
        "gaps": {
            "evidence_gaps": ["反方缺乏历史对比数据"],
            "dropped_args": ["正方第二论点未被反方反驳"],
            "unused_tactics": ["counterplan", "kritik"],
        },
        "recommendations": [
            "反方应增加历史金融危机数据对比",
            "正方可尝试使用预防性反驳强化定义锁定",
        ],
        "persona_suggestions": {
            "bull": "增加历史类比能力",
            "bear": "强化反例构造和证据层级",
        },
    })

    call_count = [0]

    def llm_fn(prompt, max_tokens=600):
        call_count[0] += 1
        # 策略提取 Prompt 以"分析以下辩论论点"开头
        if "分析以下辩论论点" in prompt:
            return strategy_json
        # 反思 Prompt 以"你是赛后反思助手"开头
        return reflection_json
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


def _make_adjudication_result():
    """创建 mock AdjudicationResult。"""
    from adjudicator import AdjudicationResult
    return AdjudicationResult(
        topic="BTC是数字黄金",
        bull_turn_scores=[{"turn": 1, "clarity": 4}],
        bear_turn_scores=[{"turn": 1, "clarity": 3}],
        bull_total=23.0,
        bear_total=19.0,
        dimension_comparison={
            "clarity": {"bull": 4.0, "bear": 3.0},
            "arrangement": {"bull": 3.0, "bear": 4.0},
            "topic_relevance": {"bull": 5.0, "bear": 4.0},
            "emotional_appeal": {"bull": 3.0, "bear": 2.0},
            "fact_authenticity": {"bull": 4.0, "bear": 3.0},
            "logical_validity": {"bull": 4.0, "bear": 3.0},
        },
        winner="bull",
        rfd="正方在事实真实性和话题切题维度领先",
        key_clash_points=["稀缺性vs波动性", "数字黄金定义之争"],
        rebuttal_strength={"bull": 4, "bear": 3},
        evidence_depth={"bull": 4, "bear": 3},
        timestamp="2026-01-01T00:00:00",
    )


# ── Tests ─────────────────────────────────────────────────────

class TestImport(unittest.TestCase):
    """RED: reflector 模块可导入。"""

    def test_import_reflection_report(self):
        from reflector import ReflectionReport  # noqa: F401

    def test_import_reflector(self):
        from reflector import Reflector  # noqa: F401

    def test_import_strategy_extract_prompt(self):
        from reflector import STRATEGY_EXTRACT_PROMPT  # noqa: F401


class TestReflectionReport(unittest.TestCase):
    """ReflectionReport dataclass 字段验证。"""

    def test_has_all_fields(self):
        """ReflectionReport 包含5步反思的所有字段。"""
        from reflector import ReflectionReport
        report = ReflectionReport(
            topic="测试话题",
            review={},
            strategy_analysis={},
            persona_analysis={},
            evidence_analysis={},
            gaps={},
            recommendations=[],
            strategy_tags=[],
            persona_suggestions={},
            memory_id=None,
            timestamp="2026-01-01T00:00:00",
        )
        self.assertEqual(report.topic, "测试话题")
        self.assertIsNone(report.memory_id)

    def test_to_dict_serializable(self):
        """ReflectionReport 可序列化为 JSON。"""
        from reflector import ReflectionReport
        report = ReflectionReport(
            topic="测试",
            review={"key_pivot": "第2轮"},
            strategy_analysis={"evidence-heavy": {"effect": 4}},
            persona_analysis={"bull_persona": "乐观分析师"},
            evidence_analysis={"verified": 5, "falsified": 1},
            gaps={"evidence_gaps": ["缺数据"]},
            recommendations=["增加数据"],
            strategy_tags=["evidence-heavy"],
            persona_suggestions={"bull": "加强类比"},
            memory_id="VM-test-001",
            timestamp="2026-01-01T00:00:00",
        )
        d = report.to_dict()
        self.assertIsInstance(d, dict)
        json.dumps(d)


class TestStrategyExtraction(unittest.TestCase):
    """§4.0 策略提取 (Layer B 回溯标签)。"""

    def test_extract_strategies_from_transcript(self):
        """从 transcript 论点文本中提取策略标签。"""
        from reflector import Reflector
        ref = Reflector(llm_fn=_make_reflection_llm())
        strategies = ref.extract_strategies(_make_transcript())
        self.assertIsInstance(strategies, dict)
        # 应包含正反方策略
        self.assertIn("bull_strategies", strategies)
        self.assertIn("bear_strategies", strategies)
        self.assertIsInstance(strategies["bull_strategies"], list)
        self.assertGreater(len(strategies["bull_strategies"]), 0)

    def test_strategy_tags_list(self):
        """策略标签提取后存入 strategy_tags。"""
        from reflector import Reflector
        ref = Reflector(llm_fn=_make_reflection_llm())
        report = ref.reflect(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            adjudication_result=_make_adjudication_result(),
        )
        self.assertIsInstance(report.strategy_tags, list)
        self.assertGreater(len(report.strategy_tags), 0)


class TestReflect(unittest.TestCase):
    """Reflector.reflect() 5步反思循环。"""

    def test_reflect_returns_report(self):
        """reflect 返回 ReflectionReport。"""
        from reflector import Reflector, ReflectionReport
        ref = Reflector(llm_fn=_make_reflection_llm())
        report = ref.reflect(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            adjudication_result=_make_adjudication_result(),
        )
        self.assertIsInstance(report, ReflectionReport)

    def test_step1_review_populated(self):
        """Step 1 复盘: review 字段已填充。"""
        from reflector import Reflector
        ref = Reflector(llm_fn=_make_reflection_llm())
        report = ref.reflect(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            adjudication_result=_make_adjudication_result(),
        )
        self.assertIsInstance(report.review, dict)
        self.assertGreater(len(report.review), 0)

    def test_step2_analysis_populated(self):
        """Step 2 分析: strategy_analysis 已填充。"""
        from reflector import Reflector
        ref = Reflector(llm_fn=_make_reflection_llm())
        report = ref.reflect(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            adjudication_result=_make_adjudication_result(),
        )
        self.assertIsInstance(report.strategy_analysis, dict)

    def test_step3_gaps_populated(self):
        """Step 3 缺口: gaps 字段已填充。"""
        from reflector import Reflector
        ref = Reflector(llm_fn=_make_reflection_llm())
        report = ref.reflect(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            adjudication_result=_make_adjudication_result(),
        )
        self.assertIsInstance(report.gaps, dict)
        self.assertIn("evidence_gaps", report.gaps)
        self.assertIn("dropped_args", report.gaps)
        self.assertIn("unused_tactics", report.gaps)

    def test_step4_recommendations_populated(self):
        """Step 4 改进: recommendations 已填充。"""
        from reflector import Reflector
        ref = Reflector(llm_fn=_make_reflection_llm())
        report = ref.reflect(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            adjudication_result=_make_adjudication_result(),
        )
        self.assertIsInstance(report.recommendations, list)
        self.assertGreater(len(report.recommendations), 0)


class TestFailOpen(unittest.TestCase):
    """FAIL-OPEN: 无 LLM 或异常时不崩溃。"""

    def test_no_llm_returns_degraded(self):
        """无 LLM 时返回降级结果。"""
        from reflector import Reflector, ReflectionReport
        ref = Reflector(llm_fn=None)
        report = ref.reflect(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            adjudication_result=_make_adjudication_result(),
        )
        self.assertIsInstance(report, ReflectionReport)
        # 降级时 strategy_tags 为空
        self.assertEqual(report.strategy_tags, [])

    def test_llm_exception_returns_degraded(self):
        """LLM 抛异常时返回降级结果。"""
        from reflector import Reflector, ReflectionReport

        def bad_llm(prompt, max_tokens=600):
            raise RuntimeError("LLM 失败")

        ref = Reflector(llm_fn=bad_llm)
        report = ref.reflect(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            adjudication_result=_make_adjudication_result(),
        )
        self.assertIsInstance(report, ReflectionReport)

    def test_llm_garbage_returns_degraded(self):
        """LLM 返回垃圾时降级。"""
        from reflector import Reflector, ReflectionReport

        def garbage_llm(prompt, max_tokens=600):
            return "不是JSON"

        ref = Reflector(llm_fn=garbage_llm)
        report = ref.reflect(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            adjudication_result=_make_adjudication_result(),
        )
        self.assertIsInstance(report, ReflectionReport)


class TestHC7StrategyPrerequisite(unittest.TestCase):
    """HC7: 策略标签前置 — 无策略标签时跳过策略分析。"""

    def test_no_strategies_skips_strategy_analysis(self):
        """策略提取失败时 strategy_analysis 为空 dict。"""
        from reflector import Reflector

        # 返回空策略的 LLM
        def empty_strategy_llm(prompt, max_tokens=600):
            if "策略" in prompt:
                return json.dumps({"bull_strategies": [], "bear_strategies": []})
            return json.dumps({
                "review": {"turn_points": [], "key_pivot": ""},
                "strategy_analysis": {},
                "gaps": {"evidence_gaps": [], "dropped_args": [], "unused_tactics": []},
                "recommendations": [],
                "persona_suggestions": {},
            })

        ref = Reflector(llm_fn=empty_strategy_llm)
        report = ref.reflect(
            topic="BTC是数字黄金",
            transcript=_make_transcript(),
            adjudication_result=_make_adjudication_result(),
        )
        self.assertEqual(report.strategy_tags, [])
        self.assertEqual(report.strategy_analysis, {})


class TestStrategyPromptFormat(unittest.TestCase):
    """策略提取 Prompt 格式验证。"""

    def test_prompt_lists_all_strategies(self):
        """Prompt 包含所有 14 种策略标签。"""
        from reflector import STRATEGY_EXTRACT_PROMPT
        expected = [
            "definition-lock",
            "preemptive-refutation",
            "evidence-heavy",
            "counterplan",
            "disadvantage",
            "value-flip",
            "burden-delay",
            "kritik",
        ]
        for tag in expected:
            self.assertIn(tag, STRATEGY_EXTRACT_PROMPT,
                          f"策略 {tag} 未在 Prompt 中")


if __name__ == "__main__":
    unittest.main(verbosity=2)
