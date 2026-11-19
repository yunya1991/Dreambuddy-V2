# -*- coding: utf-8 -*-
"""P0-D3D: 决策记录（DecisionRecord）。

只有 adopted 且未过期、哈希一致的记录才能被 DSH 消费。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any, Dict, Tuple

STATUSES = frozenset({"draft", "reviewed", "adopted", "rejected", "superseded"})


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
class DecisionRecord:
    decision_id: str
    ticket_id: str
    status: str = "draft"
    chosen_option: str = ""
    rationale: str = ""
    evidence_refs: Tuple[str, ...] = ()
    dissent: Tuple[str, ...] = ()
    confidence: float = 0.0
    owner: str = "human"
    expires_at: float = 0.0
    decision_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", str(self.status or "draft").lower())
        object.__setattr__(self, "evidence_refs", _as_tuple(self.evidence_refs))
        object.__setattr__(self, "dissent", _as_tuple(self.dissent))

    def payload(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "ticket_id": self.ticket_id,
            "status": self.status,
            "chosen_option": self.chosen_option,
            "rationale": self.rationale,
            "evidence_refs": list(self.evidence_refs),
            "dissent": list(self.dissent),
            "confidence": self.confidence,
            "owner": self.owner,
            "expires_at": self.expires_at,
        }

    def to_dict(self) -> Dict[str, Any]:
        data = self.payload()
        data["decision_hash"] = self.decision_hash
        return data


def compute_decision_hash(record: Any) -> str:
    if not isinstance(record, DecisionRecord):
        return ""
    body = json.dumps(record.payload(), sort_keys=True, ensure_ascii=False, default=str)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def adopt_record(record: Any, now: float = 0.0) -> Any:
    """将记录置为 adopted 并计算哈希；非法输入返回 None。"""
    if not isinstance(record, DecisionRecord):
        return None
    adopted = replace(record, status="adopted", decision_hash="")
    return replace(adopted, decision_hash=compute_decision_hash(adopted))


def is_consumable(record: Any, now: float = 0.0) -> bool:
    """只有 adopted、未过期、哈希一致才可消费。"""
    if not isinstance(record, DecisionRecord):
        return False
    if record.status != "adopted":
        return False
    if float(record.expires_at) <= float(now):
        return False
    return record.decision_hash == compute_decision_hash(record)
