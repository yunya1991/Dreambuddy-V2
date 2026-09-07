"""F3: 真实历史数据回放测试 — TDD 先红后绿。

验证 coin_fundamental_historical_data_loader.py：
  - query_historical_fees(coin, db_path) -> List[{date, fees_usd}]
  - query_historical_mcap(coin, db_path) -> List[{date, market_cap}]
  - query_historical_price(coin, db_path) -> List[{date, price}]
  - build_real_snapshots(coin, db_path) -> List[PhaseSnapshot]
    从真实历史数据构造阶段回放快照序列，数据不足返回空 list（FAIL-OPEN）

数据源：
  - DeFiLlama: source=defillama, category=chain, sub_category=fees_{protocol}
    timeseries: [{"date": ISO, "fees_usd": float}, ...]
  - CoinGecko: source=coingecko, category=coin, sub_category=chart_{coin_id}
    timeseries: [{"date": ISO, "price": float, "market_cap": float, "volume": float}, ...]
  - yfinance: source=yfinance, category=stock/crypto, sub_category=symbol
    timeseries: [{"date": ISO, "close": float}, ...]
"""
import pytest
import sqlite3
import sys
import tempfile
import os
import json
from pathlib import Path

# 将 force_vector 和 scripts 加入 sys.path
_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))
_SCRIPTS_DIR = _L4_DIR / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from force_vector.coin_fundamental_historical_data_loader import (
    query_historical_fees,
    query_historical_mcap,
    query_historical_price,
    build_real_snapshots,
)
from coin_fundamental_phase_replay import PhaseSnapshot


# ---------------------------------------------------------------------------
# 辅助：构造临时 data_center.db
# ---------------------------------------------------------------------------

