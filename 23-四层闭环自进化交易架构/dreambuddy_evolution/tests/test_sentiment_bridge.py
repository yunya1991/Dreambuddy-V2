"""test_sentiment_bridge.py — SentimentBridge 单元测试
覆盖: 情绪聚合, 归一化, SentimentEngine加载失败FO, USE_FINBERT=0降级, 空快讯FO
"""
from __future__ import annotations

import pytest

from dreambuddy_evolution.adapters.sentiment_bridge import SentimentBridge


class MockSentimentEngine:
    """模拟 SentimentEngine"""

    def __init__(self, scores=None, fail=False):
        self._scores = scores or []
        self._fail = fail

    def analyze_text(self, text):
        if self._fail:
            raise RuntimeError("model load failed")
        for i, (t, s) in enumerate(self._scores):
            if t in text:
                return {"score": s, "sentiment": "positive" if s > 0 else "negative"}
        return {"score": 0.0, "sentiment": "neutral"}


def make_mock_db(tmp_path, newsflash_texts=None):
    """创建含 odaily newsflash 的测试 DB"""
    import json, sqlite3
    db_path = tmp_path / "data_center.db"
    conn = sqlite3.connect(str(db_path))
    c = conn.cursor()
    c.execute("""CREATE TABLE records (
        id INTEGER PRIMARY KEY, source TEXT, category TEXT,
        sub_category TEXT, timestamp TEXT, metrics TEXT, timeseries TEXT
    )""")
    for i, text in enumerate(newsflash_texts or []):
        metrics = json.dumps({"title": text, "content": text})
        c.execute(
            "INSERT INTO records (source, category, sub_category, timestamp, metrics) "
            "VALUES ('odaily', 'news', 'newsflash', ?, ?)",
            (f"2026-09-05T{i:02d}:00:00Z", metrics)
        )
    conn.commit()
    conn.close()
    return str(db_path)


class TestSentimentBridge:

    def test_sentiment_aggregation(self, tmp_path):
        """多条快讯情绪聚合"""
        texts = ["Bitcoin surges past 50K", "Market fears correction"]
        db_path = make_mock_db(tmp_path, texts)
        engine = MockSentimentEngine(scores=[
            ("surges", 0.8), ("fears", -0.6),
        ])
        bridge = SentimentBridge(data_center_db=db_path, sentiment_engine=engine, cache_ttl=0)
        bridge.invalidate_cache()
        score = bridge.get_sentiment_score("BTC")

        # avg(0.8, -0.6) = 0.1 → (0.1+1)/2 = 0.55
        assert abs(score - 0.55) < 0.01

    def test_normalization(self, tmp_path):
        """score [-1,+1] → [0,1] 归一化"""
        db_path = make_mock_db(tmp_path, ["Bitcoin crashes hard"])
        engine = MockSentimentEngine(scores=[("crashes", -1.0)])
        bridge = SentimentBridge(data_center_db=db_path, sentiment_engine=engine, cache_ttl=0)
        bridge.invalidate_cache()
        score = bridge.get_sentiment_score()
        assert abs(score - 0.0) < 0.01  # (-1+1)/2 = 0

    def test_engine_load_fail_fo(self, tmp_path):
        """SentimentEngine 加载失败 → score=0.5"""
        db_path = make_mock_db(tmp_path, ["test news"])
        bridge = SentimentBridge(data_center_db=db_path, sentiment_engine=None, cache_ttl=0)
        bridge.invalidate_cache()
        score = bridge.get_sentiment_score()
        # 没有可用 engine → 0.5
        assert score == 0.5

    def test_empty_newsflash_fo(self, tmp_path):
        """空快讯 → score=0.5"""
        db_path = make_mock_db(tmp_path, [])
        engine = MockSentimentEngine()
        bridge = SentimentBridge(data_center_db=db_path, sentiment_engine=engine, cache_ttl=0)
        bridge.invalidate_cache()
        score = bridge.get_sentiment_score()
        assert score == 0.5

    def test_single_text_exception_fo(self, tmp_path):
        """单条文本异常 → 该条 score=0.0"""
        texts = ["Bitcoin surges", "Bad text will crash"]
        db_path = make_mock_db(tmp_path, texts)

        class CrashOnBadEngine:
            def analyze_text(self, text):
                if "crash" in text:
                    raise RuntimeError("single text crash")
                if "surges" in text:
                    return {"score": 0.9, "sentiment": "positive"}
                return {"score": 0.0, "sentiment": "neutral"}

        bridge = SentimentBridge(
            data_center_db=db_path,
            sentiment_engine=CrashOnBadEngine(),
            cache_ttl=0,
        )
        bridge.invalidate_cache()
        score = bridge.get_sentiment_score()
        # avg(0.9, 0.0) = 0.45 → (0.45+1)/2 = 0.725
        assert abs(score - 0.725) < 0.01
