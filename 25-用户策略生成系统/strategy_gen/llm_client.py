"""
25-用户策略生成系统 - LLM 客户端

复用 experiments/ab-trading/core/llm_client.py 的成熟实现，
支持千问 3.8 MAX / DeepSeek / Trae / Claude，带配额管理和自动降级。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

# 将 ab-trading 加入 path 以复用 llm_client
_AB_TRADING_DIR = Path(__file__).resolve().parents[2] / "experiments" / "ab-trading"
if str(_AB_TRADING_DIR) not in sys.path:
    sys.path.insert(0, str(_AB_TRADING_DIR))

from core.llm_client import llm_chat as _ab_llm_chat  # noqa: E402
from core.llm_client import llm_available as _ab_llm_available  # noqa: E402


def call_llm(
    prompt: str,
    *,
    system: str = "",
    max_tokens: int = 4000,
    purpose: str = "strategy_gen",
) -> Optional[str]:
    """调用 LLM 生成策略代码。

    Args:
        prompt: 用户提示词
        system: 系统提示词
        max_tokens: 最大 token 数
        purpose: 用途标识（用于配额管理）

    Returns:
        LLM 输出文本，失败返回 None
    """
    try:
        result = _ab_llm_chat(
            prompt=prompt,
            system=system,
            max_tokens=max_tokens,
            purpose=purpose,
        )
        if not result:
            return None
        return result
    except Exception as e:
        print(f"[LLM] call failed: {e}")
        return None


def llm_available() -> bool:
    """检查 LLM 是否可用。"""
    try:
        return bool(_ab_llm_available())
    except Exception:
        keys = ["QWEN_API_KEY", "DEEPSEEK_API_KEY", "TRAE_API_KEY", "ANTHROPIC_API_KEY"]
        return any(os.environ.get(k) for k in keys)
