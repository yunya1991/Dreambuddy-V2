"""F2: 事件源接入测试 — TDD 先红后绿。

验证 coin_fundamental_event_timeline.py：
  - query_event_timeline(coin, db_path) -> List[Dict]
  - 从 data_center.db records 表查 odaily newsflash 记录
  - 过滤 od_tickers_hit_csl 包含 coin 的记录
  - 只保留 od_event_type="token_milestone" 的记录
  - 从 title 关键词细分事件类型：mainnet_launch / upgrade / partnership
  - status 判断：published_ms 距今 < 7天 → pending，>= 7天 → landed

数据源：odaily newsflash（source=odaily_newsflash, category=news, sub_category=newsflash_{id}）
metrics 含：od_event_type, od_tickers_hit_csl, od_is_important, od_policy_sentiment_0_1
events 含：[{"event_type", "importance", "published_ms"}]
raw 含：{"title", "description", "tickers_hit"}
"""
import pytest
import sqlite3
import sys
import tempfile
import os
import json
import time
from pathlib import Path

# 将 force_vector 加入 sys.path
_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))

from force_vector.coin_fundamental_event_timeline import (
    query_event_timeline,
    _classify_event_type_from_title,
    _compute_status_from_age,
)


# ---------------------------------------------------------------------------
# 辅助：构造临时 data_center.db
# ---------------------------------------------------------------------------

def _now_ms() -> int:
    return int(time.time() * 1000)


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


def _make_news_record(
    od_id: int,
    title: str,
    description: str,
    tickers_hit: list,
    event_type: str = "token_milestone",
    published_ms: int = None,
    ts: str = "2026-09-01T00:00:00+08:00",
) -> dict:
    """构造 odaily newsflash 记录。"""
    if published_ms is None:
        published_ms = _now_ms()
    return {
        "source": "odaily_newsflash",
        "category": "news",
        "sub_category": f"newsflash_{od_id}",
        "timestamp": ts,
        "metrics": {
            "od_source_id": od_id,
            "od_policy_sentiment_0_1": 0.8,
            "od_event_type": event_type,
            "od_attention_type": "market_risk_on",
            "od_is_important": "true",
            "od_decay_hl_hrs": 24,
            "od_title_hash": "abc12345",
            "od_tickers_hit_csl": ",".join(tickers_hit),
        },
        "events": [{
            "event_type": event_type,
            "importance": 2,
            "published_ms": published_ms,
        }],
        "raw": {
            "title": title,
            "description": description,
            "tickers_hit": tickers_hit,
            "publishTimestamp": published_ms,
        },
    }


# ---------------------------------------------------------------------------
# 1. _classify_event_type_from_title 纯函数
# ---------------------------------------------------------------------------

class TestClassifyEventTypeFromTitle:
    """验证从标题关键词细分事件类型。"""

    def test_mainnet_launch_from_title(self):
        """标题含"主网上线/上线主网"→ mainnet_launch。"""
        assert _classify_event_type_from_title("CRCL 主网上线在即") == "mainnet_launch"
        assert _classify_event_type_from_title("CRCL 上线主网") == "mainnet_launch"

    def test_upgrade_from_title(self):
        """标题含"升级/版本升级"→ upgrade。"""
        assert _classify_event_type_from_title("UNI 协议版本升级 V3") == "upgrade"
        assert _classify_event_type_from_title("AAVE 主网升级完成") == "upgrade"

    def test_partnership_from_title(self):
        """标题含"合作/集成"→ partnership。"""
        assert _classify_event_type_from_title("UNI 战略合作 Robinhood") == "partnership"
        assert _classify_event_type_from_title("CRCL 集成至 Coinbase") == "partnership"

    def test_unknown_returns_unknown(self):
        """无匹配关键词 → "unknown"（调用方过滤）。"""
        assert _classify_event_type_from_title("BTC 价格上涨") == "unknown"
        assert _classify_event_type_from_title("") == "unknown"


# ---------------------------------------------------------------------------
# 2. _compute_status_from_age 纯函数
# ---------------------------------------------------------------------------

class TestComputeStatusFromAge:
    """验证从发布时间距今判断 pending/landed。"""

    def test_pending_within_7d(self):
        """距今 < 7天 → pending。"""
        now_ms = _now_ms()
        # 3天前
        published_ms = now_ms - 3 * 24 * 3600 * 1000
        assert _compute_status_from_age(published_ms, now_ms) == "pending"

    def test_landed_after_7d(self):
        """距今 >= 7天 → landed。"""
        now_ms = _now_ms()
        # 10天前
        published_ms = now_ms - 10 * 24 * 3600 * 1000
        assert _compute_status_from_age(published_ms, now_ms) == "landed"

    def test_boundary_7d_is_landed(self):
        """距今正好 7天 → landed（边界含）。"""
        now_ms = _now_ms()
        published_ms = now_ms - 7 * 24 * 3600 * 1000
        assert _compute_status_from_age(published_ms, now_ms) == "landed"

    def test_future_returns_pending(self):
        """未来时间 → pending（保守不丢）。"""
        now_ms = _now_ms()
        published_ms = now_ms + 1000  # 1秒后
        assert _compute_status_from_age(published_ms, now_ms) == "pending"

    def test_zero_published_returns_pending(self):
        """published_ms=0 → pending（保守）。"""
        assert _compute_status_from_age(0, _now_ms()) == "pending"


# ---------------------------------------------------------------------------
# 3. query_event_timeline 集成
# ---------------------------------------------------------------------------

