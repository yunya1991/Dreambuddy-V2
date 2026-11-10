"""P0-1 时区 / 交易日对齐 — SPEC §2.10 D1。

锁定三件事：
  1. 快讯 `published_ms` → UTC 日 的边界正确
  2. K 线 `date` / `timestamp` / 行 `timestamp` 三种形态都归一到 UTC 日
  3. NaN 日期不得生成键 'nan'（此前会绕过 as_of 截断形成前视泄漏）
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from data_center.processing.dimension_context import (
    DEFAULT_KLINE_DB,
    _load_kline,
    to_utc_day,
)
from data_center.processing.news_polarity import daily_news_series

# ── to_utc_day 单元 ───────────────────────────────────────


def test_nan_and_empty_become_none():
    assert to_utc_day(float("nan")) is None
    assert to_utc_day("nan") is None
    assert to_utc_day("") is None
    assert to_utc_day(None) is None


def test_plain_date_kept_as_is():
    assert to_utc_day("2026-10-29") == "2026-10-29"


def test_utc_iso_same_day():
    assert to_utc_day("2026-10-29T19:00:00Z") == "2026-10-29"


def test_plus08_iso_crosses_to_previous_utc_day():
    # 2026-09-10 00:00 +08:00 == 2026-09-09 16:00Z
    assert to_utc_day("2026-09-10T00:00:00+08:00") == "2026-09-09"


def test_epoch_seconds_boundary():
    a = datetime.fromisoformat("2026-01-02T23:59:59+00:00").timestamp()
    b = datetime.fromisoformat("2026-01-03T00:00:01+00:00").timestamp()
    assert to_utc_day(int(a)) == "2026-01-02"
    assert to_utc_day(int(b)) == "2026-01-03"


def test_epoch_millis_equivalent_to_seconds():
    sec = int(datetime.fromisoformat("2026-01-02T12:00:00+00:00").timestamp())
    assert to_utc_day(sec * 1000) == to_utc_day(sec) == "2026-01-02"


def test_naive_iso_treated_as_utc():
    assert to_utc_day("2026-01-02T12:00:00") == "2026-01-02"


# ── 快讯日界 ─────────────────────────────────────────────


def _flash(ts_iso: str, title: str = "BTC 上涨") -> dict:
    ms = int(datetime.fromisoformat(ts_iso.replace("Z", "+00:00")).timestamp() * 1000)
    return {"published_ms": ms, "title": title, "is_important": True}


def test_newsflash_day_boundary(tmp_path):
    p = tmp_path / "flash.jsonl"
    p.write_text(
        "\n".join(
            json.dumps(x, ensure_ascii=False)
            for x in (_flash("2026-01-02T23:59:59Z"), _flash("2026-01-03T00:00:01Z"))
        ),
        encoding="utf-8",
    )
    days = [d for d, _ in daily_news_series(path=p)]
    assert days == ["2026-01-02", "2026-01-03"]


# ── 真实 K 线回归（无库则跳过）────────────────────────────


def test_real_kline_has_no_nan_key_and_all_dates_normalized():
    if not DEFAULT_KLINE_DB.exists():
        pytest.skip("kline db 不存在")
    series = _load_kline(DEFAULT_KLINE_DB)
    assert len(series) > 1000
    for d, _ in series:
        assert len(d) == 10 and d[4] == "-" and d[7] == "-", f"非法日期键: {d!r}"
        assert d != "nan"
    assert series[-1][0] == "2026-10-29"  # 含 timestamp+close 的离群行已正确归一
