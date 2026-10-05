#!/usr/bin/env python3
"""test_intent_recognition_capability.py — 意图识别能力提升验证

测试维度：
1. 规则匹配层准确率（30 个二级意图 × 典型问法）
2. LLM 识别器 SYSTEM_PROMPT 规范（反 AI 味 + 自主性边界）
3. 边界评估 escalation 机制（交易意图强制确认）
4. 多意图检测能力
"""
import sys
import os
import json

# 确保 1-ARCHITECTURE 在 sys.path 中
_ARCH_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if _ARCH_DIR not in sys.path:
    sys.path.insert(0, _ARCH_DIR)


# ── 1. 规则匹配层准确率测试 ──────────────────────────────

RULE_TEST_CASES = [
    # (输入文本, 期望二级意图, 一级意图)
    ("比特币现在多少钱", "market_query", "query"),
    ("我现在持有多少以太坊", "holding_query", "query"),
    ("我的订单成交了吗", "order_query", "query"),
    ("账户余额多少", "account_query", "query"),
    ("今天大盘怎么样", "market_overview", "query"),
    ("分析一下比特币的走势", "technical_analysis", "analysis"),
    ("我的持仓分析一下", "holding_analysis", "analysis"),
    ("给我做个深度分析", "deep_analysis", "analysis"),
    ("三屏分析一下 SOL", "three_screen_analysis", "analysis"),
    ("区块链板块怎么样", "sector_analysis", "analysis"),
    ("买入 0.1 个比特币", "buy", "trade"),
    ("加仓以太坊", "add_position", "trade"),
    ("卖出我的比特币", "sell", "trade"),
    ("止损平仓", "close_position", "trade"),
    ("设置一个止损单", "conditional_order", "trade"),
    ("撤销这个订单", "order_manage", "trade"),
    ("推荐几个币", "stock_recommendation", "strategy"),
    ("筛选市值前 10 的币", "factor_screen", "strategy"),
    ("帮我设计一个策略", "strategy_design", "strategy"),
    ("优化一下我的策略参数", "strategy_optimization", "strategy"),
    ("这个币风险大吗", "risk_assessment", "risk"),
    ("怎么控制风险", "risk_advice", "risk"),
    ("设置一个到价提醒", "alert_setup", "risk"),
    ("我的组合风险怎么样", "portfolio_risk", "risk"),
    ("好的就这么办", "confirm", "dialog"),
    ("不要了算了", "cancel", "dialog"),
    ("改成 0.05", "modify", "dialog"),
    ("再说一遍", "repeat", "dialog"),
    ("这是什么意思", "clarify", "dialog"),
    ("你好", "chitchat", "dialog"),
]


def test_rule_classification_accuracy():
    """规则匹配层准确率测试"""
    from dreamos.core.sense.dialogue_intent.classifier import _rule_classify

    correct = 0
    errors = []
    for text, expected_secondary, _ in RULE_TEST_CASES:
        result = _rule_classify(text)
        if result == expected_secondary:
            correct += 1
        else:
            errors.append((text, expected_secondary, result))

    accuracy = correct / len(RULE_TEST_CASES) * 100
    print(f"\n[1] 规则匹配层准确率: {correct}/{len(RULE_TEST_CASES)} = {accuracy:.1f}%")
    if errors:
        print(f"    误判样例 ({len(errors)} 个):")
        for text, expected, actual in errors:
            print(f"      '{text}' → 期望={expected}, 实际={actual}")
    assert accuracy >= 95, f"规则匹配准确率应 >= 95%，实际 {accuracy:.1f}%"
    return accuracy


# ── 2. LLM 识别器 SYSTEM_PROMPT 规范测试 ──────────────────

def test_llm_prompt_has_anti_slop():
    """LLM SYSTEM_PROMPT 包含反 AI 味负面清单"""
    from dreamos.core.sense.recognizers.llm_based import SYSTEM_PROMPT

    anti_slop_keywords = [
        "总而言之", "值得注意的是", "深入分析",
        "综上所述", "首先", "其次",
    ]
    has_slop_guidance = any(kw in SYSTEM_PROMPT for kw in anti_slop_keywords)
    print(f"\n[2a] LLM SYSTEM_PROMPT 反 AI 味清单: {'✓' if has_slop_guidance else '✗'}")
    assert has_slop_guidance, "SYSTEM_PROMPT 应包含反 AI 味负面清单"


