#!/usr/bin/env python3
"""test_intent_evaluator_agent.py — S 层意图评估 subagent 测试

TDD RED 阶段：所有测试在实现前应 FAIL（ModuleNotFoundError）。
GREEN 阶段实现 intent_evaluator_agent.py 后全部通过。

覆盖：
  1. 模块导入（ModuleNotFoundError → GREEN 后通过）
  2. FAIL-OPEN：无 llm_fn → 规则降级（原 confidence 透传）
  3. FAIL-OPEN：异常 → EvalResult(keep_static_fallback=True)
  4. 空输入处理
  5. LLM 评估正常路径：adjusted_confidence + clarified_intent
  6. 认知闭环 recall + record 调用
  7. 低置信度触发评估 + 高置信度不触发
"""
import pytest
import sys
import os

# 确保路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))


def test_module_import():
    """测试 1: 模块可导入"""
    from dreamos.core.sense.evaluators.intent_evaluator_agent import IntentEvaluatorAgent, EvalResult
    assert IntentEvaluatorAgent is not None
    assert EvalResult is not None


def test_fail_open_no_llm_fn():
    """测试 2: 无 llm_fn → 规则降级，原 confidence 透传"""
    from dreamos.core.sense.evaluators.intent_evaluator_agent import IntentEvaluatorAgent, EvalResult
    from dreamos.core.sense.types import IntentResult

    agent = IntentEvaluatorAgent()  # 无 llm_fn
    intent = IntentResult(intent_type="trend_following", confidence=0.45)
    result = agent.evaluate(intent, context={})
    assert isinstance(result, EvalResult)
    assert result.keep_static_fallback is True
    # 规则降级：adjusted_confidence 应等于原值
    assert result.adjusted_confidence == pytest.approx(0.45)


def test_fail_open_exception():
    """测试 3: LLM 异常 → FAIL-OPEN 返回安全默认"""
    from dreamos.core.sense.evaluators.intent_evaluator_agent import IntentEvaluatorAgent, EvalResult
    from dreamos.core.sense.types import IntentResult

    def bad_llm(prompt: str) -> str:
        raise RuntimeError("LLM service down")

    agent = IntentEvaluatorAgent(llm_fn=bad_llm)
    intent = IntentResult(intent_type="trend_following", confidence=0.50)
    result = agent.evaluate(intent, context={})
    assert isinstance(result, EvalResult)
    assert result.keep_static_fallback is True
    # 异常时 adjusted_confidence 应保留原值
    assert result.adjusted_confidence == pytest.approx(0.50)


def test_empty_intent_result():
    """测试 4: 空 IntentResult → 返回安全默认"""
    from dreamos.core.sense.evaluators.intent_evaluator_agent import IntentEvaluatorAgent, EvalResult
    from dreamos.core.sense.types import IntentResult

    agent = IntentEvaluatorAgent()
    intent = IntentResult()  # 默认值
    result = agent.evaluate(intent, context={})
    assert isinstance(result, EvalResult)
    assert result.adjusted_confidence == pytest.approx(0.0)
    assert result.keep_static_fallback is True


def test_llm_evaluation_normal_path():
    """测试 5: LLM 正常评估路径"""
    from dreamos.core.sense.evaluators.intent_evaluator_agent import IntentEvaluatorAgent, EvalResult
    from dreamos.core.sense.types import IntentResult

    def mock_llm(prompt: str) -> str:
        # 返回 JSON 格式的评估结果
        import json
        return json.dumps({
            "adjusted_confidence": 0.78,
            "clarified_intent": "trend_following",
            "route_suggestion": "A_chain",
            "reasoning": "用户明确询问趋势分析"
        })

    agent = IntentEvaluatorAgent(llm_fn=mock_llm)
    intent = IntentResult(intent_type="trend_following", confidence=0.55)
    result = agent.evaluate(intent, context={"user_message": "分析BTC趋势"})
    assert isinstance(result, EvalResult)
    assert result.adjusted_confidence == pytest.approx(0.78)
    assert result.clarified_intent == "trend_following"
    assert result.route_suggestion == "A_chain"
    assert result.keep_static_fallback is False


def test_cognitive_recall_record():
    """测试 6: 认知闭环 recall + record 调用"""
    from dreamos.core.sense.evaluators.intent_evaluator_agent import IntentEvaluatorAgent, EvalResult
    from dreamos.core.sense.types import IntentResult

    class MockCognitive:
        def __init__(self):
            self.recalled = []
            self.recorded = []

        def recall(self, context, top_k=5, min_quality="C"):
            self.recalled.append(context)
            return [{"content": "历史经验", "score": 0.8}]

        def record(self, content, tags="", quality_level="C"):
            self.recorded.append({"content": content, "tags": tags, "quality_level": quality_level})

    cog = MockCognitive()

    def mock_llm(prompt: str) -> str:
        import json
        return json.dumps({
            "adjusted_confidence": 0.72,
            "clarified_intent": "trend_following",
            "route_suggestion": None,
            "reasoning": "意图明确"
        })

    agent = IntentEvaluatorAgent(llm_fn=mock_llm, cognitive_adapter=cog)
    intent = IntentResult(intent_type="trend_following", confidence=0.55)
    result = agent.evaluate(intent, context={"user_message": "分析BTC趋势"})

    # recall 应被调用
    assert len(cog.recalled) >= 1
    # record 应被调用
    assert len(cog.recorded) >= 1
    assert "S层" in cog.recorded[0]["tags"] or "意图评估" in cog.recorded[0]["tags"]


def test_low_confidence_triggers_evaluation():
    """测试 7: 低置信度触发评估，高置信度不触发"""
    from dreamos.core.sense.evaluators.intent_evaluator_agent import IntentEvaluatorAgent
    from dreamos.core.sense.types import IntentResult

    call_count = {"llm": 0}

    def mock_llm(prompt: str) -> str:
        call_count["llm"] += 1
        import json
        return json.dumps({"adjusted_confidence": 0.80, "clarified_intent": "trend_following"})

    agent = IntentEvaluatorAgent(llm_fn=mock_llm)

    # 低置信度 → 应调用 LLM
    low_intent = IntentResult(intent_type="trend_following", confidence=0.40)
    agent.evaluate(low_intent, context={})
    assert call_count["llm"] >= 1

    # 高置信度 → 不应调用 LLM（直接透传）
    call_count["llm"] = 0
    high_intent = IntentResult(intent_type="trend_following", confidence=0.85)
    result = agent.evaluate(high_intent, context={})
    assert call_count["llm"] == 0
    assert result.adjusted_confidence == pytest.approx(0.85)
