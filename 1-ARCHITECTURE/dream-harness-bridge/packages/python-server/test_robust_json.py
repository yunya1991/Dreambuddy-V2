"""test_robust_json.py — 验证 DSH 与 32 共享的 JSON 解析收敛。

P2 收敛目标：消除 DSH 三处 `_extract_json` 的 buggy 正则
（`\\{[^{}]*\\}` 无法处理嵌套对象），统一到 `robust_json.extract_json_object`。
"""

from __future__ import annotations

import sys
from pathlib import Path

DSH_ROOT = Path(__file__).resolve().parent
if str(DSH_ROOT) not in sys.path:
    sys.path.insert(0, str(DSH_ROOT))

from robust_json import extract_json_object  # noqa: E402


def test_extracts_nested_json_object():
    """嵌套对象：旧 `\\{[^{}]*\\}` 正则会截断，canonical 必须正确解析。"""
    raw = '前缀文字 {"a": 1, "b": {"c": 2, "d": [3, 4]}} 后缀文字'
    data = extract_json_object(raw)
    assert data is not None
    assert data["a"] == 1
    assert data["b"]["c"] == 2
    assert data["b"]["d"] == [3, 4]


def test_handles_code_fence():
    raw = '```json\n{"thesis": "x", "arguments": ["a", "b"]}\n```'
    data = extract_json_object(raw)
    assert data is not None
    assert data["thesis"] == "x"
    assert data["arguments"] == ["a", "b"]


def test_returns_none_on_invalid():
    assert extract_json_object("not json at all") is None
    assert extract_json_object("") is None
    assert extract_json_object(None) is None  # type: ignore[arg-type]


def test_first_complete_object_when_multiple():
    """多个对象时取第一个完整的。"""
    raw = '{"ok": true} trailing {"bad": }'
    data = extract_json_object(raw)
    assert data == {"ok": True}
