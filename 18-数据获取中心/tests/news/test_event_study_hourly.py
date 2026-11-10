"""P3-c1h 小时级事件研究契约测试。"""

from __future__ import annotations

import math

import pytest
from data_center.processing.event_study_hourly import (
    HOUR_MS,
    build_counts,
    hac_ols,
    holm,
    hourly_returns,
    run_event_study_hourly,
    window_hours,
    window_return,
)


def test_window_return_hourly_and_gap():
    t0 = 1_700_000_000_000 // HOUR_MS * HOUR_MS
    rets = {t0 + i * HOUR_MS: 0.01 for i in range(60)}
    h = t0 + 30 * HOUR_MS
    assert window_return(rets, h, "pre_1h") == pytest.approx(0.01)
    assert window_return(rets, h, "post_1h") == pytest.approx(0.01)
    assert window_return(rets, h, "post_4h") == pytest.approx(0.04)
    assert window_return(rets, h, "post_24h") == pytest.approx(0.24)
    assert window_return(rets, t0 - HOUR_MS, "pre_1h") is None  # 无前序
    assert window_return(rets, t0 + 50 * HOUR_MS, "post_24h") is None  # 越界
    assert window_return(rets, h, "unknown_window") is None


def test_window_hours_are_closed_ranges():
    h = 1_700_000_000_000 // HOUR_MS * HOUR_MS
    assert window_hours(h, "post_1h") == [h + HOUR_MS]
    assert window_hours(h, "post_4h") == [h + k * HOUR_MS for k in (1, 2, 3, 4)]
    assert len(window_hours(h, "pre_24h")) == 24
    assert len(window_hours(h, "post_24h")) == 24


def test_hourly_returns_skip_missing_prev():
    t0 = 1_700_000_000_000 // HOUR_MS * HOUR_MS
    closes = {t0: 100.0, t0 + HOUR_MS: 110.0, t0 + 3 * HOUR_MS: 121.0}
    rets = hourly_returns(closes)
    assert rets[t0 + HOUR_MS] == pytest.approx(0.1)
    assert (t0 + 3 * HOUR_MS) not in rets  # 前一小时缺失


def test_build_counts_floors_to_hour():
    t0 = 1_700_000_000_000 // HOUR_MS * HOUR_MS
    recs = [
        {"od_event_type": "monetary_policy", "published_ms": str(t0)},
        {"od_event_type": "monetary_policy", "published_ms": str(t0 + 59 * 60 * 1000)},
        {"od_event_type": "monetary_policy", "published_ms": str(t0 + HOUR_MS)},
        {"od_event_type": "unknown_family", "published_ms": str(t0)},
        {"od_event_type": "monetary_policy", "published_ms": "0"},
    ]
    fam, dim = build_counts(recs, "v1")
    assert fam["monetary_policy"][t0] == 2
    assert fam["monetary_policy"][t0 + HOUR_MS] == 1
    assert "unknown_family" not in fam  # 不可映射 → 丢弃
    assert dim["D1"][t0] == 2 and dim["D1"][t0 + HOUR_MS] == 1


def test_holm_monotone():
    adj = holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert adj["a"] == pytest.approx(0.03)
    assert adj["b"] == pytest.approx(0.06)
    assert adj["c"] == pytest.approx(0.06)


def test_hac_se_inflates_under_overlapping_windows():
    """持续回归元 + 重叠窗口（MA(24) 残差）下，HAC 标准误应远大于朴素 OLS。"""
    import numpy as np

    rng = np.random.default_rng(7)
    n = 4000
    x = np.zeros(n)  # 持久回归元（事件强度 z 的真实形态）
    for i in range(1, n):
        x[i] = 0.97 * x[i - 1] + rng.normal(scale=0.2)
    shocks = rng.normal(scale=0.5, size=n)
    e = np.zeros(n)
    for i in range(n):  # MA(24)：模拟 24 小时重叠窗口
        e[i] = sum(shocks[max(0, i - 24) : i + 1])
    y = 1.0 * x + e
    design = [[1.0, float(v)] for v in x]
    fit = hac_ols(design, [float(v) for v in y], lag=24)
    assert fit is not None
    beta, se = fit
    # 朴素 OLS 标准误（用残差方差，不含 HAC）
    a = np.asarray(design)
    bb = np.asarray(y)
    resid = bb - a @ np.linalg.lstsq(a, bb, rcond=None)[0]
    sigma2 = float(resid @ resid) / (n - 2)
    naive_se = math.sqrt(sigma2 * float(np.linalg.pinv(a.T @ a)[1, 1]))
    assert beta[1] == pytest.approx(1.0, abs=0.2)
    assert se[1] > naive_se * 2.0


def _synthetic(n_hours=24 * 600, effect=0.001, spacing=96):
    """事件每 spacing 小时一次（spacing > 48，避免窗口覆盖全年化把效应吸进截距）。"""
    t0 = 1_700_000_000_000 // HOUR_MS * HOUR_MS
    hours = [t0 + i * HOUR_MS for i in range(n_hours)]
    rets = dict.fromkeys(hours, 0.0)
    event_hours = [h for i, h in enumerate(hours) if i >= 1200 and i % spacing == 0]
    for h in event_hours:
        for k in range(-24, 25):  # pre/post 同号 → 可进正向池
            if h + k * HOUR_MS in rets:
                rets[h + k * HOUR_MS] += effect
    recs = [{"od_event_type": "monetary_policy", "published_ms": str(h)} for h in event_hours]
    return rets, recs


def test_run_event_study_hourly_detects_planted_effect():
    rets, recs = _synthetic()
    out = run_event_study_hourly(records=recs, returns=rets, control_hour_of_day=False)
    assert out["diagnostics"]["degraded"] is False
    assert out["diagnostics"]["granularity"] == "1h"
    rows = [r for r in out["rows"] if r["unit"] == "event_family"]
    assert rows, out["diagnostics"]
    r = rows[0]
    assert r["mean_excess_post"] > 0.0005  # 稀疏事件的 z≈10，逐 SD 效应约 1bp
    assert r["mean_excess_pre"] > 0  # pre/post 同号
    assert r["p_value"] < 0.01
    assert r["eligible"] is True
    assert r["direction"] == 1


def test_run_event_study_hourly_degraded_without_returns():
    out = run_event_study_hourly(records=[], returns={})
    assert out["rows"] == []
    assert out["diagnostics"]["degraded"] is True
    assert out["diagnostics"]["reason"] == "no_returns"


def test_run_event_study_hourly_drops_insufficient_families():
    rets, recs = _synthetic()
    out = run_event_study_hourly(
        records=recs, returns=rets, min_event_hours=10_000, control_hour_of_day=False
    )
    assert out["rows"] == []
    assert out["diagnostics"]["degraded"] is True
    assert out["diagnostics"]["reason"] == "no_family_with_enough_events"


def test_hac_lag_scales_with_window():
    rets, recs = _synthetic()
    out = run_event_study_hourly(records=recs, returns=rets, control_hour_of_day=False)
    lags = out["diagnostics"]["hac_lag_by_window"]
    assert lags["post_1h"] == 1
    assert lags["post_4h"] == 4
    assert lags["pre_24h"] == 24
    assert lags["post_24h"] == 24