def _make_test_db(records: list) -> str:
    """构造临时 sqlite db，插入 records 表数据。"""
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
    for r in records:
        conn.execute(
            "INSERT INTO records (dedupe_key, source, category, sub_category, timestamp, "
            "metrics, events, timeseries, raw, schema_version) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                r.get("dedupe_key", f"{r['source']}_{r['category']}_{r['sub_category']}"),
                r["source"], r["category"], r["sub_category"], r.get("timestamp", "2026-09-01"),
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


def _make_defillama_fees_record(protocol: str, fees_ts: list) -> dict:
    """构造 DeFiLlama protocol fees 记录。"""
    return {
        "source": "defillama",
        "category": "chain",
        "sub_category": f"fees_{protocol}",
        "timeseries": fees_ts,  # [{date, fees_usd}, ...]
        "metrics": {"protocol": protocol, "points": len(fees_ts)},
    }


def _make_coingecko_chart_record(coin_id: str, chart_ts: list) -> dict:
    """构造 CoinGecko market_chart 记录。"""
    return {
        "source": "coingecko",
        "category": "coin",
        "sub_category": f"chart_{coin_id}",
        "timeseries": chart_ts,  # [{date, price, market_cap, volume}, ...]
        "metrics": {"coin_id": coin_id, "points": len(chart_ts)},
    }


def _make_yfinance_record(symbol: str, price_ts: list) -> dict:
    """构造 yfinance 价格记录。"""
    return {
        "source": "yfinance",
        "category": "stock",
        "sub_category": symbol,
        "timeseries": price_ts,  # [{date, close}, ...]
        "metrics": {"symbol": symbol, "points": len(price_ts)},
    }


# ---------------------------------------------------------------------------
# 1. query_historical_fees
# ---------------------------------------------------------------------------

class TestQueryHistoricalFees:
    """验证从 DeFiLlama 查询历史 fees 时间序列。"""

    def test_returns_fees_timeseries_for_uni(self):
        """UNI → protocol=uniswap → 返回 fees 序列。"""
        fees_ts = [
            {"date": "2026-08-25", "fees_usd": 1_000_000},
            {"date": "2026-08-26", "fees_usd": 1_200_000},
            {"date": "2026-08-27", "fees_usd": 1_500_000},
        ]
        db = _make_test_db([_make_defillama_fees_record("uniswap", fees_ts)])
        result = query_historical_fees("UNI", db)
        assert len(result) == 3
        assert result[0]["fees_usd"] == 1_000_000
        assert result[-1]["fees_usd"] == 1_500_000

    def test_returns_empty_for_crcl_no_protocol(self):
        """CRCL → defillama_slug=None → 返回空 list。"""
        db = _make_test_db([])
        assert query_historical_fees("CRCL", db) == []

    def test_returns_empty_on_no_data(self):
        """db 无 defillama 记录 → 返回空 list。"""
        db = _make_test_db([_make_coingecko_chart_record("uniswap", [])])
        assert query_historical_fees("UNI", db) == []

    def test_failopen_on_nonexistent_db(self):
        """db 路径不存在 → 返回空 list（FAIL-OPEN）。"""
        assert query_historical_fees("UNI", "/nonexistent/db.db") == []

    def test_failopen_on_malformed_timeseries(self):
        """timeseries 畸形 JSON → 返回空 list。"""
        db = _make_test_db([{
            "source": "defillama", "category": "chain",
            "sub_category": "fees_uniswap",
            "timeseries": "not-a-json{",
        }])
        assert query_historical_fees("UNI", db) == []


# ---------------------------------------------------------------------------
# 2. query_historical_mcap
# ---------------------------------------------------------------------------

class TestQueryHistoricalMcap:
    """验证从 CoinGecko 查询历史 market_cap 时间序列。"""

    def test_returns_mcap_timeseries_for_uni(self):
        """UNI → coin_id=uniswap → 返回 market_cap 序列。"""
        chart_ts = [
            {"date": "2026-08-25", "price": 8.0, "market_cap": 8e9, "volume": 1e8},
            {"date": "2026-08-26", "price": 9.0, "market_cap": 9e9, "volume": 1.2e8},
            {"date": "2026-08-27", "price": 10.0, "market_cap": 10e9, "volume": 1.5e8},
        ]
        db = _make_test_db([_make_coingecko_chart_record("uniswap", chart_ts)])
        result = query_historical_mcap("UNI", db)
        assert len(result) == 3
        assert result[0]["market_cap"] == 8e9
        assert result[-1]["market_cap"] == 10e9

    def test_returns_empty_for_unknown_coin(self):
        """未知币种 → 返回空 list。"""
        db = _make_test_db([])
        assert query_historical_mcap("UNKNOWN", db) == []

    def test_failopen_on_nonexistent_db(self):
        """db 路径不存在 → 返回空 list。"""
        assert query_historical_mcap("UNI", "/nonexistent/db.db") == []

    def test_filters_zero_mcap_points(self):
        """market_cap=0 的点被过滤掉。"""
        chart_ts = [
            {"date": "2026-08-25", "price": 8.0, "market_cap": 0, "volume": 0},
            {"date": "2026-08-26", "price": 9.0, "market_cap": 9e9, "volume": 0},
        ]
        db = _make_test_db([_make_coingecko_chart_record("uniswap", chart_ts)])
        result = query_historical_mcap("UNI", db)
        assert len(result) == 1  # 0 值被过滤
        assert result[0]["market_cap"] == 9e9


# ---------------------------------------------------------------------------
# 3. query_historical_price
# ---------------------------------------------------------------------------

class TestQueryHistoricalPrice:
    """验证从 yfinance 查询历史价格时间序列。"""

    def test_returns_price_timeseries(self):
        """返回价格 close 序列。"""
        price_ts = [
            {"date": "2026-08-25", "close": 8.0},
            {"date": "2026-08-26", "close": 9.0},
            {"date": "2026-08-27", "close": 10.0},
        ]
        db = _make_test_db([_make_yfinance_record("UNI-USD", price_ts)])
        result = query_historical_price("UNI-USD", db)
        assert len(result) == 3
        assert result[-1]["close"] == 10.0

    def test_returns_empty_on_no_data(self):
        """db 无 yfinance 记录 → 返回空 list。"""
        db = _make_test_db([])
        assert query_historical_price("UNI-USD", db) == []

    def test_failopen_on_nonexistent_db(self):
        """db 路径不存在 → 返回空 list。"""
        assert query_historical_price("UNI-USD", "/nonexistent/db.db") == []


# ---------------------------------------------------------------------------
# 4. build_real_snapshots
# ---------------------------------------------------------------------------

class TestBuildRealSnapshots:
    """验证从真实历史数据构造 PhaseSnapshot 序列。"""

    def test_returns_snapshots_from_real_data(self):
        """有真实 fees + mcap 数据（≥7点）→ 返回 PhaseSnapshot 序列。"""
        fees_ts = [
            {"date": f"2026-08-{d:02d}", "fees_usd": 1e6 * (1 + i * 0.1)}
            for i, d in enumerate(range(25, 32))  # 7天
        ]
        chart_ts = [
            {"date": f"2026-08-{d:02d}", "price": 8.0 + i, "market_cap": (8 + i) * 1e9, "volume": 0}
            for i, d in enumerate(range(25, 32))  # 7天
        ]
        db = _make_test_db([
            _make_defillama_fees_record("uniswap", fees_ts),
            _make_coingecko_chart_record("uniswap", chart_ts),
        ])
        snaps = build_real_snapshots("UNI", db)
        assert len(snaps) == 7
        assert isinstance(snaps[0], PhaseSnapshot)
        # 最后一个点 valuation_percentile 应为 100（最高）
        assert snaps[-1].valuation_percentile == 100.0

    def test_returns_empty_on_no_data(self):
        """无任何历史数据 → 返回空 list（调用方回退合成）。"""
        db = _make_test_db([])
        assert build_real_snapshots("UNI", db) == []

    def test_returns_empty_on_insufficient_mcap(self):
        """mcap 数据不足（<7点）→ 返回空 list。"""
        fees_ts = [{"date": "2026-08-25", "fees_usd": 1e6}]
        chart_ts = [{"date": "2026-08-25", "price": 8.0, "market_cap": 8e9, "volume": 0}]
        db = _make_test_db([
            _make_defillama_fees_record("uniswap", fees_ts),
            _make_coingecko_chart_record("uniswap", chart_ts),
        ])
        # mcap 仅 1 点 < 最小窗口 7 → 数据不足 → 空 list
        assert build_real_snapshots("UNI", db) == []

    def test_failopen_on_nonexistent_db(self):
        """db 路径不存在 → 返回空 list。"""
        assert build_real_snapshots("UNI", "/nonexistent/db.db") == []

    def test_snapshots_have_valid_fields(self):
        """PhaseSnapshot 字段完整：ts/e5/e6/valuation_percentile/events。"""
        fees_ts = [
            {"date": f"2026-08-{d:02d}", "fees_usd": 1e6 * (1 + i * 0.1)}
            for i, d in enumerate(range(25, 32))  # 7天
        ]
        chart_ts = [
            {"date": f"2026-08-{d:02d}", "price": 8.0 + i, "market_cap": (8 + i) * 1e9, "volume": 0}
            for i, d in enumerate(range(25, 32))  # 7天
        ]
        db = _make_test_db([
            _make_defillama_fees_record("uniswap", fees_ts),
            _make_coingecko_chart_record("uniswap", chart_ts),
        ])
        snaps = build_real_snapshots("UNI", db)
        assert len(snaps) >= 1
        s = snaps[0]
        assert hasattr(s, "ts")
        assert hasattr(s, "e5")
        assert hasattr(s, "e6")
        assert hasattr(s, "valuation_percentile")
        assert hasattr(s, "events")
        assert isinstance(s.events, list)
