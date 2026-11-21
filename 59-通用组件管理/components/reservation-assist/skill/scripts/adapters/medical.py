"""医院挂号/疫苗适配器：只读号源，不填写就诊人信息。"""

from __future__ import annotations

from .base import BaseHttpAdapter, json_items


class Medical(BaseHttpAdapter):
    NAME = "medical"
    MIN_INTERVAL_MS = 3000
    DEFAULT_INTERVAL_MS = 3000
    PERFORMANCE = False
    REQUIRES_LOGIN = True

    def parse_items(self, body: str, target: dict) -> list[dict]:
        items = []
        for row in json_items(body, "slots"):
            items.append(
                {
                    "target_id": row.get("doctor") or target.get("target_id", ""),
                    "session": "{} {}".format(row.get("dept", ""), row.get("period", "")).strip(),
                    "tier": row.get("dept", ""),
                    "price": row.get("fee"),
                    "remaining": row.get("left", 0),
                    "url": row.get("link") or target.get("url", ""),
                }
            )
        return items
