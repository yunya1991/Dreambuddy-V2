# -*- coding: utf-8 -*-
"""P0-D3D: 立案票据（BrainstormTicket）。只记录决策过程，不改 DSH Ticket。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict, Optional, Tuple

from core.tier_policy import TierInput, decide_tier


def _as_tuple(value: Any) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    try:
        return tuple(str(v) for v in value)
    except TypeError:
        return ()


TRANSITIONS = {
    "open": frozenset({"proposing", "cancelled"}),
    "proposing": frozenset({"debating", "decided", "cancelled"}),
    "debating": frozenset({"experimenting", "decided", "cancelled"}),
    "experimenting": frozenset({"decided", "cancelled"}),
    "decided": frozenset(),
    "cancelled": frozenset(),
}


@dataclass(frozen=True)
class BrainstormTicket:
    ticket_id: str
    gap_key: str
    gap_statement: str
    source_layer: str
    evidence_refs: Tuple[str, ...] = ()
    tier: str = "T0"
    tier_reason: str = ""
    policy_version: str = ""
    status: str = "open"
    created_at: float = 0.0
    updated_at: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", _as_tuple(self.evidence_refs))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "gap_key": self.gap_key,
            "gap_statement": self.gap_statement,
            "source_layer": self.source_layer,
            "evidence_refs": list(self.evidence_refs),
            "tier": self.tier,
            "tier_reason": self.tier_reason,
            "policy_version": self.policy_version,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def create_ticket(
    ticket_id: str,
    gap_key: str,
    gap_statement: str,
    source_layer: str,
    evidence_refs: Any = (),
    tier_input: Any = None,
    now: float = 0.0,
) -> BrainstormTicket:
    decision = decide_tier(tier_input if isinstance(tier_input, TierInput) else TierInput())
    return BrainstormTicket(
        ticket_id=str(ticket_id),
        gap_key=str(gap_key),
        gap_statement=str(gap_statement),
        source_layer=str(source_layer),
        evidence_refs=_as_tuple(evidence_refs),
        tier=decision.tier,
        tier_reason=decision.tier_reason,
        policy_version=decision.policy_version,
        created_at=float(now),
        updated_at=float(now),
    )


def transition(ticket: Any, status: str) -> Optional[BrainstormTicket]:
    """非法状态迁移返回 None，不抛异常。"""
    if not isinstance(ticket, BrainstormTicket):
        return None
    target = str(status or "")
    if target not in TRANSITIONS.get(ticket.status, frozenset()):
        return None
    return replace(ticket, status=target, updated_at=ticket.updated_at + 1.0)
