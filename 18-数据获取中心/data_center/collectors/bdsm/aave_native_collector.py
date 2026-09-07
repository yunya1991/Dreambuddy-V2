# -*- coding: utf-8 -*-
"""AAVE 原生数据采集器 — 从 api.v3.aave.com/graphql 获取协议数据。

GraphQL API（无需 Key），直接 POST 查询。
采集字段（对齐 BDSM E5/E6/E7 信号需求）：
  - total_market_size_usd: 总市场规模（TVL+债务）
  - total_available_liquidity_usd: 可用流动性
  - total_debt_usd: 总债务
  - reserves: 各储备资产 [{symbol, usd, supply_apy, borrow_apy, total_debt}]
  - chain_breakdown: 按链分布 [{chain, market_size, liquidity}]
  - revenue_proxy_usd: 协议收入代理（borrow spread * total_debt * reserve_factor）

FAIL-OPEN: 网络异常/解析失败 → 返回空列表，不抛异常。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord

logger = logging.getLogger("data_center.collectors.bdsm.aave")

_GRAPHQL_URL = "https://api.v3.aave.com/graphql"
_HTTP_TIMEOUT = 20
_HTTP_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (DreamBuddy-BDSM/1.0)",
}

# AAVE V3 部署的主网链 ID（从 chains 查询获取，排除测试网）
_CHAIN_IDS = [
    1,       # Ethereum
    42161,   # Arbitrum
    43114,   # Avalanche
    8453,    # Base
    56,      # BSC
    42220,   # Celo
    100,     # Gnosis
    59144,   # Linea
    1088,    # Metis
    10,      # Optimism
    137,     # Polygon
    534352,  # Scroll
    1868,    # Soneium
    146,     # Sonic
    324,     # zkSync
    9745,    # Plasma
    57073,   # Ink
    5000,    # Mantle
    4326,    # MegaETH
    196,     # X Layer
    143,     # Monad
]

_MARKETS_QUERY = """
query {
  markets(request: {chainIds: [%s]}) {
    name
    chain { name chainId }
    totalMarketSize
    totalAvailableLiquidity
    reserves {
      underlyingToken { symbol name decimals }
      size { amount { value } usd }
      usdExchangeRate
      supplyInfo { apy { value } total { value } }
      borrowInfo { apy { value } total { amount { value } usd } }
    }
  }
}
""" % ", ".join(str(c) for c in _CHAIN_IDS)


class AaveNativeCollector(BaseCollector):
    """AAVE 原生数据采集器 — api.v3.aave.com GraphQL。"""

    source = "bdsm_aave"
    category = "bdsm"

    def is_available(self) -> bool:
        return True  # 公共 GraphQL，无需 Key

    def fetch(self, params: dict) -> list[DataRecord]:
        """查询 AAVE V3 markets 数据，返回 DataRecord。"""
        try:
            resp = requests.post(
                _GRAPHQL_URL,
                json={"query": _MARKETS_QUERY},
                headers=_HTTP_HEADERS,
                timeout=_HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            logger.warning("AAVE fetch failed: %s", exc)
            return []  # FAIL-OPEN

        if "errors" in payload or not payload.get("data"):
            logger.warning("AAVE GraphQL errors: %s", payload.get("errors"))
            return []

        markets = payload["data"].get("markets", [])
        if not markets:
            return []

        return [self._parse_markets(markets)]

    def _parse_markets(self, markets: list[dict]) -> DataRecord:
        """解析 markets 为 DataRecord。"""
        now = datetime.now(timezone.utc).isoformat()

        total_market_size = 0.0
        total_liquidity = 0.0
        chain_breakdown: list[dict] = []
        all_reserves: list[dict] = []

        for m in markets:
            m_size = float(m.get("totalMarketSize", 0) or 0)
            m_liq = float(m.get("totalAvailableLiquidity", 0) or 0)
            total_market_size += m_size
            total_liquidity += m_liq

            chain_info = m.get("chain", {})
            chain_breakdown.append({
                "chain": chain_info.get("name", ""),
                "chain_id": chain_info.get("chainId", 0),
                "market_size_usd": round(m_size, 2),
                "available_liquidity_usd": round(m_liq, 2),
            })

            for r in m.get("reserves", []):
                tok = r.get("underlyingToken", {})
                sz = r.get("size", {})
                usd_val = float(sz.get("usd", 0) or 0) if isinstance(sz, dict) else 0.0
                supply_info = r.get("supplyInfo", {}) or {}
                borrow_info = r.get("borrowInfo", {}) or {}
                supply_apy = float(
                    (supply_info.get("apy", {}) or {}).get("value", 0) or 0
                )
                borrow_apy = float(
                    (borrow_info.get("apy", {}) or {}).get("value", 0) or 0
                )
                borrow_total_usd = 0.0
                bt = borrow_info.get("total", {})
                if isinstance(bt, dict):
                    borrow_total_usd = float(bt.get("usd", 0) or 0)
                if usd_val > 0:
                    all_reserves.append({
                        "symbol": tok.get("symbol", ""),
                        "name": tok.get("name", ""),
                        "chain": chain_info.get("name", ""),
                        "usd": round(usd_val, 2),
                        "supply_apy": round(supply_apy, 6),
                        "borrow_apy": round(borrow_apy, 6),
                        "borrow_total_usd": round(borrow_total_usd, 2),
                    })

        # 排序按 USD 降序
        all_reserves.sort(key=lambda x: -x["usd"])

        # 收入代理：borrow spread = (borrow_apy - supply_apy) * borrow_total
        # 实际协议收入 = spread * reserve_factor（约 10-30%）
        revenue_proxy = 0.0
        for r in all_reserves:
            spread = r["borrow_apy"] - r["supply_apy"]
            revenue_proxy += max(0, spread) * r["borrow_total_usd"]

        metrics: dict[str, Any] = {
            "total_market_size_usd": round(total_market_size, 2),
            "total_available_liquidity_usd": round(total_liquidity, 2),
            "total_debt_usd": round(total_market_size - total_liquidity, 2),
            "revenue_proxy_usd": round(revenue_proxy, 2),
            "chain_count": len(chain_breakdown),
            "reserve_count": len(all_reserves),
            # E7 集中度：最大储备占比
            "top_reserve_pct": round(
                all_reserves[0]["usd"] / total_liquidity * 100, 2
            ) if all_reserves and total_liquidity > 0 else 0.0,
        }

        # 链分布前3（E7 集中度）
        chain_breakdown.sort(key=lambda x: -x["market_size_usd"])
        for i, cb in enumerate(chain_breakdown[:3]):
            metrics[f"top_chain_{i+1}_name"] = cb["chain"]
            metrics[f"top_chain_{i+1}_pct"] = round(
                cb["market_size_usd"] / total_market_size * 100, 2
            ) if total_market_size > 0 else 0.0

        return DataRecord(
            source=self.source,
            category=self.category,
            sub_category="aave_markets",
            timestamp=now,
            metrics=metrics,
            events=[],
            timeseries=all_reserves[:20],
            raw={
                "url": _GRAPHQL_URL,
                "chains": [cb["chain"] for cb in chain_breakdown],
                "chain_breakdown": chain_breakdown,
            },
        )


if __name__ == "__main__":
    c = AaveNativeCollector()
    recs = c.fetch({})
    if recs:
        r = recs[0]
        import json
        print("metrics:")
        for k, v in r.metrics.items():
            print(f"  {k}: {v}")
        print(f"\ntop reserves ({len(r.timeseries)}):")
        for res in r.timeseries[:5]:
            print(f"  {res}")
    else:
        print("FAIL-OPEN: empty")
