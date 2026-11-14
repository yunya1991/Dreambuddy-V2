# -*- coding: utf-8 -*-
"""S1-c: 价格回显（price_echo）单元测试 —— 纯函数 + 临时 SQLite，不联网。"""

import datetime
import os
import sqlite3
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg import price_echo as P  # noqa: E402

_DAY = 86400
NOW = int(datetime.datetime(2026, 11, 14, 12, 0, tzinfo=datetime.UTC).timestamp())
TODAY = datetime.date(2026, 11, 14)
SERIES = {
    "2026-11-09": 100.0,
    "2026-11-10": 101.0,
    "2026-11-11": 102.0,
    "2026-11-12": 103.0,
}


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


# ---------- 默认对齐基准（硬约束） ----------


def test_anchor_crypto_defaults_to_btc():
    assert P.resolve_anchor(category="crypto").primary == "BTC"


def test_anchor_us_equity_uses_indices():
    a = P.resolve_anchor(category="us_stock")
    assert a.primary == "US500"
    assert set(a.alternates) == {"US100", "DJIA"}


def test_anchor_macro_uses_gold_and_indices():
    a = P.resolve_anchor("CPIAUCSL", "value")
    assert a.group == "macro"
    assert a.primary == "XAU"
    assert "US500" in a.alternates


def test_anchor_commodity_uses_oil():
    assert P.resolve_anchor("DCOILWTICO", "value").primary == "CL"


def test_anchor_safe_haven_uses_gold():
    assert P.resolve_anchor("XAU", "close_usd").group == "safe_haven"


def test_anchor_unknown_falls_back_to_btc():
    assert P.resolve_anchor("mystery_series", "x").primary == "BTC"


# ---------- 日期解析 ----------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("2025-03-01", "2025-03-01"),
        ("2025/3/1", "2025-03-01"),
        ("2025年3月1日", "2025-03-01"),
        ("30天前", "2026-10-15"),
        ("2周前", "2026-10-31"),
        ("昨天", "2026-11-13"),
        ("前天", "2026-11-12"),
        ("上周", "2026-11-07"),
        ("年初", "2026-01-01"),
        ("现在", "2026-11-14"),
    ],
)
def test_parse_day_variants(text, expected):
    assert P.parse_day(text, today=TODAY) == expected


def test_parse_day_invalid_raises():
    with pytest.raises(P.PriceEchoError):
        P.parse_day("不是日期", today=TODAY)
    with pytest.raises(P.PriceEchoError):
        P.parse_day("2025-02-30", today=TODAY)


def test_find_past_day_reference_excludes_now():
    assert P.find_past_day_reference("BTC 现在什么价", today=TODAY) is None
    assert P.find_past_day_reference("2025-03-01 的 BTC 价格", today=TODAY) == "2025-03-01"
    assert P.find_past_day_reference("30天前的金价", today=TODAY) == "2026-10-15"


# ---------- asof ----------


def test_asof_exact_day():
    pt = P.asof_price(SERIES, "2026-11-11")
    assert (pt.asof_day, pt.price, pt.staleness_days) == ("2026-11-11", 102.0, 0)


def test_asof_uses_previous_available_day():
    pt = P.asof_price(SERIES, "2026-11-14")
    assert (pt.asof_day, pt.price, pt.staleness_days) == ("2026-11-12", 103.0, 2)


def test_asof_before_first_point_raises():
    with pytest.raises(P.PriceEchoError):
        P.asof_price(SERIES, "2026-11-01")


def test_asof_never_looks_forward():
    pt = P.asof_price(SERIES, "2026-11-10")
    assert pt.asof_day <= "2026-11-10" and pt.price == 101.0


# ---------- 回显 ----------


def test_price_echo_live_change():
    echo = P.price_echo(
        SERIES, "2026-11-10", symbol="BTC", now_price=110.0, now_ts=NOW, today=TODAY
    )
    assert echo["now"]["kind"] == "live"
    assert echo["at"]["price"] == 101.0
    assert echo["change"]["pct"] == pytest.approx(8.9109, abs=1e-3)
    assert echo["gate"] == "ok"
    assert echo["align_method"] == "asof_daily_last"
    assert echo["timezone"] == "UTC"
    assert echo["sample_n"] == 4


def test_price_echo_last_available_when_no_live_price():
    echo = P.price_echo(SERIES, "2026-11-10", symbol="BTC", today=TODAY)
    assert echo["now"]["kind"] == "last_available"
    assert echo["now"]["price"] == 103.0
    assert echo["now"]["staleness_days"] == 2
    assert echo["gate"] == "ok"


def test_price_echo_marks_stale_when_gap_too_large():
    echo = P.price_echo(SERIES, "2026-11-10", symbol="BTC", today=datetime.date(2026, 12, 1))
    assert echo["gate"] == "stale"


def test_format_echo_contains_required_fields():
    echo = P.price_echo(
        SERIES, "2026-11-10", symbol="BTC", now_price=110.0, now_ts=NOW, today=TODAY
    )
    text = P.format_echo(echo)
    assert "2026-11-10" in text and "当时价" in text and "UTC" in text and "样本 4" in text


# ---------- 从 DAL 自动选锚 ----------


def test_echo_anchor_price_resolves_macro_to_gold(tmp_path):
    db = tmp_path / "core.db"
    rows = []
    for day, price in SERIES.items():
        ts = int(
            datetime.datetime.combine(
                datetime.date.fromisoformat(day),
                datetime.time(16, 0),
                tzinfo=datetime.UTC,
            ).timestamp()
        )
        rows.append(("okx", "XAU", "close_usd", price, ts))
    _make_db(str(db), rows)

    echo = P.echo_anchor_price(
        str(db), "2026-11-10", sub_category="CPIAUCSL", metric_name="value", days=30
    )
    assert echo["symbol"] == "XAU"
    assert echo["anchor"]["group"] == "macro"
    assert echo["at"]["price"] == 101.0
