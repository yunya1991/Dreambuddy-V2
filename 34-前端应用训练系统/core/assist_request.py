# -*- coding: utf-8 -*-
"""P0-D3D: DSH → Hermes 外援请求（A6 关闭项）。

默认异步非阻塞；每 Ticket 最多 2 次；同 need_hash 不重复。
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

RESULT_STATUSES = frozenset({"resolved", "partial", "needs_brainstorm", "rejected"})


def _as_tuple(value: Any) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    try:
        return tuple(str(v) for v in value)
    except TypeError:
        return ()


def _need_hash(need: str) -> str:
    return "sha256:" + hashlib.sha256(str(need or "").encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AssistRequest:
    assist_id: str
    ticket_id: str
    trace_id: str
    need: str
    need_hash: str = ""
    context_refs: Tuple[str, ...] = ()
    allowed_tools: Tuple[str, ...] = ()
    forbidden_tools: Tuple[str, ...] = ()
    budget: Dict[str, Any] = None  # type: ignore[assignment]
    blocking: bool = False
    deadline_s: float = 300.0
    read_only: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "context_refs", _as_tuple(self.context_refs))
        object.__setattr__(self, "allowed_tools", _as_tuple(self.allowed_tools))
        object.__setattr__(self, "forbidden_tools", _as_tuple(self.forbidden_tools))
        object.__setattr__(self, "budget", dict(self.budget or {}))
        if not self.need_hash:
            object.__setattr__(self, "need_hash", _need_hash(self.need))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "assist_id": self.assist_id,
            "ticket_id": self.ticket_id,
            "trace_id": self.trace_id,
            "need": self.need,
            "need_hash": self.need_hash,
            "context_refs": list(self.context_refs),
            "allowed_tools": list(self.allowed_tools),
            "forbidden_tools": list(self.forbidden_tools),
            "budget": dict(self.budget),
            "blocking": self.blocking,
            "deadline_s": self.deadline_s,
            "read_only": self.read_only,
        }


@dataclass(frozen=True)
class AssistResult:
    assist_id: str
    status: str = "resolved"
    output: str = ""
    evidence_refs: Tuple[str, ...] = ()
    capability_gap: Optional[str] = None
    partial_reason: Optional[str] = None
    cost_usd: float = 0.0
    elapsed_ms: int = 0
    trace_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _as_tuple(self.evidence_refs))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "assist_id": self.assist_id,
            "status": self.status,
            "output": self.output,
            "evidence_refs": list(self.evidence_refs),
            "capability_gap": self.capability_gap,
            "partial_reason": self.partial_reason,
            "cost_usd": self.cost_usd,
            "elapsed_ms": self.elapsed_ms,
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Optional["AssistResult"]:
        if not isinstance(data, dict):
            return None
        status = str(data.get("status") or "")
        if status not in RESULT_STATUSES:
            return None
        return cls(
            assist_id=str(data.get("assist_id") or ""),
            status=status,
            output=str(data.get("output") or ""),
            evidence_refs=_as_tuple(data.get("evidence_refs")),
            capability_gap=data.get("capability_gap"),
            partial_reason=data.get("partial_reason"),
            cost_usd=float(data.get("cost_usd") or 0.0),
            elapsed_ms=int(data.get("elapsed_ms") or 0),
            trace_id=str(data.get("trace_id") or ""),
        )


class AssistLedger:
    """Ticket 级外援账本：最多 2 次、同 need_hash 不重复。"""

    def __init__(self, max_per_ticket: int = 2) -> None:
        self.max_per_ticket = max_per_ticket
        self._counts: Dict[str, int] = {}
        self._seen: Dict[str, set] = {}
        self._lock = threading.Lock()

    def allow(self, ticket_id: str, need_hash: str) -> bool:
        key = str(ticket_id or "")
        digest = str(need_hash or "")
        if not key or not digest:
            return False
        with self._lock:
            if self._counts.get(key, 0) >= self.max_per_ticket:
                return False
            seen = self._seen.setdefault(key, set())
            if digest in seen:
                return False
            seen.add(digest)
            self._counts[key] = self._counts.get(key, 0) + 1
            return True

    def count(self, ticket_id: str) -> int:
        with self._lock:
            return self._counts.get(str(ticket_id or ""), 0)


class AssistInbox:
    """异步外援结果收件箱：DSH 可继续执行，随后 drain 获取结果。"""

    def __init__(self) -> None:
        self._results: Dict[str, AssistResult] = {}
        self._lock = threading.Lock()

    def deliver(self, result: Any) -> bool:
        if not isinstance(result, AssistResult) or not result.assist_id:
            return False
        if result.status not in RESULT_STATUSES:
            return False
        with self._lock:
            if result.assist_id in self._results:
                return False
            self._results[result.assist_id] = result
            return True

    def drain(self) -> Tuple[AssistResult, ...]:
        with self._lock:
            items = tuple(self._results.values())
            self._results.clear()
            return items

    def get(self, assist_id: str) -> Optional[AssistResult]:
        with self._lock:
            return self._results.get(str(assist_id or ""))
