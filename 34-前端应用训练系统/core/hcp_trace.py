# -*- coding: utf-8 -*-
"""H3: ExecutionTrace v2 影子字段 + 命令信封 join（P0 / shadow）。

对齐 56/SPEC-56-H v0.3 §4.3 / §5.1:
  - span.schema.json v1.0 顶层字段不变，新 ID 只写 `attrs["hcp.*"]`
  - 缺失 session_id 时不伪造；v1.0 消费方不感知新字段
  - 命令信封（meta）携带 trace_id / session_id / tool_call_id，由 `hcp.trace.shadow` 开关控制
  - join 口径：case / trace / tool_call 任一相同为强关联（计入分子）；
    仅 session_id 相同且时间差 ≤60s 为弱关联（单列，不计入分子）
"""

from __future__ import annotations

import copy
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

HCP_FLAG = "hcp.trace.shadow"
HCP_PREFIX = "hcp."
DEFAULT_WEAK_GAP_S = 60.0

_SEGMENTS = ("sense", "arrange", "capability", "compute", "gate", "memory", "scheduler", "artifact")
_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{3,64}$")
_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
_CONTEXT_HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def hcp_enabled(flags: Optional[Dict[str, Any]]) -> bool:
    return bool(isinstance(flags, dict) and flags.get(HCP_FLAG, False))


def hcp_attrs(
    session_id: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    interaction_case_id: Optional[str] = None,
    **extra: Optional[str],
) -> Dict[str, str]:
    """只写入调用方真实提供的 ID，绝不伪造缺失值。"""
    pairs = {
        "session_id": session_id,
        "tool_call_id": tool_call_id,
        "interaction_case_id": interaction_case_id,
        **extra,
    }
    return {
        f"{HCP_PREFIX}{key}": value
        for key, value in pairs.items()
        if isinstance(value, str) and value.strip()
    }


def attach_hcp(
    span: Dict[str, Any],
    *,
    session_id: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    interaction_case_id: Optional[str] = None,
) -> Dict[str, Any]:
    """把 HCP ID 合并进 span.attrs（不原地修改、不新增顶层字段）。"""
    if not isinstance(span, dict):
        raise TypeError("span 必须是 dict")
    out = copy.deepcopy(span)
    attrs = dict(out.get("attrs") or {})
    attrs.update(hcp_attrs(session_id, tool_call_id, interaction_case_id))
    out["attrs"] = attrs
    return out


def _parse_ts(value: Any) -> Optional[datetime]:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def build_span(
    *,
    trace_id: str,
    run_id: str,
    name: str,
    segment: str,
    started_at: str,
    ended_at: str,
    context_hash: str,
    span_id: Optional[str] = None,
    parent_span_id: Optional[str] = None,
    model_id: str = "none",
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_cu: float = 0.0,
    stop_reason: Optional[str] = "done",
    attrs: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    interaction_case_id: Optional[str] = None,
) -> Dict[str, Any]:
    """生成 v1.0 顶层 + attrs.hcp 影子字段的 span（fail-closed 校验）。"""
    if segment not in _SEGMENTS:
        raise ValueError(f"segment 非法: {segment!r}")
    for label, value in (("trace_id", trace_id), ("run_id", run_id)):
        if not isinstance(value, str) or not _ID_PATTERN.match(value):
            raise ValueError(f"{label} 不符合契约 pattern: {value!r}")
    if not isinstance(name, str) or not _NAME_PATTERN.match(name):
        raise ValueError(f"name 不符合契约 pattern: {name!r}")
    if not _CONTEXT_HASH_PATTERN.match(str(context_hash)):
        raise ValueError(f"context_hash 非法: {context_hash!r}")
    if _parse_ts(ended_at) is None or _parse_ts(started_at) is None:
        raise ValueError("started_at / ended_at 必须是 RFC3339 时间")
    if _parse_ts(ended_at) < _parse_ts(started_at):
        raise ValueError("ended_at 早于 started_at")
    if model_id == "none" and (tokens_in or tokens_out or cost_cu):
        raise ValueError("model_id=none 时 tokens_in/tokens_out/cost_cu 必须为 0")

    span: Dict[str, Any] = {
        "schema_version": "1.0",
        "trace_id": trace_id,
        "run_id": run_id,
        "span_id": span_id or f"sp-{uuid.uuid4().hex[:16]}",
        "parent_span_id": parent_span_id,
        "name": name,
        "segment": segment,
        "started_at": started_at,
        "ended_at": ended_at,
        "model_id": model_id,
        "tokens_in": int(tokens_in),
        "tokens_out": int(tokens_out),
        "cost_cu": float(cost_cu),
        "stop_reason": stop_reason,
        "context_hash": context_hash,
        "attrs": dict(attrs or {}),
    }
    return attach_hcp(
        span,
        session_id=session_id,
        tool_call_id=tool_call_id,
        interaction_case_id=interaction_case_id,
    )


