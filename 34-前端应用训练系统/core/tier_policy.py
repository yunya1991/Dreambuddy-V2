# -*- coding: utf-8 -*-
"""P0-D3D: 立案分级策略（C1 关闭项）。

规则:
  T3: critical / irreversible / live / security / policy_change
  T2: cross_domain / evidence_gap>=2 / uncertainty>=0.7
  T1: option>=2 / uncertainty>=0.4
  T0: 其余
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

POLICY_VERSION = "tier-policy-v1"
_HIGH_RISK_TOKENS = ("live", "security", "policy_change", "promote_model", "prod_db_write")


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class TierInput:
    risk_level: str = "low"
    reversible: bool = True
    blast_radius: str = "single_task"
    evidence_gap_count: int = 0
    option_count: int = 1
    uncertainty_score: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "risk_level", str(self.risk_level or "low").lower())
        object.__setattr__(self, "blast_radius", str(self.blast_radius or "single_task").lower())
        object.__setattr__(self, "evidence_gap_count", _as_int(self.evidence_gap_count))
        object.__setattr__(self, "option_count", _as_int(self.option_count, 1))
        object.__setattr__(self, "uncertainty_score", _as_float(self.uncertainty_score))


@dataclass(frozen=True)
class TierDecision:
    tier: str
    tier_reason: str
    policy_version: str = POLICY_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier,
            "tier_reason": self.tier_reason,
            "policy_version": self.policy_version,
        }


def decide_tier(data: Any) -> TierDecision:
    """FAIL-OPEN：非法输入按 T3 处理，避免高风险漏判。"""
    if not isinstance(data, TierInput):
        return TierDecision("T3", "invalid_input")
    if data.risk_level == "critical":
        return TierDecision("T3", "risk=critical")
    if not data.reversible:
        return TierDecision("T3", "irreversible")
    if any(token in data.risk_level for token in _HIGH_RISK_TOKENS):
        return TierDecision("T3", f"risk={data.risk_level}")
    if data.blast_radius == "cross_domain" or data.blast_radius == "system":
        return TierDecision("T2", f"blast_radius={data.blast_radius}")
    if data.evidence_gap_count >= 2:
        return TierDecision("T2", f"evidence_gap={data.evidence_gap_count}")
    if data.uncertainty_score >= 0.7:
        return TierDecision("T2", f"uncertainty={data.uncertainty_score}")
    if data.risk_level == "high":
        return TierDecision("T2", "risk=high")
    if data.option_count >= 2:
        return TierDecision("T1", f"options={data.option_count}")
    if data.uncertainty_score >= 0.4:
        return TierDecision("T1", f"uncertainty={data.uncertainty_score}")
    return TierDecision("T0", "low_risk_single_option")
