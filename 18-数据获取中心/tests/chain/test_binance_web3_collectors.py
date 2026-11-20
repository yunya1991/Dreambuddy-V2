"""币安 Web3 采集器测试 — TDD 先红后绿。

覆盖两个采集器：
- BinanceWeb3MarketCollector（source=binance_web3_market）
  route: rank / social_hype / memeinrank? / smart_money / narrative
- BinanceWeb3TokenCollector（source=binance_web3_token）
  route: watchlist / token

约束：
- 全部 fail-open：HTTP 异常 → 返回 []
- 数值字段统一从字符串解析为 float，None 字段不写入 metrics
- raw 必须瘦身（不能包含 chart1m~chart24h 等大字段）
"""

import pytest
from data_center.core.contract import DataRecord

MARKET_MOD = "data_center.collectors.chain.binance_web3_market_collector"
TOKEN_MOD = "data_center.collectors.chain.binance_web3_token_collector"


class _Resp:
    def __init__(self, json_body, status_code=200):
        self._json = json_body
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


# ---------------------------------------------------------------------------
# Market collector
# ---------------------------------------------------------------------------


def _rank_payload():
    return {
        "code": "000000",
        "success": True,
        "data": {
            "tokens": [
                {
                    "chainId": "56",
                    "contractAddress": "0xaaa",
                    "symbol": "CAKE",
                    "price": "2.51",
                    "marketCap": "770000000",
                    "volume24h": "98132691.5",
                    "liquidity": "13393863.1",
                    "holders": "1895532",
                    "holdersTop10Percent": "3.23",
                    "devHoldingPercent": "0.4",
                    "sniperHoldersPercent": "0.1",
                    "insiderHoldingPercent": "0.2",
                    "bundlesHoldingPercent": "0.05",
                    "newAddressHoldersPercent": "12.5",
                    "smartMoneyHoldingPercent": "0.01",
                    "kolHoldingPercent": "0.02",
                    "proHoldersPercent": "0.33",
                    "kycHolders": "19802",
                    "searchCount24h": "120",
                    "percentChange24h": "3.1",
                    "uniqueTrader24h": "4210",
                    "count24h": "39869",
                    "volume24hBuy": "50000000",
                    "volume24hSell": "48132691.5",
                    "launchTime": "1619167423000",
                    "links": "[]",
                    "chart1h": '{"p":{}}',
                    "chart24h": '{"p":{}}',
                    "auditInfo": {
                        "riskLevel": 1,
                        "riskNum": 2,
                        "cautionNum": 3,
                        "extra": {"buyTax": "0", "sellTax": "5"},
                    },
                    "alphaInfo": None,
                }
            ],
            "total": 1,
        },
    }


def _social_payload():
    return {
        "code": "000000",
        "data": {
            "leaderBoardList": [
                {
                    "metaInfo": {
                        "logo": "/x.png",
                        "symbol": "BTC",
                        "chainId": "56",
                        "contractAddress": "0xbbb",
                        "tokenAge": 1599043687000,
                        "decimals": 18,
                    },
                    "marketInfo": {"marketCap": 4031479084.05, "priceChange": -0.39},
                    "tagInfoList": {},
                    "socialHypeInfo": {
                        "socialHype": 5350078,
                        "socialHypeEn": 4892506,
                        "socialHypeCn": 457572,
                        "sentiment": "Negative",
                        "socialSummaryBrief": "BTC falls below 63k",
                        "socialSummaryBriefTranslated": "BTC 跌破 6.3 万",
                    },
                }
            ]
        },
    }


def _meme_payload():
    return {
        "code": "000000",
        "data": {
            "tokens": [
                {
                    "symbol": "PEPE",
                    "contractAddress": "0xccc",
                    "chainId": "56",
                    "rank": 3,
                    "score": "88.5",
                    "marketCap": "12000000",
                    "liquidity": "450000",
                    "volume": "900000",
                    "holders": 12000,
                    "kycHolders": 300,
                    "holdersTop10Percent": "21.4",
                    "bnUniqueHolders": 8000,
                    "volumeBn7d": "1200000",
                    "countBn7d": 4300,
                    "uniqueTraderBn": 2100,
                    "impression": 330000,
                    "alphaStatus": 1,
                    "metaInfo": {"name": "Pepe", "aiNarrativeFlag": 1},
                }
            ]
        },
    }


