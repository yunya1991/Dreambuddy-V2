#!/usr/bin/env python3
"""P3 分级 grace 单测：grace 按 quality_level 分档，S 永不降权，显式数字可覆盖。"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fsrs_forgetting_scheduler import FSRSForgettingScheduler  # noqa: E402


def _mem(quality: str, days_old: int, mid: str = "m1") -> dict:
    ts = (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat()
    return {
        "id": mid,
        "quality_level": quality,
        "verify_count": 0,
        "updated_at": ts,
        "confidence": 0.2,
    }


def test_grace_days_by_quality():
    sched = FSRSForgettingScheduler()
    assert sched.grace_days_for("C") == 7
    assert sched.grace_days_for("B") == 14
    assert sched.grace_days_for("A") == 90
    assert sched.grace_days_for("S") is None


def test_explicit_override_wins():
    sched = FSRSForgettingScheduler(grace_period_days=30)
    assert sched.grace_days_for("C") == 30 and sched.grace_days_for("S") == 30


def test_c_within_7_days_not_demoted():
    sched = FSRSForgettingScheduler()
    report = sched.schedule([_mem("C", 5)], dry_run=False)
    assert report["skipped_grace"] == 1
    assert report["demoted_count"] == 0


def test_c_beyond_7_days_eligible():
    sched = FSRSForgettingScheduler()
    report = sched.schedule([_mem("C", 10)], dry_run=False)
    assert report["skipped_grace"] == 0


def test_s_never_demoted_even_if_ancient():
    sched = FSRSForgettingScheduler()
    report = sched.schedule([_mem("S", 3650)], dry_run=False)
    assert report["skipped_grace"] == 1
    assert report["demoted_count"] == 0
    assert report["archived_count"] == 0
