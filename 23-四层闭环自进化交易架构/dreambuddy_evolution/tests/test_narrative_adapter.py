"""
NarrativeAdapter 测试 — odaily 叙事标签库
覆盖: ticker 匹配 / 情绪 + 重要性 + 事件权重 + 时间衰减 / FAIL-OPEN
"""
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from dreambuddy_evolution.adapters.narrative_adapter import NarrativeAdapter


@pytest.fixture
def mock_db(tmp_path):
    """创建含 odaily_newsflash 记录的临时 SQLite DB"""
    db_path = tmp_path / "data_center.db"
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()
    c.execute("""
        CREATE TABLE records (
            id INTEGER PRIMARY KEY,
            dedupe_key TEXT,
            source TEXT,
            category TEXT,
            sub_category TEXT,
            timestamp TEXT,
            metrics TEXT,
            events TEXT,
            timeseries TEXT,
            raw TEXT,
            schema_version TEXT
        )
    """)

    now_ms = 1787944840000  # 2026-08-29
    rows = [
        # BTC 重要看多 + risk_on
        {
            "metrics": {
                "od_policy_sentiment_0_1": 0.9,
                "od_event_type": "project_ecosystem",
                "od_attention_type": "market_risk_on",
                "od_is_important": True,
                "od_decay_hl_hrs": 6.0,
                "od_tickers_hit_csl": "BTC",
            },
            "events": [{"event_type": "project_ecosystem", "importance": 1, "published_ms": now_ms}],
            "raw": {"title": "BTC 生态重大升级"},
        },
        # BTC 普通中性
        {
            "metrics": {
                "od_policy_sentiment_0_1": 0.5,
                "od_event_type": "market_sentiment",
                "od_attention_type": "neutral",
                "od_is_important": False,
                "od_decay_hl_hrs": 6.0,
                "od_tickers_hit_csl": "BTC,ETH",
            },
            "events": [{"event_type": "market_sentiment", "importance": 1, "published_ms": now_ms}],
            "raw": {"title": "BTC 价格波动"},
        },
        # ETH 看空 risk_off
        {
            "metrics": {
                "od_policy_sentiment_0_1": 0.2,
                "od_event_type": "market_sentiment",
                "od_attention_type": "market_risk_off",
                "od_is_important": False,
                "od_decay_hl_hrs": 6.0,
                "od_tickers_hit_csl": "ETH",
            },
            "events": [{"event_type": "market_sentiment", "importance": 1, "published_ms": now_ms}],
            "raw": {"title": "ETH 下跌"},
        },
        # SOL 监管高影响
        {
            "metrics": {
                "od_policy_sentiment_0_1": 0.8,
                "od_event_type": "regulatory",
                "od_attention_type": "neutral",
                "od_is_important": True,
                "od_decay_hl_hrs": 12.0,
                "od_tickers_hit_csl": "SOL",
            },
            "events": [{"event_type": "regulatory", "importance": 1, "published_ms": now_ms}],
            "raw": {"title": "SOL 监管利好"},
        },
        # 无关币种
        {
            "metrics": {
                "od_policy_sentiment_0_1": 1.0,
                "od_event_type": "market_sentiment",
                "od_attention_type": "market_risk_on",
                "od_is_important": False,
                "od_decay_hl_hrs": 6.0,
                "od_tickers_hit_csl": "DOGE",
            },
            "events": [{"event_type": "market_sentiment", "importance": 1, "published_ms": now_ms}],
            "raw": {"title": "DOGE 暴涨"},
        },
    ]

    for i, r in enumerate(rows):
        c.execute(
            "INSERT INTO records (dedupe_key, source, category, sub_category, "
            "timestamp, metrics, events, timeseries, raw, schema_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"key_{i}",
                "odaily_newsflash",
                "news",
                f"flash_{i}",
                "2026-08-29T03:46:19.363620+08:00",
                json.dumps(r["metrics"]),
                json.dumps(r["events"]),
                "[]",
                json.dumps(r["raw"]),
                "1.0",
            ),
        )

    conn.commit()
    conn.close()
    return str(db_path)


class TestNarrativeAdapter:
    def test_btc_score_high(self, mock_db):
        """BTC 有重要看多 + risk_on → 高分"""
        adapter = NarrativeAdapter(db_path=mock_db)
        score = adapter.get_narrative_score("BTC")
        assert score is not None
        assert score > 0.5

    def test_eth_score_low(self, mock_db):
        """ETH 看空 + risk_off → 低分"""
        adapter = NarrativeAdapter(db_path=mock_db)
        score = adapter.get_narrative_score("ETH")
        assert score is not None
        assert score < 0.5

    def test_sol_regulatory_weight(self, mock_db):
        """SOL 监管事件权重高 → 分数反映监管权重"""
        adapter = NarrativeAdapter(db_path=mock_db)
        score = adapter.get_narrative_score("SOL")
        assert score is not None
        # 监管权重 1.3 × 情绪 0.8 = 高分
        assert score > 0.6

    def test_btc_higher_than_eth(self, mock_db):
        """BTC 叙事 > ETH 叙事"""
        adapter = NarrativeAdapter(db_path=mock_db)
        btc = adapter.get_narrative_score("BTC")
        eth = adapter.get_narrative_score("ETH")
        assert btc is not None and eth is not None
        assert btc > eth

    def test_unrelated_coin_returns_none(self, mock_db):
        """无 ticker 匹配 → None"""
        adapter = NarrativeAdapter(db_path=mock_db)
        score = adapter.get_narrative_score("XRP")
        assert score is None

    def test_score_in_range(self, mock_db):
        """分数 ∈ [0, 1]"""
        adapter = NarrativeAdapter(db_path=mock_db)
        for sym in ["BTC", "ETH", "SOL"]:
            score = adapter.get_narrative_score(sym)
            if score is not None:
                assert 0.0 <= score <= 1.0

    def test_no_db_returns_none(self):
        """无 db_path → None"""
        adapter = NarrativeAdapter(db_path=None)
        assert adapter.get_narrative_score("BTC") is None

    def test_missing_table_fo(self, tmp_path):
        """表不存在 → FAIL-OPEN 返回 None"""
        db_path = tmp_path / "empty.db"
        sqlite3.connect(str(db_path)).close()
        adapter = NarrativeAdapter(db_path=str(db_path))
        assert adapter.get_narrative_score("BTC") is None

    def test_malformed_metrics_fo(self, tmp_path):
        """metrics JSON 损坏 → FAIL-OPEN 不崩溃"""
        db_path = tmp_path / "bad.db"
        conn = sqlite3.connect(str(db_path))
        c = conn.cursor()
        c.execute("CREATE TABLE records (metrics TEXT, events TEXT, raw TEXT, timestamp TEXT)")
        c.execute("INSERT INTO records VALUES (?, ?, ?, ?)", ("{invalid", "[]", "{}", "2026-01-01T00:00:00"))
        conn.commit()
        conn.close()
        adapter = NarrativeAdapter(db_path=str(db_path))
        # 不抛异常即可
        result = adapter.get_narrative_score("BTC")
        assert result is None

    def test_age_hours_fallback(self):
        """_age_hours 无 events/timestamp → 返回 0"""
        age = NarrativeAdapter._age_hours({})
        assert age == 0.0
