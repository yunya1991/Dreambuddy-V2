"""test_data_center_adapter.py — DataCenterAdapter 单元测试
覆盖: panewslab查询, DB不存在FO, 数据过期, per-coin匹配
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from dreambuddy_evolution.adapters.data_center import DataCenterAdapter


def _make_test_db(tmp_path: Path, metrics=None, timeseries=None):
    """创建测试用 data_center.db"""
    db_path = tmp_path / "data_center.db"
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()
    c.execute("""
        CREATE TABLE records (
            id INTEGER PRIMARY KEY,
            source TEXT,
            category TEXT,
            sub_category TEXT,
            timestamp TEXT,
            metrics TEXT,
            timeseries TEXT
        )
    """)
    metrics_str = json.dumps(metrics or {
        "fut_liq_long_24h_usd": 1.5e8,
        "fut_liq_short_24h_usd": 2.0e8,
        "fut_liq_total_24h_usd": 3.5e8,
        "fut_open_interest_usd": 5.0e10,
    })
    ts_str = json.dumps(timeseries or [])
    c.execute(
        "INSERT INTO records (source, category, sub_category, timestamp, metrics, timeseries) "
        "VALUES ('panewslab', 'derivatives', 'derivatives_spot', '2026-09-05T10:00:00Z', ?, ?)",
        (metrics_str, ts_str)
    )
    conn.commit()
    conn.close()
    return str(db_path)


class TestDataCenterAdapter:

    def test_query_returns_data(self, tmp_path):
        """panewslab 查询返回清算数据"""
        db_path = _make_test_db(tmp_path)
        adapter = DataCenterAdapter(db_path)
        result = adapter.query_latest_derivatives()

        assert "liquidation_buy" in result
        assert "liquidation_sell" in result
        assert result["liquidation_buy"] == [1.5e8]
        assert result["liquidation_sell"] == [2.0e8]
        assert "open_interest" in result

    def test_db_not_exist_fo(self, tmp_path):
        """DB 不存在 FO 降级"""
        adapter = DataCenterAdapter(str(tmp_path / "nonexistent.db"))
        result = adapter.query_latest_derivatives()
        assert result == {}

    def test_liq_index_change(self, tmp_path):
        """liq_index_change: 两次查询之间的变化比"""
        db_path = _make_test_db(tmp_path, metrics={
            "fut_liq_long_24h_usd": 1e8,
            "fut_liq_short_24h_usd": 1e8,
            "fut_liq_total_24h_usd": 2e8,
            "fut_open_interest_usd": 5e10,
        })
        adapter = DataCenterAdapter(db_path)

        # 第一次查询
        result1 = adapter.query_latest_derivatives()
        # 同一条记录 → change = 0
        if "liq_index_change" in result1:
            assert result1["liq_index_change"] == 0.0

        # 更新 DB 中的 total
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("UPDATE records SET metrics = ?",
                  (json.dumps({"fut_liq_total_24h_usd": 4e8}),))
        conn.commit()
        conn.close()

        # 第二次查询 → 应检测到变化
        result2 = adapter.query_latest_derivatives()
        assert "liq_index_change" in result2
        # (4e8 - 2e8) / 2e8 = 1.0
        assert abs(result2["liq_index_change"] - 1.0) < 0.01

    def test_per_coin_match(self, tmp_path):
        """per-coin 清算数据匹配"""
        ts = [{
            "name": "futures_markets",
            "items": [
                {"symbol": "BTC", "long_liq_usd_24h": 5e7, "short_liq_usd_24h": 6e7,
                 "open_interest_usd": 1e10},
                {"symbol": "ETH", "long_liq_usd_24h": 3e7, "short_liq_usd_24h": 4e7,
                 "open_interest_usd": 5e9},
            ],
        }]
        db_path = _make_test_db(tmp_path, timeseries=ts)
        adapter = DataCenterAdapter(db_path)
        result = adapter.query_latest_derivatives(symbol="BTC")

        assert result["liquidation_buy"] == [5e7]
        assert result["liquidation_sell"] == [6e7]

    def test_no_record_fo(self, tmp_path):
        """空表 FO"""
        db_path = str(tmp_path / "empty.db")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("CREATE TABLE records (source TEXT, sub_category TEXT, timestamp TEXT, metrics TEXT)")
        conn.commit()
        conn.close()

        adapter = DataCenterAdapter(db_path)
        result = adapter.query_latest_derivatives()
        assert result == {}
