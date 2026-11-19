# -*- coding: utf-8 -*-
"""P0-D3D: 紧急运维预授权策略（H6 关闭项）。

只覆盖可逆、低/中风险的运维类；Gate/live/不可逆/安全/生产写一律排除。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

HARD_EXCLUSIONS = frozenset(
    {
        "gate",
        "gate_approval",
        "live",
        "live_trade",
        "place_order",
        "irreversible",
        "security",
        "policy_change",
        "prod_db_write",
        "credential",
        "promote_model",
    }
)


@dataclass(frozen=True)
class UrgentPolicy:
    policy_id: str
    task_class: str
    risk: str = "low"
    reversible: bool = True
    max_scope: str = ""
    max_budget: float = 0.0
    ttl_s: float = 600.0
    audit: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_class", str(self.task_class or "").lower())
        object.__setattr__(self, "risk", str(self.risk or "low").lower())


class UrgentPolicyRegistry:
    def __init__(self) -> None:
        self._policies: Dict[str, UrgentPolicy] = {}

    def register(self, policy: Any) -> List[str]:
        errors: List[str] = []
        if not isinstance(policy, UrgentPolicy):
            return ["invalid_policy"]
        if not policy.policy_id:
            errors.append("policy_id_required")
        if not policy.task_class:
            errors.append("task_class_required")
        if policy.risk not in {"low", "medium"}:
            errors.append("risk_not_allowed")
        if not policy.reversible:
            errors.append("irreversible")
        if not policy.audit:
            errors.append("audit_required")
        if any(token in policy.task_class for token in HARD_EXCLUSIONS):
            errors.append("hard_exclusion")
        if errors:
            return errors
        self._policies[policy.policy_id] = policy
        return []

    def can_auto_approve(self, policy_id: str, task_class: str) -> bool:
        policy = self._policies.get(str(policy_id or ""))
        if policy is None:
            return False
        return (
            policy.task_class == str(task_class or "").lower()
            and policy.reversible
            and policy.risk in {"low", "medium"}
            and policy.audit
        )
