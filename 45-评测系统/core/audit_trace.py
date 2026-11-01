# -*- coding: utf-8 -*-
"""
audit_trace.py — 全链路审计查询（P3-5）
=========================================
职责（PLAN P3-5 验收）：
「申请 → 执行 → 判定 → 回滚」全链路一次查全，供事后追责与复算：
- 申请：eval_requests（purpose / category / object_ref / 状态）
- 执行：latest run + 评测项 + 证据链（prev/hash 可校验）
- 判定：eval_report（verdict / block_reasons / expires_at）
- 门禁：enforcement.jsonl 中的放行/拦截裁决（含影子观测）
- 回滚：`status=cancelled` 即表示取消；撤销后仍可查到原始报告（报告不可变）

只读：不修改任何记录（SPEC §3.4 Gate 只读 Run + Threshold）。
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any

from storage.audit import AuditLog
from storage.repo import EvalRepo, zulu


class TraceError(LookupError):
    """未知 eval_id。"""


def trace(
    repo: EvalRepo,
    eval_id: str,
    audit: AuditLog | None = None,
    *,
    limit: int = 50,
) -> dict[str, Any]:
    request = repo.get_request(eval_id)
    if request is None:
        raise TraceError(f"未知 eval_id: {eval_id}")

    run = repo.latest_run_for_eval(eval_id)
    items = repo.list_items(run.run_id) if run else []
    evidence = repo.list_evidence(run.run_id) if run else []
    report = repo.get_report(eval_id)
    enforcements = audit.query(eval_id=eval_id, limit=limit) if audit else []

    return {
        "eval_id": eval_id,
        "request": _norm(request),
        "run": _norm(run) if run else None,
        "items": [_norm(i) for i in items],
        "evidence": [_norm(e) for e in evidence],
        "report": report,
        "enforcements": enforcements,
        "cancelled": getattr(request, "status", "") == "cancelled",
        "complete": report is not None,
    }


def _norm(obj: Any) -> Any:
    """dataclass → JSON 友好 dict（datetime 统一为 UTC Z 字符串）。"""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _norm(v) for k, v in asdict(obj).items()}
    if isinstance(obj, datetime):
        return zulu(obj)
    if isinstance(obj, dict):
        return {k: _norm(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_norm(v) for v in obj]
    return obj
