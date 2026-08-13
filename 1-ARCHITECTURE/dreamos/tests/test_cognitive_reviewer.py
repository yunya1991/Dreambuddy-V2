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


# ---- Task 2: persist_lessons ----

def test_cognitive_reviewer_persist_lessons(tmp_path):
    """Test persist_lessons saves lessons to JSON file."""
    import json

    reviewer = CognitiveReviewer()
    trade = {
        "symbol": "BTC", "direction": "LONG", "entry_price": 100000.0,
        "exit_price": 105000.0, "position_size": 0.01, "confidence": 0.75,
        "hexagram": {}, "addon_count": 0, "hold_hours": 5.0,
        "exit_reason": "ATR trailing TP hit", "pnl_usdt": 50.0, "pnl_pct": 0.05,
    }
    reviewer.review(trade)

    filepath = tmp_path / "lessons.json"
    reviewer.persist_lessons(str(filepath))

    assert filepath.exists()
    saved = json.loads(filepath.read_text(encoding="utf-8"))
    assert "lessons" in saved
    assert "total_reviews" in saved
    assert "persisted_at" in saved
    assert saved["total_reviews"] == 1
    assert len(saved["lessons"]) > 0


# ---- Task 3: CognitiveReviewerNode ----

def test_cognitive_reviewer_node():
    """Test CognitiveReviewerNode node wrapper."""
    from dreamos.capabilities.trading.cognitive_reviewer import CognitiveReviewerNode
    from dreamos.shared.state import State, NodeResult, new_state

    node = CognitiveReviewerNode()
    assert node.node_id == "COGNITIVE_REVIEW"
    assert node.chain == "E"

    state = new_state(cycle_id="test-review-001")
    state.market = {
        "symbol": "BTC",
        "direction": "LONG",
        "entry_price": 100000.0,
        "exit_price": 105000.0,
        "position_size": 0.01,
        "confidence": 0.75,
        "hexagram": {},
        "addon_count": 0,
        "hold_hours": 5.0,
        "exit_reason": "ATR trailing TP hit",
        "pnl_usdt": 50.0,
        "pnl_pct": 0.05,
    }

    result = node.execute(state)

    assert isinstance(result, NodeResult)
    assert result.node_id == "COGNITIVE_REVIEW"
    assert result.success
    assert "assessment" in result.outputs
    assert result.outputs["assessment"] in ("GOOD", "NEUTRAL", "BAD")
    assert "score" in result.outputs
    assert "lessons" in result.outputs


# ---- Task 4: Phase 5 integration test ----

def test_phase5_integration():
    """Phase 5 end-to-end: review -> lessons -> context -> persist -> node."""
    import json
    from dreamos.capabilities.trading.cognitive_reviewer import CognitiveReviewer, CognitiveReviewerNode
    from dreamos.shared.state import new_state

    # Step 1: Initialize reviewer
    reviewer = CognitiveReviewer()
    assert reviewer is not None

    # Step 2: Review winning trade
    win_trade = {
        "symbol": "BTC", "direction": "LONG", "entry_price": 100000.0,
        "exit_price": 105000.0, "position_size": 0.01, "confidence": 0.75,
        "hexagram": {"original_gua": "Qian_1"}, "addon_count": 0,
        "hold_hours": 5.0, "exit_reason": "ATR trailing TP hit",
        "pnl_usdt": 50.0, "pnl_pct": 0.05,
    }
    win_review = reviewer.review(win_trade)
    assert win_review["assessment"] == "GOOD"
    assert win_review["score"] > 0.5

    # Step 3: Review losing trade
    loss_trade = {
        "symbol": "DOGE", "direction": "SHORT", "entry_price": 0.12,
        "exit_price": 0.15, "position_size": 1000.0, "confidence": 0.40,
        "hexagram": {}, "addon_count": 3, "hold_hours": 38.0,
        "exit_reason": "Timeout exit", "pnl_usdt": -30.0, "pnl_pct": -0.25,
    }
    loss_review = reviewer.review(loss_trade)
    assert loss_review["assessment"] == "BAD"
    assert len(loss_review["lessons"]) > 0

    # Step 4: Get cognitive context
    ctx = reviewer.get_cognitive_context()
    assert ctx["total_reviews"] == 2
    assert ctx["total_pnl"] == 20.0  # 50 - 30
    assert isinstance(ctx["recent_lessons"], list)
    assert isinstance(ctx["confidence_adjustment"], float)

    # Step 5: Get symbol-specific context
    btc_ctx = reviewer.get_cognitive_context(symbol="BTC")
    assert isinstance(btc_ctx["symbol_lessons"], list)

    # Step 6: Verify node wrapper
    node = CognitiveReviewerNode()
    assert node.node_id == "COGNITIVE_REVIEW"
    assert node.chain == "E"

    state = new_state(cycle_id="phase5-integration")
    state.market = win_trade
    result = node.execute(state)
    assert result.success
    assert result.outputs["assessment"] in ("GOOD", "NEUTRAL", "BAD")
