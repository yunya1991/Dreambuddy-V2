"""政务/签证/车管所/场馆适配器：页面轮询，低速只读。"""

from __future__ import annotations

import json

from .base import BaseHttpAdapter, json_items


class Gov(BaseHttpAdapter):
    NAME = "gov"
    MIN_INTERVAL_MS = 5000
    DEFAULT_INTERVAL_MS = 5000
    PERFORMANCE = False
    REQUIRES_LOGIN = False  # 公开预约时段页面，只读轮询

    def parse_items(self, body: str, target: dict) -> list[dict]:
        items = []
        try:
            rows = json_items(body, "slots")
        except ValueError:
            rows = []
        for row in rows:
            items.append(
                {
                    "target_id": row.get("site") or target.get("target_id", ""),
                    "session": "{} {}".format(row.get("date", ""), row.get("period", "")).strip(),
                    "tier": row.get("period", ""),
                    "price": row.get("fee"),
                    "remaining": row.get("left", 0),
                    "url": row.get("link") or target.get("url", ""),
                }
            )
        if items:
            return items
        return self._status_items(body, target)

    def _status_items(self, body: str, target: dict) -> list[dict]:
        """状态型接口（如场馆开放时段 timelist）：状态变化即一条命中。"""
        try:
            payload = json.loads(body)
        except ValueError:
            return []
        data = payload.get("data") if isinstance(payload, dict) else None
        timelist = (data or {}).get("timelist") if isinstance(data, dict) else None
        if not isinstance(timelist, dict):
            return []
        opened = str(timelist.get("opened") or "")
        closed = str(timelist.get("closed") or "")
        return [
            {
                "target_id": target.get("target_id", ""),
                "session": "{}-{}".format(opened, closed),
                "tier": "status",
                "price": None,
                "remaining": 1 if payload.get("status") == 1 else 0,
                "url": target.get("url", ""),
            }
        ]
