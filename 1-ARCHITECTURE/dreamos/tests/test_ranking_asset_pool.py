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


@pytest.fixture(scope="module")
def decision_card():
    return _load(
        "1-ARCHITECTURE/dreamos/cli/ranking_decision_card.py", "ranking_decision_card_for_test"
    )


@pytest.fixture(scope="module")
def ranking_news():
    return _load("1-ARCHITECTURE/dreamos/cli/ranking_news.py", "ranking_news_for_test")


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


def test_score_symbol_skips_flat_quote(producer):
    # OKX 合成合约无成交时连续复制收盘价，不能当作真实行情进榜单
    assert producer.score_symbol("NG", _candles([3.366] * 60), None, {}) is None


def test_score_symbol_omits_zero_momentum_reason(producer):
    closes = [100.0] * 30 + [100.0 + i * 0.2 for i in range(1, 21)]
    scored = producer.score_symbol("USO", _candles(closes), None, {})
    assert scored is not None
    assert not any(reason.startswith("7日+0.0%") for reason in scored["reasons"])


def test_direction_signal_never_maps_buy_candidate_to_sell(ranking):
    assert ranking._direction_signal(0.43, "BUY") == "WEAK_BUY"
    assert ranking._direction_signal(0.88, "BUY") == "STRONG_BUY"
    assert ranking._direction_signal(0.3, "HOLD") == "NEUTRAL"
    assert ranking._direction_signal(0.43, "SELL") == "WEAK_SELL"
    assert ranking._direction_signal(0.88, "SELL") == "STRONG_SELL"


def test_normalize_take_profit_supports_dict_and_number(ranking):
    raw = [{"price": 81.5631, "pct": 0.5}, 87.4939, {"pct": 0.5}]
    assert ranking._normalize_take_profit(raw) == [81.5631, 87.4939]


def test_align_card_mirrors_levels_on_direction_conflict(ranking):
    decision = {"entry": {"price": 100.0}, "stopLoss": 110.0, "takeProfit": [88.0, 82.0]}

    ranking._align_card_to_direction(decision, "long", "short")

    assert decision["stopLoss"] == 90.0
    assert decision["takeProfit"] == [112.0, 118.0]
    assert decision["directionConflict"] is True


def test_align_card_keeps_levels_when_direction_matches(ranking):
    decision = {"entry": {"price": 100.0}, "stopLoss": 90.0, "takeProfit": [112.0]}

    ranking._align_card_to_direction(decision, "long", "long")

    assert decision["stopLoss"] == 90.0
    assert "directionConflict" not in decision


def test_resolve_direction_falls_back_to_long(decision_card):
    # BCRM2 不可用时不能生成与榜单多头相反的卡片
    assert decision_card._resolve_direction("neutral") == "long"
    assert decision_card._resolve_direction("") == "long"
    assert decision_card._resolve_direction("short") == "short"


def test_classify_impact_priority(ranking_news):
    assert ranking_news.classify_impact("某交易所被盗，资金安全受质疑") == "高"
    assert ranking_news.classify_impact("BTC 突破 10 万美元，创历史新高") == "中"
    assert ranking_news.classify_impact("某项目发布例行周报") == "低"
    assert ranking_news.classify_impact("例行周报", is_important=True) == "高"


def test_match_symbol_aliases(ranking_news):
    assert ranking_news.match_symbol_aliases("英伟达财报超预期") == ["NVDA"]
    assert ranking_news.match_symbol_aliases("黄金价格创历史新高") == ["XAU"]
    assert ranking_news.match_symbol_aliases("Meta 发布新模型") == ["META"]
    assert ranking_news.match_symbol_aliases("Uniswap 提案通过") == ["UNI"]
    assert ranking_news.match_symbol_aliases("metadata 字段更新") == []


