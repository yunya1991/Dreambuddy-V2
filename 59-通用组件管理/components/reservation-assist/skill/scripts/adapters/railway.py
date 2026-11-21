"""铁路余票/候补适配器：页面结构变化只改本文件。"""

from __future__ import annotations

from .base import BaseHttpAdapter, json_items


class Railway(BaseHttpAdapter):
    NAME = "railway"
    MIN_INTERVAL_MS = 1500
    DEFAULT_INTERVAL_MS = 1500
    PERFORMANCE = False
    REQUIRES_LOGIN = True

    def parse_items(self, body: str, target: dict) -> list[dict]:
        items = []
        for row in json_items(body, "trains"):
            items.append(
                {
                    "target_id": row.get("train_no") or target.get("target_id", ""),
                    "session": row.get("date") or target.get("session", ""),
                    "tier": row.get("seat", ""),
                    "price": row.get("price"),
                    "remaining": row.get("remaining", 0),
                    "url": row.get("url") or target.get("url", ""),
                }
            )
        return items
