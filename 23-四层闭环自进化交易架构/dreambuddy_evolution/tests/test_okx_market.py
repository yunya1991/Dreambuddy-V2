"""test_okx_market.py — OKXMarketAdapter 单元测试
覆盖: K线获取+格式转换, ticker spread, ma_200, FO降级, vol_5/20
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from dreambuddy_evolution.adapters.okx_market import OKXMarketAdapter


class MockOKXClient:
    """模拟 OKX 客户端"""

    def __init__(self, candles=None, ticker=None, positions=None,
                 long_short_ratio=None, open_interest=None):
        self._candles = candles or []
        self._ticker = ticker or {}
        self._positions = positions
        self._lsr = long_short_ratio
        self._oi = open_interest

    def get_kline(self, inst_id, bar="1H", limit=100):
        return {"ok": True, "candles": self._candles}

    def get_ticker(self, inst_id):
        return self._ticker

    def get_positions(self, inst_id):
        if self._positions is None:
            return {"ok": False}
        return {"ok": True, "positions": self._positions}

    def _get(self, path, params=None, auth=True):
        if path == "/api/v5/rubik/stat/contracts/long-short-account-ratio" and self._lsr:
            return {"code": "0", "data": [self._lsr]}
        if path == "/api/v5/public/open-interest" and self._oi:
            return {"code": "0", "data": [self._oi]}
        return {"code": "1", "data": []}


def _make_candles(n=200, base_price=50000.0):
    """生成 n 根模拟 K 线（降序=OKX 格式）"""
    candles = []
    for i in range(n):
        p = base_price + i * 10
        candles.append({
            "ts": str(1700000000000 + i * 3600000),
            "o": str(p), "h": str(p + 50),
            "l": str(p - 50), "c": str(p),
            "vol": str(1000 + i),
        })
    return list(reversed(candles))  # 降序 (新→旧)


class TestOKXMarketAdapter:

    def test_kline_fetch_and_format(self):
        """K线获取 + 降序→升序转换"""
        candles = _make_candles(200)
        client = MockOKXClient(candles=candles)
        adapter = OKXMarketAdapter(client)
        data = adapter.fetch("BTC", "BTC-USDT-SWAP")

        assert "close" in data
        assert len(data["close"]) == 200
        # 升序：第一根应该是最旧的
        assert data["close"][0] < data["close"][-1]
        assert "high" in data
        assert "low" in data
        assert "volume" in data

    def test_ma_200_calculation(self):
        """ma_200 正确计算"""
        candles = _make_candles(200, base_price=40000.0)
        client = MockOKXClient(candles=candles)
        adapter = OKXMarketAdapter(client)
        data = adapter.fetch("BTC", "BTC-USDT-SWAP")

        assert "ma_200" in data
        expected = float(np.mean([40000.0 + i * 10 for i in range(200)]))
        assert abs(data["ma_200"] - expected) < 0.01

    def test_ticker_spread(self):
        """ticker bid/ask spread 计算"""
        candles = _make_candles(200)
        client = MockOKXClient(
            candles=candles,
            ticker={"ok": True, "bid": "49999", "ask": "50001"},
        )
        adapter = OKXMarketAdapter(client)
        data = adapter.fetch("BTC", "BTC-USDT-SWAP")

        assert "bid_ask_spread_bps" in data
        expected = (50001 - 49999) / 50000 * 10000
        assert abs(data["bid_ask_spread_bps"] - expected) < 0.01

    def test_vol_5_vol_20(self):
        """vol_5 / vol_20 计算"""
        candles = _make_candles(200)
        client = MockOKXClient(candles=candles)
        adapter = OKXMarketAdapter(client)
        data = adapter.fetch("BTC", "BTC-USDT-SWAP")

        assert "vol_5" in data
        assert "vol_20" in data
        # vol_5 = mean of last 5 volumes (1000+199, 1000+198, ...)
        vols = [1000 + i for i in range(200)]
        assert abs(data["vol_5"] - float(np.mean(vols[-5:]))) < 0.01
        assert abs(data["vol_20"] - float(np.mean(vols[-20:]))) < 0.01

    def test_fib_retrace(self):
        """fib_retrace_0786 计算"""
        candles = _make_candles(200, base_price=40000.0)
        client = MockOKXClient(candles=candles)
        adapter = OKXMarketAdapter(client)
        data = adapter.fetch("BTC", "BTC-USDT-SWAP")

        assert "fib_retrace_0786" in data
        closes = [40000.0 + i * 10 for i in range(200)]
        lo, hi = min(closes), max(closes)
        expected = lo + 0.786 * (hi - lo)
        assert abs(data["fib_retrace_0786"] - expected) < 0.01

    def test_api_fail_fo(self):
        """API 失败 FO 降级 — 不抛异常"""
        client = MockOKXClient(candles=[], ticker={})
        adapter = OKXMarketAdapter(client)
        data = adapter.fetch("BTC", "BTC-USDT-SWAP")

        # 不应有 close 字段（获取失败）
        assert "close" not in data
        assert "bid_ask_spread_bps" not in data
        # 但 symbol 一定有
        assert data["symbol"] == "BTC"

    def test_long_short_ratio(self):
        """OKX long-short-ratio 获取 (rubik stat 端点)"""
        candles = _make_candles(200)
        # 新 API 响应: data=[[ts, longShortRatio],...]
        # longShortRatio=1.5 → long=0.6, short=0.4
        client = MockOKXClient(
            candles=candles,
            long_short_ratio=["1788768000000", "1.5"],
        )
        adapter = OKXMarketAdapter(client)
        data = adapter.fetch("BTC", "BTC-USDT-SWAP")

        assert "okx_positions" in data
        assert data["okx_positions"]["long"] == pytest.approx(0.6, abs=0.01)
        assert data["okx_positions"]["short"] == pytest.approx(0.4, abs=0.01)

    def test_crash_doesnt_propagate(self):
        """okx_client 方法抛异常不传播"""
        class CrashClient:
            def get_kline(self, *a, **kw):
                raise RuntimeError("network error")
            def get_ticker(self, *a, **kw):
                raise RuntimeError("timeout")
            def get_positions(self, *a, **kw):
                raise RuntimeError("auth fail")
            def _get(self, *a, **kw):
                raise RuntimeError("nope")

        adapter = OKXMarketAdapter(CrashClient())
        data = adapter.fetch("BTC", "BTC-USDT-SWAP")
        assert data["symbol"] == "BTC"

    def test_open_interest_fetch(self):
        """OKX OI 获取 + 归一化"""
        candles = _make_candles(200)
        client = MockOKXClient(
            candles=candles,
            open_interest={"oi": "5000000", "oiCcy": "50000"},
        )
        adapter = OKXMarketAdapter(client)
        data = adapter.fetch("BTC", "BTC-USDT-SWAP")

        assert "open_interest" in data
        assert data["open_interest"] == 5000000
        assert "oi_change_pct" in data
        # log10(5e6) = 6.7 → (6.7 - 6.0)/2.0 = 0.35
        assert abs(data["oi_change_pct"] - 0.35) < 0.01

    def test_open_interest_large(self):
        """大 OI → 归一化接近 +1"""
        candles = _make_candles(200)
        client = MockOKXClient(
            candles=candles,
            open_interest={"oi": "100000000", "oiCcy": "1000000"},
        )
        adapter = OKXMarketAdapter(client)
        data = adapter.fetch("BTC", "BTC-USDT-SWAP")
        # log10(1e8) = 8.0 → (8.0-6.0)/2.0 = 1.0
        assert data["oi_change_pct"] == 1.0

    def test_open_interest_small(self):
        """小 OI → 归一化接近 -1"""
        candles = _make_candles(200)
        client = MockOKXClient(
            candles=candles,
            open_interest={"oi": "10000", "oiCcy": "100"},
        )
        adapter = OKXMarketAdapter(client)
        data = adapter.fetch("BTC", "BTC-USDT-SWAP")
        # log10(1e4) = 4.0 → (4.0-6.0)/2.0 = -1.0
        assert data["oi_change_pct"] == -1.0
