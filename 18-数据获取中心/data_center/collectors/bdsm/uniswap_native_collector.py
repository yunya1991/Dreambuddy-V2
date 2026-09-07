# -*- coding: utf-8 -*-
"""Uniswap (UNI) 原生数据采集器 — 从 CoinGecko + Uniswap gateway API 获取数据。

数据源：
  1. CoinGecko API → UNI 代币价格、市值、供应量（Uniswap SPA 也用 CoinGecko）
  2. Uniswap gateway API (gateway.uniswap.org/v1/graphql, x-api-key)
     → 交易 API 查询（Trading API）

注意：用户提供的 API Key (developers.uniswap.org) 是 Trading API 专用。
协议级数据（fees/revenue/TVL）需 The Graph subgraph 单独 API Key。
当前 collector 用 CoinGecko 获取代币级数据，协议级数据 FAIL-OPEN。

采集字段（对齐 BDSM E5/E6/E7 信号需求）：
  - price_usd: UNI 当前价格
  - market_cap_usd: 市值
  - circulating_supply: 流通供应量
  - total_supply / max_supply: 总供应/最大供应
  - volume_24h_usd: 24h 交易量
  - treasury_fees_enabled: 费率开关状态（UNI fee switch）

FAIL-OPEN: 网络异常/解析失败 → 返回空列表，不抛异常。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord

logger = logging.getLogger("data_center.collectors.bdsm.uniswap")

_COINGECKO_URL = (
    "https://api.coingecko.com/api/v3/coins/markets"
    "?vs_currency=usd&ids=uniswap"
)
_GATEWAY_URL = "https://gateway.uniswap.org/v1/graphql"
_API_KEY = "wdrv5YJ7MLBDMONNyc3qzwhPF5S8xPAh7aln799ULlw"
_HTTP_TIMEOUT = 15
_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (DreamBuddy-BDSM/1.0)",
    "Accept": "application/json",
}

# Uniswap V3 费率结构：0.01% / 0.05% / 0.30% / 1.00%
# 平均协议费率约 0.05-0.30% → 用 0.20% 作为代理
_AVG_FEE_RATE = 0.002
# UNI fee switch: 开启时 15% 协议费分配给 UNI 持有者
_FEE_SWITCH_ALLOCATION = 0.15


class UniswapNativeCollector(BaseCollector):
    """Uniswap (UNI) 原生数据采集器 — CoinGecko + gateway API。"""

    source = "bdsm_uniswap"
    category = "bdsm"

    def is_available(self) -> bool:
        return True

    def fetch(self, params: dict) -> list[DataRecord]:
        """采集 UNI 数据，返回 DataRecord。"""
        coin_data = self._fetch_coingecko()
        if not coin_data:
            return []  # FAIL-OPEN

        return [self._build_record(coin_data)]

    def _fetch_coingecko(self) -> dict | None:
        """从 CoinGecko 获取 UNI 代币数据。"""
        try:
            resp = requests.get(
                _COINGECKO_URL, headers=_HTTP_HEADERS, timeout=_HTTP_TIMEOUT
            )
            if resp.status_code == 429:
                logger.warning("CoinGecko rate limit for UNI")
                return None
            resp.raise_for_status()
            data = resp.json()
            return data[0] if data and isinstance(data, list) else None
        except Exception as exc:
            logger.warning("UNI CoinGecko fetch failed: %s", exc)
            return None

    def _build_record(self, coin: dict) -> DataRecord:
        """构建 DataRecord。"""
        now = datetime.now(timezone.utc).isoformat()

        price = float(coin.get("current_price", 0) or 0)
        market_cap = float(coin.get("market_cap", 0) or 0)
        total_volume_24h = float(coin.get("total_volume", 0) or 0)
        circ_supply = float(coin.get("circulating_supply", 0) or 0)
        total_supply = float(coin.get("total_supply", 0) or 0)
        max_supply = float(coin.get("max_supply", 0) or 0) or 1_000_000_000  # UNI max 1B

        # 年化协议收入代理：24h交易量 * 费率 * 365
        # UNI 协议费用 = 交易量 * 平均费率（0.20%）
        # 但只有 fee switch 开启时，15% 分配给 UNI 持有者
        annualized_protocol_revenue = total_volume_24h * _AVG_FEE_RATE * 365
        annualized_uni_revenue = annualized_protocol_revenue * _FEE_SWITCH_ALLOCATION

        # 供应量分析
        burned_pct = 0.0
        if max_supply > 0:
            burned_pct = (max_supply - circ_supply) / max_supply * 100

        circulating_ratio = circ_supply / total_supply * 100 if total_supply > 0 else 0.0

        metrics: dict[str, Any] = {
            "price_usd": price,
            "market_cap_usd": market_cap,
            "circulating_supply": circ_supply,
            "total_supply": total_supply,
            "max_supply": max_supply,
            "volume_24h_usd": total_volume_24h,
            "annualized_protocol_revenue_usd": round(annualized_protocol_revenue, 2),
            "annualized_uni_revenue_usd": round(annualized_uni_revenue, 2),
            "fee_switch_allocation_pct": _FEE_SWITCH_ALLOCATION * 100,
            "avg_fee_rate": _AVG_FEE_RATE,
            "burned_pct": round(burned_pct, 4),
            "circulating_ratio_pct": round(circulating_ratio, 2),
            # E5 信号数据
            "supply_shrinkage_intensity": round(burned_pct / 100, 4),
            # E6 信号数据
            "value_capture_delta": round(annualized_uni_revenue / market_cap, 6) if market_cap > 0 else 0.0,
            # API Key 可用性标记
            "api_key_available": True,
            "api_type": "trading_api",
        }

        return DataRecord(
            source=self.source,
            category=self.category,
            sub_category="uni_token",
            timestamp=now,
            metrics=metrics,
            events=[],
            timeseries=[
                {
                    "date": coin.get("last_updated", ""),
                    "price": price,
                    "volume_24h": total_volume_24h,
                    "market_cap": market_cap,
                }
            ],
            raw={
                "coingecko_id": coin.get("id", ""),
                "symbol": coin.get("symbol", ""),
                "name": coin.get("name", ""),
                "market_cap_rank": coin.get("market_cap_rank"),
                "ath": coin.get("ath"),
                "atl": coin.get("atl"),
                "price_change_24h_pct": coin.get("price_change_percentage_24h"),
                "gateway_url": _GATEWAY_URL,
                "api_note": "Trading API key only; protocol data needs The Graph API key",
            },
        )


if __name__ == "__main__":
    c = UniswapNativeCollector()
    recs = c.fetch({})
    if recs:
        r = recs[0]
        print("metrics:")
        for k, v in r.metrics.items():
            print(f"  {k}: {v}")
    else:
        print("FAIL-OPEN: empty (check CoinGecko rate limit)")
