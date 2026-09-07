"""代理模块：S2 EventLedgerGenerator（ops/nanoclaw/core_task1 深路径薄封装）。

Spec §4.3 FAIL-OPEN：ImportError 或任何异常 → 返回空 list，不阻断热路径。
对外统一函数名：generate_ledger(news_list: List[Dict]) -> List[Dict]
  · 返回值语义：List[entry_dict]（entry_dict 至少含 event_type/risk_dir/sentiment_mean
    /sentiment_weighted/urgency_score/window/surprise_bucket/risk_action_proposal 等）
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

_THIS_DIR = Path(__file__).resolve().parent
# 注入 ops/nanoclaw/core_task1/scripts（与 event_ledger_generator.py 同目录）
_OP_SCRIPTS = _THIS_DIR.parent / "ops" / "nanoclaw" / "core_task1" / "scripts"
_OP_CORE = _THIS_DIR.parent / "ops" / "nanoclaw" / "core_task1"
for _p in (str(_OP_SCRIPTS), str(_OP_CORE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def generate_ledger(news_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """S2 对外函数：输入 news_list[dict] → 事件账本条目 list。

    FAIL-OPEN：任何异常吞掉 → 返回空 []。
    """
    if not isinstance(news_list, list) or not news_list:
        return []
    try:
        from event_ledger_generator import EventLedgerGenerator  # type: ignore
    except Exception:
        return []
    try:
        gen = EventLedgerGenerator()
        # EventLedgerGenerator 实际对外通常提供 generate/process/add_news 等方法；
        # 这里用反射探测常见 API，找不到则返回空。
        # 1) add_news + entries：最朴素 V9.x 常用模式
        # 2) generate_from_news(news_list)：V9.5 新 API
        for api_name in ("generate_from_news", "process_news_list", "generate_ledger_from_news"):
            fn = getattr(gen, api_name, None)
            if callable(fn):
                try:
                    res = fn(news_list)
                    return _coerce_list(res)
                except Exception:
                    pass
        # 退化：尝试 add_news 逐条 feed
        added = 0
        for n in news_list:
            add = getattr(gen, "add_news", None)
            if callable(add):
                try:
                    add(n)
                    added += 1
                except Exception:
                    continue
        if added:
            ent = getattr(gen, "entries", None) or getattr(gen, "ledger", None) or []
            return _coerce_list(ent)
        # 最终兜底：V9.5 generate 默认输出
        try:
            out = gen.generate() if callable(getattr(gen, "generate", None)) else []
            return _coerce_list(out)
        except Exception:
            return []
    except Exception:
        return []


def _coerce_list(v: Any) -> List[Dict[str, Any]]:
    if isinstance(v, list):
        return [x for x in v if isinstance(x, dict)]
    if isinstance(v, dict):
        if "entries" in v and isinstance(v["entries"], list):
            return [x for x in v["entries"] if isinstance(x, dict)]
        return [v]
    return []
