"""币安 Web3 跨币聚合器测试。

被聚合的原始数据是「榜单快照」：成员每轮变化、逐币记录有数百条，
不能直接当因子（symbol 对齐会造出假因子）。聚合器把它们压成一条
sub_category=web3_market 的横截面指标，供 19-DAL mm_metrics 消费。

约束：
- 只用中位数 / 比率，不用 sum（榜单成员变化会让 sum 跳变）
- 代币化股票（alpha 榜 xxxon，raw.stockCompanyName 非空）只计数，不进热度聚合
- 全部 fail-open：无数据 → 返回 []
"""

import pytest
from data_center.core.contract import DataRecord

MOD = "data_center.collectors.chain.binance_web3_aggregator"


def _rec(sub, metrics, raw=None):
    return DataRecord(
        source="binance_web3_market",
        category="chain",
        sub_category=sub,
        timestamp="2026-11-20T10:00:00+08:00",
        metrics=metrics,
        events=[],
        timeseries=[],
        raw=raw or {},
    )


def _groups():
    return {
        "trending": [
            _rec(
                "web3_trending_aaa_11111111",
                {
                    "new_wallet_pct": 4.0,
                    "top10_holders_pct": 40.0,
                    "dev_holding_pct": 0.4,
                    "sniper_holding_pct": 0.1,
                    "bundler_holding_pct": 0.2,
                    "risk_level": 1.0,
                    "liquidity": 1_000_000.0,
                    "volume_24h_buy": 300.0,
                    "volume_24h_sell": 100.0,
                },
            ),
            _rec(
                "web3_trending_bbb_22222222",
                {
                    "new_wallet_pct": 8.0,
                    "top10_holders_pct": 60.0,
                    "dev_holding_pct": 1.6,
                    "risk_level": 2.5,
                    "liquidity": 3_000_000.0,
                    "volume_24h_buy": 100.0,
                    "volume_24h_sell": 300.0,
                },
            ),
        ],
        "top_search": [
            _rec(
                "web3_top_search_ccc_33333333",
                {
                    "new_wallet_pct": 12.0,
                    "top10_holders_pct": 80.0,
                    "risk_level": 0.0,
                    "liquidity": 5_000_000.0,
                },
            )
        ],
        "social": [
            _rec("web3_social_hype_aaa_11111111", {"social_hype": 100.0, "sentiment_score": 1.0}),
            _rec("web3_social_hype_bbb_22222222", {"social_hype": 300.0, "sentiment_score": -1.0}),
        ],
        "smart": [
            _rec("web3_smart_money_aaa_11111111", {"inflow_usd": 5000.0, "smart_traders": 7.0}),
            _rec("web3_smart_money_bbb_22222222", {"inflow_usd": -1000.0, "smart_traders": 3.0}),
        ],
        "meme": [
            _rec("web3_meme_rank_aaa_11111111", {"score": 80.0, "ai_narrative_flag": 1.0}),
            _rec("web3_meme_rank_bbb_22222222", {"score": 40.0, "ai_narrative_flag": 0.0}),
        ],
        "narrative": [
            _rec("web3_narrative_11111111", {"net_inflow_usd": 20000.0}),
            _rec("web3_narrative_22222222", {"net_inflow_usd": 5000.0}),
        ],
        "alpha": [
            _rec("web3_alpha_nvdaon_aaaa1111", {"risk_level": 0.0}, {"stockCompanyName": "NVIDIA"}),
            _rec("web3_alpha_crypto1_bbbb2222", {"risk_level": 1.0}, {}),
        ],
    }


def test_aggregate_uses_medians_not_sums():
    from data_center.collectors.chain.binance_web3_aggregator import aggregate_web3_metrics

    m = aggregate_web3_metrics(_groups())

    # 结构榜 = trending + top_search 共 3 条
    assert m["web3_structure_count"] == 3.0
    assert m["web3_new_wallet_pct_med"] == 8.0
    assert m["web3_top10_conc_med"] == 60.0
    assert m["web3_liquidity_med"] == 3_000_000.0
    # dev 只有 2 条有值 → 中位数 1.0
    assert m["web3_dev_holding_pct_med"] == pytest.approx(1.0)
    # sniper+bundler 逐币求和后取中位数（只有 1 条有值 → 0.3）
    assert m["web3_sniper_bundler_pct_med"] == pytest.approx(0.3)


