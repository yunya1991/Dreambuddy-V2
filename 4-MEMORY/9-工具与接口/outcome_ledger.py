"""Outcome Ledger — T-G1 后果回传账本

SPEC-33-G：
  - §1 G-G1：每次假设可关联 outcome{accepted, tests_pass, reverted}；verify 只接受带 outcome 的调用
  - §2.11.9：单一事实源 `ledger/events.jsonl`；幂等键 (change_id, run_id, outcome_seq)；
    事件带 prev_hash 形成哈希链；schema 演进走 expand-contract

工程约束：纯 Python 标准库；append-only JSONL；原子写（tmp + os.replace）。
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = "1"
REQUIRED_BOOL_FIELDS = ("accepted", "tests_pass", "reverted")
_GENESIS = "0" * 64
_DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "ledger" / "events.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_outcome(outcome: Any) -> Tuple[bool, str]:
    """校验 outcome 契约。

    必需：accepted / tests_pass / reverted 三个布尔字段（严格 bool）。
    幂等三元组：change_id / run_id / outcome_seq 要么全缺，要么全给。
    """
    if not isinstance(outcome, dict):
        return False, "outcome must be an object"
    for key in REQUIRED_BOOL_FIELDS:
        if key not in outcome:
            return False, f"missing required field: {key}"
        if not isinstance(outcome[key], bool):
            return False, f"field {key} must be boolean"

    triple = ("change_id", "run_id", "outcome_seq")
    present = [k for k in triple if outcome.get(k) not in (None, "")]
    if present and len(present) != len(triple):
        missing = [k for k in triple if k not in present]
        return (
            False,
            f"change_id/run_id/outcome_seq must be provided together; missing: {', '.join(missing)}",
        )
    if "outcome_seq" in present:
        seq = outcome["outcome_seq"]
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
            return False, "outcome_seq must be a non-negative integer"
    return True, ""


@dataclass
class OutcomeEvent:
    accepted: bool
    tests_pass: bool
    reverted: bool
    change_id: str = ""
    run_id: str = ""
    outcome_seq: Optional[int] = None
    memory_id: str = ""
    policy_id: str = ""
    section: str = ""
    source: str = "verify"
    created_at: str = field(default_factory=_now)
    schema_version: str = SCHEMA_VERSION
    event_id: str = field(default_factory=lambda: f"oe_{uuid.uuid4().hex}")

    def idempotency_key(self) -> Optional[Tuple[str, str, int]]:
        if not self.change_id or not self.run_id or self.outcome_seq is None:
            return None
        return (self.change_id, self.run_id, self.outcome_seq)

    def payload(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "accepted": self.accepted,
            "tests_pass": self.tests_pass,
            "reverted": self.reverted,
            "change_id": self.change_id,
            "run_id": self.run_id,
            "outcome_seq": self.outcome_seq,
            "memory_id": self.memory_id,
            "policy_id": self.policy_id,
            "section": self.section,
            "source": self.source,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
        }


class OutcomeLedger:
    """append-only outcome 账本，带 prev_hash 哈希链与幂等覆盖。"""

    def __init__(self, path: Optional[str | Path] = None):
        if path is None:
            path = os.environ.get("COGNITIVE_OUTCOME_LEDGER_PATH") or _DEFAULT_PATH
        self.path = Path(path)

    # ---------- 写 ----------

    def record(
        self,
        outcome: Dict[str, Any],
        *,
        memory_id: str = "",
        source: str = "verify",
    ) -> Dict[str, Any]:
        ok, reason = validate_outcome(outcome)
        if not ok:
            raise ValueError(reason)

        event = OutcomeEvent(
            accepted=outcome["accepted"],
            tests_pass=outcome["tests_pass"],
            reverted=outcome["reverted"],
            change_id=str(outcome.get("change_id") or ""),
            run_id=str(outcome.get("run_id") or ""),
            outcome_seq=outcome.get("outcome_seq"),
            memory_id=str(outcome.get("memory_id") or memory_id or ""),
            policy_id=str(outcome.get("policy_id") or ""),
            section=str(outcome.get("section") or ""),
            source=str(outcome.get("source") or source),
        )

        events = self._read_all()
        key = event.idempotency_key()
        index = self._find_key(events, key) if key else None
        if index is None:
            prev = events[-1]["receipt_hash"] if events else _GENESIS
            entry = {"prev_hash": prev, **event.payload()}
            entry["receipt_hash"] = _hash_entry(entry)
            events.append(entry)
        else:
            entry = {"prev_hash": events[index]["prev_hash"], **event.payload()}
            entry["receipt_hash"] = _hash_entry(entry)
            events[index] = entry
            _rechain(events, index + 1)

        self._write_all(events)
        return dict(entry)

    # ---------- 读 ----------

    def events(self) -> List[Dict[str, Any]]:
        return self._read_all()

    def verify_chain(self, events: Optional[List[Dict[str, Any]]] = None) -> bool:
        events = self._read_all() if events is None else events
        prev = _GENESIS
        for entry in events:
            if entry.get("prev_hash") != prev:
                return False
            if entry.get("receipt_hash") != _hash_entry(entry):
                return False
            prev = entry["receipt_hash"]
        return True

    # ---------- 内部 ----------

    def _read_all(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        events: List[Dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))
        return events

    def _write_all(self, events: List[Dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        body = "\n".join(json.dumps(e, ensure_ascii=False, sort_keys=True) for e in events)
        tmp.write_text(body + ("\n" if events else ""), encoding="utf-8")
        os.replace(tmp, self.path)

    @staticmethod
    def _find_key(
        events: List[Dict[str, Any]], key: Optional[Tuple[str, str, int]]
    ) -> Optional[int]:
        if key is None:
            return None
        for i, entry in enumerate(events):
            if (
                entry.get("change_id"),
                entry.get("run_id"),
                entry.get("outcome_seq"),
            ) == key:
                return i
        return None


def _hash_entry(entry: Dict[str, Any]) -> str:
    payload = {k: v for k, v in entry.items() if k not in ("prev_hash", "receipt_hash")}
    return _sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False) + entry.get("prev_hash", "")
    )


def _rechain(events: List[Dict[str, Any]], start: int) -> None:
    for i in range(max(1, start), len(events)):
        events[i]["prev_hash"] = events[i - 1]["receipt_hash"]
        events[i]["receipt_hash"] = _hash_entry(events[i])
