#!/usr/bin/env python3
"""test_skill_dual_channel.py — RESULT_TEMPLATE 双通道输出测试

TDD: 验证 RESULT_TEMPLATE 支持 Commentary + Final 双通道，
_parse_output 能从双通道输出中正确解析 Final JSON
覆盖 AC-6
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


def test_result_template_has_dual_channel():
    """TR-4.1: RESULT_TEMPLATE 包含 commentary 和 final 标识"""
    from dreamos.adapters.skill_adapter import RESULT_TEMPLATE
    assert "commentary" in RESULT_TEMPLATE.lower(), "模板应包含 commentary 通道"
    assert "final" in RESULT_TEMPLATE.lower(), "模板应包含 final 通道"


def test_parse_dual_channel_output():
    """TR-4.2: 双通道输出文本能正确解析出 Final JSON"""
    from dreamos.adapters.skill_adapter import SkillNode

    node = SkillNode(skill_path="/tmp/test.md", node_id="test")

    dual_output = """分析过程：
当前 BTC 价格处于 EMA20 上方，RSI 未超买，趋势偏多。

Final:
{
  "direction": "LONG",
  "confidence": 0.75,
  "rationale": ["价格在EMA20上方", "RSI未超买"],
  "outputs": {"signal": "buy"}
}
"""
    parsed = node._parse_output(dual_output)
    assert parsed["direction"] == "LONG"
    assert parsed["confidence"] == 0.75
    assert "价格在EMA20上方" in parsed["rationale"]


def test_parse_backward_compatible_single_json():
    """向后兼容：单 JSON 输出（无 commentary/final 标记）仍能解析"""
    from dreamos.adapters.skill_adapter import SkillNode

    node = SkillNode(skill_path="/tmp/test.md", node_id="test")

    single_output = '''{
  "direction": "SHORT",
  "confidence": 0.6,
  "rationale": ["看跌信号"],
  "outputs": {}
}'''
    parsed = node._parse_output(single_output)
    assert parsed["direction"] == "SHORT"
    assert parsed["confidence"] == 0.6


if __name__ == "__main__":
    test_result_template_has_dual_channel()
    test_parse_dual_channel_output()
    test_parse_backward_compatible_single_json()
    print("All tests passed!")
