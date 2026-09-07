"""代理模块：S4 event_mapping_policy.map_event_type（ops/nanoclaw/core_task1 深路径薄封装）。

对外统一函数名：map_event_type(title: str, body: str, *, topic: str = "", category: str = "") -> str
  · 返回值语义：str（monetary_policy / crypto_regulation / us_policy / us_data /
    geopolitics / security_incident / project_update / market_analysis / onchain_data /
    kols_view / protocol_tech / meme_culture / unknown 等枚举值之一）

FAIL-OPEN：任何异常 → 返回 "unknown"。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

_THIS_DIR = Path(__file__).resolve().parent
_OP_SCRIPTS = _THIS_DIR.parent / "ops" / "nanoclaw" / "core_task1" / "scripts"
_OP_CORE = _THIS_DIR.parent / "ops" / "nanoclaw" / "core_task1"
for _p in (str(_OP_SCRIPTS), str(_OP_CORE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def map_event_type(
    title: str = "",
    body: str = "",
    *,
    topic: str = "",
    category: str = "",
    **kw: Any,
) -> str:
    """S4 对外函数：(title, body, topic, category) → event_type str。

    注意：真实 API 签名是 map_event_type(topic, category, title, body)；此代理重排参数
    更符合直觉，内部按真实顺序调用。
    """
    try:
        from event_mapping_policy import map_event_type as _real  # type: ignore
    except Exception:
        return "unknown"
    try:
        t = str(topic or kw.get("topic") or "").strip()
        c = str(category or kw.get("category") or "").strip()
        tl = str(title or "").strip()
        bd = str(body or "").strip()
        result = _real(t, c, tl, bd)
        if isinstance(result, str) and result:
            return result
        return "unknown"
    except Exception:
        return "unknown"
