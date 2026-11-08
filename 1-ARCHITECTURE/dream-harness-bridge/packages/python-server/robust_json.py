"""robust_json.py — DSH 与 32 Bot 共享的 JSON 解析 canonical 入口。

收敛目标（P2）：消除 DSH 三处 `_extract_json` 的重复实现与 buggy 正则
（`\\{[^{}]*\\}` 无法处理嵌套对象）。

策略：
- 优先导入 32 Bot 的 `core.robust_json`（canonical，带 249 测试覆盖）；
- 32 不可用时（DSH 独立运行，如 C-Drive 自驱动）回退到同算法的本地实现，
  保证行为一致、不静默失败。
"""
from __future__ import annotations

import json
import re
from typing import Any

# ── 优先使用 32 canonical ─────────────────────────────────────
try:  # pragma: no cover - import 路径取决于运行环境
    from core.robust_json import (  # type: ignore[import-not-found]
        extract_json_object,
        extract_json_text,
    )
except ImportError:  # pragma: no cover - DSH 独立运行时走本地实现

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


__all__ = ["extract_json_object", "extract_json_text"]
