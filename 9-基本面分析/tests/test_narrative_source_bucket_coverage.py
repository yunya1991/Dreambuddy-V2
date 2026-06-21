import json
from pathlib import Path

import pytest

from ops.nanoclaw.core_task1.narrative.scripts.narrative_analyzer import NarrativeAnalyzer


def test_source_bucket_coverage_hits_target_with_flow_snapshot_proxies() -> None:
    a = NarrativeAnalyzer(hours=24)
    flow_snapshot = {
        "items": [
            {"bindBase": "social_heat_event_score__btc__okx__na", "value": 0.2, "quality": {"status": "ok"}},
            {"bindBase": "macro_event_pressure_score__btc__macro__na", "value": 0.4, "quality": {"status": "ok"}},
            {"bindBase": "whale_position_delta_usd__btc__hyperliquid__perp", "value": 1000000.0, "quality": {"status": "ok"}},
            {"bindBase": "cex_exchange_reserve_usd__all__all__all", "value": 250000000000.0, "quality": {"status": "ok"}},
            {"bindBase": "funding_rate_bps__btc__okx__perp", "value": 8.0, "quality": {"status": "ok"}},
            {"bindBase": "oi_usd__btc__okx__perp", "value": 800000000.0, "quality": {"status": "ok"}},
        ]
    }
    events = [{"title": "ETF inflow rises", "summary": "macro tailwind", "timestamp": "2026-04-08T00:00:00Z"}]
    macro_sent = {"event_count": 0, "index": 55.0}
    onchain_rank = {"quality": "missing"}
    pm_curve = {"quality": "missing"}
    okx_market_intel = {"quality": {"status": "ok"}, "topics": [{"title": "ETF flow", "url": "https://example.com", "ts": "2026-04-08T00:00:00Z"}]}
    coverage, buckets, missing = a._compute_source_bucket_coverage(
        events=events,
        macro_sent=macro_sent,
        onchain_rank=onchain_rank,
        pm_curve=pm_curve,
        flow_skill_snapshot=flow_snapshot,
        okx_market_intel=okx_market_intel,
    )
    assert coverage >= 0.80
    assert buckets.get("news") in {"ok", "stale", "backfilled"}
    assert buckets.get("macro") in {"ok", "stale", "backfilled"}
    assert buckets.get("onchain") in {"ok", "stale", "backfilled"}
    assert buckets.get("derivatives") in {"ok", "stale", "backfilled"}
    assert "news" not in missing


def test_source_bucket_coverage_missing_when_no_inputs() -> None:
    a = NarrativeAnalyzer(hours=24)
    coverage, buckets, missing = a._compute_source_bucket_coverage(
        events=[],
        macro_sent={},
        onchain_rank={},
        pm_curve={},
        flow_skill_snapshot={},
        okx_market_intel={},
    )
    assert coverage == 0.0
    assert set(missing) == {"okx_market_intel", "news", "macro", "onchain", "derivatives"}


def test_onchain_backfilled_requires_two_proxy_signals() -> None:
    a = NarrativeAnalyzer(hours=24)
    flow_snapshot = {
        "items": [
            {"bindBase": "whale_position_delta_usd__btc__hyperliquid__perp", "value": 1000000.0, "quality": {"status": "ok"}},
            {"bindBase": "funding_rate_bps__btc__okx__perp", "value": 8.0, "quality": {"status": "ok"}},
            {"bindBase": "oi_usd__btc__okx__perp", "value": 800000000.0, "quality": {"status": "ok"}},
        ]
    }
    coverage, buckets, missing = a._compute_source_bucket_coverage(
        events=[{"title": "macro", "summary": "", "timestamp": "2026-04-08T00:00:00Z"}],
        macro_sent={},
        onchain_rank={"quality": "missing"},
        pm_curve={"quality": "missing"},
        flow_skill_snapshot=flow_snapshot,
        okx_market_intel={},
    )
    assert buckets.get("onchain") == "missing"
    assert "onchain" in missing
