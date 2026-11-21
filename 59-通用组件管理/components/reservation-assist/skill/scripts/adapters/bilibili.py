"""演出票适配器 B：会员购 H5 接口。"""

from __future__ import annotations

from .base import BaseHttpAdapter, json_items


class Bilibili(BaseHttpAdapter):
    NAME = "bilibili"
    MIN_INTERVAL_MS = 1000
    DEFAULT_INTERVAL_MS = 1000
    PERFORMANCE = True
    REQUIRES_LOGIN = True

    def parse_items(self, body: str, target: dict) -> list[dict]:
        items = []
        for row in json_items(body, "data.tickets"):
            items.append(
                {
                    "target_id": row.get("id") or target.get("target_id", ""),
                    "session": row.get("session") or target.get("session", ""),
                    "tier": row.get("sku_name", ""),
                    "price": row.get("price"),
                    "remaining": row.get("stock", 0),
                    "url": row.get("link") or target.get("url", ""),
                }
            )
        return items
