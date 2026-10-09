"""CoinMarketCalCollector 测试 — 加密技术升级事件采集。

SPEC-Phase2 §6.1:
  - CoinMarketCal RESTful API
  - 事件类型映射: Hard Fork/Soft Fork/Mainnet Launch/Protocol Upgrade/Listing/Delisting → tech_upgrade
  - direction 动态判定: 价格趋势 + 社区情绪(percentage) + 子类型语义，阈值 ±0.3
  - FAIL-OPEN: API 失败返回空列表

RED 阶段：CoinMarketCalCollector 类尚未实现，测试应因 ImportError 失败。
"""
import pytest

from data_center.core.contract import DataRecord

CMC_MOD = "data_center.collectors.macro.coinmarketcal_collector"


@pytest.fixture
def collector():
    from data_center.collectors.macro.coinmarketcal_collector import CoinMarketCalCollector
    return CoinMarketCalCollector()


# ---------- 基础属性 ----------

def test_source_category(collector):
    assert collector.source == "coinmarketcal"
    assert collector.category == "protocol"


# ---------- API 响应解析 ----------

def test_fetch_parses_api_response(collector, mocker):
    """解析 API JSON 响应，构造 DataRecord。"""
    mock_api = mocker.patch(f"{CMC_MOD}.CoinMarketCalCollector._fetch_api")
    mock_api.return_value = [
        {
            "title": "Ethereum Dencun Upgrade",
            "coin": {"symbol": "ETH"},
            "date_event": "2026-10-15T00:00:00Z",
            "category": "Protocol Upgrade",
            "percentage": 75.0,
            "source": "official",
            "proof": "confirmed",
        }
    ]

    recs = collector.fetch({"days_ahead": 7})

    assert len(recs) == 1
    r = recs[0]
    assert isinstance(r, DataRecord)
    assert r.source == "coinmarketcal"
    assert r.category == "protocol"
    assert r.sub_category == "tech_upgrade"
    assert r.metrics["event_type"] == "tech_upgrade"


# ---------- 事件类型映射 ----------

def test_event_type_mapping_hard_fork(collector, mocker):
    """Hard Fork → tech_upgrade。"""
    mocker.patch(f"{CMC_MOD}.CoinMarketCalCollector._fetch_api", return_value=[
        {"title": "BTC Taproot", "coin": {"symbol": "BTC"},
         "date_event": "2026-10-20", "category": "Hard Fork",
         "percentage": 60.0, "source": "official", "proof": "confirmed"}
    ])
    recs = collector.fetch({"days_ahead": 7})
    assert recs[0].metrics["event_type"] == "tech_upgrade"


def test_event_type_mapping_listing(collector, mocker):
    """Exchange Listing → tech_upgrade。"""
    mocker.patch(f"{CMC_MOD}.CoinMarketCalCollector._fetch_api", return_value=[
        {"title": "SOL listed on Binance", "coin": {"symbol": "SOL"},
         "date_event": "2026-10-12", "category": "Exchange Listing",
         "percentage": 80.0, "source": "official", "proof": "confirmed"}
    ])
    recs = collector.fetch({"days_ahead": 7})
    assert recs[0].metrics["event_type"] == "tech_upgrade"


def test_event_type_mapping_other_filtered(collector, mocker):
    """非 tech_upgrade 类型（如 AMA）被过滤，不返回 DataRecord。"""
    mocker.patch(f"{CMC_MOD}.CoinMarketCalCollector._fetch_api", return_value=[
        {"title": "Project AMA", "coin": {"symbol": "XXX"},
         "date_event": "2026-10-12", "category": "AMA",
         "percentage": 50.0, "source": "community", "proof": "unconfirmed"}
    ])
    recs = collector.fetch({"days_ahead": 7})
    assert recs == []


# ---------- direction 动态判定 ----------

def test_direction_long_listing_with_uptrend(collector, mocker):
    """listing + 价格上涨趋势 + 高社区情绪 → direction=long。"""
    mocker.patch(f"{CMC_MOD}.CoinMarketCalCollector._fetch_api", return_value=[
        {"title": "ETH Listing", "coin": {"symbol": "ETH"},
         "date_event": "2026-10-12", "category": "Exchange Listing",
         "percentage": 80.0, "source": "official", "proof": "confirmed"}
    ])
    # price_trend > 0 表示上涨
    recs = collector.fetch({"days_ahead": 7, "price_trend": 0.05})
    assert recs[0].metrics["direction"] == "long"


def test_direction_short_delisting_with_downtrend(collector, mocker):
    """delisting + 价格下跌趋势 → direction=short。"""
    mocker.patch(f"{CMC_MOD}.CoinMarketCalCollector._fetch_api", return_value=[
        {"title": "XXX Delisting", "coin": {"symbol": "XXX"},
         "date_event": "2026-10-12", "category": "Exchange Delisting",
         "percentage": 20.0, "source": "official", "proof": "confirmed"}
    ])
    recs = collector.fetch({"days_ahead": 7, "price_trend": -0.05})
    assert recs[0].metrics["direction"] == "short"


def test_direction_neutral_when_weak_signals(collector, mocker):
    """加权和在 [-0.3, 0.3] 区间 → direction=neutral。"""
    mocker.patch(f"{CMC_MOD}.CoinMarketCalCollector._fetch_api", return_value=[
        {"title": "Protocol Upgrade", "coin": {"symbol": "ETH"},
         "date_event": "2026-10-12", "category": "Protocol Upgrade",
         "percentage": 50.0, "source": "official", "proof": "confirmed"}
    ])
    # 无 price_trend，percentage=50% 中性
    recs = collector.fetch({"days_ahead": 7})
    assert recs[0].metrics["direction"] == "neutral"


# ---------- FAIL-OPEN ----------

def test_fail_open_api_error(collector, mocker):
    """_fetch_api 抛异常 → 返回空列表，不抛异常。"""
    mocker.patch(
        f"{CMC_MOD}.CoinMarketCalCollector._fetch_api",
        side_effect=Exception("API timeout"),
    )
    recs = collector.fetch({"days_ahead": 7})
    assert recs == []


def test_fail_open_empty_response(collector, mocker):
    """_fetch_api 返回空 → 返回空列表。"""
    mocker.patch(f"{CMC_MOD}.CoinMarketCalCollector._fetch_api", return_value=[])
    recs = collector.fetch({"days_ahead": 7})
    assert recs == []


# ---------- DataRecord 契约 ----------

def test_datarecord_contract_valid(collector, mocker):
    """返回的 DataRecord 能通过 validate_record 契约校验。"""
    from data_center.core.contract import validate_record

    mocker.patch(f"{CMC_MOD}.CoinMarketCalCollector._fetch_api", return_value=[
        {"title": "Ethereum Upgrade", "coin": {"symbol": "ETH"},
         "date_event": "2026-10-15", "category": "Protocol Upgrade",
         "percentage": 70.0, "source": "official", "proof": "confirmed"}
    ])
    recs = collector.fetch({"days_ahead": 7})
    # validate_record 不抛异常即为通过
    validate_record(recs[0])
