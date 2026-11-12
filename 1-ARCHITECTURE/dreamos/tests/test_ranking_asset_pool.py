"""榜单多资产接入单测：品类映射 / 6+2+2 配额 / 多资产评分。"""

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load(relative_path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ranking():
    return _load("3.1-FRONTEND/scripts/trading_ranking.py", "trading_ranking_for_test")


@pytest.fixture(scope="module")
def producer():
    return _load("1-ARCHITECTURE/dreamos/cli/ranking_asset_pool.py", "ranking_asset_pool_for_test")


def test_symbol_category_mapping(ranking):
    assert ranking._symbol_category("BTC") == "crypto"
    assert ranking._symbol_category("BTC-USDT-SWAP") == "crypto"
    assert ranking._symbol_category("HEMI") == "crypto"
    assert ranking._symbol_category("XAU") == "commodity"
    assert ranking._symbol_category("CL") == "commodity"
    assert ranking._symbol_category("GC=F") == "commodity"
    assert ranking._symbol_category("NVDA") == "index"
    assert ranking._symbol_category("US500") == "index"
    assert ranking._symbol_category("SPY") == "index"


def test_select_top10_enforces_quota(ranking):
    crypto = [{"symbol": f"C{i}", "score": 0.9 - i * 0.01, "category": "crypto"} for i in range(12)]
    commodity = [
        {"symbol": f"M{i}", "score": 0.8 - i * 0.01, "category": "commodity"} for i in range(4)
    ]
    index = [{"symbol": f"I{i}", "score": 0.7 - i * 0.01, "category": "index"} for i in range(4)]

    selected = ranking._select_top10(crypto + commodity + index)

    assert len(selected) == 10
    counts = {"crypto": 0, "commodity": 0, "index": 0}
    for item in selected:
        counts[item["category"]] += 1
    assert counts == {"crypto": 6, "commodity": 2, "index": 2}
    assert selected[0]["symbol"] == "C0"
    assert {item["symbol"] for item in selected if item["category"] == "commodity"} == {"M0", "M1"}
    assert {item["symbol"] for item in selected if item["category"] == "index"} == {"I0", "I1"}


def test_select_top10_fills_when_category_missing(ranking):
    crypto = [{"symbol": f"C{i}", "score": 0.6 - i * 0.01, "category": "crypto"} for i in range(14)]
    selected = ranking._select_top10(crypto)

    assert len(selected) == 10
    assert all(item["category"] == "crypto" for item in selected)


def _candles(closes):
    return [[str(i * 86400000), "0", "0", "0", str(close)] for i, close in enumerate(closes)]


def test_score_symbol_uptrend_scores_higher_than_downtrend(producer):
    up = producer.score_symbol("XAU", _candles([100 + i for i in range(80)]), None, {})
    down = producer.score_symbol("XAU", _candles([200 - i for i in range(80)]), None, {})

    assert up is not None and down is not None
    assert up["score"] > down["score"]
    assert 0.0 <= up["score"] <= 1.0


def test_score_symbol_requires_enough_history(producer):
    assert producer.score_symbol("XAU", _candles([100] * 10), None, {}) is None
