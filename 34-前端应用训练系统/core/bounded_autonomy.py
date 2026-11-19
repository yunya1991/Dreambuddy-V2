# -*- coding: utf-8 -*-
"""P0-D3C: 有界自主授权。

约束:
  - 任何等级都拒绝硬排除项（下单/凭据/生产写/策略上线/自审批）；
  - AL0 只建议；AL1 仅可逆低风险；AL2 预算内多步；AL3 单 Ticket 显式授权；
  - 自己发起的动作不得自己审批（四眼原则）。

依据: SPEC-P0-D3C §4。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, FrozenSet, Optional, Tuple


class AutonomyLevel(str, Enum):
    AL0 = "AL0"
    AL1 = "AL1"
    AL2 = "AL2"
    AL3 = "AL3"


HARD_EXCLUSIONS: FrozenSet[str] = frozenset(
    {
        "live_trade",
        "place_order",
        "cancel_order",
        "credential",
        "prod_db_write",
        "policy_change",
        "promote_model",
        "self_approval",
    }
)

_ORDER_PATTERNS = (
    "place_order",
    "cancel_order",
    "live_trade",
    "credential",
    "prod_db_write",
    "policy_change",
    "promote_model",
)


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
class AutonomyGrant:
    grant_id: str
    subject: str
    level: AutonomyLevel
    allowed_tools: FrozenSet[str] = frozenset()
    max_budget_usd: float = 0.0
    ttl_s: float = 3600.0
    issued_at: float = 0.0
    revoked: bool = False
    exclusions: FrozenSet[str] = HARD_EXCLUSIONS

    def __post_init__(self) -> None:
        level = self.level
        if not isinstance(level, AutonomyLevel):
            try:
                level = AutonomyLevel(str(level))
            except ValueError:
                level = AutonomyLevel.AL0
        object.__setattr__(self, "level", level)
        object.__setattr__(self, "allowed_tools", frozenset(self.allowed_tools or ()))
        object.__setattr__(self, "exclusions", frozenset(self.exclusions or HARD_EXCLUSIONS))

    def is_active(self, now: Optional[float] = None) -> bool:
        if self.revoked:
            return False
        now_ts = float(now if now is not None else time.time())
        return now_ts <= float(self.issued_at) + float(self.ttl_s)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "grant_id": self.grant_id,
            "subject": self.subject,
            "level": self.level.value,
            "allowed_tools": sorted(self.allowed_tools),
            "max_budget_usd": self.max_budget_usd,
            "ttl_s": self.ttl_s,
            "issued_at": self.issued_at,
            "revoked": self.revoked,
            "exclusions": sorted(self.exclusions),
        }


@dataclass(frozen=True)
class ActionRequest:
    action: str
    tools: Tuple[str, ...] = ()
    reversible: bool = True
    risk: str = "low"
    estimated_cost_usd: float = 0.0
    initiator: str = ""
    is_approval: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "tools", _as_tuple(self.tools))
        object.__setattr__(self, "risk", str(self.risk or "low").lower())


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    reason: str
    requires_human: bool = False
    requires_second_approver: bool = False


def _deny(reason: str, *, human: bool = False, second: bool = False) -> AuthorizationDecision:
    return AuthorizationDecision(
        allowed=False, reason=reason, requires_human=human, requires_second_approver=second
    )


def authorize(grant: Any, request: Any, now: Optional[float] = None) -> AuthorizationDecision:
    """FAIL-OPEN：非法输入一律拒绝，不抛异常。"""
    try:
        if not isinstance(grant, AutonomyGrant) or not isinstance(request, ActionRequest):
            return _deny("invalid_input")
        if grant.revoked:
            return _deny("revoked")
        if not grant.is_active(now):
            return _deny("expired")

        action = str(request.action or "").lower()
        tools = tuple(str(t).lower() for t in request.tools)

        if request.is_approval and request.initiator == grant.subject:
            return _deny("self_approval", second=True)

        for token in grant.exclusions:
            token = str(token).lower()
            if token and (token in action or token in tools):
                return _deny("hard_exclusion")

        if any(pattern in action for pattern in _ORDER_PATTERNS):
            return _deny("hard_exclusion")

        if not set(tools).issubset(set(grant.allowed_tools)):
            return _deny("tool_not_allowed")

        if float(request.estimated_cost_usd) > float(grant.max_budget_usd):
            return _deny("budget_exceeded")

        if grant.level == AutonomyLevel.AL0:
            return _deny("suggest_only")

        if grant.level == AutonomyLevel.AL1:
            if request.reversible and request.risk == "low":
                return AuthorizationDecision(True, "al1_reversible")
            return _deny("requires_human", human=True)

        if grant.level == AutonomyLevel.AL2:
            if request.risk == "high" or not request.reversible:
                return _deny("requires_human", human=True)
            return AuthorizationDecision(True, "al2_bounded")

        if grant.level == AutonomyLevel.AL3:
            if not request.reversible or request.risk in {"medium", "high"}:
                return _deny("requires_second_approver", second=True)
            return AuthorizationDecision(True, "al3_granted")

        return _deny("unknown_level")
    except Exception:  # FAIL-OPEN
        return _deny("internal_error")
