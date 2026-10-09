"""CoinMarketCalCollector — 加密技术升级事件采集（CoinMarketCal API）。

SPEC-Phase2 §6.1:
  - 数据源: CoinMarketCal RESTful API（coinmarketcal.com/en/api）
  - 事件类型映射: Hard Fork/Soft Fork/Mainnet Launch/Protocol Upgrade/Listing/Delisting → tech_upgrade
  - direction 动态判定: 价格趋势 + 社区情绪(percentage) + 子类型语义，阈值 ±0.3
  - FAIL-OPEN: API 失败返回空列表
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record

logger = logging.getLogger(__name__)


class CoinMarketCalCollector(BaseCollector):
    """CoinMarketCal 加密事件采集器。"""

    source = "coinmarketcal"
    category = "protocol"  # 协议级升级（硬分叉/主网上线等），sub_category=tech_upgrade

    # CoinMarketCal category → event_type 映射（仅采集 tech_upgrade 相关）
    CATEGORY_MAP = {
        "Hard Fork": "tech_upgrade",
        "Soft Fork": "tech_upgrade",
        "Mainnet Launch": "tech_upgrade",
        "Protocol Upgrade": "tech_upgrade",
        "Exchange Listing": "tech_upgrade",
        "Exchange Delisting": "tech_upgrade",
    }

    # 子类型语义偏置（SPEC §6.1 M3）
    SUBTYPE_BIAS = {
        "Exchange Listing": 0.3,
        "Mainnet Launch": 0.3,
        "Exchange Delisting": -0.3,
    }

    def is_available(self) -> bool:
        """需 API Key，由 config 提供；无 Key 时不可用。"""
        return bool(self.config.get("api_key"))

    def fetch(self, params: dict) -> list[DataRecord]:
        """
        采集未来 N 天的加密技术升级事件。

        Args:
            params:
                days_ahead: int = 7  # 前瞻天数
                coins: list[str] | None = None  # 筛选币种
                price_trend: float | None = None  # close 20 周期斜率，用于 direction 判定

        Returns:
            DataRecord 列表，失败时返回空列表（FAIL-OPEN）。
        """
        days_ahead = params.get("days_ahead", 7)
        coins = params.get("coins")
        price_trend = params.get("price_trend")

        try:
            data = self._fetch_api(days_ahead, coins)
        except Exception as e:
            logger.warning("CoinMarketCal 采集失败，FAIL-OPEN: %s", e)
            return []

        if not data:
            return []

        return self._parse_events(data, price_trend)

    def _fetch_api(self, days_ahead: int, coins: list[str] | None) -> list[dict]:
        """调用 CoinMarketCal API，返回原始事件列表。

        API: https://developers.coinmarketcal.com/v1/events
        认证: x-api-key header（免费档 10-30 calls/min）
        FAIL-OPEN: 无 API Key / 网络异常 / 非 200 → 返回 []
        """
        api_key = self.config.get("api_key")
        if not api_key:
            logger.debug("CoinMarketCal: 无 API Key，FAIL-OPEN 返回空")
            return []

        try:
            import requests
        except ImportError:
            logger.warning("CoinMarketCal: requests 未安装，FAIL-OPEN")
            return []

        from datetime import timedelta

        now = datetime.now(timezone.utc)
        date_start = now.strftime("%Y-%m-%d")
        date_end = (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

        url = "https://developers.coinmarketcal.com/v1/events"
        params = {
            "dateRangeStart": date_start,
            "dateRangeEnd": date_end,
        }
        if coins:
            params["coins"] = ",".join(coins)

        headers = {"x-api-key": api_key}

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            if resp.status_code != 200:
                logger.warning(
                    "CoinMarketCal API HTTP %s: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return []
            body = resp.json()
            return body.get("body", []) if isinstance(body, dict) else []
        except Exception as e:
            logger.warning("CoinMarketCal API 调用异常，FAIL-OPEN: %s", e)
            return []

    def _parse_events(
        self, data: list[dict], price_trend: float | None
    ) -> list[DataRecord]:
        """解析 API 响应，构造 DataRecord 列表（仅保留 tech_upgrade 类型）。"""
        records: list[DataRecord] = []
        for item in data:
            category = item.get("category", "")
            event_type = self.CATEGORY_MAP.get(category)
            if event_type is None:
                # 非 tech_upgrade 类型，过滤
                continue

            percentage = float(item.get("percentage", 50.0))
            direction = self._compute_direction(category, percentage, price_trend)

            rec = DataRecord(
                source=self.source,
                category=self.category,
                sub_category=event_type,
                timestamp=datetime.now(timezone.utc).astimezone().isoformat(),
                metrics={
                    "event_type": event_type,
                    "direction": direction,
                    "impact_level": round(percentage / 100.0, 4),
                    "is_scheduled": True,
                    "coin": (item.get("coin") or {}).get("symbol", ""),
                    "date_event": item.get("date_event", ""),
                },
                events=[{
                    "title": item.get("title", ""),
                    "coin": (item.get("coin") or {}).get("symbol", ""),
                    "date_event": item.get("date_event", ""),
                    "category": category,
                    "percentage": percentage,
                    "source": item.get("source", ""),
                    "proof": item.get("proof", ""),
                }],
                timeseries=[],
                raw=item,
            )
            validate_record(rec)
            records.append(rec)
        return records

    @staticmethod
    def _compute_direction(
        category: str, percentage: float, price_trend: float | None
    ) -> str:
        """动态判定 direction（SPEC §6.1 M3）。

        加权因子:
          - 社区情绪(percentage): >60% → +0.3, <40% → -0.3
          - 价格趋势(price_trend): >0 → +0.4, <0 → -0.4
          - 子类型语义: listing/mainnet → +0.3, delisting → -0.3

        判定: score ≥ 0.3 → long, ≤ -0.3 → short, 否则 neutral。
        """
        score = 0.0

        # 社区情绪
        if percentage > 60:
            score += 0.3
        elif percentage < 40:
            score -= 0.3

        # 价格趋势
        if price_trend is not None:
            if price_trend > 0:
                score += 0.4
            elif price_trend < 0:
                score -= 0.4

        # 子类型语义
        score += CoinMarketCalCollector.SUBTYPE_BIAS.get(category, 0.0)

        if score >= 0.3:
            return "long"
        elif score <= -0.3:
            return "short"
        return "neutral"
