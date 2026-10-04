"""W3b-1 RED 测试 — 洗盘判定 3 采集器 + quality.py 硬门禁。

Spec: docs/superpowers/specs/2026-09-21-washout-detector-design.md §9.3 测试 1-7

测试清单:
  1. test_cvd_collector_fetch_returns_cvd_value       — CVD 采集成功
  2. test_cvd_collector_fail_open_on_api_error        — CVD FAIL-OPEN
  3. test_ofi_collector_fetch_returns_ofi_value       — OFI 采集成功
  4. test_ofi_collector_snapshot_interval             — 1min snapshot 间隔
  5. test_long_short_ratio_collector_fetch             — L-S Ratio 采集成功
  6. test_quality_validate_washout_data_rejects_missing — 缺字段 → 拦截
  7. test_quality_validate_washout_data_rejects_outlier — 数值越界 → 拦截

设计原则:
  - Mock API 响应，不依赖真实 API key 和网络（CI 友好）
  - 采集器遵循 BaseCollector 模式: fetch(params) -> list[DataRecord]
  - FAIL-OPEN 铁律: API 异常 → 返回空列表不阻塞
"""
from __future__ import annotations

from data_center.collectors.chain.cvd_collector import CvdCollector
from data_center.collectors.chain.ofi_collector import OfiCollector
from data_center.collectors.chain.long_short_ratio_collector import (
    LongShortRatioCollector,
)
from data_center.core.contract import DataRecord
from data_center.monitoring.quality import validate_washout_data


# ============================================================
# 测试 1: CVD 采集器拉取成功
# ============================================================
def test_cvd_collector_fetch_returns_cvd_value(mocker):
    """CVD collector fetch 成功返回 DataRecord 含 cvd_value/buy_volume/sell_volume。"""
    mock_resp = {
        "code": 0,
        "data": [
            {
                "t": 1697200000000,
                "c": 12345.6,        # cvd_value
                "b": 50000.0,        # buy_volume
                "s": 37654.4,        # sell_volume
            }
        ],
    }
    mocker.patch(
        "data_center.collectors.chain.cvd_collector.requests.get",
        return_value=mocker.Mock(json=lambda: mock_resp, status_code=200),
    )
    c = CvdCollector(config={"api_key": "test_key"})
    recs = c.fetch({"symbol": "BTC", "interval": "5min"})
    assert len(recs) == 1
    r = recs[0]
    assert isinstance(r, DataRecord)
    assert r.source == "coinglass"
    assert r.category == "chain"
    assert r.sub_category == "BTC"
    assert "cvd_value" in r.metrics
    assert "buy_volume" in r.metrics
    assert "sell_volume" in r.metrics
    assert r.metrics["cvd_value"] == 12345.6
    assert r.metrics["buy_volume"] == 50000.0
    assert r.metrics["sell_volume"] == 37654.4


# ============================================================
# 测试 2: CVD 采集器 FAIL-OPEN
# ============================================================
def test_cvd_collector_fail_open_on_api_error(mocker):
    """CVD collector API 异常 → 返回空列表不阻塞。"""
    mocker.patch(
        "data_center.collectors.chain.cvd_collector.requests.get",
        side_effect=Exception("API timeout"),
    )
    c = CvdCollector(config={"api_key": "test_key"})
    recs = c.fetch({"symbol": "BTC", "interval": "5min"})
    # FAIL-OPEN: 返回空列表，不抛异常
    assert recs == []
    assert c.is_available() is True  # 有 API Key 走 API，无 Key 走回退


# ============================================================
# 测试 3: OFI 采集器拉取成功
# ============================================================
def test_ofi_collector_fetch_returns_ofi_value(mocker):
    """OFI collector fetch 成功返回 DataRecord 含 bid_volume/ask_volume/ofi_value。"""
    # mock ccxt exchange.fetch_order_book
    mock_order_book = {
        "bids": [[60000.0, 1.5], [59999.0, 2.0], [59998.0, 3.0]],
        "asks": [[60001.0, 1.2], [60002.0, 1.8], [60003.0, 2.5]],
        "timestamp": 1697200000000,
    }
    mock_ccxt = mocker.patch(
        "data_center.collectors.chain.ofi_collector.ccxt"
    )
    mock_exchange = mock_ccxt.binance.return_value
    mock_exchange.fetch_order_book.return_value = mock_order_book

    c = OfiCollector()
    recs = c.fetch({"symbol": "BTC/USDT", "exchange": "binance"})
    assert len(recs) == 1
    r = recs[0]
    assert isinstance(r, DataRecord)
    assert r.source == "ccxt_ofi"
    assert r.category == "chain"
    assert r.sub_category == "BTC/USDT"
    assert "bid_volume" in r.metrics
    assert "ask_volume" in r.metrics
    assert "ofi_value" in r.metrics
    # bid_volume = sum of bid quantities = 1.5 + 2.0 + 3.0 = 6.5
    assert r.metrics["bid_volume"] == 6.5
    # ask_volume = sum of ask quantities = 1.2 + 1.8 + 2.5 = 5.5
    assert r.metrics["ask_volume"] == 5.5
    # ofi_value = bid_volume - ask_volume = 1.0
    assert r.metrics["ofi_value"] == 1.0


