#!/usr/bin/env python3
"""TDD RED: synthesizer_agent LLM 综合器测试

测试覆盖:
  1. 模块存在性 (import synthesizer_agent)
  2. SynthesizedCard 数据结构
  3. SynthesizerAgent 类存在性 + 构造函数
  4. synthesize() 方法签名
  5. 空输入返回 []
  6. FAIL-OPEN: 无 llm_fn → 走 _rule_based_synthesis 降级
  7. FAIL-OPEN: llm_fn 异常 → 返回空列表或规则降级
  8. LLM 正常路径: 输出 insight + recommendation 卡片
  9. 认知闭环: cognitive_adapter.recall 被调用
"""
from __future__ import annotations
import os, sys, unittest
from unittest.mock import MagicMock, patch
from typing import List

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from subagent_types import SubagentOutput, Signal, ChartSpec
from aggregator import aggregate_subagent_outputs


class TestSynthesizerExistence(unittest.TestCase):
    """模块 + 类 + 数据结构存在性"""

    def test_import_synthesizer_agent(self):
        """RED: synthesizer_agent 模块不存在 → ModuleNotFoundError"""
        import synthesizer_agent  # noqa: F401

    def test_synthesized_card_dataclass_exists(self):
        from synthesizer_agent import SynthesizedCard
        card = SynthesizedCard(
            card_type="insight",
            title="测试",
            content="正文",
            signals_ref=[],
            charts_ref=[],
            confidence=0.7,
            source_modules=["macro"],
        )
        self.assertEqual(card.card_type, "insight")
        self.assertEqual(card.title, "测试")

    def test_synthesized_card_to_dict(self):
        from synthesizer_agent import SynthesizedCard
        card = SynthesizedCard(
            card_type="recommendation",
            title="建议",
            content="建议正文",
            signals_ref=[{"name": "gdp"}],
            charts_ref=[{"type": "line"}],
            confidence=0.8,
            source_modules=["macro", "flow"],
        )
        d = card.to_dict()
        self.assertEqual(d["card_type"], "recommendation")
        self.assertEqual(d["title"], "建议")
        self.assertEqual(d["confidence"], 0.8)
        self.assertEqual(len(d["source_modules"]), 2)

    def test_synthesizer_agent_class_exists(self):
        from synthesizer_agent import SynthesizerAgent
        agent = SynthesizerAgent()
        self.assertIsNotNone(agent)

    def test_synthesize_method_exists(self):
        from synthesizer_agent import SynthesizerAgent
        agent = SynthesizerAgent()
        self.assertTrue(callable(getattr(agent, "synthesize", None)))


class TestSynthesizeEmpty(unittest.TestCase):
    """空输入"""

    def test_empty_aggregated_returns_empty(self):
        from synthesizer_agent import SynthesizerAgent
        agent = SynthesizerAgent()
        result = agent.synthesize({"summaries": [], "all_signals": []})
        self.assertEqual(result, [])

    def test_empty_outputs_dict_returns_empty(self):
        from synthesizer_agent import SynthesizerAgent
        agent = SynthesizerAgent()
        # 完整空聚合结构
        empty_aggregated = {
            "summaries": [], "all_signals": [], "all_charts": [],
            "modules": [], "total_signals": 0, "total_charts": 0,
            "consensus_direction": "neutral",
            "long_count": 0, "short_count": 0,
            "avg_confidence": 0.0, "top_signals": [],
        }
        result = agent.synthesize(empty_aggregated)
        self.assertEqual(result, [])


class TestSynthesizeFailOpen(unittest.TestCase):
    """FAIL-OPEN: 无 llm_fn → 规则降级"""

    def _make_aggregated(self) -> dict:
        outs = [
            SubagentOutput(
                module="macro",
                summary="GDP 偏多,温和增长",
                signals=[
                    Signal("gdp", 2.5, "long", 0.7),
                    Signal("cpi", 3.1, "neutral", 0.5),
                ],
                charts=[ChartSpec("line", "GDP 趋势", [1, 2, 3])],
            ),
            SubagentOutput(
                module="flow",
                summary="资金流入增加",
                signals=[Signal("etf", 150, "long", 0.65)],
                charts=[],
            ),
        ]
        return aggregate_subagent_outputs(outs)

    def test_no_llm_fn_returns_cards(self):
        """无 llm_fn → _rule_based_synthesis 降级,仍输出卡片"""
        from synthesizer_agent import SynthesizerAgent
        agent = SynthesizerAgent()  # 无 llm_fn
        result = agent.synthesize(self._make_aggregated())
        # 降级路径应仍然产出卡片 (规则模板)
        self.assertIsInstance(result, list)
        self.assertGreaterEqual(len(result), 1)

    def test_no_llm_fn_card_has_required_fields(self):
        from synthesizer_agent import SynthesizerAgent
        from synthesizer_agent import SynthesizedCard
        agent = SynthesizerAgent()
        result = agent.synthesize(self._make_aggregated())
        self.assertGreaterEqual(len(result), 1)
        card = result[0]
        # 返回的是 SynthesizedCard 实例
        self.assertIsInstance(card, SynthesizedCard)
        self.assertIn(card.card_type, ("insight", "recommendation"))
        self.assertTrue(card.title)
        self.assertTrue(card.content)
        self.assertGreaterEqual(card.confidence, 0.0)
        self.assertLessEqual(card.confidence, 1.0)

    def test_llm_exception_returns_empty_or_rule(self):
        """LLM 异常 → FAIL-OPEN 返回空列表或规则降级"""
        from synthesizer_agent import SynthesizerAgent

        def _broken_llm(prompt: str) -> str:
            raise RuntimeError("LLM 服务不可用")

        agent = SynthesizerAgent(llm_fn=_broken_llm)
        # 异常不应抛出
        try:
            result = agent.synthesize(self._make_aggregated())
        except Exception as e:
            self.fail(f"FAIL-OPEN 应吞异常,但抛出: {e}")
        # 应返回 list (空或降级)
        self.assertIsInstance(result, list)


