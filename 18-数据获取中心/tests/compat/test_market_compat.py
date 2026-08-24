"""compat/market_compat 测试 — fetch_candles 走 ccxt + resample_candles 纯转发。

老 market_data.fetch_candles 用 OKX SDK 直连，compat 版用 ccxt 替换底层，
inst_id/bar 格式自动转换，返回格式保持 {"ts","o","h","l","c","vol"} 不变。
"""
from data_center.compat.market_compat import fetch_candles, resample_candles

CCXT_MOD = "data_center.compat.market_compat.ccxt"


def test_fetch_candles_basic(mocker):
    """ccxt fetch_ohlcv → 标准 candle dict 列表。"""
    mock_ccxt = mocker.patch(CCXT_MOD)
    mock_ex = mocker.MagicMock()
    mock_ccxt.okx.return_value = mock_ex
    mock_ex.fetch_ohlcv.return_value = [
        [1700000060000, 50050, 50200, 50000, 50150, 200.0],
        [1700000000000, 50000, 50100, 49900, 50050, 100.0],
    ]

    candles = fetch_candles("BTC-USDT", "1m", 2)

    # inst_id 格式转换：BTC-USDT → BTC/USDT
    mock_ccxt.okx.assert_called_once()
    mock_ex.fetch_ohlcv.assert_called_once()
    call_args = mock_ex.fetch_ohlcv.call_args
    assert call_args[0][0] == "BTC/USDT"        # 位置参数
    assert call_args[1]["timeframe"] == "1m"    # 关键字参数
    assert call_args[1]["limit"] == 2

    assert len(candles) == 2
    assert candles[0]["ts"] == 1700000000   # ms → s
    assert candles[0]["o"] == 50000.0
    assert candles[0]["h"] == 50100.0
    assert candles[0]["l"] == 49900.0
    assert candles[0]["c"] == 50050.0
    assert candles[0]["vol"] == 100.0


def test_fetch_candles_bar_conversion(mocker):
    """OKX bar 格式 → ccxt timeframe：1H→1h, 4H→4h, 1D→1d, 1W→1w。"""
    mock_ccxt = mocker.patch(CCXT_MOD)
    mock_ex = mocker.MagicMock()
    mock_ccxt.okx.return_value = mock_ex
    mock_ex.fetch_ohlcv.return_value = []

    fetch_candles("BTC-USDT", "1H", 10)
    assert mock_ex.fetch_ohlcv.call_args[1]["timeframe"] == "1H".lower()

    fetch_candles("BTC-USDT", "4H", 10)
    assert mock_ex.fetch_ohlcv.call_args[1]["timeframe"] == "4H".lower()

    fetch_candles("BTC-USDT", "1D", 10)
    assert mock_ex.fetch_ohlcv.call_args[1]["timeframe"] == "1D".lower()

    fetch_candles("BTC-USDT", "1W", 10)
    assert mock_ex.fetch_ohlcv.call_args[1]["timeframe"] == "1W".lower()


def test_fetch_candles_empty_on_error(mocker):
    """ccxt 异常 → 空列表，不抛异常。"""
    mock_ccxt = mocker.patch(CCXT_MOD)
    mock_ex = mocker.MagicMock()
    mock_ccxt.okx.return_value = mock_ex
    mock_ex.fetch_ohlcv.side_effect = RuntimeError("network")

    assert fetch_candles("BTC-USDT", "1m", 10) == []


def test_resample_candles_pure():
    """resample_candles 是纯数据变换，30m→1h 聚合 2 根为 1 根。"""
    # 30 分钟间隔的 ts（毫秒），4 根 → 2 组 → 2 根聚合
    candles = [
        {"ts": 0,       "o": 10, "h": 15, "l": 8,  "c": 12, "vol": 100},
        {"ts": 1800000, "o": 12, "h": 18, "l": 11, "c": 16, "vol": 200},
        {"ts": 3600000, "o": 16, "h": 20, "l": 14, "c": 18, "vol": 150},
        {"ts": 5400000, "o": 18, "h": 22, "l": 17, "c": 21, "vol": 50},
    ]
    resampled = resample_candles(candles, "1h")
    assert len(resampled) == 2
    r0 = resampled[0]
    assert r0["ts"] == 0
    assert r0["o"] == 10
    assert r0["h"] == 18
    assert r0["l"] == 8
    assert r0["c"] == 16
    assert r0["vol"] == 300
    r1 = resampled[1]
    assert r1["ts"] == 3600000
    assert r1["c"] == 21
    assert r1["vol"] == 200


def test_resample_no_mapping_returns_original():
    """无映射关系时返回原始列表。"""
    candles = [{"ts": 0, "o": 1, "h": 2, "l": 0, "c": 1, "vol": 1}]
    assert resample_candles(candles, "3m") == candles
