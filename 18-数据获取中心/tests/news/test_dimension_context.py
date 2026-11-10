"""DimensionContext（P3-a 维度上下文）测试 — SPEC-D1-MULTIDIM-STATE §2.6。

契约：
  get_dimension_context(dimension, as_of, window) -> DimensionContext
  get_dimension_matrix(as_of, dimensions) -> dict[str, DimensionContext]

口径（预注册）：
  direction  ±0.3 阈值 | strength=abs(tanh(z)) | 滚动窗口 z/分位 | as_of 严格截断
  availability: long ≥900 天 / short ≥30 天 / none
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timedelta

import pytest
from data_center.processing.dimension_context import (
    DIMENSION_MAP,
    DimensionContext,
    get_dimension_context,
    get_dimension_matrix,
)

N_DAYS = 1000


def _kline_db(path, n=N_DAYS, start_price=100.0, step=0.5):
    """加速上涨序列（非严格线性，避免滚动 z 退化全零）。"""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE records ("
        "id INTEGER PRIMARY KEY, dedupe_key TEXT, source TEXT, category TEXT, "
        "sub_category TEXT, timestamp TEXT, metrics TEXT, events TEXT, "
        "timeseries TEXT, raw TEXT, schema_version TEXT)"
    )
    d0 = datetime(2023, 1, 1)
    for i in range(n):
        d = (d0 + timedelta(days=i)).strftime("%Y-%m-%d")
        ts = f"{d}T00:00:00Z"
        close = start_price * math.exp(0.0005 * i + 2e-6 * i * i)
        arr = [{"timestamp": ts, "close": close}]
        conn.execute(
            "INSERT INTO records (dedupe_key, source, category, sub_category, timestamp,"
            " metrics, events, timeseries, raw, schema_version)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                f"k{i}",
                "yfinance",
                "finance",
                "BTC-USD",
                ts,
                "{}",
                "[]",
                json.dumps(arr),
                "{}",
                "1.0",
            ),
        )
    conn.commit()
    conn.close()
    return str(path)


def _mm_db(path, source="fred", sub="DGS10", n=N_DAYS, start=3.0, step=0.01):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE mm_metrics (source TEXT, sub_category TEXT, metric_name TEXT,"
        " metric_value REAL, timestamp INTEGER)"
    )
    t0 = int(datetime(2023, 1, 1).timestamp())
    for i in range(n):
        conn.execute(
            "INSERT INTO mm_metrics VALUES (?,?,?,?,?)",
            (source, sub, "value", start + step * i, t0 + i * 86400),
        )
    conn.commit()
    conn.close()
    return str(path)


@pytest.fixture()
def dbs(tmp_path):
    return _kline_db(tmp_path / "k.db"), _mm_db(tmp_path / "m.db")


def test_direction_up_on_ascending_close(dbs):
    kdb, mdb = dbs
    ctx = get_dimension_context("D3", "2025-06-01", kline_db=kdb, mm_db=mdb)
    assert isinstance(ctx, DimensionContext)
    assert ctx.dimension == "D3"
    assert ctx.direction == "up"
    assert 0.0 < ctx.strength <= 1.0


def test_rising_yield_is_bearish_macro(dbs):
    kdb, mdb = dbs
    ctx = get_dimension_context("D1", "2025-06-01", kline_db=kdb, mm_db=mdb)
    assert ctx.direction == "down", "美债收益率上行应对风险资产为 bearish"
    assert ctx.strength > 0


def test_as_of_strict_truncation(dbs):
    kdb, mdb = dbs
    early = get_dimension_context("D3", "2023-03-01", kline_db=kdb, mm_db=mdb)
    assert early.data_points <= 60
    assert early.as_of == "2023-03-01"


def test_before_series_start_returns_none(dbs):
    kdb, mdb = dbs
    ctx = get_dimension_context("D3", "2020-01-01", kline_db=kdb, mm_db=mdb)
    assert ctx.availability == "none"
    assert ctx.direction == "neutral"
    assert ctx.data_points == 0


def test_missing_dimension_flow_none(dbs):
    kdb, mdb = dbs
    ctx = get_dimension_context("D2", "2025-06-01", kline_db=kdb, mm_db=mdb)
    assert ctx.availability == "none"
    assert ctx.strength == 0.0


def test_availability_long_when_900_days(dbs):
    kdb, mdb = dbs
    ctx = get_dimension_context("D3", "2025-06-01", kline_db=kdb, mm_db=mdb)
    assert ctx.availability == "long"


def test_percentile_and_z_ranges(dbs):
    kdb, mdb = dbs
    ctx = get_dimension_context("D3", "2025-06-01", kline_db=kdb, mm_db=mdb)
    assert 0.0 <= ctx.percentile <= 1.0
    assert -3.0 <= ctx.z <= 3.0


def test_matrix_has_all_dimensions(dbs):
    kdb, mdb = dbs
    matrix = get_dimension_matrix("2025-06-01", kline_db=kdb, mm_db=mdb)
    assert set(matrix) == {"D1", "D2", "D3", "D4", "C6", "C7", "C8", "NEWS"}
    assert all(isinstance(v, DimensionContext) for v in matrix.values())


def test_fail_open_on_bad_db(tmp_path):
    ctx = get_dimension_context(
        "D3", "2025-06-01", kline_db=str(tmp_path / "nope.db"), mm_db=str(tmp_path / "nope2.db")
    )
    assert ctx.availability == "none"


def test_dimension_map_covers_six_categories():
    assert DIMENSION_MAP["technical"] == "D3"
    assert DIMENSION_MAP["flow"] == "D2"
    assert DIMENSION_MAP["macro"] == "D1"
    assert DIMENSION_MAP["sentiment"] == "D4"


# ── NEWS 维（P3-b：快讯极性，SPEC §2.8）────────────────────


def _newsflash_jsonl(path, n_days=60, bull_days=10):
    """前 n_days-bull_days 天中性、最后 bull_days 天全利好 → 末值显著为正。"""
    d0 = datetime(2026, 1, 1)
    with open(path, "w", encoding="utf-8") as f:
        for i in range(n_days):
            d = d0 + timedelta(days=i)
            title = "比特币突破新高" if i >= n_days - bull_days else "Odaily星球日报讯"
            rec = {"title": title, "published_ms": int(d.timestamp()) * 1000 + 3600_000}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return str(path)


def test_news_dimension_direction_disabled(dbs, tmp_path):
    """SPEC §4.4 P3-b2 裁决：NEWS 方向降级（neutral/none），强度仍保留。

    快讯极性方向平衡准确率 0.50（无判别力），故 direction 强制 neutral、
    availability 强制 none，不参与 dominant/agreement；但 strength/data_points
    仍应反映真实快讯序列，供 news_density 等弱辅助使用。
    """
    kdb, mdb = dbs
    nf = _newsflash_jsonl(tmp_path / "nf.jsonl")
    ctx = get_dimension_context("NEWS", "2026-02-28", kline_db=kdb, mm_db=mdb, newsflash_jsonl=nf)
    assert ctx.direction == "neutral"
    assert ctx.availability == "none"
    assert ctx.strength > 0
    assert ctx.data_points > 0
    assert ctx.series_id == "dim:NEWS"
    assert ctx.factors_used == ("news.polarity",)


def test_news_dimension_none_without_newsflash(dbs):
    """无快讯文件 → NEWS 仍为 none（不伪造）。"""
    kdb, mdb = dbs
    ctx = get_dimension_context(
        "NEWS",
        "2026-02-28",
        kline_db=kdb,
        mm_db=mdb,
        newsflash_jsonl="/nonexistent/nf.jsonl",
    )
    assert ctx.availability == "none"
    assert ctx.direction == "neutral"
