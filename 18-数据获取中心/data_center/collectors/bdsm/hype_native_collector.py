# -*- coding: utf-8 -*-
"""HYPE 原生数据采集器 — 从 Hyperliquid API + CoinGecko 获取数据。

数据源（原生项目 API，非第三方数据网站）：
  1. CoinGecko API（HYPE SPA 也用此 API 获取价格）
     → HYPE 代币价格、市值、供应量
  2. Hyperliquid API (api.hyperliquid.xyz/info)
     → 市场元数据（perps + spot）、交易量

采集字段（对齐 BDSM E5/E6/E7 信号需求）：
  - price_usd: HYPE 当前价格
  - market_cap_usd: 市值
  - circulating_supply: 流通供应量
  - total_supply: 总供应量
  - max_supply: 最大供应量
  - annualized_revenue_usd: 年化协议收入（代理：24h_volume * fee_rate）
  - perp_market_count: 永续合约市场数
  - spot_market_count: 现货市场数
  - buyback_burn_pct: 回购销毁百分比（流通/最大供应比）

FAIL-OPEN: 网络异常/解析失败 → 返回空列表，不抛异常。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord

logger = logging.getLogger("data_center.collectors.bdsm.hype")

_COINGECKO_URL = (
    "https://api.coingecko.com/api/v3/coins/markets"
    "?vs_currency=usd&ids=hyperliquid"
)
_HYPERLIQUID_URL = "https://api.hyperliquid.xyz/info"
_HTTP_TIMEOUT = 15
_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (DreamBuddy-BDSM/1.0)",
    "Accept": "application/json",
}

# Hyperliquid 费率结构（公开信息）：
# - Perps: 0.035% taker / 0.015% maker → 平均约 0.025%
# - Spot: 0.01% taker / 0.005% maker
_PERP_FEE_RATE = 0.00025  # 0.025% blended
_HYPE_BUYBACK_ALLOCATION = 0.462  # HYPE 回购分配比例（约 46.2%）


class HypeNativeCollector(BaseCollector):
    """HYPE 原生数据采集器 — CoinGecko + Hyperliquid API。"""

    source = "bdsm_hype"
    category = "bdsm"

    def is_available(self) -> bool:
        return True

    def fetch(self, params: dict) -> list[DataRecord]:
        """采集 HYPE 数据，返回 DataRecord。"""
        coin_data = self._fetch_coingecko()
        if not coin_data:
            return []  # FAIL-OPEN

        market_meta = self._fetch_hyperliquid_meta()

        return [self._build_record(coin_data, market_meta)]

    def _fetch_coingecko(self) -> dict | None:
        """从 CoinGecko 获取 HYPE 代币数据。"""
        try:
            resp = requests.get(
                _COINGECKO_URL, headers=_HTTP_HEADERS, timeout=_HTTP_TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
            return data[0] if data and isinstance(data, list) else None
        except Exception as exc:
            logger.warning("HYPE CoinGecko fetch failed: %s", exc)
            return None

    def _fetch_hyperliquid_meta(self) -> dict:
        """从 Hyperliquid API 获取市场元数据。"""
        result: dict[str, Any] = {"perp_count": 0, "spot_count": 0}
        try:
            # Perps meta
            resp = requests.post(
                _HYPERLIQUID_URL,
                json={"type": "meta"},
                headers={**_HTTP_HEADERS, "Content-Type": "application/json"},
                timeout=_HTTP_TIMEOUT,
            )
            if resp.ok:
                meta = resp.json()
                universe = meta.get("universe", [])
                result["perp_count"] = len(universe)
        except Exception:
            pass

        try:
            # Spot meta
            resp = requests.post(
                _HYPERLIQUID_URL,
                json={"type": "spotMeta"},
                headers={**_HTTP_HEADERS, "Content-Type": "application/json"},
                timeout=_HTTP_TIMEOUT,
            )
            if resp.ok:
                meta = resp.json()
                universe = meta.get("universe", [])
                result["spot_count"] = len(universe)
        except Exception:
            pass

        return result

    def _build_record(
        self, coin: dict, market_meta: dict
    ) -> DataRecord:
        """构建 DataRecord。"""
        now = datetime.now(timezone.utc).isoformat()

        price = float(coin.get("current_price", 0) or 0)
        market_cap = float(coin.get("market_cap", 0) or 0)
        total_volume_24h = float(coin.get("total_volume", 0) or 0)
        circ_supply = float(coin.get("circulating_supply", 0) or 0)
        total_supply = float(coin.get("total_supply", 0) or 0)
        max_supply = float(coin.get("max_supply", 0) or 0)

        # 年化收入代理：24h交易量 * 费率 * 365
        annualized_revenue = total_volume_24h * _PERP_FEE_RATE * 365

        # 供应量缩减：已销毁 = max_supply - circulating_supply
        burned_pct = 0.0
        if max_supply > 0 and circ_supply > 0:
            burned_pct = (max_supply - circ_supply) / max_supply * 100

        # 回购销毁比例：流通量占总供应量比（越低说明锁仓/销毁越多）
        circulating_ratio = circ_supply / total_supply * 100 if total_supply > 0 else 0.0

        metrics: dict[str, Any] = {
            "price_usd": price,
            "market_cap_usd": market_cap,
            "circulating_supply": circ_supply,
            "total_supply": total_supply,
            "max_supply": max_supply,
            "volume_24h_usd": total_volume_24h,
            "annualized_revenue_usd": round(annualized_revenue, 2),
            "perp_market_count": market_meta.get("perp_count", 0),
            "spot_market_count": market_meta.get("spot_count", 0),
            "burned_pct": round(burned_pct, 4),
            "circulating_ratio_pct": round(circulating_ratio, 2),
            "buyback_allocation_pct": _HYPE_BUYBACK_ALLOCATION * 100,
            # E5 信号数据
            "supply_shrinkage_intensity": round(burned_pct / 100, 4),
            # E6 信号数据
            "value_capture_delta": round(annualized_revenue / market_cap, 6) if market_cap > 0 else 0.0,
        }

        timeseries = [
            {
                "date": coin.get("last_updated", ""),
                "price": price,
                "volume_24h": total_volume_24h,
                "market_cap": market_cap,
            }
        ]

        return DataRecord(
            source=self.source,
            category=self.category,
            sub_category="hype_token",
            timestamp=now,
            metrics=metrics,
            events=[],
            timeseries=timeseries,
            raw={
                "coingecko_id": coin.get("id", ""),
                "symbol": coin.get("symbol", ""),
                "name": coin.get("name", ""),
                "market_cap_rank": coin.get("market_cap_rank"),
                "ath": coin.get("ath"),
                "atl": coin.get("atl"),
                "price_change_24h_pct": coin.get("price_change_percentage_24h"),
            },
        )


if __name__ == "__main__":
    c = HypeNativeCollector()
    recs = c.fetch({})
    if recs:
        r = recs[0]
        import json
        print("metrics:")
        for k, v in r.metrics.items():
            print(f"  {k}: {v}")
    else:
        print("FAIL-OPEN: empty")
