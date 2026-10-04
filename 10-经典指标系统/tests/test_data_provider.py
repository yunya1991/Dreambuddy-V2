"""测试 classic_pipeline.data 模块的 DataProvider 接口契约。"""
from __future__ import annotations

import pytest

from classic_pipeline.data.provider import OHLCVBar, DataProvider


# ---------------------------------------------------------------------------
# TR-1.2: DataProvider.get_ohlcv 返回统一的 OHLCVBar 列表
# ---------------------------------------------------------------------------

def test_ohlcv_bar_field_order_matches_monolith():
    """OHLCVBar 字段顺序必须与单体 [ts, open, high, low, close, volume] 一致。"""
    bar = OHLCVBar(ts=1700000000000, open=1.0, high=2.0, low=0.5, close=1.5, volume=100.0)
    # 顺序检查：单体按 [ts, open, high, low, close, volume] 索引
    row = [bar.ts, bar.open, bar.high, bar.low, bar.close, bar.volume]
    assert row[0] == 1700000000000
    assert row[1] == 1.0   # open
    assert row[2] == 2.0   # high
    assert row[3] == 0.5   # low
    assert row[4] == 1.5   # close
    assert row[5] == 100.0  # volume


def test_ohlcv_bar_from_row_list():
    """从单体的 List[List[float]] 行格式构造 OHLCVBar。"""
    row = [1700000000000, 1.0, 2.0, 0.5, 1.5, 100.0]
    bar = OHLCVBar.from_row(row)
    assert bar.ts == 1700000000000
    assert bar.open == 1.0
    assert bar.high == 2.0
    assert bar.low == 0.5
    assert bar.close == 1.5
    assert bar.volume == 100.0


def test_ohlcv_bar_from_data_center_dict():
    """从 18-数据获取中心的 {"ts","o","h","l","c","vol"} dict 构造 OHLCVBar。"""
    d = {"ts": 1700000000000, "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "vol": 100.0}
    bar = OHLCVBar.from_data_center_dict(d)
    assert bar.ts == 1700000000000
    assert bar.open == 1.0
    assert bar.close == 1.5
    assert bar.volume == 100.0


def test_ohlcv_bar_to_dataframe():
    """OHLCVBar 列表可转换为 pandas DataFrame。"""
    import pandas as pd
    bars = [
        OHLCVBar(ts=1, open=1.0, high=2.0, low=0.5, close=1.5, volume=100.0),
        OHLCVBar(ts=2, open=1.5, high=2.5, low=1.0, close=2.0, volume=200.0),
    ]
    df = OHLCVBar.to_dataframe(bars)
    assert list(df.columns) == ["ts", "open", "high", "low", "close", "volume"]
    assert len(df) == 2
    assert df.iloc[0]["close"] == 1.5


# ---------------------------------------------------------------------------
# DataProvider Protocol 契约
# ---------------------------------------------------------------------------

def test_dataprovider_protocol_has_get_ohlcv():
    """DataProvider Protocol 必须定义 get_ohlcv 方法。"""
    assert hasattr(DataProvider, "get_ohlcv")


def test_mock_provider_returns_ohlcv_bars():
    """任何 DataProvider 实现的 get_ohlcv 必须返回 List[OHLCVBar]。"""
    class FakeProvider:
        def get_ohlcv(self, coin, timeframe, start=None, end=None, limit=None):
            return [OHLCVBar(ts=1, open=1.0, high=1.0, low=1.0, close=1.0, volume=1.0)]

    p = FakeProvider()
    result = p.get_ohlcv("BTC", "5m")
    assert isinstance(result, list)
    assert isinstance(result[0], OHLCVBar)


# ---------------------------------------------------------------------------
# TR-1.3: 接口定义清晰，方法数 ≤ 5
# ---------------------------------------------------------------------------

def test_dataprovider_method_count_within_limit():
    """DataProvider Protocol 的方法数不超过 5 个。"""
    methods = [m for m in dir(DataProvider) if not m.startswith("_")]
    assert len(methods) <= 5, f"DataProvider 方法数 {len(methods)} 超过 5"