# ============================================================
# 测试 4: OFI 采集器 snapshot 间隔
# ============================================================
def test_ofi_collector_snapshot_interval(mocker):
    """OFI collector 默认 snapshot_interval_sec=60 (1min)。"""
    c = OfiCollector()
    # 默认 snapshot 间隔为 60 秒 (1min)
    assert c.snapshot_interval_sec == 60
    # 可通过 config 自定义
    c2 = OfiCollector(config={"snapshot_interval_sec": 30})
    assert c2.snapshot_interval_sec == 30


# ============================================================
# 测试 5: L-S Ratio 采集器拉取成功
# ============================================================
def test_long_short_ratio_collector_fetch(mocker):
    """L-S Ratio collector fetch 成功返回 DataRecord 含 long_ratio/short_ratio。"""
    # mock Binance Futures API
    mock_resp = {
        "code": 200,
        "data": [
            {
                "timestamp": 1697200000000,
                "longShortRatio": 1.25,
                "longAccount": 0.5556,
                "shortAccount": 0.4444,
            }
        ]
    }
    mocker.patch(
        "data_center.collectors.chain.long_short_ratio_collector.requests.get",
        return_value=mocker.Mock(json=lambda: mock_resp, status_code=200),
    )
    c = LongShortRatioCollector()
    recs = c.fetch({"symbol": "BTCUSDT", "interval": "5min"})
    assert len(recs) == 1
    r = recs[0]
    assert isinstance(r, DataRecord)
    assert r.source == "binance_futures"
    assert r.category == "chain"
    assert r.sub_category == "BTCUSDT"
    assert "long_ratio" in r.metrics
    assert "short_ratio" in r.metrics
    assert r.metrics["long_ratio"] == 1.25
    assert r.metrics["short_ratio"] == 0.4444


# ============================================================
# 测试 6: quality.py validate_washout_data 缺字段拦截
# ============================================================
def test_quality_validate_washout_data_rejects_missing():
    """validate_washout_data 缺字段 → 返回 False。"""
    # 缺 cvd_value
    r1 = {"timestamp": "2026-09-21T00:00:00Z", "symbol": "BTC", "ofi_value": 1.0}
    assert validate_washout_data(r1) is False
    # 缺 symbol
    r2 = {"timestamp": "2026-09-21T00:00:00Z", "cvd_value": 100.0, "ofi_value": 1.0}
    assert validate_washout_data(r2) is False
    # 缺 timestamp
    r3 = {"symbol": "BTC", "cvd_value": 100.0, "ofi_value": 1.0}
    assert validate_washout_data(r3) is False
    # 字段值为 None
    r4 = {"timestamp": "2026-09-21T00:00:00Z", "symbol": "BTC",
          "cvd_value": None, "ofi_value": 1.0}
    assert validate_washout_data(r4) is False


# ============================================================
# 测试 7: quality.py validate_washout_data 数值越界拦截
# ============================================================
def test_quality_validate_washout_data_rejects_outlier():
    """validate_washout_data 数值越界 → 返回 False。"""
    # cvd_value 超出 [-1e9, 1e9] 范围
    r1 = {"timestamp": "2026-09-21T00:00:00Z", "symbol": "BTC",
          "cvd_value": 2e9, "ofi_value": 1.0}
    assert validate_washout_data(r1) is False
    # cvd_value 负越界
    r2 = {"timestamp": "2026-09-21T00:00:00Z", "symbol": "BTC",
          "cvd_value": -2e9, "ofi_value": 1.0}
    assert validate_washout_data(r2) is False
    # ofi_value 越界
    r3 = {"timestamp": "2026-09-21T00:00:00Z", "symbol": "BTC",
          "cvd_value": 100.0, "ofi_value": 2e9}
    assert validate_washout_data(r3) is False
    # 正常数据 → True
    r_ok = {"timestamp": "2026-09-21T00:00:00Z", "symbol": "BTC",
            "cvd_value": 100.0, "ofi_value": 1.0}
    assert validate_washout_data(r_ok) is True
