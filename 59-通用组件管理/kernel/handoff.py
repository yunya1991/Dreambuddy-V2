#!/usr/bin/env python3
"""可装配指针的公共骨架：token 估算、预算装配、契约外壳。

构建期由 tools/sync_kernel.py 注入到组件 `scripts/_kernel/`。
业务 item 的构造与文本表格由各组件自己维护。
"""

import json
from datetime import datetime

HANDOFF_VERSION = "1.0"


def estimate_tokens(obj):
    raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    return max(1, round((len(raw) / 3.0) / 1.5))


def pack(items, budget):
    picked, skipped, used = [], 0, 0
    for it in items:
        cost = it["estimated_tokens"]
        if used + cost <= budget:
            picked.append(it)
            used += cost
        else:
            skipped += 1
    return picked, skipped, used


def envelope(skill, target, budget, items, missing, skipped, used, limits):
    """handoff 契约 v1.0 外壳；键顺序即输出顺序。"""
    return {
        "handoff_version": HANDOFF_VERSION,
        "skill": skill,
        "target": target,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "budget": budget,
        "items": items,
        "missing": missing,
        "skipped": skipped,
        "total_tokens": used,
        "read_only": True,
        "limits": limits,
    }
