# R2-02: 4 维裁决测试（50 SPEC §4.4）。
from __future__ import annotations

from core.path_synthesis import Path
from core.w4 import (
    DOMINANCE_THRESHOLD,
    RESONANCE_THRESHOLD,
    adjudicate,
    consistency_score,
    force_score,
    urgency_score,
)


def _path(
    source, direction, confidence, dimension="D3", horizon="hours", intent="trend", weight=0.2
):
    return Path(
        path_id=f"ev:{source}:BTC:{dimension}:{horizon}:{intent}",
        source=source,
        symbol="BTC",
        direction=direction,
        confidence=confidence,
        expected_return=confidence,
        resistance=1.0 - confidence,
        continuation_score=confidence,
        dimension=dimension,
        horizon=horizon,
        intent=intent,
        metadata={"weight": weight},
    )


def test_force_score_long_dominant():
    paths = [
        _path("11-bdsm", "long", 0.8, weight=0.2),
        _path("11-washout", "short", 0.2, weight=0.2),
    ]
    f = force_score(paths)
    assert f > 0.5
    assert abs(f - 0.8) < 1e-9


def test_force_score_empty_neutral():
    assert force_score([]) == 0.5


def test_urgency_horizon_mapping():
    minutes = [_path("11-washout", "long", 0.8, horizon="minutes")]
    weeks = [_path("11-bdsm", "long", 0.8, horizon="weeks")]
    assert urgency_score(minutes) > urgency_score(weeks)
    assert urgency_score([]) == 0.0


def test_consistency_agreement_uplift():
    paths = [_path("11-bdsm", "long", 0.8)]
    score, conflict = consistency_score(paths, {"agreement_ratio": 1.0})
    assert not conflict
    assert score > 0.5


def test_consistency_disagreement_flagged():
    paths = [_path("11-bdsm", "long", 0.8)]
    score, conflict = consistency_score(paths, {"agreement_ratio": 0.2})
    assert conflict
    assert score < 0.5


def test_consistency_missing_fail_open():
    paths = [_path("11-bdsm", "long", 0.8)]
    score, conflict = consistency_score(paths, None)
    assert not conflict
    assert score == 0.5


def test_adjudicate_thresholds():
    # 强多头证据：force 高 + 对账一致 -> total 应达主导阈值
    paths = [
        _path("11-bdsm", "long", 0.9, dimension="C6", weight=0.2),
        _path("11-bcrm-tactical", "long", 0.85, dimension="D3", weight=0.35),
        _path("11-washout", "long", 0.7, dimension="D3", weight=0.15),
        _path("11-event-arbitrage", "long", 0.6, dimension="C7", weight=0.15),
    ]
    result = adjudicate(paths, {"agreement_ratio": 1.0})
    assert result["direction"] == "long"
    assert result["total"] >= DOMINANCE_THRESHOLD
    assert result["dominant"] is True
    assert result["resonance"] is True
    assert not result["conflict_flag"]


def test_adjudicate_empty_degrades():
    result = adjudicate([])
    assert result["direction"] == "neutral"
    assert result["dominant"] is False
    assert result["path_count"] == 0


def test_adjudicate_weights_sum():
    result = adjudicate([])
    w = result["weights"]
    assert abs(w["force"] + w["urgency"] + w["consistency"] + w["impact"] - 1.0) < 1e-9
    assert RESONANCE_THRESHOLD == 0.6
    assert DOMINANCE_THRESHOLD == 0.55
