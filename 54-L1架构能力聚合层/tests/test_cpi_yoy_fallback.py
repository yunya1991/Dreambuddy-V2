# -*- coding: utf-8 -*-
"""CPI 同比回退用例：mm_metrics 无 cpi/actual 时，由 CPIAUCSL 月度指数计算同比。"""

import datetime
import os
import sqlite3
import sys

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_FRONTEND_SCRIPTS = os.path.join(_MODULE_ROOT, "..", "3.1-FRONTEND", "scripts")
if _FRONTEND_SCRIPTS not in sys.path:
    sys.path.insert(0, _FRONTEND_SCRIPTS)

from data_query_executor import _fetch_cpi_yoy  # noqa: E402

_CST = datetime.timezone(datetime.timedelta(hours=8))


def _ts_cst(y: int, m: int, day: int = 1, hour: int = 0) -> int:
    return int(datetime.datetime(y, m, day, hour, tzinfo=_CST).timestamp())


def _make_db(path: str, rows) -> None:
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


def _months(start_y: int, start_m: int, n: int):
    out = []
    y, m = start_y, start_m
    for _ in range(n):
        out.append((y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def _cpi_rows(months, base_value: float = 300.0):
    return [
        ("fred", "CPIAUCSL", "value", base_value + i, _ts_cst(y, m))
        for i, (y, m) in enumerate(months)
    ]


def test_yoy_from_monthly_index_ignores_intraday_snapshots(tmp_path):
    """14 个连续月度观测 → 最新月/去年同月；增量采集的"当前时间"快照不得参与。"""
    db = str(tmp_path / "core.db")
    rows = _cpi_rows(_months(2025, 8, 14))  # 2025-08 .. 2026-09
    rows.append(("fred", "CPIAUCSL", "value", 9999.0, _ts_cst(2026, 11, 14, 10)))
    _make_db(db, rows)

    got = _fetch_cpi_yoy(db)
    assert got is not None
    assert got["period"] == "2026-09"
    assert got["base_period"] == "2025-09"
    assert got["actual"] == round((313.0 / 301.0 - 1) * 100, 2)


def test_yoy_base_falls_back_to_nearest_earlier_month(tmp_path):
    """去年同月缺失（如 FRED 停更月）→ 取最近可用更早月。"""
    db = str(tmp_path / "core.db")
    months = [m for m in _months(2025, 6, 16) if m != (2025, 9)]  # 2025-06 .. 2026-09
    _make_db(db, _cpi_rows(months))

    got = _fetch_cpi_yoy(db)
    assert got is not None
    assert got["period"] == "2026-09"
    assert got["base_period"] == "2025-08"


def test_yoy_returns_none_when_history_insufficient(tmp_path):
    db = str(tmp_path / "core.db")
    _make_db(db, _cpi_rows(_months(2026, 1, 6)))
    assert _fetch_cpi_yoy(db) is None


def test_release_caliber_takes_priority(tmp_path):
    """存在 cpi/actual（财经日历口径）时优先使用，返回预期与前值。"""
    db = str(tmp_path / "core.db")
    rows = _cpi_rows(_months(2025, 8, 14))
    rows += [
        ("jin10", "cpi", "actual", 3.1, _ts_cst(2026, 10, 15)),
        ("jin10", "cpi", "forecast", 3.0, _ts_cst(2026, 10, 15)),
        ("jin10", "cpi", "previous", 3.2, _ts_cst(2026, 10, 15)),
    ]
    _make_db(db, rows)

    got = _fetch_cpi_yoy(db)
    assert got == {"actual": 3.1, "forecast": 3.0, "previous": 3.2}


def test_missing_db_returns_none(tmp_path):
    assert _fetch_cpi_yoy(str(tmp_path / "nope.db")) is None
