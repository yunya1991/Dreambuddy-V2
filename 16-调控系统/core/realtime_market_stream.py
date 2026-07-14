#!/usr/bin/env python3
"""
实时市场数据流 — 16-调控系统 Phase 2+

WebSocket 实时行情推送模块，支持 Hyperliquid 实时数据。

特性：
  - Hyperliquid WebSocket 连接（全市场 ticker）
  - 自动重连机制
  - 数据缓存（最新价格、24h变化、成交量等）
  - 回调机制（价格变动触发）
  - 线程安全的单例模式
  - 优雅降级（WS不可用时回退到REST轮询）
"""

import json
import time
import threading
from typing import Dict, Any, Callable, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import defaultdict

try:
    import urllib.request
    HAS_URLLIB = True
except ImportError:
    HAS_URLLIB = False

try:
    import websocket
    HAS_WEBSOCKET = True
except ImportError:
    HAS_WEBSOCKET = False


@dataclass
class MarketTicker:
    """市场 ticker 数据"""
    symbol: str
    price: float = 0.0
    price_24h_ago: float = 0.0
    change_24h_pct: float = 0.0
    high_24h: float = 0.0
    low_24h: float = 0.0
    volume_24h: float = 0.0
    funding_rate: float = 0.0
    open_interest: float = 0.0
    last_update: float = 0.0
    source: str = ""


