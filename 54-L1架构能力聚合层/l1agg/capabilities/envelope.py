# -*- coding: utf-8 -*-
"""统一能力结果信封（CapabilityResult）。

契约唯一事实源：`contracts/capability_result.schema.json`（SPEC-54 §5.3）。
本模块只做「组装 + 校验」，不做计算、不读库、不写库。

约束：
  - 顶层字段固定：`ok/capability/intent/answer/data/quality/trace_id`；
  - `quality` 只在顶层出现，`data` 内禁止嵌套 `quality`；
  - `answer` 禁止为空串；`quality.status != "good"` 时必须带降级说明；
  - 无法作答 → `ok=false`、`status=empty`，由 L1 转 L2（不伪造数据）。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

STATUS_GOOD = "good"
STATUS_PARTIAL = "partial"
STATUS_EMPTY = "empty"

_INSUFFICIENT = "insufficient_samples"


def quality(
    *,
    status: str,
    sample_n: int = 0,
    span: Optional[Sequence[str]] = None,
    is_stale: bool = False,
    degraded_reason: Optional[str] = None,
    sources: Optional[Iterable[str]] = None,
    missing_rate: Optional[float] = None,
    align_method: Optional[str] = None,
    timezone: Optional[str] = None,
) -> Dict[str, Any]:
    if status not in (STATUS_GOOD, STATUS_PARTIAL, STATUS_EMPTY):
        raise ValueError(f"invalid quality.status: {status!r}")
    if status != STATUS_GOOD and not degraded_reason:
        raise ValueError("quality.status != good 时必须提供 degraded_reason")
    return {
        "status": status,
        "sample_n": int(sample_n),
        "span": list(span) if span else None,
        "is_stale": bool(is_stale),
        "degraded_reason": degraded_reason,
        "sources": list(sources) if sources is not None else [],
        "missing_rate": missing_rate,
        "align_method": align_method,
        "timezone": timezone,
    }


def quality_for(
    sample_n: int,
    *,
    min_n: int,
    span: Optional[Sequence[str]] = None,
    is_stale: bool = False,
    sources: Optional[Iterable[str]] = None,
    missing_rate: Optional[float] = None,
    align_method: Optional[str] = None,
    timezone: Optional[str] = None,
) -> Dict[str, Any]:
    """按最小样本门禁自动定级：0 → empty，< min_n → partial，否则 good。"""
    if sample_n <= 0:
        return quality(
            status=STATUS_EMPTY,
            sample_n=0,
            span=span,
            is_stale=is_stale,
            degraded_reason="no_history",
            sources=sources,
            missing_rate=missing_rate,
            align_method=align_method,
            timezone=timezone,
        )
    if sample_n < min_n:
        return quality(
            status=STATUS_PARTIAL,
            sample_n=sample_n,
            span=span,
            is_stale=is_stale,
            degraded_reason=_INSUFFICIENT,
            sources=sources,
            missing_rate=missing_rate,
            align_method=align_method,
            timezone=timezone,
        )
    reason = "stale_data" if is_stale else None
    return quality(
        status=STATUS_PARTIAL if reason else STATUS_GOOD,
        sample_n=sample_n,
        span=span,
        is_stale=is_stale,
        degraded_reason=reason,
        sources=sources,
        missing_rate=missing_rate,
        align_method=align_method,
        timezone=timezone,
    )


def build(
    *,
    capability: str,
    intent: str,
    answer: str,
    data: Mapping[str, Any],
    quality_block: Mapping[str, Any],
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """组装并校验 CapabilityResult；契约违规直接抛 ValueError（禁止静默降级）。"""
    if not capability or not intent:
        raise ValueError("capability/intent 必填")
    text = (answer or "").strip()
    if not text:
        raise ValueError("answer 禁止为空串；无法作答请返回 ok=false + status=empty")
    if "quality" in data:
        raise ValueError("data 内禁止嵌套 quality（quality 固定顶层）")
    if "answer" in data:
        raise ValueError("data 内禁止嵌套 answer（answer 固定顶层）")
    status = quality_block.get("status")
    if status not in (STATUS_GOOD, STATUS_PARTIAL, STATUS_EMPTY):
        raise ValueError(f"invalid quality.status: {status!r}")
    if status != STATUS_GOOD and "降级" not in text and "样本" not in text and "不足" not in text:
        raise ValueError("quality.status != good 时 answer 必须含降级说明")
    return {
        "ok": status != STATUS_EMPTY,
        "capability": capability,
        "intent": intent,
        "answer": text,
        "data": dict(data),
        "quality": dict(quality_block),
        "trace_id": trace_id,
    }


def unavailable(
    *,
    capability: str,
    intent: str,
    reason: str,
    data: Optional[Mapping[str, Any]] = None,
    sources: Optional[Iterable[str]] = None,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """干净交接：ok=false + status=empty，answer 说明原因但不给数值。"""
    text = f"暂无法给出该项统计：{reason}。样本或数据不足，不做推算（转 L2 处理）。"
    return build(
        capability=capability,
        intent=intent,
        answer=text,
        data=dict(data or {}),
        quality_block=quality(status=STATUS_EMPTY, degraded_reason=reason, sources=sources),
        trace_id=trace_id,
    )
