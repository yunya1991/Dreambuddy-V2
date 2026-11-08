"""robust_json.py — 从 LLM 输出中稳健提取 JSON 对象。

修复的问题：
- 模型返回 ```json 代码围栏；
- JSON 前后夹杂解释性文字；
- 嵌套对象/数组（旧实现 `\\{[^{}]*\\}` 会截断）；
- 输出被截断时仍尽量提取第一个完整对象。
"""

from __future__ import annotations

import json
import re
from typing import Any


def extract_json_object(raw: str) -> dict[str, Any] | None:
    """提取第一个完整 JSON 对象；失败返回 None（FAIL-OPEN）。"""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None

    # 去掉常见代码围栏
    text = re.sub(r"^```(?:json|JSON)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()

    # 1) 直接解析
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass

    # 2) 从每个 '{' 起尝试 raw_decode（支持嵌套与前后散文）
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            data, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def extract_json_text(raw: str) -> str:
    """返回去掉代码围栏后的文本，便于日志/debug。"""
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json|JSON)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    return text
