"""CoinGecko coin/market_cap collector — 无 Key 公共 API，为 CoinFundamentalRanker 提供单币数据。

API 端点（HTTPS GET 无需 Key，10-30 req/min）：
  - GET https://api.coingecko.com/api/v3/coins/{id}
      → market_cap / total_supply / circulating_supply / max_supply / current_price
  - GET https://api.coingecko.com/api/v3/coins/{id}/market_chart?days=30
      → 历史 prices / market_caps / total_volumes

用于 CoinFundamentalRanker 的 MC/Fees Mean Reversion 信号（market_cap 分母）。

fail-open：网络不通 / HTTP 非 200（非 429） → 返回空列表，不抛异常。
429 限流 → 抛 RateLimitError（由调度器退避重试）。
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record
from data_center.core.errors import RateLimitError


_BASE = "https://api.coingecko.com/api/v3"


class CoinGeckoCollector(BaseCollector):
    source = "coingecko"
    category = "coin"

    def is_available(self) -> bool:
        # 公共 API 无需 Key → 默认可用，只要网络可达
        return True

    # ------------------------------------------------------------------
    # 统一入口
    # ------------------------------------------------------------------
    def fetch(self, params: dict) -> list[DataRecord]:
        route = params.get("route")
        try:
            if route == "coin_info":
                return self._fetch_coin_info(params.get("coin_id", ""))
            if route == "coin_chart":
                return self._fetch_coin_chart(
                    params.get("coin_id", ""),
                    int(params.get("days", 30)),
                )
            # 未知路由：静默返回空，避免意外触发网络
            return []
        except RateLimitError:
            raise
        except Exception:
            # fail-open：其它任何异常 → 空列表
            return []

    # ------------------------------------------------------------------
    # HTTP helper
    # ------------------------------------------------------------------
    @staticmethod
    def _get(url: str, timeout: int = 20):
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 429:
            raise RateLimitError(f"CoinGecko 429 限流: {url}")
        if not resp.ok:
            raise RuntimeError(f"CoinGecko HTTP {resp.status_code}: {url}")
        return resp.json()

    # ------------------------------------------------------------------
    # routes
    # ------------------------------------------------------------------
    def _fetch_coin_info(self, coin_id: str) -> list[DataRecord]:
        """GET /api/v3/coins/{id} → market_cap / supply 数据。

        用于 CoinFundamentalRanker 的 MC/Fees Mean Reversion 信号。
        """
        if not coin_id:
            return []
        data = self._get(f"{_BASE}/coins/{coin_id}")
        if not isinstance(data, dict):
            return []
        md = data.get("market_data")
        if not isinstance(md, dict):
            return []

        # 安全提取嵌套字段（market_cap / current_price 是 {usd: float} 字典）
        def _price(key: str) -> float:
            v = md.get(key)
            if isinstance(v, dict):
                return float(v.get("usd") or 0.0)
            if v is None:
                return 0.0
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0

        now = datetime.now(timezone.utc).astimezone().isoformat()
        rec = DataRecord(
            source="coingecko",
            category="coin",
            sub_category=coin_id,
            timestamp=now,
            metrics={
                "coin_id": coin_id,
                "current_price_usd": _price("current_price"),
                "market_cap_usd": _price("market_cap"),
                "total_supply": _price("total_supply"),
                "circulating_supply": _price("circulating_supply"),
                "max_supply": _price("max_supply"),
            },
            events=[],
            timeseries=[],
            raw={"url": f"/api/v3/coins/{coin_id}"},
        )
        validate_record(rec)
        return [rec]

    def _fetch_coin_chart(self, coin_id: str, days: int = 30) -> list[DataRecord]:
        """GET /api/v3/coins/{id}/market_chart?days={days} → 历史 prices/market_caps。

        用于 CoinFundamentalRanker 的价格趋势/均值回归信号。
        """
        if not coin_id:
            return []
        days = max(1, min(days, 90))  # 限制 1-90 天
        data = self._get(f"{_BASE}/coins/{coin_id}/market_chart?days={days}")
        if not isinstance(data, dict):
            return []

        prices = data.get("prices") or []
        market_caps = data.get("market_caps") or []
        total_volumes = data.get("total_volumes") or []
        if not prices:
            return []

        # 合并 prices / market_caps / total_volumes 到统一时序列
        # 按 index 对齐（CoinGecko 保证三者时间戳一致）
        ts = []
        for i, item in enumerate(prices):
            try:
                ts_ms = int(item[0])
                price = float(item[1])
            except (TypeError, IndexError, ValueError):
                continue
            dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date().isoformat()
            mcap = 0.0
            vol = 0.0
            if i < len(market_caps):
                try:
                    mcap = float(market_caps[i][1])
                except (TypeError, IndexError, ValueError):
                    pass
            if i < len(total_volumes):
                try:
                    vol = float(total_volumes[i][1])
                except (TypeError, IndexError, ValueError):
                    pass
            ts.append({"date": dt, "price": price, "market_cap": mcap, "volume": vol})

        if not ts:
            return []

        now = datetime.now(timezone.utc).astimezone().isoformat()
        rec = DataRecord(
            source="coingecko",
            category="coin",
            sub_category=f"chart_{coin_id}",
            timestamp=now,
            metrics={
                "coin_id": coin_id,
                "days": days,
                "points": len(ts),
                "latest_price": ts[-1]["price"],
                "latest_market_cap": ts[-1]["market_cap"],
            },
            events=[],
            timeseries=ts,
            raw={"url": f"/api/v3/coins/{coin_id}/market_chart?days={days}"},
        )
        validate_record(rec)
        return [rec]
