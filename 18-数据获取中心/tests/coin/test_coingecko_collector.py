"""CoinGeckoCollector 单元测试 — TDD 先红后绿。

覆盖 2 类路由 + 容错：
- coin_info：GET /api/v3/coins/{id} → market_cap / total_supply / circulating_supply / max_supply
- coin_chart：GET /api/v3/coins/{id}/market_chart?days=30 → 历史 prices / market_caps
- 429 限流 → 抛 RateLimitError
- 无效 coin_id / HTTP 非 200 → 返回空列表（fail-open）

CoinGecko 公共 API **无需 Key**（10-30 req/min），网络不通/限流时降级。
"""
import pytest

from data_center.core.contract import DataRecord
from data_center.core.errors import RateLimitError

COINGECKO_MOD = "data_center.collectors.coin.coingecko_collector.requests"


def _coin_info_resp():
    """模拟 GET /api/v3/coins/uniswap 响应。"""
    return {
        "id": "uniswap",
        "symbol": "uni",
        "name": "Uniswap",
        "market_data": {
            "current_price": {"usd": 7.5},
            "market_cap": {"usd": 7_500_000_000},
            "total_supply": 1_000_000_000,
            "circulating_supply": 600_000_000,
            "max_supply": 1_000_000_000,
        },
    }


def _coin_chart_resp():
    """模拟 GET /api/v3/coins/uniswap/market_chart?days=30 响应。"""
    return {
        "prices": [
            [1700000000000, 7.5],
            [1700086400000, 7.6],
            [1700172800000, 7.4],
        ],
        "market_caps": [
            [1700000000000, 7_500_000_000],
            [1700086400000, 7_600_000_000],
            [1700172800000, 7_400_000_000],
        ],
        "total_volumes": [
            [1700000000000, 500_000_000],
            [1700086400000, 480_000_000],
            [1700172800000, 520_000_000],
        ],
    }


class _Resp:
    def __init__(self, json_body, status_code=200, ok=True):
        self._json = json_body
        self.status_code = status_code
        self.ok = ok

    def json(self):
        return self._json


# ---------------------------------------------------------------------------
# 基础属性
# ---------------------------------------------------------------------------

def test_collector_importable():
    from data_center.collectors.coin.coingecko_collector import CoinGeckoCollector
    assert CoinGeckoCollector.source == "coingecko"
    assert CoinGeckoCollector.category == "coin"


def test_default_is_available_true_no_api_key_needed():
    from data_center.collectors.coin.coingecko_collector import CoinGeckoCollector
    # CoinGecko 公共 API 不需要 Key，默认可用
    assert CoinGeckoCollector().is_available() is True


# ---------------------------------------------------------------------------
# coin_info 路由
# ---------------------------------------------------------------------------

def test_coin_info_returns_market_data(mocker):
    """coin_info 路由返回 market_cap / total_supply / circulating_supply / max_supply。"""
    from data_center.collectors.coin.coingecko_collector import CoinGeckoCollector

    m = mocker.patch(COINGECKO_MOD)
    m.get.return_value = _Resp(_coin_info_resp())

    c = CoinGeckoCollector()
    recs = c.fetch({"route": "coin_info", "coin_id": "uniswap"})

    assert len(recs) == 1
    r = recs[0]
    assert isinstance(r, DataRecord)
    assert r.source == "coingecko"
    assert r.category == "coin"
    assert r.sub_category == "uniswap"
    # metrics 扁平 number/string
    assert r.metrics["coin_id"] == "uniswap"
    assert r.metrics["market_cap_usd"] == pytest.approx(7_500_000_000)
    assert r.metrics["total_supply"] == pytest.approx(1_000_000_000)
    assert r.metrics["circulating_supply"] == pytest.approx(600_000_000)
    assert r.metrics["max_supply"] == pytest.approx(1_000_000_000)
    assert r.metrics["current_price_usd"] == pytest.approx(7.5)
    # raw 保留原始 payload
    assert r.raw["url"] == "/api/v3/coins/uniswap"


def test_coin_info_missing_fields_default_zero(mocker):
    """market_data 部分字段缺失 → 默认 0.0，不抛异常。"""
    from data_center.collectors.coin.coingecko_collector import CoinGeckoCollector

    m = mocker.patch(COINGECKO_MOD)
    m.get.return_value = _Resp({
        "id": "bitcoin",
        "symbol": "btc",
        "name": "Bitcoin",
        "market_data": {
            "current_price": {"usd": 50000},
            # market_cap / total_supply 缺失
        },
    })

    c = CoinGeckoCollector()
    recs = c.fetch({"route": "coin_info", "coin_id": "bitcoin"})

    assert len(recs) == 1
    r = recs[0]
    assert r.metrics["current_price_usd"] == pytest.approx(50000)
    assert r.metrics["market_cap_usd"] == pytest.approx(0.0)
    assert r.metrics["total_supply"] == pytest.approx(0.0)


