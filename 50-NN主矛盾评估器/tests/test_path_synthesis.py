"""R0-07: evidence → path 合成测试。"""

from __future__ import annotations  # noqa: I001

from datetime import datetime, timezone

import pytest

from core.path_synthesis import Path, synthesize_paths

NOW = datetime(2026, 11, 8, 1, 0, tzinfo=timezone.utc)


def evidence(**overrides):
    base = {
        "evidence_id": "e1",
        "source": "11-bdsm",
        "symbol": "BTC-USDT-SWAP",
        "granularity": "per_symbol",
        "direction": "long",
        "confidence": 0.8,
        "horizon": "hours",
        "intent": None,
        "ts": "2026-11-08T00:00:00Z",
        "expires_at": "2026-11-08T02:00:00Z",
        "provenance": "42-bus",
        "payload": {},
    }
    base.update(overrides)
    return base


def test_external_evidence_generates_path_with_formula():
    paths = synthesize_paths([evidence()], now=NOW)
    assert len(paths) == 1
    path = paths[0]
    assert isinstance(path, Path)
    assert path.path_id == "ev:11-bdsm:BTC-USDT-SWAP:C6:hours:trend"
    # freshness = 1h remaining / 2h total = 0.5
    assert path.confidence == pytest.approx(0.4)
    assert path.expected_return == pytest.approx(0.2)  # 0.4 * hours(0.5)
    assert path.resistance == pytest.approx(0.6)
    assert path.continuation_score == pytest.approx(0.2)  # 0.4 * 0.5


def test_constraint_and_self_mirror_do_not_generate_paths():
    paths = synthesize_paths(
        [
            evidence(source="40-cycle"),
            evidence(source="43-strategic"),
            evidence(source="29-event"),
            evidence(source="23-contradiction"),
        ],
        now=NOW,
    )
    assert paths == []


def test_expired_or_zero_confidence_dropped():
    paths = synthesize_paths(
        [
            evidence(evidence_id="expired", expires_at="2026-11-08T00:30:00Z"),
            evidence(evidence_id="zero", confidence=0.0),
        ],
        now=NOW,
    )
    assert paths == []


def test_missing_expires_is_fresh_but_degraded():
    paths = synthesize_paths([evidence(expires_at=None)], now=NOW)
    assert len(paths) == 1
    assert paths[0].confidence == pytest.approx(0.8)
    assert "missing_expires_at" in paths[0].metadata["degraded"]


def test_dedup_same_key_keeps_highest_confidence():
    paths = synthesize_paths(
        [
            evidence(evidence_id="low", confidence=0.5),
            evidence(evidence_id="high", confidence=0.9),
        ],
        now=NOW,
    )
    assert len(paths) == 1
    assert paths[0].metadata["evidence_id"] == "high"
    assert paths[0].metadata["dedup_count"] == 2


def test_source_alias_is_normalized():
    paths = synthesize_paths([evidence(source="bdsm")], now=NOW)
    assert paths[0].source == "11-bdsm"


def test_conflict_penalty_applied():
    paths = synthesize_paths([evidence(payload={"conflict_penalty": 0.5})], now=NOW)
    assert paths[0].confidence == pytest.approx(0.2)  # 0.8 * 0.5 * 0.5


def test_reversal_continuation_uses_trend_confidence():
    paths = synthesize_paths(
        [
            evidence(
                source="11-washout",
                confidence=0.8,
                payload={"trend_confidence": 0.7},
            )
        ],
        now=NOW,
    )
    assert paths[0].continuation_score == pytest.approx(0.3)


def test_event_shock_continuation_equals_confidence():
    paths = synthesize_paths([evidence(source="11-event-arbitrage", horizon="hours")], now=NOW)
    assert paths[0].continuation_score == pytest.approx(paths[0].confidence)


def test_unknown_source_degrades_to_c3():
    paths = synthesize_paths([evidence(source="99-unknown")], now=NOW)
    assert len(paths) == 1
    assert paths[0].dimension == "C3"
    assert "source_unmapped" in paths[0].metadata["degraded"]


def test_dimension_hint_overrides_map():
    paths = synthesize_paths([evidence(dimension_hint="D4")], now=NOW)
    assert paths[0].dimension == "D4"


def test_direction_aliases():
    paths = synthesize_paths([evidence(direction="buy")], now=NOW)
    assert paths[0].direction == "long"