def test_buy_sell_ratio_and_risk_ratio():
    from data_center.collectors.chain.binance_web3_aggregator import aggregate_web3_metrics

    m = aggregate_web3_metrics(_groups())

    # Σbuy=400, Σsell=400
    assert m["web3_buy_sell_vol_ratio"] == pytest.approx(1.0)
    # risk_level 观测值域 0/1/2.5，>=2.5 记高风险 → 1/3
    assert m["web3_risk_level_med"] == pytest.approx(1.0)
    assert m["web3_high_risk_ratio"] == pytest.approx(1 / 3)


def test_cross_route_metrics():
    from data_center.collectors.chain.binance_web3_aggregator import aggregate_web3_metrics

    m = aggregate_web3_metrics(_groups())

    assert m["web3_hype_med"] == 200.0
    assert m["web3_sentiment_mean"] == pytest.approx(0.0)
    assert m["web3_smart_money_net_inflow_usd"] == pytest.approx(4000.0)
    assert m["web3_smart_traders"] == pytest.approx(10.0)
    assert m["web3_meme_score_med"] == pytest.approx(60.0)
    assert m["web3_ai_narrative_ratio"] == pytest.approx(0.5)
    assert m["web3_narrative_net_inflow_med"] == pytest.approx(12500.0)


def test_tokenized_stock_excluded_from_heat():
    from data_center.collectors.chain.binance_web3_aggregator import aggregate_web3_metrics

    m = aggregate_web3_metrics(_groups())

    assert m["web3_alpha_stock_count"] == 1.0
    # 代币化股票不进结构榜热度聚合
    assert m["web3_structure_count"] == 3.0


def test_empty_groups_returns_empty_metrics():
    from data_center.collectors.chain.binance_web3_aggregator import aggregate_web3_metrics

    assert aggregate_web3_metrics({}) == {}
    assert aggregate_web3_metrics({"trending": [], "social": []}) == {}


def test_fetch_emits_single_market_record(monkeypatch):
    from data_center.collectors.chain import binance_web3_aggregator as agg

    monkeypatch.setattr(agg.BinanceWeb3MarketCollector, "_fetch_rank", lambda self, *a, **k: [])
    monkeypatch.setattr(
        agg.BinanceWeb3MarketCollector, "_fetch_social_hype", lambda self, *a, **k: []
    )
    monkeypatch.setattr(
        agg.BinanceWeb3MarketCollector, "_fetch_smart_money", lambda self, *a, **k: []
    )
    monkeypatch.setattr(
        agg.BinanceWeb3MarketCollector, "_fetch_meme_rank", lambda self, *a, **k: []
    )
    monkeypatch.setattr(
        agg.BinanceWeb3MarketCollector, "_fetch_narrative", lambda self, *a, **k: []
    )
    assert agg.BinanceWeb3MarketAggregator().fetch({}) == []


def test_fetch_record_shape(monkeypatch):
    from data_center.collectors.chain import binance_web3_aggregator as agg

    groups = _groups()
    monkeypatch.setattr(
        agg.BinanceWeb3MarketCollector,
        "_fetch_rank",
        lambda self, c, rt, s, ts: groups.get(
            {10: "trending", 11: "top_search", 20: "alpha"}[rt], []
        ),
    )
    monkeypatch.setattr(
        agg.BinanceWeb3MarketCollector, "_fetch_social_hype", lambda self, c, ts: groups["social"]
    )
    monkeypatch.setattr(
        agg.BinanceWeb3MarketCollector,
        "_fetch_smart_money",
        lambda self, c, p, ts: groups["smart"],
    )
    monkeypatch.setattr(
        agg.BinanceWeb3MarketCollector, "_fetch_meme_rank", lambda self, c, ts: groups["meme"]
    )
    monkeypatch.setattr(
        agg.BinanceWeb3MarketCollector,
        "_fetch_narrative",
        lambda self, c, rt, s, ts: groups["narrative"],
    )

    recs = agg.BinanceWeb3MarketAggregator().fetch({"chain_id": "56"})

    assert len(recs) == 1
    rec = recs[0]
    assert rec.source == "binance_web3_agg"
    assert rec.category == "chain"
    assert rec.sub_category == "web3_market"
    assert rec.metrics["web3_structure_count"] == 3.0
    assert rec.raw["counts"]["trending"] == 2
