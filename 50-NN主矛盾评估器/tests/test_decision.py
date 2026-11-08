# R3-01: FinalDecisionSignal v1 测试（50 决策整合 + 执行权校验）。
from __future__ import annotations

from datetime import datetime, timezone

from core.decision import make_decision


def _ev(source, direction, confidence, symbol="BTC-USDT-SWAP", i=0):
    return {
        "evidence_id": f"e-{source}-{i}",
        "source": source,
        "symbol": symbol,
        "direction": direction,
        "confidence": confidence,
        "horizon": "hours",
        "ts": "2026-11-08T10:00:00Z",
        "expires_at": "2026-11-08T22:00:00Z",
        "provenance": "42-bus",
        "payload": {},
    }


_CONSTRAINTS = {
    "position_band": [0, 100],
    "freeze": False,
    "per_asset_class": {},
    "degraded": [],
}

_RIGHTS = {
    "fifty_nn_domain": {
        "default_outcome": "paper",
        "symbols": {"BTC-USDT-SWAP": {"outcome": "paper"}},
    }
}


def test_decision_long_integration():
    now = datetime(2026, 11, 8, 12, 0, 0, tzinfo=timezone.utc)
    evidences = [
        _ev("11-bcrm-tactical", "long", 0.9, i=1),
        _ev("11-bdsm", "long", 0.8, i=2),
        _ev("11-washout", "long", 0.7, i=3),
    ]
    d = make_decision(
        evidences,
        symbol="BTC-USDT-SWAP",
        constraints=_CONSTRAINTS,
        rights=_RIGHTS,
        reconciliation={"agreement_ratio": 1.0},
        now=now,
    )
    assert d["source"] == "50-nn"
    assert d["direction"] == "long"
    assert d["confidence"] > 0
    assert 0 <= d["position_pct"] <= 100
    assert d["payload"]["path_count"] == 3
    assert "w4" in d["payload"]
    assert "dominance" in d["payload"]
    assert d["execution"]["outcome"] == "paper"
    assert d["execution"]["allowed"] is True


def test_decision_kill_switch_fail_closed():
    now = datetime(2026, 11, 8, 12, 0, 0, tzinfo=timezone.utc)
    d = make_decision(
        [_ev("11-bdsm", "long", 0.8)],
        constraints=_CONSTRAINTS,
        rights=_RIGHTS,
        kill_switch=True,
        now=now,
    )
    assert d["execution"]["outcome"] == "disabled"
    assert d["execution"]["allowed"] is False
    assert d["execution"]["reason"] == "kill_switch"


def test_decision_empty_evidences_neutral():
    now = datetime(2026, 11, 8, 12, 0, 0, tzinfo=timezone.utc)
    d = make_decision(
        [],
        constraints=_CONSTRAINTS,
        rights=_RIGHTS,
        now=now,
    )
    assert d["direction"] == "neutral"
    assert d["payload"]["path_count"] == 0
    assert d["execution"]["outcome"] == "paper"


def test_decision_constraint_clamp():
    now = datetime(2026, 11, 8, 12, 0, 0, tzinfo=timezone.utc)
    constraints = dict(_CONSTRAINTS)
    constraints["per_asset_class"] = {"crypto_usdt": {"position_band": [10, 20]}}
    d = make_decision(
        [_ev("11-bdsm", "long", 0.9)],
        asset_class="crypto_usdt",
        constraints=constraints,
        rights=_RIGHTS,
        now=now,
    )
    assert 10 <= d["position_pct"] <= 20