def _inflow_payload():
    return {
        "code": "000000",
        "data": [
            {
                "tokenName": "PancakeSwap",
                "symbol": "CAKE",
                "ca": "0xaaa",
                "price": "2.51",
                "priceChangeRate": "4.2",
                "marketCap": "770000000",
                "volume": "98132691.5",
                "liquidity": "13393863.1",
                "holders": "1895532",
                "holdersTop10Percent": "3.23",
                "count": "39869",
                "countBuy": "19850",
                "countSell": "20019",
                "inflow": 1523400.5,
                "traders": 42,
                "tokenRiskLevel": 1,
                "launchTime": 1619167423000,
            }
        ],
    }


def _topic_payload():
    return {
        "code": "000000",
        "data": [
            {
                "topicId": "fa0aff59-b017-47ec-9ce9-ed6272e7dd0f",
                "chainId": "56",
                "name": {"topicNameEn": "GTA6", "topicNameCn": "GTA6 预测"},
                "type": "Giants",
                "close": 0,
                "topicLink": "https://x.com/x/status/1",
                "createTime": 1795165950645,
                "topicNetInflow": "20014.14",
                "topicNetInflow1h": "1200.5",
                "topicNetInflowAth": "35000",
                "tokenSize": 6,
                "progress": "42",
                "aiSummary": {"summaryCn": "叙事摘要"},
                "tokenList": [
                    {
                        "symbol": "COGE",
                        "contractAddress": "0xddd",
                        "marketCap": "120000",
                        "netInflow": "8000",
                        "smartMoneyHolders": 4,
                        "kolHolders": 2,
                        "holders": 900,
                    }
                ],
            }
        ],
    }


def test_market_collector_importable():
    from data_center.collectors.chain.binance_web3_market_collector import (
        BinanceWeb3MarketCollector,
    )

    assert BinanceWeb3MarketCollector.source == "binance_web3_market"
    assert BinanceWeb3MarketCollector.category == "chain"
    assert BinanceWeb3MarketCollector().is_available() is True


def test_market_rank_parses_holder_structure_and_trims_raw(mocker):
    from data_center.collectors.chain.binance_web3_market_collector import (
        BinanceWeb3MarketCollector,
    )

    m = mocker.patch(f"{MARKET_MOD}.requests")
    m.post.return_value = _Resp(_rank_payload())
    mocker.patch(f"{MARKET_MOD}._RETRY_SLEEP_SEC", 0)

    recs = BinanceWeb3MarketCollector().fetch({"route": "rank", "chain_id": "56", "size": 1})

    assert len(recs) == 1
    r = recs[0]
    assert isinstance(r, DataRecord)
    assert r.sub_category == "web3_trending_cake_aaa"
    assert r.metrics["symbol"] == "CAKE"
    assert r.metrics["holders"] == pytest.approx(1895532)
    assert r.metrics["top10_holders_pct"] == pytest.approx(3.23)
    assert r.metrics["dev_holding_pct"] == pytest.approx(0.4)
    assert r.metrics["sniper_holding_pct"] == pytest.approx(0.1)
    assert r.metrics["insider_holding_pct"] == pytest.approx(0.2)
    assert r.metrics["bundler_holding_pct"] == pytest.approx(0.05)
    assert r.metrics["new_wallet_pct"] == pytest.approx(12.5)
    assert r.metrics["smart_money_pct"] == pytest.approx(0.01)
    assert r.metrics["kol_pct"] == pytest.approx(0.02)
    assert r.metrics["pro_pct"] == pytest.approx(0.33)
    assert r.metrics["kyc_holders"] == pytest.approx(19802)
    assert r.metrics["risk_level"] == pytest.approx(1)
    assert r.metrics["buy_tax"] == pytest.approx(0)
    assert r.metrics["sell_tax"] == pytest.approx(5)
    # raw 瘦身：不含 chart 字段
    assert "chart24h" not in r.raw
    assert r.raw["contractAddress"] == "0xaaa"
    # metrics 必须扁平（validate_record 已在校验中覆盖）