def test_coin_info_no_market_data_returns_empty(mocker):
    """coin_info 返回无 market_data 键 → 返回空列表。"""
    from data_center.collectors.coin.coingecko_collector import CoinGeckoCollector

    m = mocker.patch(COINGECKO_MOD)
    m.get.return_value = _Resp({"id": "uni", "symbol": "uni", "name": "Uniswap"})

    c = CoinGeckoCollector()
    recs = c.fetch({"route": "coin_info", "coin_id": "uni"})

    assert len(recs) == 0


# ---------------------------------------------------------------------------
# coin_chart 路由
# ---------------------------------------------------------------------------

def test_coin_chart_returns_price_history(mocker):
    """coin_chart 路由返回历史 prices / market_caps 时序列。"""
    from data_center.collectors.coin.coingecko_collector import CoinGeckoCollector

    m = mocker.patch(COINGECKO_MOD)
    m.get.return_value = _Resp(_coin_chart_resp())

    c = CoinGeckoCollector()
    recs = c.fetch({"route": "coin_chart", "coin_id": "uniswap", "days": 30})

    assert len(recs) == 1
    r = recs[0]
    assert isinstance(r, DataRecord)
    assert r.source == "coingecko"
    assert r.sub_category == "chart_uniswap"
    # metrics
    assert r.metrics["coin_id"] == "uniswap"
    assert r.metrics["days"] == 30
    assert r.metrics["points"] == 3
    # timeseries 包含 prices
    assert len(r.timeseries) == 3
    assert r.timeseries[0]["price"] == pytest.approx(7.5)
    assert r.timeseries[0]["market_cap"] == pytest.approx(7_500_000_000)
    # raw 保留完整请求 URL（含 query string 便于溯源）
    assert r.raw["url"] == "/api/v3/coins/uniswap/market_chart?days=30"


def test_coin_chart_empty_response_returns_empty(mocker):
    """coin_chart 返回空 prices → 返回空列表。"""
    from data_center.collectors.coin.coingecko_collector import CoinGeckoCollector

    m = mocker.patch(COINGECKO_MOD)
    m.get.return_value = _Resp({"prices": [], "market_caps": [], "total_volumes": []})

    c = CoinGeckoCollector()
    recs = c.fetch({"route": "coin_chart", "coin_id": "uniswap", "days": 30})

    assert len(recs) == 0


# ---------------------------------------------------------------------------
# 容错
# ---------------------------------------------------------------------------

def test_rate_limit_429_raises_rate_limit_error(mocker):
    """HTTP 429 → 抛 RateLimitError（由上层调度器退避）。"""
    from data_center.collectors.coin.coingecko_collector import CoinGeckoCollector

    m = mocker.patch(COINGECKO_MOD)
    m.get.return_value = _Resp(None, status_code=429, ok=False)

    c = CoinGeckoCollector()
    with pytest.raises(RateLimitError):
        c.fetch({"route": "coin_info", "coin_id": "uniswap"})


def test_invalid_coin_id_http_404_returns_empty(mocker):
    """无效 coin_id → HTTP 404 → fail-open 返回空列表。"""
    from data_center.collectors.coin.coingecko_collector import CoinGeckoCollector

    m = mocker.patch(COINGECKO_MOD)
    m.get.return_value = _Resp(None, status_code=404, ok=False)

    c = CoinGeckoCollector()
    recs = c.fetch({"route": "coin_info", "coin_id": "nonexistent-coin"})

    assert recs == []


def test_unknown_route_returns_empty(mocker):
    """未知路由 → 静默返回空列表，不触发网络。"""
    from data_center.collectors.coin.coingecko_collector import CoinGeckoCollector

    m = mocker.patch(COINGECKO_MOD)
    m.get.return_value = _Resp([])

    c = CoinGeckoCollector()
    recs = c.fetch({"route": "unknown_route", "coin_id": "bitcoin"})

    assert recs == []
    # 未知路由不应触发 HTTP 请求
    m.get.assert_not_called()


def test_missing_coin_id_returns_empty(mocker):
    """coin_info 路由但缺少 coin_id → 返回空列表。"""
    from data_center.collectors.coin.coingecko_collector import CoinGeckoCollector

    m = mocker.patch(COINGECKO_MOD)
    m.get.return_value = _Resp(_coin_info_resp())

    c = CoinGeckoCollector()
    recs = c.fetch({"route": "coin_info"})

    assert recs == []
    m.get.assert_not_called()
