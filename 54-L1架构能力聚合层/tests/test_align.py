# -*- coding: utf-8 -*-
"""S1-b: 时间轴对齐层（align）单元测试 —— 纯内存 SQLite，不触真实 DB。"""

import datetime
import os
import sqlite3
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg import align as A  # noqa: E402

_DAY = 86400
NOW = int(datetime.datetime(2026, 11, 14, 12, 0, tzinfo=datetime.UTC).timestamp())


def _make_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE mm_metrics (
            source TEXT NOT NULL, sub_category TEXT NOT NULL, metric_name TEXT NOT NULL,
            metric_value REAL, timestamp INTEGER NOT NULL,
            PRIMARY KEY (source, sub_category, metric_name, timestamp)
        ) WITHOUT ROWID
        """)
    conn.executemany("INSERT INTO mm_metrics VALUES (?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _days_ago(n: int) -> int:
    return NOW - n * _DAY


# ---------- 取数 ----------


def test_load_daily_same_day_last_and_cross_source_dedup(tmp_path):
    db = tmp_path / "core.db"
    _make_db(
        str(db),
        [
            # 同一 UTC 日两条 → 取最后一条
            ("okx", "BTC", "close_usd", 100.0, _days_ago(2)),
            ("okx", "BTC", "close_usd", 101.0, _days_ago(2) + 3600),
            # 跨源同 ts → 保留 source 字典序最小（binance_funding_rate < binance_futures）
            ("binance_futures", "funding_rate", "pct", 0.01, _days_ago(1)),
            ("binance_funding_rate", "funding_rate", "pct", 0.02, _days_ago(1)),
        ],
    )
    series = A.load_daily(str(db), "BTC", "close_usd")
    assert list(series.values()) == [101.0]
    fr = A.load_daily(str(db), "funding_rate", "pct")
    assert list(fr.values()) == [0.02]


def test_load_daily_missing_db_raises(tmp_path):
    with pytest.raises(A.AlignError):
        A.load_daily(str(tmp_path / "nope.db"), "BTC", "close_usd")


# ---------- 对齐 ----------


def test_align_ffills_low_frequency_factor():
    price = {"2026-01-01": 100.0, "2026-01-02": 101.0, "2026-01-03": 102.0}
    factor = {"2026-01-01": 5.0}
    out = A.align(factor, price)
    assert out.n == 3
    assert out.factor == [5.0, 5.0, 5.0]
    assert out.meta["stale_ratio"] == pytest.approx(2 / 3, rel=1e-3)
    assert out.meta["align_method"] == A.ALIGN_METHOD
    assert out.meta["timezone"] == "UTC"


def test_align_respects_max_stale_days():
    price = {f"2026-01-0{d}": 100.0 + d for d in range(1, 6)}
    factor = {"2026-01-01": 5.0}
    out = A.align(factor, price, max_stale_days=2)
    # 01-01 有效；01-02/01-03 填充；01-04 起超过 2 天被丢弃
    assert out.n == 3
    assert out.meta["max_stale_days"] == 2


def test_align_skips_before_first_factor_point():
    price = {"2026-01-01": 100.0, "2026-01-02": 101.0, "2026-01-03": 102.0}
    factor = {"2026-01-03": 7.0}
    out = A.align(factor, price)
    assert out.dates == ["2026-01-03"]
    assert out.factor == [7.0]


def test_align_gate_insufficient_samples():
    price = {f"2026-01-{d:02d}": 100.0 for d in range(1, 11)}  # 10 点
    factor = {f"2026-01-{d:02d}": 1.0 for d in range(1, 11)}
    out = A.align(factor, price, min_n=60)
    assert out.n == 10
    assert out.gate(60) == "insufficient_samples"
    assert out.meta["gate"] == "insufficient_samples"
    assert out.gate(1) == "ok"


def test_align_empty_inputs_raise():
    with pytest.raises(A.AlignError):
        A.align({}, {"2026-01-01": 1.0})
    with pytest.raises(A.AlignError):
        A.align({"2026-01-01": 1.0}, {})


def test_infer_max_stale_by_frequency():
    daily = [f"2026-01-{d:02d}" for d in range(1, 6)]
    monthly = ["2026-01-01", "2026-02-01", "2026-03-01"]
    assert A._infer_max_stale(daily) == A._STALE_BY_FREQ["daily"]
    assert A._infer_max_stale(monthly) == A._STALE_BY_FREQ["monthly"]


# ---------- 收益 ----------


def test_forward_returns_no_extra_shift():
    """fwd[i] 必须严格对应 i 之后 h 期，不得多位移（修正 23 旧实现缺陷）。"""
    closes = [100.0, 110.0, 121.0, 133.1]
    fwd2 = A.forward_returns(closes, 2)
    assert fwd2[0] == pytest.approx(0.21)
    assert fwd2[1] == pytest.approx(0.21)
    assert fwd2[2] is None and fwd2[3] is None


def test_simple_and_log_returns_length():
    closes = [100.0, 110.0, 121.0]
    assert len(A.simple_returns(closes)) == 2
    assert A.simple_returns(closes)[0] == pytest.approx(0.1)
    assert A.log_returns(closes)[1] == pytest.approx(0.0953102, rel=1e-5)


def test_overlap_free_indices():
    assert A.overlap_free_indices(10, 3) == [0, 3, 6]
    assert A.overlap_free_indices(0, 3) == []


def test_paired_xy_drops_tail():
    out = A.Aligned(
        dates=["d0", "d1", "d2"],
        factor=[1.0, 2.0, 3.0],
        price=[100.0, 110.0, 121.0],
    )
    xs, ys = A.paired_xy(out, 1)
    assert xs == [1.0, 2.0]
    assert ys == [pytest.approx(0.1), pytest.approx(0.1)]
