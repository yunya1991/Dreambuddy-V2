"""演出票适配器 C：H5 场次页面。"""

from __future__ import annotations

from .base import BaseHttpAdapter, json_items


class Maoyan(BaseHttpAdapter):
    NAME = "maoyan"
    MIN_INTERVAL_MS = 1500
    DEFAULT_INTERVAL_MS = 1500
    PERFORMANCE = True
    REQUIRES_LOGIN = True

    def parse_items(self, body: str, target: dict) -> list[dict]:
        items = []
        for row in json_items(body, "shows"):
            items.append(
                {
                    "target_id": row.get("show_id") or target.get("target_id", ""),
                    "session": row.get("session") or target.get("session", ""),
                    "tier": row.get("tier", ""),
                    "price": row.get("price"),
                    "remaining": row.get("left", 0),
                    "url": row.get("link") or target.get("url", ""),
                }
            )
        return items
