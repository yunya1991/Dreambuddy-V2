"""P3-c1 事件研究契约测试 — SPEC §2.9.2。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from data_center.processing.event_study import (
    build_family_counts,
    holm,
    run_event_study,
    spearman,
    window_return,
)


def _days(n=120):
    d0 = date(2026, 1, 1)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


def _ts(day: str) -> int:
    dt = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def test_window_return_returns_none_on_gap():
    rets = {"2026-01-01": 0.01, "2026-01-02": 0.01}
    assert window_return(rets, "2026-01-02", "pre_24h") == pytest.approx(0.01)
    assert window_return(rets, "2026-01-02", "post_24h") == pytest.approx(0.01)
    assert window_return(rets, "2026-01-05", "post_24h") is None
    assert window_return(rets, "2026-01-01", "pre_24h") is None


def test_holm_monotone():
    adj = holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adj["a"] == pytest.approx(0.03)
    assert adj["b"] == pytest.approx(0.06)
    assert adj["c"] == pytest.approx(0.06)


def test_spearman_perfect_and_none():
    a = {"x": 1.0, "y": 2.0, "z": 3.0}
    assert spearman(a, {"x": 10.0, "y": 20.0, "z": 30.0}) == pytest.approx(1.0)
    assert spearman(a, {"x": 3.0, "y": 2.0, "z": 1.0}) == pytest.approx(-1.0)
    assert spearman(a, {"x": 1.0}) is None


def test_build_family_counts_aggregates_by_utc_day():
    recs = [
        {"od_event_type": "monetary_policy", "published_ms": _ts("2026-01-02")},
        {"od_event_type": "monetary_policy", "published_ms": _ts("2026-01-02") + 3600_000},
        {"od_event_type": "unknown", "published_ms": _ts("2026-01-03")},
    ]
    ev = build_family_counts(recs, "v1")
    assert ev == {"monetary_policy": {"2026-01-02": 2}}


def _synthetic_case():
    days = _days()
    rets = dict.fromkeys(days, 0.0)
    event_days = days[10::3][:40]
    for d in event_days:
        prev = (date.fromisoformat(d) - timedelta(days=1)).isoformat()
        rets[d] = 0.01
        rets[prev] = 0.01
    recs = [
        {
            "od_event_type": "monetary_policy",
            "published_ms": _ts(d),
            "title": "美联储议息",
            "description": "",
        }
        for d in event_days
    ]
    return rets, recs


def test_event_study_recovers_positive_sensitivity():
    rets, recs = _synthetic_case()
    out = run_event_study(records=recs, returns=rets, mapping="v1")
    assert out["diagnostics"]["degraded"] is False
    fam = [r for r in out["rows"] if r["unit"] == "event_family"]
    assert len(fam) == 1
    row = fam[0]
    assert row["key"] == "monetary_policy"
    assert row["verdict"] == "positive"
    assert row["eligible"] is True
    # 事件日与事件前一日各 +1%；强度经扩张窗标准化后被摊薄，
    # 只断言符号为正且量级合理。
    assert 0.001 < row["mean_excess_post"] < 0.03
    assert 0.001 < row["mean_excess_pre"] < 0.03
    dims = [r for r in out["rows"] if r["unit"] == "dim"]
    assert dims and dims[0]["key"] == "D1"
    assert dims[0]["eligible"] is True


def test_event_study_degrades_on_no_returns():
    out = run_event_study(returns={}, records=[])
    assert out["rows"] == []
    assert out["diagnostics"]["degraded"] is True
    assert out["diagnostics"]["reason"] == "no_returns"
