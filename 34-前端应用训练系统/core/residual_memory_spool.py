# -*- coding: utf-8 -*-
"""settle → 残差记忆候选暂存（P2.5 写入口）。

链路：
  L0.settle 识别到有价值发现（数据源的坑/降级模式）
    → 写入 `.data/memory/pending.jsonl`（原始候选，不做准入）
    → 治理周期 `/api/governance/cycle` 统一走残差准入后落正式记录。

为什么不在 settle 内直接准入：
  准入规则（四禁入/四残差/三测试）唯一实现在前端 TS；settle 只负责
  "把值得记的现象交出来"，避免 Python 侧复制判定导致口径漂移。

硬约束：FAIL-OPEN——写暂存失败不影响 settle 主流程。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

PENDING_REL = os.path.join(".data", "memory", "pending.jsonl")


def pending_path(root: str) -> str:
    return os.path.join(str(root), PENDING_REL)


def build_candidate(
    finding: str,
    intent: str,
    message: str,
    result: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """把 settle 发现转成残差候选（字段与前端 MemoryRecordInput 对齐）。"""
    context = context or {}
    result = result or {}
    data = result.get("data")
    source = data.get("source") if isinstance(data, dict) else None

    anchor = context.get("source_anchor")
    if not anchor and source:
        anchor = "source:{}".format(source)

    candidate: Dict[str, Any] = {
        "content": str(finding)[:500],
        "subclass": "runtime",
        "summary": str(finding)[:200],
        "trace_id": str(context.get("trace_id") or ""),
        "intent": intent,
        "message": message,
    }
    if anchor:
        # anchor 供准入判 M1；source_anchor 供治理复核（source: 不参与文件复核）
        candidate["anchor"] = anchor
        candidate["source_anchor"] = anchor
    return candidate


def append_candidate(candidate: Dict[str, Any], root: str) -> bool:
    """追加候选到暂存文件；坏输入/IO 异常 → False，不抛错。"""
    try:
        if not isinstance(candidate, dict) or not candidate.get("content"):
            return False
        path = pending_path(root)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(candidate, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def read_candidates(root: str) -> list:
    """读取暂存候选（坏行跳过，FAIL-OPEN）。"""
    try:
        path = pending_path(root)
        if not os.path.exists(path):
            return []
        out = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                text = line.strip()
                if not text:
                    continue
                try:
                    item = json.loads(text)
                    if isinstance(item, dict) and item.get("content"):
                        out.append(item)
                except Exception:
                    continue
        return out
    except Exception:
        return []
