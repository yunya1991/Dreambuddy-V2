"""SPEC-54d：卡片模式动态推荐（价格信号回测打分）验收。"""

from __future__ import annotations

import importlib.util
import os
import sys

import pytest

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_L1 = os.path.join(_REPO, "54-L1架构能力聚合层")
if _L1 not in sys.path:
    sys.path.insert(0, _L1)

_spec = importlib.util.spec_from_file_location(
    "card_recommender", os.path.join(_L1, "scripts", "card_recommender.py")
)
card_recommender = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(card_recommender)

_DB_READY = os.path.exists(card_recommender.DB_PATH)
_needs_db = pytest.mark.skipif(not _DB_READY, reason="dreambuddy_core.db 不存在")

ALLOWED = {
    "D-E15",
    "D-G08",
    "D-E01",
    "D-E02",
    "D-E07",
    "D-E10",
    "D-E14",
    "D-G20",
}


def test_rules_are_price_based_and_deterministic():
    prices = [100.0 + i * 0.4 for i in range(400)]
    for rule in (
        "close_above_ema26",
        "momentum_12_1_positive",
        "momentum_20_positive",
        "price_percentile_high",
        "up_state_persistence",
        "drawdown_rebound",
        "momentum_top_quintile",
    ):
        signals = card_recommender._rule_signals(rule, prices)
        assert len(signals) == len(prices)
        assert any(signal is not None for signal in signals), rule
        assert signals == card_recommender._rule_signals(rule, prices)


def test_wilson_bounds_and_backtest_counts():
    assert card_recommender._wilson(0, 0) == 0.0
    lower = card_recommender._wilson(55, 100)
    assert 0.4 < lower < 0.55
    assert card_recommender._wilson(100, 100) > 0.9

    prices = [100.0 * (1.002**i) for i in range(400)]
    stats = card_recommender._backtest_symbol(prices, "momentum_20_positive")
    assert stats["n_20d"] > 300
    assert stats["win_rate_20d"] > 0.9


def test_high_corr_state_aligns_dates():
    prices = [100.0 + i for i in range(300)]
    bench = [50.0 + i for i in range(300)]
    stats = card_recommender._backtest_symbol(prices, "high_corr_state", bench)
    assert stats["n_20d"] > 200


@_needs_db
def test_recommend_returns_6_to_8_price_cards():
    payload = card_recommender.recommend(days=750)
    cards = payload["cards"]
    assert 6 <= len(cards) <= 8
    assert {card["capability_id"] for card in cards} <= ALLOWED
    scores = [card["score"] for card in cards]
    assert scores == sorted(scores, reverse=True)
    for card in cards:
        assert card["n_20d"] >= card_recommender.MIN_N
        assert 0.0 <= (card["win_rate_20d"] or 0.0) <= 1.0
        assert card["args"].get("symbol") == "BTC"


@_needs_db
def test_dry_run_does_not_write(tmp_path):
    out = tmp_path / "recommendation.json"
    code = card_recommender.main(["--days", "750", "--out", str(out), "--dry-run", "--json"])
    assert code == 0
    assert not out.exists()
