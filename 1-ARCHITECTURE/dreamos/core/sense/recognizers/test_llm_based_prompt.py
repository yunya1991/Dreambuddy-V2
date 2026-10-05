#!/usr/bin/env python3
"""test_llm_based_prompt.py — LLM 识别器 SYSTEM_PROMPT 结构测试

TDD: 验证 SYSTEM_PROMPT 升级为 5 层结构（身份/意图分类/自主性边界/输出风格/输出格式）
覆盖 AC-1, AC-2
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))


def test_system_prompt_has_five_layers():
    """AC-1: SYSTEM_PROMPT 包含'输出风格'和'自主性边界'段落"""
    from dreamos.core.sense.recognizers.llm_based import LLMBasedRecognizer
    prompt = LLMBasedRecognizer()._system_prompt
    assert "输出风格" in prompt, "SYSTEM_PROMPT 应包含'输出风格'段落"
    assert "自主性边界" in prompt, "SYSTEM_PROMPT 应包含'自主性边界'段落"


def test_system_prompt_has_anti_slop_blacklist():
    """AC-2: 输出风格段落包含至少 5 个 AI 套话词的负面清单"""
    from dreamos.core.sense.recognizers.llm_based import LLMBasedRecognizer
    prompt = LLMBasedRecognizer()._system_prompt
    # 常见 AI 套话词
    slop_words = ["总而言之", "值得注意的是", "深入", "综上所述", "重要的是"]
    found = [w for w in slop_words if w in prompt]
    assert len(found) >= 5, f"负面清单应包含至少 5 个 AI 套话词，当前找到: {found}"


def test_system_prompt_trade_intent_requires_escalation():
    """AC-3(部分): 自主性边界段落明确交易类意图必须 escalation"""
    from dreamos.core.sense.recognizers.llm_based import LLMBasedRecognizer
    prompt = LLMBasedRecognizer()._system_prompt
    assert "EXECUTE_TRADE" in prompt
    # 应包含 escalation 或 确认 相关表述
    assert ("escalation" in prompt.lower() or "确认" in prompt or "用户确认" in prompt), \
        "自主性边界应明确交易意图需用户确认"


if __name__ == "__main__":
    test_system_prompt_has_five_layers()
    test_system_prompt_has_anti_slop_blacklist()
    test_system_prompt_trade_intent_requires_escalation()
    print("All tests passed!")
