# R3-01: FinalDecisionSignal v1 测试（50 决策整合 + 执行权校验）。
from __future__ import annotations

from datetime import datetime, timezone

from adapters.constraint_loader import clamp_position
from core.decision import _build_overlay_attribution, make_decision
from core.path_synthesis import Path
from core.w4 import adjudicate


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


def _path(confidence: float, direction: str = "long", path_id: str = "p1") -> Path:
    return Path(
        path_id=path_id,
        source="11-bdsm",
        symbol="BTC-USDT-SWAP",
        direction=direction,
        confidence=confidence,
        expected_return=0.02,
        resistance=0.2,
        continuation_score=0.6,
        dimension="D3",
        horizon="hours",
        intent="trend",
        metadata={"weight": 0.2},
    )


def test_overlay_attribution_reports_counterfactual_delta():
    """M4-4 归因：基线用未调制 path 复算，delta 只反映 overlay 的净影响。"""
    constraints = {"position_band": [0, 100], "per_asset_class": {}, "freeze": False}
    baseline_paths = [_path(0.6), _path(0.6, path_id="p2")]
    modulated_paths = [_path(0.8), _path(0.8, path_id="p2")]

    base = adjudicate(baseline_paths)
    modulated = adjudicate(modulated_paths)
    expected_position = clamp_position(constraints, 50.0 + 50.0 * modulated["total"], "crypto_usdt")

    attribution = _build_overlay_attribution(
        baseline_paths,
        constraints,
        "crypto_usdt",
        None,
        modulated["direction"],
        modulated["total"],
        expected_position,
    )
    assert attribution["baseline"]["confidence"] == base["total"]
    assert attribution["delta"]["confidence"] == round(modulated["total"] - base["total"], 6)
    assert attribution["delta"]["confidence"] > 0
    assert attribution["direction_flip"] is False


def test_overlay_attribution_flags_direction_flip():
    constraints = {"position_band": [0, 100], "per_asset_class": {}, "freeze": False}
    short_paths = [_path(0.9, direction="short"), _path(0.9, direction="short", path_id="p2")]

    attribution = _build_overlay_attribution(
        short_paths, constraints, "crypto_usdt", None, "long", 0.5, 50.0
    )
    assert attribution["baseline"]["direction"] == "short"
    assert attribution["direction_flip"] is True
