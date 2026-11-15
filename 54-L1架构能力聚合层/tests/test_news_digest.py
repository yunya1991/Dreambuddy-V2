# -*- coding: utf-8 -*-
"""D-E20 新闻统一出口（L1S-03）单元测试。

锁定：统一信封结构、as_of 截断、缺失降级、方向措辞零命中。
"""

import os
import sqlite3
import sys
from datetime import datetime, timezone

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

from l1agg.capabilities import news  # noqa: E402


def _ts(day: str) -> int:
    return (
        int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()) + 12 * 3600
    )


def _make_db(path, rows):
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE mm_metrics ("
            "source TEXT, sub_category TEXT, metric_name TEXT, "
            "metric_value REAL, timestamp INTEGER)"
        )
        conn.executemany(
            "INSERT INTO mm_metrics VALUES (?, ?, ?, ?, ?)",
            [("test", "social_volume", metric, value, _ts(day)) for day, metric, value in rows],
        )
        conn.commit()
    finally:
        conn.close()


def test_scan_forbidden_positive_and_negative():
    assert news.scan_forbidden("短期看涨信号") == ["看涨"]
    assert news.scan_forbidden("新闻条数与社交热度") == []
    assert news.scan_forbidden(None) == []


def test_missing_db_degrades_to_empty(tmp_path):
    result = news.news_digest(db_path=str(tmp_path / "none.db"))
    assert result["ok"] is False
    assert result["capability"] == "D-E20"
    assert result["quality"]["status"] == "empty"
    assert "样本" in result["answer"]


def test_insufficient_observations_degrade(tmp_path):
    db = tmp_path / "core.db"
    _make_db(db, [("2026-11-11", "news_count_24h", 120.0)])
    result = news.news_digest(db_path=str(db), as_of="2026-11-11", days=30)
    assert result["ok"] is False
    assert result["quality"]["status"] == "empty"
    assert "有效观测" in result["answer"]


def test_full_observations_return_unified_envelope(tmp_path):
    db = tmp_path / "core.db"
    _make_db(
        db,
        [
            ("2026-11-10", "news_count_24h", 100.0),
            ("2026-11-10", "social_volume", 5000.0),
            ("2026-11-11", "news_count_24h", 120.0),
            ("2026-11-11", "social_volume", 6000.0),
            ("2026-11-12", "news_count_24h", 90.0),
            ("2026-11-12", "social_volume", 5500.0),
        ],
    )
    result = news.news_digest(db_path=str(db), as_of="2026-11-12", days=30)
    assert result["ok"] is True
    assert result["capability"] == "D-E20"
    assert result["intent"] == "trend_query"
    assert result["quality"]["status"] == "good"
    assert result["quality"]["sample_n"] == 3
    assert result["quality"]["span"] == ["2026-11-10", "2026-11-12"]
    assert result["data"]["source"] == "mm_metrics.social_volume"
    items = result["data"]["items"]
    assert [row["date"] for row in items] == ["2026-11-12", "2026-11-11", "2026-11-10"]
    assert items[0]["news_count_24h"] == 90.0
    assert items[0]["social_volume"] == 5500.0
    assert news.scan_forbidden(result["answer"]) == []


def test_partial_metric_marks_partial_and_mentions_sample(tmp_path):
    db = tmp_path / "core.db"
    _make_db(
        db,
        [
            ("2026-11-10", "news_count_24h", 100.0),
            ("2026-11-11", "social_volume", 6000.0),
            ("2026-11-12", "social_volume", 5500.0),
        ],
    )
    result = news.news_digest(db_path=str(db), as_of="2026-11-12", days=30)
    assert result["ok"] is True
    assert result["quality"]["status"] == "partial"
    assert result["quality"]["degraded_reason"] == "news_metric_partial"
    assert "样本" in result["answer"]
    assert "news_count_24h" not in result["data"]["items"][0]


def test_as_of_truncates_future_rows(tmp_path):
    db = tmp_path / "core.db"
    _make_db(
        db,
        [
            ("2026-11-10", "news_count_24h", 100.0),
            ("2026-11-11", "news_count_24h", 120.0),
            ("2026-11-12", "news_count_24h", 90.0),
        ],
    )
    result = news.news_digest(db_path=str(db), as_of="2026-11-11", days=30)
    assert [row["date"] for row in result["data"]["items"]] == ["2026-11-11", "2026-11-10"]
    assert result["data"]["as_of"] == "2026-11-11"


def test_invalid_as_of_degrades(tmp_path):
    db = tmp_path / "core.db"
    _make_db(db, [("2026-11-11", "news_count_24h", 120.0)])
    result = news.news_digest(db_path=str(db), as_of="2026-13-99")
    assert result["ok"] is False
    assert result["quality"]["status"] == "empty"
