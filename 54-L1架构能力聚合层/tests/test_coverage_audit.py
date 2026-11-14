# -*- coding: utf-8 -*-
"""S1.0-4 覆盖体检的离线用例（临时库，不触真实 DB）。"""

import datetime
import os
import sqlite3
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_SCRIPTS = os.path.join(_MODULE_ROOT, "scripts")
for _p in (_MODULE_ROOT, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from coverage_audit import (  # noqa: E402
    _business_days,
    audit,
    render_markdown,
    series_detail,
)

_DAY = 86400
# 2026-11-11 是周三：便于校验交易日口径的陈旧天数
NOW = int(datetime.datetime(2026, 11, 11, 12, 0, tzinfo=datetime.UTC).timestamp())


def _make_db(path: str, rows) -> None:
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE mm_metrics (
            source TEXT NOT NULL,
            sub_category TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            metric_value REAL,
            timestamp INTEGER NOT NULL,
            PRIMARY KEY (source, sub_category, metric_name, timestamp)
        ) WITHOUT ROWID
        """)
    conn.executemany(
        "INSERT OR REPLACE INTO mm_metrics"
        " (source, sub_category, metric_name, metric_value, timestamp)"
        " VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def _daily(source, sub, metric, days, *, start_day=None, every=1, value=100.0):
    end_day = NOW // _DAY
    start_day = start_day if start_day is not None else end_day - days + 1
    out = []
    for i in range(0, days, every):
        out.append((source, sub, metric, value + i, (start_day + i) * _DAY))
    return out


def _business_rows(source, sub, metric, days):
    """仅工作日，模拟 FRED 日频（含假日视为缺失，落在 6% 容忍内）。"""
    end = datetime.datetime.fromtimestamp(NOW, datetime.UTC).date()
    out = []
    for i in range(days):
        day = end - datetime.timedelta(days=i)
        if day.weekday() >= 5:
            continue
        ts = int(datetime.datetime(day.year, day.month, day.day, tzinfo=datetime.UTC).timestamp())
        out.append((source, sub, metric, 4.0 + i * 0.001, ts))
    return out


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "coverage.db")
    rows = []
    # 7×24 完整 3 年：应 PASS
    rows += _daily("okx", "BTC", "close_usd", 1095, value=40000.0)
    rows += _daily("okx", "BTC", "volume_usd", 1095, value=1e9)
    # 7×24 隔天缺失：应 FAIL（行数 / 缺口）
    rows += _daily("okx", "ETH", "close_usd", 1095, every=2, value=2000.0)
    # 交易日口径完整 3 年：应 PASS
    rows += _business_rows("fred", "DGS10", "value", 1095)
    # NULL 与负时间戳（真实历史）
    rows.append(("fred", "PPIACO", "value", None, (NOW // _DAY) * _DAY))
    rows.append(("fred", "CPIAUCSL", "value", 21.48, -725846400))
    # 跨源重复
    rows.append(("coingecko", "BTC", "close_usd", 40001.0, (NOW // _DAY) * _DAY))
    # 异常点（|z|>5）
    rows += _daily("coingecko", "TOTAL_MCAP", "value", 40, value=1.0)
    rows.append(("coingecko", "TOTAL_MCAP", "value", 3000.0, (NOW // _DAY) * _DAY))
    _make_db(path, rows)
    return path


def test_business_days_denominator():
    start = int(datetime.datetime(2026, 11, 2, tzinfo=datetime.UTC).timestamp())
    end = int(datetime.datetime(2026, 11, 11, tzinfo=datetime.UTC).timestamp())
    # 11-02(一) ~ 11-11(三) 共 10 天，含 2 个周末日 → 8 个工作日
    assert _business_days(start, end) == 8


def test_anchor_judgement(db_path):
    result = audit(db_path, days=1095, now=NOW)
    by_id = {a["id"]: a for a in result["anchors"]}
    assert by_id["BTC"]["status"] == "PASS"
    assert by_id["BTC"]["n"] == 1095
    assert by_id["ETH"]["status"] == "FAIL"
    assert any("行数" in r for r in by_id["ETH"]["reasons"])
    assert by_id["US10Y"]["status"] == "PASS"
    assert by_id["US10Y"]["trading_calendar"] is True
    assert by_id["IXIC"]["status"] == "MISSING"
    assert result["anchors_pass"] == 2


def test_negative_epoch_not_treated_as_dirty(db_path):
    result = audit(db_path, days=1095, now=NOW)
    anomalies = result["anomalies"]
    assert anomalies["negative_total"] == 1
    assert anomalies["negative_top"][0]["sub_category"] == "CPIAUCSL"
    md = render_markdown(result)
    assert "1970 前" in md and "不得当脏数据删除" in md


def test_null_and_multi_source(db_path):
    result = audit(db_path, days=1095, now=NOW)
    anomalies = result["anomalies"]
    assert anomalies["null_total"] == 1
    assert anomalies["null_top"][0]["sub_category"] == "PPIACO"
    dup = {(r["sub_category"], r["metric_name"]) for r in anomalies["multi_source"]}
    assert ("BTC", "close_usd") in dup


def test_outlier_detection(db_path):
    keys = ("coingecko", "TOTAL_MCAP", "value")
    detail = series_detail(sqlite3.connect(db_path), keys, NOW - 1095 * _DAY)
    assert detail["outliers"] >= 1
    assert detail["outlier_samples"][0]["z"] > 5


def test_markdown_sections(db_path):
    md = render_markdown(audit(db_path, days=1095, now=NOW))
    for title in (
        "## 1. 锚定资产达标",
        "## 2. 口径说明",
        "## 3. 数据规模",
        "## 5. 跨源重复",
        "## 6. 结论",
    ):
        assert title in md
    assert "FAIL" in md and "PASS" in md
