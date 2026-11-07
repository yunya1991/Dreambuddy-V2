"""R0-03 本地 fixture 总线验收。"""

from __future__ import annotations

from datetime import datetime, timezone

from adapters.bus_reader import to_evidence
from core.path_synthesis import synthesize_paths
from tools.fixture_bus import (
    authority_negative_bus,
    make_fixture_bus,
    run_cycles,
)


def test_fixture_has_at_least_six_sources():
    bus = make_fixture_bus()
    assert len(bus["sources"]) >= 6
    assert bus["signal_count"] >= 6


def test_three_cycles_each_six_sources():
    cycles = run_cycles(n=3)
    assert len(cycles) == 3
    for bus in cycles:
        assert bus["signal_count"] >= 6


def test_ttl_expired_signals_are_dropped():
    now = datetime(2026, 11, 8, 1, 0, tzinfo=timezone.utc)
    bus = make_fixture_bus(now=now, ttl_hours=-1)
    evidences = [to_evidence(sig) for sig in bus["signals"]]
    paths = synthesize_paths(evidences, now=now)
    assert paths == []


def test_empty_bus_alert():
    bus = authority_negative_bus()
    assert bus["signal_count"] == 0
    assert bus["sources"] == []


def test_authority_negative_yields_no_paths():
    bus = authority_negative_bus()
    evidences = [to_evidence(sig) for sig in bus["signals"]]
    assert synthesize_paths(evidences) == []
