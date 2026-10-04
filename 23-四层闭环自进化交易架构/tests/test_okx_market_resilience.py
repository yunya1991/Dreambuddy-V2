"""
OKXMarketAdapter 韧性测试 — 重试 + TTL 缓存 + stale 降级
TDD RED→GREEN：验证 OKX API 单次失败不再直穿下游 6 层 fallback
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from dreambuddy_evolution.adapters.okx_market import OKXMarketAdapter


class _FakeClient:
    """模拟 OKX client：可控制 get_kline 行为"""

    def __init__(self):
        self.get_kline_mock = MagicMock()
        self.get_ticker_mock = MagicMock(return_value={"ok": False})
        self.get_positions_mock = MagicMock(return_value={"ok": False})
        self.get_open_interest_mock = MagicMock(return_value={"ok": False})
        self._get_mock = MagicMock(return_value=None)

    def get_kline(self, *args, **kwargs):
        return self.get_kline_mock(*args, **kwargs)

    def get_ticker(self, *args, **kwargs):
        return self.get_ticker_mock(*args, **kwargs)

    def get_positions(self, *args, **kwargs):
        return self.get_positions_mock(*args, **kwargs)

    def get_open_interest(self, *args, **kwargs):
        return self.get_open_interest_mock(*args, **kwargs)

    def _get(self, *args, **kwargs):
        return self._get_mock(*args, **kwargs)


def _make_kline_resp(n_candles=200):
    """构造合法 OKX kline 响应"""
    candles = []
    base = 100.0
    for i in range(n_candles):
        c = base + i * 0.1
        candles.append({"o": str(c), "h": str(c + 0.5), "l": str(c - 0.5),
                        "c": str(c), "vol": "100"})
    # OKX 返回降序（新→旧）
    return {"ok": True, "candles": list(reversed(candles))}


# ============================================================================
# 测试 1: 首次失败、二次成功 → 返回正常 payload，缓存被写入
# ============================================================================
def test_retry_succeeds_on_second_attempt():
    """首次 Timeout、二次成功 → 返回正常数据"""
    client = _FakeClient()
    client.get_kline_mock.side_effect = [
        TimeoutError("simulated timeout"),
        _make_kline_resp(200),
    ]

    adapter = OKXMarketAdapter(client)
    result = adapter._fetch_kline("BTC-USDT", limit=200)

    assert "close" in result, "二次成功应返回 close 数组"
    assert "ma_200" in result
    assert client.get_kline_mock.call_count == 2, "应重试 1 次后成功"


# ============================================================================
# 测试 2: 3 次全失败 + 有过期缓存 → 返回 stale payload
# ============================================================================
def test_stale_cache_fallback_on_all_failures(caplog):
    """全部失败 + 有过期缓存 → 返回 stale 数据并打 FO-raw-stale 日志"""
    import logging
    client = _FakeClient()
    client.get_kline_mock.return_value = None  # 始终失败

    adapter = OKXMarketAdapter(client)
    # 手动注入过期缓存（模拟上次成功响应）
    adapter._last_good["kline:BTC-USDT"] = (time.time() - 3600,
                                            {"close": [100.0], "ma_200": 100.0})

    with caplog.at_level(logging.WARNING, logger="dreambuddy_evolution.adapters.okx_market"):
        result = adapter._fetch_kline("BTC-USDT", limit=200)

    assert "close" in result, "应返回 stale 缓存的 close 数组"
    assert any("FO-raw-stale" in r.message for r in caplog.records), "应打 stale 日志"
    assert client.get_kline_mock.call_count == 3, "应重试 3 次"


# ============================================================================
# 测试 3: 3 次全失败 + 无缓存 → 返回空 dict（FAIL-OPEN 语义）
# ============================================================================
def test_all_fail_no_cache_returns_empty():
    """全部失败 + 无缓存 → 返回空 dict，保持现有 FAIL-OPEN 语义"""
    client = _FakeClient()
    client.get_kline_mock.return_value = None

    adapter = OKXMarketAdapter(client)
    result = adapter._fetch_kline("BTC-USDT", limit=200)

    assert result == {}, "无缓存时应返回空 dict"
    assert client.get_kline_mock.call_count == 3, "应重试 3 次"


# ============================================================================
# 测试 4: TTL 内连续 2 次调用 → client 只被调用 1 次（缓存命中）
# ============================================================================
def test_ttl_cache_hit():
    """TTL 内连续调用 → 命中缓存，client 只调用 1 次"""
    client = _FakeClient()
    client.get_kline_mock.return_value = _make_kline_resp(200)

    adapter = OKXMarketAdapter(client)

    r1 = adapter._fetch_kline("BTC-USDT", limit=200)
    r2 = adapter._fetch_kline("BTC-USDT", limit=200)

    assert "close" in r1 and "close" in r2
    assert client.get_kline_mock.call_count == 1, "第二次应命中缓存"


# ============================================================================
# 测试 5: 4xx 错误立即返回不重试
# ============================================================================
def test_4xx_no_retry():
    """4xx 错误立即返回，不重试"""
    client = _FakeClient()
    # 模拟 4xx（resp 包含 error_code=401）
    client.get_kline_mock.return_value = {"ok": False, "error_code": 401}

    adapter = OKXMarketAdapter(client)
    result = adapter._fetch_kline("BTC-USDT", limit=200)

    assert result == {}, "4xx 应立即返回空 dict"
    assert client.get_kline_mock.call_count == 1, "4xx 不应重试"