def test_llm_prompt_has_autonomy_boundary():
    """LLM SYSTEM_PROMPT 包含自主性边界声明"""
    from dreamos.core.sense.recognizers.llm_based import SYSTEM_PROMPT

    has_boundary = "自主" in SYSTEM_PROMPT or "escalation" in SYSTEM_PROMPT or "确认" in SYSTEM_PROMPT
    print(f"[2b] LLM SYSTEM_PROMPT 自主性边界: {'✓' if has_boundary else '✗'}")
    assert has_boundary, "SYSTEM_PROMPT 应包含自主性边界声明"


def test_llm_prompt_has_output_format():
    """LLM SYSTEM_PROMPT 包含 JSON 输出格式约束"""
    from dreamos.core.sense.recognizers.llm_based import SYSTEM_PROMPT

    has_json = "{" in SYSTEM_PROMPT and "intent" in SYSTEM_PROMPT.lower()
    print(f"[2c] LLM SYSTEM_PROMPT JSON 输出格式: {'✓' if has_json else '✗'}")
    assert has_json, "SYSTEM_PROMPT 应包含 JSON 输出格式约束"


# ── 3. 边界评估 escalation 机制测试 ─────────────────────

def test_trade_intent_triggers_escalation():
    """交易类意图触发 escalation_required"""
    from dreamos.core.sense.evaluators.intent_evaluator_agent import IntentEvaluatorAgent, EvalResult

    evaluator = IntentEvaluatorAgent()
    eval_result = EvalResult(adjusted_confidence=0.9)
    # 交易意图类型 EXECUTE_TRADE
    result = evaluator._apply_escalation(eval_result, "EXECUTE_TRADE")
    print(f"\n[3a] 交易意图 escalation: expected=True, actual={result.escalation_required}")
    assert result.escalation_required is True, "交易意图应触发 escalation_required"
    assert result.justification, "escalation 时 justification 应非空"


def test_query_intent_no_escalation():
    """查询类意图不触发 escalation"""
    from dreamos.core.sense.evaluators.intent_evaluator_agent import IntentEvaluatorAgent, EvalResult

    evaluator = IntentEvaluatorAgent()
    eval_result = EvalResult(adjusted_confidence=0.95)
    result = evaluator._apply_escalation(eval_result, "MARKET_QUERY")
    print(f"[3b] 查询意图 escalation: expected=False, actual={result.escalation_required}")
    assert result.escalation_required is False, "查询意图不应触发 escalation"


# ── 4. 多意图检测能力测试 ────────────────────────────────

def test_multi_intent_detection():
    """多意图检测：复杂查询拆分为多个意图"""
    from dreamos.core.sense.dialogue_intent.multi_intent import MultiIntentDetector

    detector = MultiIntentDetector()
    # 用逗号分隔的查询+分析意图
    text = "查一下比特币价格，同时分析一下以太坊走势"
    result = detector.detect(text)
    has_multiple = len(result) >= 2
    print(f"\n[4] 多意图检测: 输入='{text}', 检测到 {len(result)} 个意图={result}, has_multiple={has_multiple}")
    assert has_multiple, f"应检测到至少 2 个意图，实际检测到 {len(result)} 个: {result}"


# ── 汇总 ──────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("意图识别能力提升验证")
    print("=" * 60)

    results = {}

    # 1. 规则匹配层
    results["rule_accuracy"] = test_rule_classification_accuracy()

    # 2. LLM prompt 规范
    test_llm_prompt_has_anti_slop()
    test_llm_prompt_has_autonomy_boundary()
    test_llm_prompt_has_output_format()
    results["prompt_compliance"] = "PASS"

    # 3. escalation 机制
    test_trade_intent_triggers_escalation()
    test_query_intent_no_escalation()
    results["escalation"] = "PASS"

    # 4. 多意图检测
    test_multi_intent_detection()
    results["multi_intent"] = "PASS"

    print("\n" + "=" * 60)
    print("测试汇总:")
    print(f"  规则匹配准确率: {results['rule_accuracy']:.1f}%")
    print(f"  LLM Prompt 规范: {results['prompt_compliance']}")
    print(f"  Escalation 机制: {results['escalation']}")
    print(f"  多意图检测: {results['multi_intent']}")
    print("=" * 60)
    print("All tests passed! 意图识别能力提升验证通过 ✓")
