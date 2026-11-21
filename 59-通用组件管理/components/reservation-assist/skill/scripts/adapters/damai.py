"""演出票适配器 A：H5 场次/票档接口。"""

from __future__ import annotations

from .base import BaseHttpAdapter, json_items


class Damai(BaseHttpAdapter):
    NAME = "damai"
    MIN_INTERVAL_MS = 1000
    DEFAULT_INTERVAL_MS = 1000
    PERFORMANCE = True
    REQUIRES_LOGIN = True

    def parse_items(self, body: str, target: dict) -> list[dict]:
        items = []
        for row in json_items(body, "sessions"):
            items.append(
                {
                    "target_id": row.get("session_id") or target.get("target_id", ""),
                    "session": row.get("name") or target.get("session", ""),
                    "tier": row.get("tier", ""),
                    "price": row.get("price"),
                    "remaining": row.get("remaining", 0),
                    "url": row.get("url") or target.get("url", ""),
                }
            )
        return items
