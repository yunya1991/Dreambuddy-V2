"""F1: 估值分位真实查询测试 — TDD 先红后绿。

验证 coin_fundamental_valuation_query.py：
  - query_valuation_percentile(coin, db_path) -> float
  - 从 data_center.db records 表查 coingecko coin_chart 的 timeseries
  - 计算当前 market_cap 在历史序列中的百分位 [0, 100]
  - FAIL-OPEN：异常或数据不足返回 50.0（中性）

数据源：CoinGecko coin_chart（source=coingecko, category=coin, sub_category=chart_{coin_id}）
timeseries 格式：[{"date": ISO, "price": float, "market_cap": float, "volume": float}, ...]
"""
import pytest
import sqlite3
import sys
import tempfile
import os
from pathlib import Path

# 将 force_vector 加入 sys.path
_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))

from force_vector.coin_fundamental_valuation_query import (
    query_valuation_percentile,
    _compute_percentile,
)


# ---------------------------------------------------------------------------
# 辅助：构造临时 data_center.db
# ---------------------------------------------------------------------------

def _make_test_db(records: list) -> str:
    """构造临时 sqlite db，插入 records 表数据。

    records: list of dict {source, category, sub_category, timestamp, metrics, timeseries, ...}
    """
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dedupe_key TEXT UNIQUE,
            source TEXT, category TEXT, sub_category TEXT, timestamp TEXT,
            metrics TEXT, events TEXT, timeseries TEXT, raw TEXT, schema_version TEXT
        )
    """)
    import json
    for r in records:
        conn.execute(
            "INSERT INTO records (dedupe_key, source, category, sub_category, timestamp, "
            "metrics, events, timeseries, raw, schema_version) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                r.get("dedupe_key", f"{r['source']}_{r['category']}_{r['sub_category']}_{r['timestamp']}"),
                r["source"], r["category"], r["sub_category"], r["timestamp"],
                json.dumps(r.get("metrics", {})),
                json.dumps(r.get("events", [])),
                json.dumps(r.get("timeseries", [])),
                json.dumps(r.get("raw", {})),
                r.get("schema_version", "1.0"),
            ),
        )
    conn.commit()
    conn.close()
    return db_path


def _make_chart_record(coin_id: str, market_caps: list, ts: str = "2026-09-01T00:00:00+08:00") -> dict:
    """构造 coingecko coin_chart 记录。

    market_caps: list of float，每个对应一天的 market_cap
    """
    timeseries = []
    for i, mc in enumerate(market_caps):
        date_str = f"2026-08-{i+1:02d}"
        timeseries.append({"date": date_str, "price": 1.0, "market_cap": mc, "volume": 0.0})
    return {
        "source": "coingecko",
        "category": "coin",
        "sub_category": f"chart_{coin_id}",
        "timestamp": ts,
        "metrics": {"coin_id": coin_id, "days": len(market_caps), "latest_market_cap": market_caps[-1]},
        "timeseries": timeseries,
    }


# ---------------------------------------------------------------------------
# 1. _compute_percentile 纯函数
# ---------------------------------------------------------------------------

class TestComputePercentile:
    """验证百分位计算纯函数。"""

    def test_returns_100_on_max_value(self):
        """当前值是序列最大 → 百分位接近 100。"""
        series = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        assert _compute_percentile(series, current=10.0) >= 80.0

    def test_returns_0_on_min_value(self):
        """当前值是序列最小 → 百分位接近 0。"""
        series = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        assert _compute_percentile(series, current=1.0) <= 20.0

    def test_returns_50_on_median(self):
        """当前值在中间 → 百分位接近 50。"""
        series = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        pct = _compute_percentile(series, current=5.0)
        assert 40.0 <= pct <= 60.0

    def test_filters_zero_market_caps(self):
        """market_cap=0 的点应被过滤（数据缺失）。"""
        # 10 个点，含 3 个 0，过滤后剩 7 个
        series = [0.0, 0.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        # 过滤 0 后剩 [1,2,3,4,5,6,7]，current=7 → 高分位
        pct = _compute_percentile(series, current=7.0)
        assert pct >= 80.0

    def test_returns_50_on_insufficient_data(self):
        """序列长度 < 7（不足一周）→ 返回 50（中性）。"""
        assert _compute_percentile([1.0, 2.0], current=2.0) == 50.0
        assert _compute_percentile([], current=2.0) == 50.0

    def test_returns_50_on_current_zero(self):
        """current=0 → 返回 50（中性，避免误判）。"""
        assert _compute_percentile([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0], current=0.0) == 50.0


# ---------------------------------------------------------------------------
# 2. query_valuation_percentile 集成
# ---------------------------------------------------------------------------

class TestQueryValuationPercentile:
    """验证从 data_center.db 查询估值分位。"""

    def test_query_returns_50_on_empty_db(self):
        """空 db → 返回 50（中性，FAIL-OPEN）。"""
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, source TEXT, category TEXT, "
                     "sub_category TEXT, timestamp TEXT, metrics TEXT, events TEXT, "
                     "timeseries TEXT, raw TEXT, schema_version TEXT, dedupe_key TEXT)")
        conn.commit(); conn.close()
        assert query_valuation_percentile("UNI", db_path) == 50.0

    def test_query_returns_50_on_no_chart_data(self):
        """db 有数据但无 coingecko chart 记录 → 返回 50。"""
        db = _make_test_db([{
            "source": "defillama", "category": "protocol", "sub_category": "uniswap",
            "timestamp": "2026-09-01", "metrics": {}, "timeseries": [],
        }])
        assert query_valuation_percentile("UNI", db) == 50.0

    def test_query_returns_high_on_recent_peak(self):
        """当前 market_cap 是序列最高 → 返回高分位。"""
        # UNI 的 coingecko_id 是 "uniswap"
        # 序列：1B → 2B → 3B → 4B → 5B → 6B → 7B（递增）
        mcaps = [1e9, 2e9, 3e9, 4e9, 5e9, 6e9, 7e9]
        db = _make_test_db([_make_chart_record("uniswap", mcaps)])
        pct = query_valuation_percentile("UNI", db)
        assert pct >= 80.0, f"当前是历史最高，应返回高分位，实际: {pct}"

    def test_query_returns_low_on_recent_trough(self):
        """当前 market_cap 是序列最低 → 返回低分位。"""
        # 序列：7B → 6B → 5B → 4B → 3B → 2B → 1B（递减，当前最低）
        mcaps = [7e9, 6e9, 5e9, 4e9, 3e9, 2e9, 1e9]
        db = _make_test_db([_make_chart_record("uniswap", mcaps)])
        pct = query_valuation_percentile("UNI", db)
        assert pct <= 20.0, f"当前是历史最低，应返回低分位，实际: {pct}"

    def test_query_returns_mid_on_middle(self):
        """当前 market_cap 在中间 → 返回中分位。"""
        # 序列：1,2,3,4,5,6,7,8,9,5 → current=5（最后一点），中等
        mcaps = [1e9, 2e9, 3e9, 4e9, 5e9, 6e9, 7e9, 8e9, 9e9, 5e9]
        db = _make_test_db([_make_chart_record("uniswap", mcaps)])
        pct = query_valuation_percentile("UNI", db)
        assert 30.0 <= pct <= 80.0, f"中间值应返回中分位，实际: {pct}"

    def test_query_uses_latest_record_when_multiple(self):
        """多条 chart 记录时，取 timestamp 最新的一条。"""
        old_ts = "2026-08-01T00:00:00+08:00"
        new_ts = "2026-09-01T00:00:00+08:00"
        # 旧记录：当前值低
        old_mcaps = [7e9, 6e9, 5e9, 4e9, 3e9, 2e9, 1e9]
        # 新记录：当前值高
        new_mcaps = [1e9, 2e9, 3e9, 4e9, 5e9, 6e9, 7e9]
        db = _make_test_db([
            _make_chart_record("uniswap", old_mcaps, ts=old_ts),
            _make_chart_record("uniswap", new_mcaps, ts=new_ts),
        ])
        pct = query_valuation_percentile("UNI", db)
        # 取最新记录（new_ts），当前=7e9 是最高 → 高分位
        assert pct >= 80.0

    def test_query_failopen_on_exception(self):
        """db 路径异常或查询失败 → 返回 50（FAIL-OPEN）。"""
        assert query_valuation_percentile("UNI", "/nonexistent/path/db.db") == 50.0

    def test_query_failopen_on_malformed_timeseries(self):
        """timeseries 字段是畸形 JSON → 返回 50。"""
        db = _make_test_db([{
            "source": "coingecko", "category": "coin",
            "sub_category": "chart_uniswap", "timestamp": "2026-09-01",
            "timeseries": "not-a-json{", "metrics": {},
        }])
        assert query_valuation_percentile("UNI", db) == 50.0

    def test_query_for_hype_uses_hyperliquid_id(self):
        """HYPE 查询用 coingecko_id=hyperliquid（sub_category=chart_hyperliquid）。"""
        mcaps = [1e9, 2e9, 3e9, 4e9, 5e9, 6e9, 7e9]
        db = _make_test_db([_make_chart_record("hyperliquid", mcaps)])
        pct = query_valuation_percentile("HYPE", db)
        assert pct >= 80.0  # 当前是最高
