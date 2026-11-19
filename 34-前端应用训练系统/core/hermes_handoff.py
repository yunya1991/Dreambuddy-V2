# -*- coding: utf-8 -*-
"""P0-D3C: DSH ↔ Hermes 断路交接协议。

职责:
  - 定义交接信封、触发分类、进度账本与防乒乓判定；
  - 只做协议与记录，不执行任务、不修改 Ticket。

硬规则:
  - 同一 Ticket 最多 2 次交接；
  - 每次交接必须携带新的 info_hash；
  - 冷却期内不得重复交接；
  - 未知触发/非法信封一律拒绝（FAIL-OPEN 返回拒绝，不抛错）。

依据: SPEC-P0-D3C §2。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

TRIGGERS = frozenset(
    {
        "route_miss",
        "tool_missing",
        "retry_exhausted",
        "no_progress",
        "evidence_gap",
        "out_of_scope",
    }
)

MAX_HANDOFFS_PER_TICKET = 2
DEFAULT_COOLDOWN_S = 60.0


def _as_tuple(value: Any) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    try:
        return tuple(str(v) for v in value)
    except TypeError:
        return ()


@dataclass(frozen=True)
class HandoffEnvelope:
    """不可变交接信封。只传结构化失败记录与证据引用，不传思维链。"""

    ticket_id: str
    trace_id: str
    trigger: str
    goal: str
    failure_class: str = "manual"
    attempted_steps: Tuple[str, ...] = ()
    evidence_refs: Tuple[str, ...] = ()
    allowed_tools: Tuple[str, ...] = ()
    forbidden_tools: Tuple[str, ...] = ()
    budget: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = "v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempted_steps", _as_tuple(self.attempted_steps))
        object.__setattr__(self, "evidence_refs", _as_tuple(self.evidence_refs))
        object.__setattr__(self, "allowed_tools", _as_tuple(self.allowed_tools))
        object.__setattr__(self, "forbidden_tools", _as_tuple(self.forbidden_tools))
        if not isinstance(self.budget, dict):
            object.__setattr__(self, "budget", {})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "trace_id": self.trace_id,
            "trigger": self.trigger,
            "goal": self.goal,
            "failure_class": self.failure_class,
            "attempted_steps": list(self.attempted_steps),
            "evidence_refs": list(self.evidence_refs),
            "allowed_tools": list(self.allowed_tools),
            "forbidden_tools": list(self.forbidden_tools),
            "budget": dict(self.budget),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "HandoffEnvelope":
        data = data if isinstance(data, dict) else {}
        return cls(
            ticket_id=str(data.get("ticket_id") or ""),
            trace_id=str(data.get("trace_id") or ""),
            trigger=str(data.get("trigger") or ""),
            goal=str(data.get("goal") or ""),
            failure_class=str(data.get("failure_class") or "manual"),
            attempted_steps=_as_tuple(data.get("attempted_steps")),
            evidence_refs=_as_tuple(data.get("evidence_refs")),
            allowed_tools=_as_tuple(data.get("allowed_tools")),
            forbidden_tools=_as_tuple(data.get("forbidden_tools")),
            budget=data.get("budget") if isinstance(data.get("budget"), dict) else {},
            schema_version=str(data.get("schema_version") or "v1"),
        )


@dataclass(frozen=True)
class HandoffDecision:
    allowed: bool
    reason: str


def info_hash(envelope: HandoffEnvelope) -> str:
    """失败信息指纹：只有出现新指纹才允许再次交接。"""
    payload = {
        "trigger": envelope.trigger,
        "failure_class": envelope.failure_class,
        "attempted_steps": list(envelope.attempted_steps),
        "evidence_refs": list(envelope.evidence_refs),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class HandoffLedger:
    """单调追加的交接账本；同时支持内存与 JSONL。"""

    def __init__(self, path: Optional[str] = None) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._entries: List[Dict[str, Any]] = []
        if path:
            self._entries = self._load(path)

    @staticmethod
    def _load(path: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        try:
            if not os.path.exists(path):
                return out
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except (TypeError, ValueError):
                        continue
                    if isinstance(item, dict):
                        out.append(item)
        except OSError:
            return []
        return out

    def append(
        self, envelope: HandoffEnvelope, status: str = "handed_off", now: Optional[float] = None
    ) -> Dict[str, Any]:
        record = envelope.to_dict()
        record.update(
            {
                "status": status,
                "ts": float(now if now is not None else time.time()),
                "info_hash": info_hash(envelope),
            }
        )
        with self._lock:
            self._entries.append(record)
            if self._path:
                try:
                    os.makedirs(os.path.dirname(os.path.abspath(self._path)), exist_ok=True)
                    with open(self._path, "a", encoding="utf-8") as handle:
                        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                except OSError:
                    pass
        return dict(record)

    def entries(self, ticket_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            if ticket_id is None:
                return [dict(item) for item in self._entries]
            return [dict(item) for item in self._entries if item.get("ticket_id") == ticket_id]

    def handoff_count(self, ticket_id: str) -> int:
        with self._lock:
            return sum(
                1
                for item in self._entries
                if item.get("ticket_id") == ticket_id and item.get("status") == "handed_off"
            )

    def has_new_information(self, ticket_id: str, fingerprint: str) -> bool:
        with self._lock:
            return not any(
                item.get("ticket_id") == ticket_id and item.get("info_hash") == fingerprint
                for item in self._entries
            )

    def last_ts(self, ticket_id: str) -> Optional[float]:
        with self._lock:
            values = [
                item.get("ts")
                for item in self._entries
                if item.get("ticket_id") == ticket_id and isinstance(item.get("ts"), (int, float))
            ]
        return max(values) if values else None


def decide_handoff(
    envelope: Any,
    ledger: HandoffLedger,
    now: Optional[float] = None,
    cooldown_s: float = DEFAULT_COOLDOWN_S,
) -> HandoffDecision:
    """判定是否允许交接；FAIL-OPEN：任何异常都返回拒绝。"""
    try:
        if not isinstance(envelope, HandoffEnvelope):
            return HandoffDecision(False, "invalid_envelope")
        if not envelope.ticket_id or not envelope.trace_id or not envelope.goal:
            return HandoffDecision(False, "invalid_envelope")
        if envelope.trigger not in TRIGGERS:
            return HandoffDecision(False, "unknown_trigger")
        if not isinstance(ledger, HandoffLedger):
            return HandoffDecision(False, "invalid_ledger")

        if ledger.handoff_count(envelope.ticket_id) >= MAX_HANDOFFS_PER_TICKET:
            return HandoffDecision(False, "handoff_limit")

        now_ts = float(now if now is not None else time.time())
        last = ledger.last_ts(envelope.ticket_id)
        if last is not None and cooldown_s > 0 and now_ts - last < cooldown_s:
            return HandoffDecision(False, "cooldown")

        if not ledger.has_new_information(envelope.ticket_id, info_hash(envelope)):
            return HandoffDecision(False, "no_new_information")

        return HandoffDecision(True, "ok")
    except Exception:  # FAIL-OPEN
        return HandoffDecision(False, "internal_error")
