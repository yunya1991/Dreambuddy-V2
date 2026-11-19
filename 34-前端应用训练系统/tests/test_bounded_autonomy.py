# -*- coding: utf-8 -*-
"""P0-D3C RED: 有界自主授权。

契约:
  AutonomyGrant + ActionRequest + authorize
  硬排除: 下单/凭据/生产写/策略上线/自审批。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.bounded_autonomy import (  # noqa: E402
    ActionRequest,
    AutonomyGrant,
    AutonomyLevel,
    authorize,
)

NOW = 10_000.0


def _grant(level=AutonomyLevel.AL2, **kw):
    data = {
        "grant_id": "AG-1",
        "subject": "hermes-field-assistant",
        "level": level,
        "allowed_tools": frozenset({"recall", "unified_search"}),
        "max_budget_usd": 1.0,
        "ttl_s": 3600,
        "issued_at": NOW - 10,
    }
    data.update(kw)
    return AutonomyGrant(**data)


def test_al0_is_suggest_only():
    d = authorize(_grant(level=AutonomyLevel.AL0), ActionRequest(action="draft"), now=NOW)
    assert d.allowed is False
    assert d.reason == "suggest_only"


def test_al1_reversible_low_risk_allowed():
    d = authorize(
        _grant(level=AutonomyLevel.AL1),
        ActionRequest(action="read_report", tools=("recall",), reversible=True, risk="low"),
        now=NOW,
    )
    assert d.allowed is True


def test_al1_irreversible_requires_human():
    d = authorize(
        _grant(level=AutonomyLevel.AL1),
        ActionRequest(action="write_report", tools=("recall",), reversible=False, risk="low"),
        now=NOW,
    )
    assert d.allowed is False
    assert d.requires_human is True


def test_hard_exclusion_order_denied():
    d = authorize(
        _grant(),
        ActionRequest(action="place_order", tools=("recall",), reversible=False, risk="high"),
        now=NOW,
    )
    assert d.allowed is False
    assert d.reason == "hard_exclusion"


def test_tool_not_allowed_denied():
    d = authorize(
        _grant(),
        ActionRequest(action="read", tools=("place_order",), reversible=True, risk="low"),
        now=NOW,
    )
    assert d.allowed is False
    assert d.reason in {"hard_exclusion", "tool_not_allowed"}


def test_expired_grant_denied():
    d = authorize(_grant(issued_at=NOW - 7200, ttl_s=60), ActionRequest(action="read"), now=NOW)
    assert d.allowed is False
    assert d.reason == "expired"


def test_revoked_grant_denied():
    d = authorize(_grant(revoked=True), ActionRequest(action="read"), now=NOW)
    assert d.allowed is False
    assert d.reason == "revoked"


def test_budget_exceeded_denied():
    d = authorize(
        _grant(max_budget_usd=0.1), ActionRequest(action="read", estimated_cost_usd=0.5), now=NOW
    )
    assert d.allowed is False
    assert d.reason == "budget_exceeded"


def test_self_approval_requires_second_approver():
    d = authorize(
        _grant(level=AutonomyLevel.AL3),
        ActionRequest(action="approve", is_approval=True, initiator="hermes-field-assistant"),
        now=NOW,
    )
    assert d.allowed is False
    assert d.requires_second_approver is True
    assert d.reason == "self_approval"


def test_al3_irreversible_requires_second_approver():
    d = authorize(
        _grant(level=AutonomyLevel.AL3),
        ActionRequest(action="publish_report", reversible=False, risk="medium"),
        now=NOW,
    )
    assert d.allowed is False
    assert d.requires_second_approver is True