def test_market_rank_same_symbol_different_address_gets_unique_key(mocker):
    """同名不同合约必须产生不同 sub_category，否则整批会被质量门禁拦截。"""
    from data_center.collectors.chain.binance_web3_market_collector import (
        BinanceWeb3MarketCollector,
    )

    payload = _rank_payload()
    dup = dict(payload["data"]["tokens"][0])
    dup["contractAddress"] = "0xdeadbeef"
    payload["data"]["tokens"].append(dup)

    m = mocker.patch(f"{MARKET_MOD}.requests")
    m.post.return_value = _Resp(payload)

    recs = BinanceWeb3MarketCollector().fetch({"route": "rank", "chain_id": "56", "size": 2})
    subs = {r.sub_category for r in recs}
    assert len(recs) == 2
    assert len(subs) == 2
    assert "web3_trending_cake_aaa" in subs
    assert "web3_trending_cake_deadbeef" in subs


def test_market_social_hype_maps_sentiment_to_score(mocker):
    from data_center.collectors.chain.binance_web3_market_collector import (
        BinanceWeb3MarketCollector,
    )

    m = mocker.patch(f"{MARKET_MOD}.requests")
    m.get.return_value = _Resp(_social_payload())

    recs = BinanceWeb3MarketCollector().fetch({"route": "social_hype", "chain_id": "56"})

    assert len(recs) == 1
    r = recs[0]
    assert r.sub_category == "web3_social_hype_btc_bbb"
    assert r.metrics["social_hype"] == pytest.approx(5350078)
    assert r.metrics["sentiment_score"] == -1  # Negative
    assert r.metrics["market_cap"] == pytest.approx(4031479084.05)
    assert "跌破" in r.raw["social_summary_cn"]


def test_market_meme_rank_fields(mocker):
    from data_center.collectors.chain.binance_web3_market_collector import (
        BinanceWeb3MarketCollector,
    )

    m = mocker.patch(f"{MARKET_MOD}.requests")
    m.get.return_value = _Resp(_meme_payload())

    recs = BinanceWeb3MarketCollector().fetch({"route": "meme_rank", "chain_id": "56"})
    assert len(recs) == 1
    r = recs[0]
    assert r.sub_category == "web3_meme_rank_pepe_ccc"
    assert r.metrics["score"] == pytest.approx(88.5)
    assert r.metrics["rank"] == pytest.approx(3)
    assert r.metrics["impression"] == pytest.approx(330000)
    assert r.metrics["ai_narrative_flag"] == pytest.approx(1)


def test_market_smart_money_inflow(mocker):
    from data_center.collectors.chain.binance_web3_market_collector import (
        BinanceWeb3MarketCollector,
    )

    m = mocker.patch(f"{MARKET_MOD}.requests")
    m.post.return_value = _Resp(_inflow_payload())

    recs = BinanceWeb3MarketCollector().fetch({"route": "smart_money", "chain_id": "56"})
    assert len(recs) == 1
    r = recs[0]
    assert r.sub_category == "web3_smart_money_cake_aaa"
    assert r.metrics["inflow_usd"] == pytest.approx(1523400.5)
    assert r.metrics["smart_traders"] == pytest.approx(42)
    assert r.metrics["risk_level"] == pytest.approx(1)


def test_market_narrative_topic(mocker):
    from data_center.collectors.chain.binance_web3_market_collector import (
        BinanceWeb3MarketCollector,
    )

    m = mocker.patch(f"{MARKET_MOD}.requests")
    m.get.return_value = _Resp(_topic_payload())

    recs = BinanceWeb3MarketCollector().fetch(
        {"route": "narrative", "chain_id": "56", "rank_type": 30, "sort": 30}
    )
    assert len(recs) == 1
    r = recs[0]
    assert r.sub_category == "web3_narrative_fa0aff59"
    assert r.metrics["net_inflow_usd"] == pytest.approx(20014.14)
    assert r.metrics["net_inflow_1h_usd"] == pytest.approx(1200.5)
    assert r.metrics["token_size"] == pytest.approx(6)
    assert r.raw["name_cn"] == "GTA6 预测"
    assert r.raw["tokens"][0]["symbol"] == "COGE"


