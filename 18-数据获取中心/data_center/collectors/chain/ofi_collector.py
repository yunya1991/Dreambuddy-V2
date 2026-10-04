"""OfiCollector — Order Flow Imbalance 采集器。

数据源: Binance/OKX 公开订单簿（通过 ccxt fetch_order_book）
  - 免费档够用
  - 频率: 1min snapshot
  - 字段: bid_volume, ask_volume, ofi_value

Spec: docs/superpowers/specs/2026-09-21-washout-detector-design.md §6.2 / §9.3 测试 3-4

OFI 计算:
  - bid_volume = sum(所有 bid 档位 quantity)
  - ask_volume = sum(所有 ask 档位 quantity)
  - ofi_value = bid_volume - ask_volume
  - ofi > 0 → 买方压力强；ofi < 0 → 卖方压力强

FAIL-OPEN 铁律: API 异常 → 返回空列表不阻塞，不抛错。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import ccxt

from data_center.collectors._base import BaseCollector
from data_center.collectors._proxy import system_proxy
from data_center.core.contract import DataRecord, validate_record

logger = logging.getLogger(__name__)

# 默认交易所回退顺序
_DEFAULT_EXCHANGES = ["binance", "okx", "coinbase"]

# 默认订单簿深度（取前 N 档）
_DEFAULT_DEPTH = 20


class OfiCollector(BaseCollector):
    """Order Flow Imbalance 采集器（Binance/OKX 公开订单簿）。

    采集 OFI（订单流不平衡）数据，用于洗盘判定 F12 ofi_std_20d。
    支持 1min snapshot 间隔配置（snapshot_interval_sec）。
    """

    source = "ccxt_ofi"
    category = "chain"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        # snapshot 间隔配置，默认 60 秒 (1min)
        self.snapshot_interval_sec: int = int(
            self.config.get("snapshot_interval_sec", 60)
        )
        self._depth: int = int(self.config.get("depth", _DEFAULT_DEPTH))

    def is_available(self) -> bool:
        """ccxt 是免费公开 API，始终可用。"""
        return True

    def fetch(self, params: dict) -> list[DataRecord]:
        """采集 OFI 数据。

        Args:
            params: {"symbol": "BTC/USDT", "exchange": "binance"}

        Returns:
            list[DataRecord] — 含 bid_volume/ask_volume/ofi_value。
            API 异常时返回空列表（FAIL-OPEN）。
        """
        symbol = params.get("symbol", "BTC/USDT")
        exchange_id = params.get("exchange", "binance")
        exchanges = [exchange_id] if exchange_id else list(_DEFAULT_EXCHANGES)

        proxy = system_proxy()
        last_err: Exception | None = None

        for ex_id in exchanges:
            try:
                exchange_cls = getattr(ccxt, ex_id)
                exchange = exchange_cls()
                if proxy:
                    exchange.proxies = {"http": proxy, "https": proxy}

                order_book = exchange.fetch_order_book(symbol, limit=self._depth)
                return self._build_records(order_book, symbol, ex_id)
            except Exception as e:
                last_err = e
                logger.debug(
                    "OfiCollector %s 获取 %s 失败 (%s: %s), 尝试下一个交易所",
                    ex_id, symbol, type(e).__name__, str(e)[:120],
                )
                continue

        # 所有交易所都失败 → FAIL-OPEN 返回空列表
        logger.debug("OfiCollector all exchanges failed: %s", last_err)
        return []

    def _build_records(
        self, order_book: dict, symbol: str, exchange_id: str
    ) -> list[DataRecord]:
        """从订单簿构建 DataRecord。"""
        try:
            bids = order_book.get("bids", [])
            asks = order_book.get("asks", [])

            # sum quantities for each side
            bid_volume = sum(
                float(qty) for _, qty in bids[: self._depth] if qty is not None
            )
            ask_volume = sum(
                float(qty) for _, qty in asks[: self._depth] if qty is not None
            )
            ofi_value = bid_volume - ask_volume

            rec = DataRecord(
                source=self.source,
                category=self.category,
                sub_category=symbol,
                timestamp=datetime.now(timezone.utc).astimezone().isoformat(),
                metrics={
                    "bid_volume": bid_volume,
                    "ask_volume": ask_volume,
                    "ofi_value": ofi_value,
                    "exchange": exchange_id,
                },
                events=[],
                timeseries=[],
                raw={"symbol": symbol, "exchange": exchange_id, "order_book": order_book},
            )
            validate_record(rec)
            return [rec]
        except Exception as e:
            logger.debug("OfiCollector _build_records FAIL-OPEN: %s", e)
            return []
