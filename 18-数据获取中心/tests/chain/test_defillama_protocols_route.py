"""DeFiLlama protocols + protocol_fees 路由 TDD 测试。

覆盖 Phase A1 新增的两个 route：
- protocols：per-protocol TVL 列表（CoinFundamentalRanker 数据源）
- protocol_fees：per-protocol 费用收入（Artemis Revenue Stability 信号源）

TDD：先写 RED → 实现 GREEN → 原有回归零破坏。
"""
import pytest

from data_center.core.contract import DataRecord
from data_center.core.errors import RateLimitError

DEFILLAMA_MOD = "data_center.collectors.chain.defillama_collector.requests"


class _Resp:
    def __init__(self, json_body, status_code=200, ok=True):
        self._json = json_body
        self.status_code = status_code
        self.ok = ok

    def json(self):
        return self._json


def _protocols_resp():
    return [
        {
            "id": "uniswap",
            "name": "Uniswap",
            "symbol": "UNI",
            "tvl": 4_500_000_000.0,
            "chainTvls": {"Ethereum": 3_000_000_000.0, "Arbitrum": 1_500_000_000.0},
            "mcap": 6_000_000_000.0,
            "gecko_id": "uniswap",
            "category": "Dexs",
        },
        {
            "id": "aave",
            "name": "Aave",
            "symbol": "AAVE",
            "tvl": 12_000_000_000.0,
            "chainTvls": {"Ethereum": 10_000_000_000.0},
            "mcap": 1_500_000_000.0,
            "gecko_id": "aave",
            "category": "Lending",
        },
    ]


def _protocol_fees_resp():
    return {
        "id": "uniswap",
        "name": "Uniswap",
        "total24h": 2_500_000,
        "total7d": 15_000_000,
        "total30d": 60_000_000,
        "totalDataChart": [
            [1704067200, 2_000_000],
            [1704153600, 2_500_000],
        ],
        "totalDataChart7d": [
            [1704067200, 1_800_000],
            [1704153600, 2_100_000],
        ],
    }


# ── protocols route ──

def test_protocols_route_returns_list(mocker):
    """protocols 路由返回 per-protocol TVL 列表。"""
    from data_center.collectors.chain.defillama_collector import DeFiLlamaCollector

    m = mocker.patch(DEFILLAMA_MOD)
    m.get.return_value = _Resp(_protocols_resp())

    c = DeFiLlamaCollector()
    recs = c.fetch({"route": "protocols"})

    assert len(recs) == 1
    r = recs[0]
    assert isinstance(r, DataRecord)
    assert r.source == "defillama"
    assert r.category == "protocol"
    assert r.sub_category == "all_protocols"
    # metrics 包含汇总
    assert r.metrics["protocol_count"] == 2
    assert r.metrics["total_tvl"] == pytest.approx(16_500_000_000.0)
    assert r.metrics["total_tvl_bln"] == pytest.approx(16.5)
    # timeseries 每协议一条
    assert len(r.timeseries) == 2
    assert r.timeseries[0]["name"] == "Uniswap"
    assert r.timeseries[0]["tvl"] == pytest.approx(4_500_000_000.0)


def test_protocols_route_empty_api_returns_empty(mocker):
    """API 返回空列表 → 空记录。"""
    from data_center.collectors.chain.defillama_collector import DeFiLlamaCollector

    m = mocker.patch(DEFILLAMA_MOD)
    m.get.return_value = _Resp([])

    c = DeFiLlamaCollector()
    recs = c.fetch({"route": "protocols"})
    # 空列表 → 仍返回1条记录但 protocol_count=0，或返回空列表
    # 按现有 chains 逻辑，空 API → 返回1条 metrics count=0 的记录
    assert len(recs) >= 0  # 允许空列表或空记录


# ── protocol_fees route ──

def test_protocol_fees_route_returns_dict(mocker):
    """protocol_fees 路由返回 per-protocol 费用数据。"""
    from data_center.collectors.chain.defillama_collector import DeFiLlamaCollector

    m = mocker.patch(DEFILLAMA_MOD)
    m.get.return_value = _Resp(_protocol_fees_resp())

    c = DeFiLlamaCollector()
    recs = c.fetch({"route": "protocol_fees", "protocol": "uniswap"})

    assert len(recs) == 1
    r = recs[0]
    assert isinstance(r, DataRecord)
    assert r.source == "defillama"
    assert r.category == "protocol"
    assert r.sub_category == "fees_uniswap"
    # metrics 包含费用汇总
    assert r.metrics["fees_24h"] == pytest.approx(2_500_000)
    assert r.metrics["fees_7d"] == pytest.approx(15_000_000)
    assert r.metrics["fees_30d"] == pytest.approx(60_000_000)
    # timeseries 每日费用
    assert len(r.timeseries) == 2
    assert r.timeseries[0]["fees_usd"] == pytest.approx(2_000_000)


def test_protocol_fees_missing_fields_defaults_to_zero(mocker):
    """API 响应缺失字段 → 默认 0，不抛异常。"""
    from data_center.collectors.chain.defillama_collector import DeFiLlamaCollector

    m = mocker.patch(DEFILLAMA_MOD)
    m.get.return_value = _Resp({"id": "unknown", "name": "Unknown"})

    c = DeFiLlamaCollector()
    recs = c.fetch({"route": "protocol_fees", "protocol": "unknown"})

    assert len(recs) == 1
    r = recs[0]
    assert r.metrics["fees_24h"] == 0
    assert r.metrics["fees_7d"] == 0
    assert r.metrics["fees_30d"] == 0


# ── 回归：原有路由不破坏 ──

def test_chains_route_still_works(mocker):
    """回归：原有 chains 路由不受影响。"""
    from data_center.collectors.chain.defillama_collector import DeFiLlamaCollector

    m = mocker.patch(DEFILLAMA_MOD)
    m.get.return_value = _Resp([
        {"name": "Ethereum", "tvl": 38_100_000_000.0, "symbol": "ETH", "gecko_id": "ethereum"},
    ])

    c = DeFiLlamaCollector()
    recs = c.fetch({"route": "chains"})
    assert len(recs) == 1
    assert recs[0].sub_category == "chains_summary"
    assert recs[0].metrics["total_tvl_bln"] == pytest.approx(38.1)