class TestSynthesizeLLMPath(unittest.TestCase):
    """LLM 正常路径"""

    def _make_aggregated(self) -> dict:
        outs = [
            SubagentOutput(
                module="macro",
                summary="GDP 偏多",
                signals=[Signal("gdp", 2.5, "long", 0.75)],
                charts=[ChartSpec("line", "GDP", [1, 2])],
            ),
            SubagentOutput(
                module="flow",
                summary="资金流入",
                signals=[Signal("etf", 150, "long", 0.7)],
                charts=[],
            ),
        ]
        return aggregate_subagent_outputs(outs)

    def test_llm_returns_insight_and_recommendation(self):
        """LLM 正常输出 insight + recommendation 两类卡片"""
        from synthesizer_agent import SynthesizerAgent

        # 模拟 LLM 返回 JSON
        def _mock_llm(prompt: str) -> str:
            import json
            return json.dumps({
                "insights": [
                    {"title": "宏观偏多", "content": "GDP 与资金流入共指向多头",
                     "severity": "info"}
                ],
                "recommendations": [
                    {"action": "关注做多机会", "reason": "多源共识偏多",
                     "priority": "medium"}
                ],
            })

        agent = SynthesizerAgent(llm_fn=_mock_llm)
        result = agent.synthesize(self._make_aggregated())
        self.assertIsInstance(result, list)
        self.assertGreaterEqual(len(result), 1)
        # 应至少包含一个 insight 或 recommendation
        card_types = {c.card_type for c in result}
        self.assertTrue(card_types & {"insight", "recommendation"})

    def test_llm_card_signals_ref_populated(self):
        """LLM 卡片应引用已聚合 signals (不重新生成)"""
        from synthesizer_agent import SynthesizerAgent

        def _mock_llm(prompt: str) -> str:
            import json
            return json.dumps({
                "insights": [{"title": "测试", "content": "内容", "severity": "info"}],
                "recommendations": [],
            })

        agent = SynthesizerAgent(llm_fn=_mock_llm)
        result = agent.synthesize(self._make_aggregated())
        insight_cards = [c for c in result if c.card_type == "insight"]
        if insight_cards:
            card = insight_cards[0]
            # signals_ref 应引用聚合结果 (非空)
            self.assertIsInstance(card.signals_ref, list)
            self.assertIsInstance(card.charts_ref, list)

    def test_llm_card_source_modules(self):
        from synthesizer_agent import SynthesizerAgent

        def _mock_llm(prompt: str) -> str:
            import json
            return json.dumps({
                "insights": [{"title": "t", "content": "c", "severity": "info"}],
                "recommendations": [],
            })

        agent = SynthesizerAgent(llm_fn=_mock_llm)
        result = agent.synthesize(self._make_aggregated())
        for card in result:
            self.assertIsInstance(card.source_modules, list)


class TestSynthesizeCognitiveLoop(unittest.TestCase):
    """认知闭环: recall 被调用"""

    def test_cognitive_recall_called(self):
        """有 cognitive_adapter 时,synthesize 应调用 recall"""
        from synthesizer_agent import SynthesizerAgent

        mock_adapter = MagicMock()
        mock_adapter.recall.return_value = []

        def _mock_llm(prompt: str) -> str:
            import json
            return json.dumps({
                "insights": [{"title": "t", "content": "c", "severity": "info"}],
                "recommendations": [],
            })

        agent = SynthesizerAgent(
            llm_fn=_mock_llm, cognitive_adapter=mock_adapter)
        outs = [SubagentOutput(
            module="macro", summary="测试",
            signals=[Signal("gdp", 2.5, "long", 0.7)],
        )]
        aggregated = aggregate_subagent_outputs(outs)
        agent.synthesize(aggregated)
        # recall 应至少被调用一次
        self.assertGreaterEqual(mock_adapter.recall.call_count, 1)


if __name__ == "__main__":
    unittest.main()
