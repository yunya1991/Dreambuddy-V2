"""test_data_center_adapter.py — DataCenterAdapter 单元测试
覆盖: panewslab查询, DB不存在FO, 数据过期, per-coin匹配
"""

from __future__ import annotations  # noqa: I001

import json
import sqlite3
from pathlib import Path


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
    metrics_str = json.dumps(
        metrics
        or {
            "fut_liq_long_24h_usd": 1.5e8,
            "fut_liq_short_24h_usd": 2.0e8,
            "fut_liq_total_24h_usd": 3.5e8,
            "fut_open_interest_usd": 5.0e10,
        }
    )
    ts_str = json.dumps(timeseries or [])
    c.execute(
        "INSERT INTO records (source, category, sub_category, timestamp, metrics, timeseries) "
        "VALUES ('panewslab', 'derivatives', 'derivatives_spot', '2026-09-05T10:00:00Z', ?, ?)",
        (metrics_str, ts_str),
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
        """liq_index_change: 最新记录 vs 上一条采集记录（跨进程确定）"""
        db_path = tmp_path / "data_center.db"
        conn = sqlite3.connect(str(db_path))
        c = conn.cursor()
        c.execute(
            "CREATE TABLE records (id INTEGER PRIMARY KEY, source TEXT, category TEXT, "
            "sub_category TEXT, timestamp TEXT, metrics TEXT, timeseries TEXT)"
        )
        rows = [
            ("2026-09-05T06:00:00Z", {"fut_liq_total_24h_usd": 2e8}),
            ("2026-09-05T10:00:00Z", {"fut_liq_total_24h_usd": 4e8}),
        ]
        for ts, m in rows:
            c.execute(
                "INSERT INTO records (source, category, sub_category, timestamp, metrics, timeseries) "
                "VALUES ('panewslab', 'chain', 'derivatives_spot', ?, ?, '[]')",
                (ts, json.dumps(m)),
            )
        conn.commit()
        conn.close()

        adapter = DataCenterAdapter(str(db_path))
        result = adapter.query_latest_derivatives()
        # (4e8 - 2e8) / 2e8 = 1.0
        assert abs(result["liq_index_change"] - 1.0) < 0.01

        # 仅一条记录 → 冷启动 change=0（不再依赖进程内上一次查询）
        single_dir = tmp_path / "single"
        single_dir.mkdir()
        single = _make_test_db(single_dir)
        assert DataCenterAdapter(single).query_latest_derivatives()["liq_index_change"] == 0.0

    def test_per_coin_from_flat_metrics(self, tmp_path):
        """云端 PG 扁平键 fut1_BTC_liq24 / fut1_BTC_oi → 按全局多空占比拆分"""
        db_path = _make_test_db(
            tmp_path,
            metrics={
                "fut_liq_long_24h_usd": 3e8,
                "fut_liq_short_24h_usd": 1e8,
                "fut_liq_total_24h_usd": 4e8,
                "fut_open_interest_usd": 5e10,
                "fut1_BTC_liq24": 2e8,
                "fut1_BTC_oi": 4e10,
            },
        )
        result = DataCenterAdapter(db_path).query_latest_derivatives(symbol="BTC")
        assert result["liquidation_buy"] == [1.5e8]
        assert result["liquidation_sell"] == [0.5e8]
        assert result["open_interest"] == 4e10

    def test_per_coin_match(self, tmp_path):
        """per-coin 清算数据匹配"""
        ts = [
            {
                "name": "futures_markets",
                "items": [
                    {
                        "symbol": "BTC",
                        "long_liq_usd_24h": 5e7,
                        "short_liq_usd_24h": 6e7,
                        "open_interest_usd": 1e10,
                    },
                    {
                        "symbol": "ETH",
                        "long_liq_usd_24h": 3e7,
                        "short_liq_usd_24h": 4e7,
                        "open_interest_usd": 5e9,
                    },
                ],
            }
        ]
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
        c.execute(
            "CREATE TABLE records (source TEXT, sub_category TEXT, timestamp TEXT, metrics TEXT)"
        )
        conn.commit()
        conn.close()

        adapter = DataCenterAdapter(db_path)
        result = adapter.query_latest_derivatives()
        assert result == {}
