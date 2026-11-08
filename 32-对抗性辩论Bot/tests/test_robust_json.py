"""robust_json 单元测试：代码围栏/散文/嵌套/截断。"""
from core.robust_json import extract_json_object, extract_json_text


def test_plain_json():
    assert extract_json_object('{"a": 1}') == {"a": 1}


def test_code_fence():
    raw = '```json\n{"thesis": "t", "arguments": ["a"]}\n```'
    assert extract_json_object(raw)["thesis"] == "t"


def test_prose_prefix():
    raw = '好的，以下是结果：\n{"thesis": "t", "arguments": ["a", "b"]}\n希望有帮助。'
    assert extract_json_object(raw)["arguments"] == ["a", "b"]


def test_nested_object():
    raw = '{"thesis": "t", "meta": {"x": {"y": 1}}, "arguments": ["a"]}'
    assert extract_json_object(raw)["meta"]["x"]["y"] == 1


def test_invalid_returns_none():
    assert extract_json_object("no json here") is None
    assert extract_json_object("") is None
    assert extract_json_object(None) is None


def test_extract_text_strips_fence():
    assert extract_json_text("```json\n{}\n```") == "{}"