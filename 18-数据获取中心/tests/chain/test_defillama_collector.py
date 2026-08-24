"""DeFiLlamaCollector 单元测试 — TDD 先红后绿。

覆盖 3 类路由：
- chains：所有链的 TVL + stablecoin mcap 汇总（D7/D8）
- historicalChainTvl：单链历史 TVL（D8 的时序）
- summary/fees：手续费（可选，给 D9 交叉验证留接口）

DeFiLlama 公共 API **无需 Key**，网络不通时降级返回空列表。
"""
import pytest

from data_center.core.contract import DataRecord
from data_center.core.errors import RateLimitError

DEFILLAMA_MOD = "data_center.collectors.chain.defillama_collector.requests"


def _chains_resp():
    return [
        {
            "gecko_id": "ethereum", "name": "Ethereum", "symbol": "ETH",
            "tvl": 38_100_000_000.0,
            "tokenSymbol": "ETH",
            "cmcId": "1027",
            "chainId": "1",
        },
        {
            "gecko_id": "tron", "name": "TRON", "symbol": "TRX",
            "tvl": 6_200_000_000.0,
            "tokenSymbol": "TRX",
            "cmcId": "1958",
            "chainId": "tron",
        },
    ]


class _Resp:
    def __init__(self, json_body, status_code=200, ok=True):
        self._json = json_body
        self.status_code = status_code
        self.ok = ok

    def json(self):
        return self._json


def test_collector_importable():
    from data_center.collectors.chain.defillama_collector import DeFiLlamaCollector
    assert DeFiLlamaCollector.source == "defillama"
    assert DeFiLlamaCollector.category == "chain"


def test_default_is_available_true_no_api_key_needed():
    from data_center.collectors.chain.defillama_collector import DeFiLlamaCollector
    # DeFiLlama 公共 API 不需要 Key，默认可用
    assert DeFiLlamaCollector().is_available() is True


def test_fetch_chains_route_sums_tvl_and_stablecoins(mocker):
    from data_center.collectors.chain.defillama_collector import DeFiLlamaCollector

    m = mocker.patch(DEFILLAMA_MOD)
    m.get.return_value = _Resp(_chains_resp())

    c = DeFiLlamaCollector()
    recs = c.fetch({"route": "chains"})

    assert len(recs) == 1
    r = recs[0]
    assert isinstance(r, DataRecord)
    assert r.source == "defillama"
    assert r.sub_category == "chains_summary"
    # 总 TVL 汇总
    assert r.metrics["total_tvl_bln"] == pytest.approx(44.3)  # 38.1+6.2
    assert "Ethereum" in r.raw["chains"]  # 嵌套明细放 raw，metrics 扁平
    assert r.raw["chains"]["Ethereum"]["tvl_bln"] == pytest.approx(38.1)
    # timeseries: 每条链一条
    assert len(r.timeseries) >= 2


def test_fetch_historical_chain_tvl_route(mocker):
    from data_center.collectors.chain.defillama_collector import DeFiLlamaCollector

    m = mocker.patch(DEFILLAMA_MOD)
    m.get.return_value = _Resp([
        {"date": 1704067200, "tvl": 38_000_000_000.0},
        {"date": 1704153600, "tvl": 38_100_000_000.0},
    ])

    c = DeFiLlamaCollector()
    recs = c.fetch({"route": "historicalChainTvl", "chain": "Ethereum"})

    assert len(recs) == 1
    r = recs[0]
    assert r.sub_category == "historical_tvl_Ethereum"
    assert r.metrics["latest_tvl_bln"] == pytest.approx(38.1)
    assert len(r.timeseries) == 2
    assert r.timeseries[0]["tvl_bln"] == pytest.approx(38.0)


def test_fetch_unknown_route_empty(mocker):
    from data_center.collectors.chain.defillama_collector import DeFiLlamaCollector

    m = mocker.patch(DEFILLAMA_MOD)
    c = DeFiLlamaCollector()
    # 未知路由不发 HTTP，直接返回空
    assert c.fetch({"route": "nonexistent"}) == []
    m.get.assert_not_called()


def test_network_error_degrades_empty(mocker):
    from data_center.collectors.chain.defillama_collector import DeFiLlamaCollector

    m = mocker.patch(DEFILLAMA_MOD)
    m.get.side_effect = Exception("Connection refused")

    c = DeFiLlamaCollector()
    # fail-open：网络异常返回空列表，不抛异常
    assert c.fetch({"route": "chains"}) == []


def test_429_raises_rate_limit(mocker):
    from data_center.collectors.chain.defillama_collector import DeFiLlamaCollector

    m = mocker.patch(DEFILLAMA_MOD)
    m.get.return_value = _Resp({}, status_code=429, ok=False)

    c = DeFiLlamaCollector()
    with pytest.raises(RateLimitError):
        c.fetch({"route": "chains"})


def test_fees_summary_route(mocker):
    from data_center.collectors.chain.defillama_collector import DeFiLlamaCollector

    m = mocker.patch(DEFILLAMA_MOD)
    # summary/fees 返回 dailyFees 列表
    m.get.return_value = _Resp({
        "total24h": 1_200_000,
        "totalDataChart": [
            [1704067200, 800_000],
            [1704153600, 1_200_000],
        ],
    })

    c = DeFiLlamaCollector()
    recs = c.fetch({"route": "fees", "chain": "Ethereum"})
    assert len(recs) == 1
    r = recs[0]
    assert r.sub_category == "fees_Ethereum"
    assert r.metrics["fees_24h_usd"] == 1_200_000
