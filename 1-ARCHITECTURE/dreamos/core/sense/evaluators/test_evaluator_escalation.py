#!/usr/bin/env python3
"""test_evaluator_escalation.py — IntentEvaluatorAgent Escalation 机制测试

TDD: 验证交易类意图强制 escalation + justification，非交易类不触发
覆盖 AC-3, AC-4, AC-8
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))


class FakeIntentResult:
    """模拟 IntentResult"""
    def __init__(self, intent_type="UNCERTAIN", confidence=0.0, rationale=""):
        self.intent_type = intent_type
        self.confidence = confidence
        self.rationale = rationale


def test_trade_intent_requires_escalation_low_conf():
    """AC-3: 无 llm_fn + EXECUTE_TRADE（低置信度）→ escalation_required=True, justification 非空"""
    from dreamos.core.sense.evaluators.intent_evaluator_agent import IntentEvaluatorAgent

    agent = IntentEvaluatorAgent()  # 无 llm_fn，规则降级
    intent = FakeIntentResult(intent_type="EXECUTE_TRADE", confidence=0.45)
    result = agent.evaluate(intent, context={})
    assert result.escalation_required is True
    assert result.justification != "", "交易意图必须有 justification"


def test_trade_intent_requires_escalation_high_conf():
    """AC-3: 无 llm_fn + EXECUTE_TRADE（高置信度>=0.65）→ 仍需 escalation"""
    from dreamos.core.sense.evaluators.intent_evaluator_agent import IntentEvaluatorAgent

    agent = IntentEvaluatorAgent()
    intent = FakeIntentResult(intent_type="EXECUTE_TRADE", confidence=0.90)
    result = agent.evaluate(intent, context={})
    assert result.escalation_required is True
    assert result.justification != ""


def test_query_intent_no_escalation():
    """AC-4: 无 llm_fn + MARKET_QUERY（高置信度）→ escalation_required=False"""
    from dreamos.core.sense.evaluators.intent_evaluator_agent import IntentEvaluatorAgent

    agent = IntentEvaluatorAgent()
    intent = FakeIntentResult(intent_type="MARKET_QUERY", confidence=0.90)
    result = agent.evaluate(intent, context={})
    assert result.escalation_required is False


def test_eval_result_has_escalation_fields():
    """验证 EvalResult 数据类包含 escalation_required 和 justification 字段"""
    from dreamos.core.sense.evaluators.intent_evaluator_agent import EvalResult
    r = EvalResult(adjusted_confidence=0.5)
    assert hasattr(r, "escalation_required")
    assert hasattr(r, "justification")
    assert r.escalation_required is False  # 默认值
    assert r.justification == ""  # 默认值


if __name__ == "__main__":
    test_trade_intent_requires_escalation_low_conf()
    test_trade_intent_requires_escalation_high_conf()
    test_query_intent_no_escalation()
    test_eval_result_has_escalation_fields()
    print("All tests passed!")
