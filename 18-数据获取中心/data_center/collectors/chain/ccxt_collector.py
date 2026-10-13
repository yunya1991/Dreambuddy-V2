"""CCXT collector — 迁移自 flow_collector 交易所行情。

用 ccxt 库薄封装（100+ 交易所统一 API），fetch_ticker -> DataRecord(category=chain)。
"""
from __future__ import annotations

from datetime import datetime, timezone

import ccxt

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record


def _num(d: dict, key: str) -> float:
    """取数值字段，None -> 0.0（metrics 禁止 None）。"""
    v = d.get(key)
    return float(v) if v is not None else 0.0


class CcxtCollector(BaseCollector):
    source = "ccxt"
    category = "chain"

    def fetch(self, params: dict) -> list[DataRecord]:
        symbol = params["symbol"]            # 如 "BTC/USDT"
        exchange_id = params.get("exchange", "binance")
        kind = params.get("kind", "ticker")

        exchange_cls = getattr(ccxt, exchange_id)
        exchange = exchange_cls()

        if kind == "ticker":
            ticker = exchange.fetch_ticker(symbol)
            rec = DataRecord(
                source="ccxt",
                category="chain",
                sub_category=symbol,
                timestamp=datetime.now(timezone.utc).astimezone().isoformat(),
                metrics={
                    "symbol": symbol, "exchange": exchange_id,
                    "last": _num(ticker, "last"), "bid": _num(ticker, "bid"),
                    "ask": _num(ticker, "ask"), "high": _num(ticker, "high"),
                    "low": _num(ticker, "low"), "volume": _num(ticker, "volume"),
                },
                events=[],
                timeseries=[],
                raw={"symbol": symbol, "exchange": exchange_id, "ticker": dict(ticker)},
            )
            validate_record(rec)
            return [rec]

        if kind == "open_interest":
            # 用 ccxt fetch_open_interest 获取合约持仓量（OKX/Binance 等支持）
            swap_symbol = params.get("swap_symbol", symbol + ":USDT")
            oi = exchange.fetch_open_interest(swap_symbol)
            rec = DataRecord(
                source="ccxt",
                category="chain",
                sub_category="open_interest",
                timestamp=datetime.now(timezone.utc).astimezone().isoformat(),
                metrics={
                    "symbol": symbol,
                    "exchange": exchange_id,
                    "open_interest_value": _num(oi, "openInterestValue"),
                    "open_interest_amount": _num(oi, "openInterestAmount"),
                    "base_volume": _num(oi, "baseVolume"),
                },
                events=[],
                timeseries=[],
                raw={"symbol": symbol, "exchange": exchange_id, "oi": dict(oi)},
            )
            validate_record(rec)
            return [rec]

        return []
