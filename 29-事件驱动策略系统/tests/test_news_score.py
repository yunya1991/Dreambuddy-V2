"""test_news_score.py — Phase 3.1 新增第 6 维 news_score 评分

SPEC: SPEC-事件驱动策略独立化-共享事件层与弹性约束.md §3.2.1 (v1.3)

测试组:
A. news_score 评分方法 (3)
B. 6 维加权集成 (1)
"""
from __future__ import annotations

import pytest


def _make_strategy():
    from event_driven.event_driven_strategy import EventDrivenStrategy
    return EventDrivenStrategy()


# ================================================================
# A. news_score 评分方法
# ================================================================

def test_news_score_bullish():
    """news_sentiment_score=0.8（偏多） → news_score > 0.5"""
    s = _make_strategy()
    score = s._score_news({"news_sentiment_score": 0.8}, {})
    assert score > 0.5
    assert score <= 1.0


def test_news_score_bearish():
    """news_sentiment_score=0.2（偏空） → news_score < 0.5"""
    s = _make_strategy()
    score = s._score_news({"news_sentiment_score": 0.2}, {})
    assert score < 0.5
    assert score >= 0.0


def test_news_score_fail_open():
    """FAIL-OPEN: news_sentiment_score=None → news_score=0.5（中性）"""
    s = _make_strategy()
    score = s._score_news({}, {})
    assert score == 0.5


def test_news_score_neutral():
    """news_sentiment_score=0.5 → news_score≈0.5"""
    s = _make_strategy()
    score = s._score_news({"news_sentiment_score": 0.5}, {})
    assert abs(score - 0.5) < 0.01


# ================================================================
# B. 6 维加权集成
# ================================================================

def test_composite_includes_news():
    """6 维加权包含 news_score，权重 10%。

    验证：仅 news_sentiment_score 变化时，composite(strength) 随之同向变化。
    构造 FOMC 事件场景使 evaluate 走到 composite 计算。
    """
    s = _make_strategy()
    fomc_ctx = {
        "event_type": "fomc",
        "in_fomc_cycle": True,
        "cycle_phase": "event",
        "hike_prob": 0.5,
    }
    base_data = {"symbol": "BTC", "event_context": fomc_ctx}

    # 无新闻（FAIL-OPEN news_score=0.5）
    neutral = s.evaluate(base_data)
    # 强看多新闻
    bullish = s.evaluate({**base_data, "news_sentiment_score": 0.9})
    # 强看空新闻
    bearish = s.evaluate({**base_data, "news_sentiment_score": 0.1})

    assert bullish.strength > neutral.strength, (
        f"看多新闻应提升 composite: bullish={bullish.strength} > neutral={neutral.strength}"
    )
    assert bearish.strength < neutral.strength, (
        f"看空新闻应降低 composite: bearish={bearish.strength} < neutral={neutral.strength}"
    )


def test_scores_dict_contains_news():
    """_compute_scores 返回的 dict 包含 'news' 键"""
    s = _make_strategy()
    scores = s._compute_scores({"news_sentiment_score": 0.6}, {})
    assert "news" in scores