class RealtimeMarketStream:
    """
    实时市场数据流

    使用方式：
        stream = RealtimeMarketStream()
        stream.start()
        ticker = stream.get_ticker("BTC")
        stream.stop()
    """

    _instance: Optional["RealtimeMarketStream"] = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        self._tickers: Dict[str, MarketTicker] = {}
        self._tickers_lock = threading.Lock()

        self._running = False
        self._ws_thread: Optional[threading.Thread] = None
        self._polling_thread: Optional[threading.Thread] = None
        self._ws = None

        self._callbacks: List[Callable[[Dict[str, MarketTicker]], None]] = []
        self._callbacks_lock = threading.Lock()

        self._update_interval = 10.0
        self._last_rest_update = 0.0

        self._ws_url = "wss://api.hyperliquid.xyz/ws"
        self._rest_url = "https://api.hyperliquid.xyz"

        self._reconnect_delay = 5.0
        self._max_reconnect_attempts = 10

    def start(self, symbols: Optional[List[str]] = None) -> bool:
        """
        启动实时数据流

        Args:
            symbols: 关注的币种列表，None 则全市场

        Returns:
            是否启动成功
        """
        if self._running:
            return True

        self._running = True

        if HAS_WEBSOCKET:
            self._ws_thread = threading.Thread(target=self._ws_main_loop, daemon=True)
            self._ws_thread.start()

        self._polling_thread = threading.Thread(target=self._rest_polling_loop, daemon=True)
        self._polling_thread.start()

        return True

    def stop(self):
        """停止实时数据流"""
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        self._ws = None

    def get_ticker(self, symbol: str) -> Optional[MarketTicker]:
        """获取指定币种的最新 ticker"""
        with self._tickers_lock:
            ticker = self._tickers.get(symbol.upper())
            if ticker:
                return ticker

            alt_symbols = []
            if symbol.upper() == "BTC":
                alt_symbols = ["BTC", "BTC-PERP", "BTC/USDC"]
            elif symbol.upper() == "ETH":
                alt_symbols = ["ETH", "ETH-PERP", "ETH/USDC"]
            elif symbol.upper() == "SOL":
                alt_symbols = ["SOL", "SOL-PERP", "SOL/USDC"]

            for alt in alt_symbols:
                if alt in self._tickers:
                    return self._tickers[alt]

            return None

    def get_all_tickers(self) -> Dict[str, MarketTicker]:
        """获取所有 ticker"""
        with self._tickers_lock:
            return dict(self._tickers)

    def get_market_snapshot(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        获取多币种市场快照（兼容 market_data_fetcher 格式）

        Args:
            symbols: 币种列表

        Returns:
            市场数据字典，格式与 fetch_market_data 兼容
        """
        result = {}
        for sym in symbols:
            ticker = self.get_ticker(sym)
            if ticker:
                result[sym] = {
                    "symbol": sym,
                    "current_price": ticker.price,
                    "price": ticker.price,
                    "last": ticker.price,
                    "change_24h_pct": ticker.change_24h_pct,
                    "change_pct": ticker.change_24h_pct,
                    "high_24h": ticker.high_24h,
                    "low_24h": ticker.low_24h,
                    "volume_24h": ticker.volume_24h,
                    "funding_rate": ticker.funding_rate,
                    "open_interest": ticker.open_interest,
                    "last_update": ticker.last_update,
                    "source": ticker.source,
                    "is_realtime": True,
                }
        return result

    def register_callback(self, callback: Callable[[Dict[str, MarketTicker]], None]):
        """注册价格更新回调"""
        with self._callbacks_lock:
            self._callbacks.append(callback)

    def unregister_callback(self, callback: Callable):
        """取消注册回调"""
        with self._callbacks_lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

    def _ws_main_loop(self):
        """WebSocket 主循环"""
        attempts = 0
        while self._running and attempts < self._max_reconnect_attempts:
            try:
                self._connect_ws()
                attempts = 0
            except Exception:
                attempts += 1
                if self._running:
                    time.sleep(self._reconnect_delay)

    def _connect_ws(self):
        """连接 WebSocket"""
        if not HAS_WEBSOCKET:
            return

        def on_message(ws, message):
            try:
                data = json.loads(message)
                self._process_ws_message(data)
            except Exception:
                pass

        def on_error(ws, error):
            pass

        def on_close(ws, close_status_code, close_msg):
            pass

        def on_open(ws):
            try:
                sub_msg = {
                    "method": "subscribe",
                    "subscription": {
                        "type": "allMids"
                    }
                }
                ws.send(json.dumps(sub_msg))
            except Exception:
                pass

        self._ws = websocket.WebSocketApp(
            self._ws_url,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open,
        )
        self._ws.run_forever(ping_interval=30)

    def _process_ws_message(self, data: Dict[str, Any]):
        """处理 WebSocket 消息"""
        channel = data.get("channel", "")

        if channel == "allMids":
            mids = data.get("data", {})
            if isinstance(mids, dict):
                now = time.time()
                updated = False
                with self._tickers_lock:
                    for symbol, price_str in mids.items():
                        try:
                            price = float(price_str)
                            base_symbol = symbol.replace("-PERP", "").replace("/USDC", "").upper()

                            if base_symbol not in self._tickers:
                                self._tickers[base_symbol] = MarketTicker(
                                    symbol=base_symbol,
                                    source="hyperliquid-ws",
                                )

                            ticker = self._tickers[base_symbol]
                            old_price = ticker.price
                            ticker.price = price
                            ticker.last_update = now

                            if old_price > 0:
                                change = (price - old_price) / old_price * 100
                                if abs(change) < 5:
                                    ticker.change_24h_pct = ticker.change_24h_pct * 0.99 + change * 0.01

                            if symbol in self._tickers:
                                self._tickers[symbol].price = price
                                self._tickers[symbol].last_update = now

                            updated = True
                        except (ValueError, TypeError):
                            pass

                if updated:
                    self._trigger_callbacks()

    def _rest_polling_loop(self):
        """REST 轮询循环（作为 WebSocket 的补充/降级）"""
        while self._running:
            try:
                now = time.time()
                if now - self._last_rest_update >= self._update_interval:
                    self._fetch_rest_snapshot()
                    self._last_rest_update = now
            except Exception:
                pass
            time.sleep(1.0)

    def _fetch_rest_snapshot(self):
        """从 REST API 获取市场快照"""
        if not HAS_URLLIB:
            return

        try:
            payload = json.dumps({"type": "allMids"}).encode("utf-8")
            req = urllib.request.Request(
                f"{self._rest_url}/info",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            if isinstance(data, list):
                now = time.time()
                with self._tickers_lock:
                    for item in data:
                        if isinstance(item, dict):
                            coin = item.get("coin", "").upper()
                            px = float(item.get("px", 0))
                            if coin and px > 0:
                                if coin not in self._tickers:
                                    self._tickers[coin] = MarketTicker(
                                        symbol=coin,
                                        source="hyperliquid-rest",
                                    )
                                ticker = self._tickers[coin]
                                ticker.price = px
                                ticker.last_update = now

            self._trigger_callbacks()
        except Exception:
            pass

    def _trigger_callbacks(self):
        """触发所有注册的回调"""
        with self._callbacks_lock:
            callbacks = list(self._callbacks)
            snapshot = dict(self._tickers)

        if callbacks:
            for cb in callbacks:
                try:
                    cb(snapshot)
                except Exception:
                    pass

    def is_connected(self) -> bool:
        """检查是否有有效数据"""
        with self._tickers_lock:
            if not self._tickers:
                return False
            now = time.time()
            for ticker in self._tickers.values():
                if now - ticker.last_update < 60:
                    return True
            return False


_global_stream: Optional[RealtimeMarketStream] = None


def get_market_stream() -> RealtimeMarketStream:
    """获取全局市场数据流单例"""
    global _global_stream
    if _global_stream is None:
        _global_stream = RealtimeMarketStream()
    return _global_stream


def start_realtime_stream(symbols: Optional[List[str]] = None) -> bool:
    """便捷函数：启动实时数据流"""
    stream = get_market_stream()
    return stream.start(symbols)


def stop_realtime_stream():
    """便捷函数：停止实时数据流"""
    stream = get_market_stream()
    stream.stop()


def get_realtime_ticker(symbol: str) -> Optional[MarketTicker]:
    """便捷函数：获取实时 ticker"""
    stream = get_market_stream()
    return stream.get_ticker(symbol)


def get_realtime_snapshot(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """便捷函数：获取市场快照"""
    stream = get_market_stream()
    return stream.get_market_snapshot(symbols)


if __name__ == "__main__":
    print("启动实时市场数据流...")
    start_realtime_stream()
    time.sleep(3)

    btc = get_realtime_ticker("BTC")
    eth = get_realtime_ticker("ETH")

    if btc:
        print(f"BTC 价格: ${btc.price:,.2f} (更新于 {btc.last_update})")
        print(f"  24h 变化: {btc.change_24h_pct:+.2f}%")
        print(f"  数据源: {btc.source}")
    else:
        print("BTC 数据不可用")

    if eth:
        print(f"ETH 价格: ${eth.price:,.2f}")
    else:
        print("ETH 数据不可用")

    print(f"已连接: {get_market_stream().is_connected()}")
    print(f"总 ticker 数: {len(get_market_stream().get_all_tickers())}")

    stop_realtime_stream()