def stamp_envelope(
    envelope: Dict[str, Any],
    *,
    trace_id: Optional[str] = None,
    session_id: Optional[str] = None,
    tool_call_id: Optional[str] = None,
) -> Dict[str, Any]:
    """命令信封 meta 注入同一 trace/session/tool_call；缺失值不写入。"""
    if not isinstance(envelope, dict):
        return envelope
    meta = dict(envelope.get("meta") or {})
    for key, value in (
        ("trace_id", trace_id),
        ("session_id", session_id),
        ("tool_call_id", tool_call_id),
    ):
        if isinstance(value, str) and value.strip():
            meta.setdefault(key, value)
    envelope["meta"] = meta
    return envelope


def _pick(*values: Any) -> Optional[str]:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
    return None


def _record_ids(record: Any) -> Dict[str, Optional[str]]:
    if not isinstance(record, dict):
        return {}
    attrs = record.get("attrs") or {}
    meta = record.get("meta") or {}
    return {
        "trace_id": _pick(record.get("trace_id"), meta.get("trace_id")),
        "session_id": _pick(
            attrs.get("hcp.session_id"), meta.get("session_id"), record.get("session_id")
        ),
        "tool_call_id": _pick(
            attrs.get("hcp.tool_call_id"), meta.get("tool_call_id"), record.get("tool_call_id")
        ),
        "interaction_case_id": _pick(
            attrs.get("hcp.interaction_case_id"),
            meta.get("interaction_case_id"),
            record.get("interaction_case_id"),
        ),
    }


def _case_ids(case: Dict[str, Any]) -> Dict[str, Optional[str]]:
    links = case.get("links") or {}
    return {
        "trace_id": _pick(case.get("trace_id"), links.get("trace_id")),
        "session_id": _pick(case.get("session_id")),
        "tool_call_id": _pick(case.get("tool_call_id")),
        "interaction_case_id": _pick(case.get("interaction_case_id"), case.get("case_id")),
    }


def classify_join(
    case: Dict[str, Any],
    records: Iterable[Dict[str, Any]],
    *,
    weak_gap_s: float = DEFAULT_WEAK_GAP_S,
) -> Dict[str, Any]:
    """G-L2-14 join 口径：strong 才计入分子；weak 单列；无 session_id 的案例不进分母。"""
    case_ids = _case_ids(case or {})
    eligible = bool(case_ids.get("session_id"))
    records = list(records or [])
    record_ids = [_record_ids(record) for record in records]

    basis = []
    for key in ("interaction_case_id", "trace_id", "tool_call_id"):
        target = case_ids.get(key)
        if target and any(ids.get(key) == target for ids in record_ids):
            basis.append(key)
    strong = bool(basis)

    weak = False
    if not strong and eligible:
        case_ts = _parse_ts(case.get("ended_at") or case.get("at"))
        if case_ts is not None:
            for record, ids in zip(records, record_ids, strict=True):
                if ids.get("session_id") != case_ids["session_id"]:
                    continue
                record_ts = _parse_ts(
                    record.get("ended_at")
                    or record.get("ts")
                    or (record.get("meta") or {}).get("ended_at")
                )
                if record_ts is None:
                    continue
                if abs((record_ts - case_ts).total_seconds()) <= weak_gap_s:
                    weak = True
                    basis.append("session_id_window")
                    break

    return {
        "eligible": eligible,
        "strong": strong,
        "weak": weak,
        "basis": basis,
    }


__all__ = [
    "DEFAULT_WEAK_GAP_S",
    "HCP_FLAG",
    "HCP_PREFIX",
    "attach_hcp",
    "build_span",
    "classify_join",
    "hcp_attrs",
    "hcp_enabled",
    "stamp_envelope",
]