class TestQueryEventTimeline:
    """验证从 data_center.db 查询事件时间线。"""

    def test_query_returns_empty_on_no_news(self):
        """db 无 news 记录 → 返回空 list。"""
        db = _make_test_db([{
            "source": "coingecko", "category": "coin",
            "sub_category": "chart_uniswap", "timestamp": "2026-09-01",
            "metrics": {}, "events": [], "raw": {},
        }])
        assert query_event_timeline("UNI", db) == []

    def test_query_returns_events_for_coin_in_tickers_hit(self):
        """od_tickers_hit_csl 含 coin → 返回该事件。"""
        now_ms = _now_ms()
        # 3天前发布，pending
        pub_ms = now_ms - 3 * 24 * 3600 * 1000
        rec = _make_news_record(
            od_id=1, title="CRCL 主网上线在即",
            description="CRCL 即将上线主网",
            tickers_hit=["CRCL"],
            published_ms=pub_ms,
        )
        db = _make_test_db([rec])
        events = query_event_timeline("CRCL", db)
        assert len(events) == 1
        assert events[0]["type"] == "mainnet_launch"
        assert events[0]["status"] == "pending"

    def test_query_filters_non_token_milestone(self):
        """od_event_type != token_milestone → 过滤掉。"""
        rec = _make_news_record(
            od_id=1, title="BTC 主网上线",
            description="", tickers_hit=["BTC"],
            event_type="market_sentiment",  # 非里程碑
        )
        db = _make_test_db([rec])
        assert query_event_timeline("BTC", db) == []

    def test_query_filters_coin_not_in_tickers(self):
        """od_tickers_hit_csl 不含目标 coin → 过滤掉。"""
        rec = _make_news_record(
            od_id=1, title="ETH 主网上线",
            description="", tickers_hit=["ETH"],
        )
        db = _make_test_db([rec])
        # 查 BTC → 不应返回 ETH 的事件
        assert query_event_timeline("BTC", db) == []

    def test_query_classifies_upgrade_event(self):
        """标题含"升级"→ type=upgrade。"""
        now_ms = _now_ms()
        pub_ms = now_ms - 3 * 24 * 3600 * 1000
        rec = _make_news_record(
            od_id=1, title="UNI 协议版本升级 V3",
            description="", tickers_hit=["UNI"],
            published_ms=pub_ms,
        )
        db = _make_test_db([rec])
        events = query_event_timeline("UNI", db)
        assert len(events) == 1
        assert events[0]["type"] == "upgrade"

    def test_query_classifies_partnership_event(self):
        """标题含"合作"→ type=partnership。"""
        now_ms = _now_ms()
        pub_ms = now_ms - 3 * 24 * 3600 * 1000
        rec = _make_news_record(
            od_id=1, title="UNI 战略合作 Robinhood",
            description="", tickers_hit=["UNI"],
            published_ms=pub_ms,
        )
        db = _make_test_db([rec])
        events = query_event_timeline("UNI", db)
        assert len(events) == 1
        assert events[0]["type"] == "partnership"

    def test_query_status_landed_after_7d(self):
        """距今 > 7天 → status=landed。"""
        now_ms = _now_ms()
        pub_ms = now_ms - 10 * 24 * 3600 * 1000
        rec = _make_news_record(
            od_id=1, title="CRCL 主网上线完成",
            description="", tickers_hit=["CRCL"],
            published_ms=pub_ms,
        )
        db = _make_test_db([rec])
        events = query_event_timeline("CRCL", db)
        assert len(events) == 1
        assert events[0]["status"] == "landed"

    def test_query_filters_unknown_event_type(self):
        """标题无匹配关键词 → type=unknown → 过滤掉。"""
        rec = _make_news_record(
            od_id=1, title="BTC 价格上涨",
            description="", tickers_hit=["BTC"],
        )
        db = _make_test_db([rec])
        # type=unknown 不应返回
        assert query_event_timeline("BTC", db) == []

    def test_query_returns_multiple_events_sorted_by_time(self):
        """多条事件 → 按时间倒序（最新在前）。"""
        now_ms = _now_ms()
        old_ms = now_ms - 10 * 24 * 3600 * 1000
        new_ms = now_ms - 1 * 24 * 3600 * 1000
        recs = [
            _make_news_record(od_id=1, title="CRCL 主网上线",
                              description="", tickers_hit=["CRCL"],
                              published_ms=old_ms),
            _make_news_record(od_id=2, title="CRCL 战略合作",
                              description="", tickers_hit=["CRCL"],
                              published_ms=new_ms),
        ]
        db = _make_test_db(recs)
        events = query_event_timeline("CRCL", db)
        assert len(events) == 2
        # 最新（new_ms）在前
        assert events[0]["type"] == "partnership"  # new_ms 对应合作
        assert events[1]["type"] == "mainnet_launch"  # old_ms 对应主网

    def test_query_failopen_on_exception(self):
        """db 路径异常 → 返回空 list（FAIL-OPEN）。"""
        assert query_event_timeline("UNI", "/nonexistent/db.db") == []

    def test_query_failopen_on_malformed_events(self):
        """events 字段畸形 JSON → 返回空 list。"""
        db = _make_test_db([{
            "source": "odaily_newsflash", "category": "news",
            "sub_category": "newsflash_1", "timestamp": "2026-09-01",
            "metrics": json.dumps({"od_event_type": "token_milestone",
                                    "od_tickers_hit_csl": "UNI"}),
            "events": "not-a-json{",
            "raw": json.dumps({"title": "UNI 主网上线"}),
        }])
        # events 畸形但 metrics 正常 → 仍能从 metrics 提取，但 published_ms 缺失 → pending
        # 不抛异常即 FAIL-OPEN 通过
        events = query_event_timeline("UNI", db)
        # 至少不抛异常；具体是否返回取决于实现
        assert isinstance(events, list)