def test_market_fail_open_on_http_error(mocker):
    from data_center.collectors.chain.binance_web3_market_collector import (
        BinanceWeb3MarketCollector,
    )

    m = mocker.patch(f"{MARKET_MOD}.requests")
    m.get.side_effect = ConnectionError("boom")
    m.post.side_effect = ConnectionError("boom")
    mocker.patch(f"{MARKET_MOD}._RETRY_SLEEP_SEC", 0)

    assert BinanceWeb3MarketCollector().fetch({"route": "rank"}) == []
    assert BinanceWeb3MarketCollector().fetch({"route": "social_hype"}) == []


def test_market_retries_once_then_succeeds(mocker):
    from data_center.collectors.chain.binance_web3_market_collector import (
        BinanceWeb3MarketCollector,
    )

    m = mocker.patch(f"{MARKET_MOD}.requests")
    m.post.side_effect = [ConnectionError("ssl eof"), _Resp(_inflow_payload())]
    mocker.patch(f"{MARKET_MOD}._RETRY_SLEEP_SEC", 0)

    recs = BinanceWeb3MarketCollector().fetch({"route": "smart_money", "chain_id": "56"})
    assert len(recs) == 1


def test_market_unknown_route_returns_empty(mocker):
    from data_center.collectors.chain.binance_web3_market_collector import (
        BinanceWeb3MarketCollector,
    )

    mocker.patch(f"{MARKET_MOD}.requests")
    assert BinanceWeb3MarketCollector().fetch({"route": "nope"}) == []


# ---------------------------------------------------------------------------
# Token collector
# ---------------------------------------------------------------------------


def _dynamic_payload():
    return {
        "code": "000000",
        "data": {
            "price": "2.51",
            "marketCap": "770000000",
            "fdv": "780000000",
            "totalSupply": "350000000",
            "circulatingSupply": "349676272",
            "liquidity": "13393863.1",
            "holders": "1895532",
            "top10HoldersPercentage": "3.23",
            "kycHolderCount": "19802",
            "kolHolders": "349",
            "proHolders": "5455",
            "smartMoneyHolders": "9",
            "smartMoneyHoldingPercent": "0.01",
            "volume24h": "53803143",
            "volume24hBuy": "26880240",
            "volume24hSell": "26922902",
            "count24h": "39869",
            "percentChange24h": "0.01",
            "priceHigh24h": "2.6",
            "priceLow24h": "2.4",
            "launchTime": 1619167423000,
        },
    }


def _audit_payload():
    return {
        "code": "000000",
        "data": {
            "hasResult": True,
            "isSupported": True,
            "riskLevelEnum": "MEDIUM",
            "riskLevel": 3,
            "extraInfo": {"buyTax": "1", "sellTax": "2", "isVerified": True},
            "riskItems": [
                {
                    "id": "CONTRACT_RISK",
                    "details": [
                        {"title": "Honeypot Risk Not Found", "isHit": False, "riskType": "RISK"},
                        {"title": "Freezable", "isHit": True, "riskType": "CAUTION"},
                    ],
                },
                {
                    "id": "SCAM_RISK",
                    "details": [
                        {"title": "Fake token", "isHit": True, "riskType": "RISK"},
                    ],
                },
            ],
        },
    }


def test_token_collector_importable():
    from data_center.collectors.chain.binance_web3_token_collector import (
        BinanceWeb3TokenCollector,
    )

    assert BinanceWeb3TokenCollector.source == "binance_web3_token"
    assert BinanceWeb3TokenCollector.category == "chain"


def test_token_explicit_route_emits_profile_and_audit(mocker):
    from data_center.collectors.chain.binance_web3_token_collector import (
        BinanceWeb3TokenCollector,
    )

    m = mocker.patch(f"{TOKEN_MOD}.requests")
    m.get.return_value = _Resp(_dynamic_payload())
    m.post.return_value = _Resp(_audit_payload())

    recs = BinanceWeb3TokenCollector().fetch(
        {
            "route": "token",
            "tokens": [{"chain_id": "56", "contract_address": "0xaaa", "symbol": "CAKE"}],
        }
    )
    by_sub = {r.sub_category: r for r in recs}
    assert set(by_sub) == {"web3_token_profile_cake_aaa", "web3_token_audit_cake_aaa"}

    prof = by_sub["web3_token_profile_cake_aaa"]
    assert prof.metrics["holders"] == pytest.approx(1895532)
    assert prof.metrics["fdv"] == pytest.approx(780000000)
    assert prof.metrics["kol_holders"] == pytest.approx(349)
    assert prof.metrics["pro_holders"] == pytest.approx(5455)
    assert prof.metrics["smart_money_holders"] == pytest.approx(9)

    aud = by_sub["web3_token_audit_cake_aaa"]
    assert aud.metrics["risk_level"] == pytest.approx(3)
    assert aud.metrics["buy_tax"] == pytest.approx(1)
    assert aud.metrics["sell_tax"] == pytest.approx(2)
    assert aud.metrics["is_verified"] == pytest.approx(1)
    assert aud.metrics["risk_hits"] == pytest.approx(1)  # 仅 isHit=True 的 RISK 项
    assert aud.metrics["caution_hits"] == pytest.approx(1)


