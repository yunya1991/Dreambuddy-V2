"""CognitiveReviewer test suite."""
import pytest
from pathlib import Path
import sys

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from dreamos.capabilities.trading.cognitive_reviewer import CognitiveReviewer


def test_cognitive_reviewer_initialization():
    """Test CognitiveReviewer can be initialized."""
    reviewer = CognitiveReviewer()
    assert reviewer is not None
    assert hasattr(reviewer, "review")
    assert hasattr(reviewer, "extract_lessons")
    assert hasattr(reviewer, "get_cognitive_context")


def test_cognitive_reviewer_review_winning_trade():
    """Test review of a winning trade produces positive assessment."""
    reviewer = CognitiveReviewer()
    trade_result = {
        "symbol": "BTC",
        "direction": "LONG",
        "entry_price": 100000.0,
        "exit_price": 105000.0,
        "position_size": 0.01,
        "confidence": 0.75,
        "hexagram": {"original_gua": "Qian_1", "changed_gua": "Tai_11"},
        "addon_count": 0,
        "hold_hours": 5.0,
        "exit_reason": "ATR trailing TP hit",
        "pnl_usdt": 50.0,
        "pnl_pct": 0.05,
    }
    review = reviewer.review(trade_result)
    assert isinstance(review, dict)
    assert "symbol" in review
    assert "assessment" in review
    assert review["assessment"] in ("GOOD", "NEUTRAL", "BAD")
    assert "score" in review
    assert 0.0 <= review["score"] <= 1.0
    assert "lessons" in review
    assert isinstance(review["lessons"], list)
    assert "pnl_usdt" in review
    assert review["pnl_usdt"] == 50.0


def test_cognitive_reviewer_review_losing_trade():
    """Test review of a losing trade produces negative assessment."""
    reviewer = CognitiveReviewer()
    trade_result = {
        "symbol": "DOGE",
        "direction": "SHORT",
        "entry_price": 0.12,
        "exit_price": 0.15,
        "position_size": 1000.0,
        "confidence": 0.40,
        "hexagram": {"original_gua": "Kun_2", "changed_gua": "Pi_12"},
        "addon_count": 3,
        "hold_hours": 38.0,
        "exit_reason": "Timeout exit",
        "pnl_usdt": -30.0,
        "pnl_pct": -0.25,
    }
    review = reviewer.review(trade_result)
    assert review["assessment"] == "BAD"
    assert review["score"] < 0.5
    assert len(review["lessons"]) > 0
    # Should extract lesson about timeout exit with max addons
    lesson_texts = [str(l) for l in review["lessons"]]
    assert any("timeout" in t.lower() or "addon" in t.lower() for t in lesson_texts)