def test_build_news_snapshot_ignores_ambiguous_commodity_ticker(ranking_news):
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    now = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
    recent = int((now - timedelta(hours=1)).timestamp() * 1000)

    def record(title, tickers):
        return SimpleNamespace(
            raw={"title": title, "publishTimestamp": recent, "tickers_hit": tickers},
            metrics={"od_source_id": 9, "od_is_important": "false"},
        )

    # CL 同时是高露洁的美股代码，不能仅凭 TICKER 命中就挂到大宗商品
    assert (
        "CL"
        not in ranking_news.build_snapshot([record("Colgate CL 宣布派息", ["CL"])], now=now)[
            "by_symbol"
        ]
    )
    # 通过中文品种别名命中才允许
    assert (
        "CL" in ranking_news.build_snapshot([record("WTI 原油价格上涨", [])], now=now)["by_symbol"]
    )


def test_build_news_snapshot_groups_filters_and_dedupes(ranking_news):
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    now = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
    recent = int((now - timedelta(hours=2)).timestamp() * 1000)
    stale = int((now - timedelta(hours=100)).timestamp() * 1000)

    def record(record_id, title, published_ms, tickers):
        return SimpleNamespace(
            raw={"title": title, "publishTimestamp": published_ms, "tickers_hit": tickers},
            metrics={"od_source_id": record_id, "od_is_important": "false"},
        )

    snapshot = ranking_news.build_snapshot(
        [
            record(1, "BTC 突破 10 万美元，创历史新高", recent, ["BTC"]),
            record(2, "某交易所被盗，SOL 受影响", recent, ["SOL"]),
            record(3, "100 小时前的旧闻", stale, ["BTC"]),
            record(1, "重复记录", recent, ["ETH"]),
        ],
        now=now,
    )

    assert sorted(snapshot["by_symbol"]) == ["BTC", "SOL"]
    assert len(snapshot["by_symbol"]["BTC"]) == 1
    assert snapshot["by_symbol"]["BTC"][0]["date"] == "11-16 10:00"
    assert snapshot["by_symbol"]["BTC"][0]["impact"] == "中"
    assert snapshot["by_symbol"]["SOL"][0]["impact"] == "高"


def test_attach_news_events_normalizes_symbol_and_caps(ranking):
    items = [{"symbol": "BTC-USDT-SWAP", "decisionCard": {"events": []}}]
    news = {"BTC": [{"date": "11-16 10:00", "name": f"新闻{i}", "impact": "低"} for i in range(5)]}

    ranking._attach_news_events(items, news)

    assert len(items[0]["decisionCard"]["events"]) == 3
    assert items[0]["decisionCard"]["events"][0]["name"] == "新闻0"


def test_crypto_filter_drops_unlisted_low_volume_and_small_cap(ranking):
    candidates = [
        {"symbol": "HEMI", "score": 0.9, "category": "crypto"},  # OKX 未上市
        {"symbol": "LOWVOL", "score": 0.8, "category": "crypto"},  # 成交额不足
        {"symbol": "SMALLCAP", "score": 0.7, "category": "crypto"},  # 市值不足
        {"symbol": "BTC", "score": 0.6, "category": "crypto"},
        {"symbol": "XAU", "score": 0.5, "category": "commodity"},  # 非加密不过滤
    ]
    snapshot = {
        "degraded": False,
        "markets": {
            "LOWVOL": {"last": 1.0, "quote_volume_usd": 1e5},
            "SMALLCAP": {"last": 1.0, "quote_volume_usd": 2e7},
            "BTC": {"last": 70000.0, "quote_volume_usd": 8e8},
        },
        "market_caps": {"SMALLCAP": 1e7},
    }

    kept = [c["symbol"] for c in ranking._filter_crypto_candidates(candidates, snapshot)]

    assert kept == ["BTC", "XAU"]


def test_crypto_filter_fail_open_when_degraded(ranking):
    candidates = [{"symbol": "HEMI", "score": 0.9, "category": "crypto"}]

    assert ranking._filter_crypto_candidates(candidates, {"degraded": True}) == candidates
    assert ranking._filter_crypto_candidates(candidates, {"markets": {}}) == candidates