def test_token_audit_skips_numbers_when_unsupported(mocker):
    from data_center.collectors.chain.binance_web3_token_collector import (
        BinanceWeb3TokenCollector,
    )

    m = mocker.patch(f"{TOKEN_MOD}.requests")
    m.get.return_value = _Resp(_dynamic_payload())
    m.post.return_value = _Resp(
        {
            "code": "000000",
            "data": {
                "hasResult": False,
                "isSupported": False,
                "riskLevelEnum": None,
                "riskLevel": None,
                "extraInfo": {},
                "riskItems": [],
            },
        }
    )

    recs = BinanceWeb3TokenCollector().fetch(
        {
            "route": "token",
            "tokens": [{"chain_id": "56", "contract_address": "0xaaa", "symbol": "CAKE"}],
        }
    )
    aud = next(r for r in recs if r.sub_category == "web3_token_audit_cake_aaa")
    assert "risk_level" not in aud.metrics
    assert aud.metrics["has_result"] == 0
    assert aud.metrics["is_supported"] == 0


def test_token_watchlist_derives_from_rank(mocker):
    from data_center.collectors.chain.binance_web3_token_collector import (
        BinanceWeb3TokenCollector,
    )

    m = mocker.patch(f"{TOKEN_MOD}.requests")
    m.post.side_effect = [
        _Resp(_rank_payload()),  # 第一次：trending 榜单
        _Resp(_audit_payload()),  # 第二次：CAKE 审计
    ]
    m.get.return_value = _Resp(_dynamic_payload())

    recs = BinanceWeb3TokenCollector().fetch({"route": "watchlist", "chain_id": "56", "limit": 5})
    subs = {r.sub_category for r in recs}
    assert "web3_token_profile_cake_aaa" in subs
    assert "web3_token_audit_cake_aaa" in subs


def test_token_fail_open(mocker):
    from data_center.collectors.chain.binance_web3_token_collector import (
        BinanceWeb3TokenCollector,
    )

    m = mocker.patch(f"{TOKEN_MOD}.requests")
    m.get.side_effect = TimeoutError("timeout")
    m.post.side_effect = TimeoutError("timeout")
    mocker.patch(f"{TOKEN_MOD}._RETRY_SLEEP_SEC", 0)

    assert BinanceWeb3TokenCollector().fetch({"route": "watchlist", "limit": 2}) == []
    assert (
        BinanceWeb3TokenCollector().fetch(
            {"route": "token", "tokens": [{"chain_id": "56", "contract_address": "0xaaa"}]}
        )
        == []
    )


# ---------------------------------------------------------------------------
# 注册 / 调度
# ---------------------------------------------------------------------------


def test_dispatcher_registers_binance_web3_collectors():
    from data_center.core.dispatcher import DataCenter

    collectors = set(DataCenter().list_collectors())
    assert ("chain", "binance_web3_market") in collectors
    assert ("chain", "binance_web3_token") in collectors


def test_scheduler_includes_binance_web3_tasks():
    from data_center.scheduler import CollectionScheduler

    tasks = CollectionScheduler.default_tasks()
    names = {t.name for t in tasks}
    for name in (
        "binance_web3_rank",
        "binance_web3_social",
        "binance_web3_meme",
        "binance_web3_smart_money",
        "binance_web3_narrative",
        "binance_web3_token_watchlist",
    ):
        assert name in names, f"缺少任务: {name}"
