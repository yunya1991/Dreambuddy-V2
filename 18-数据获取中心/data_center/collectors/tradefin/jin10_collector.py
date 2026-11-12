"""金十数据快讯采集器 — SPEC §3.2 P1-A。

接口：`https://flash-api.jin10.com/get_flash_list?channel=-8200&vip=1`
需要公开 Web 端请求头 `x-app-id` / `x-version`（页面自带，非登录凭据）。

实测 2026-11-11：返回 `{"status":200,"data":[{"id","time","data":{"content","title"}}]}`，
`time` 为北京时间（无时区）。

宏观日历：SPEC §3.2 表格要求"宏观日历+快讯"，但金十日历接口
`datacenter-api.jin10.com/reports/list_v2` 与 `cdn.jin10.com/data_center/releases/calendar`
于 2026-11-11 实测分别返回 502 / NoSuchKey，属源站下线；CPI/非农日历已由
P0-C 的官方 BLS `macro_calendar_collector` 覆盖，故此处显式禁用而不虚报成功
（`CALENDAR_ENABLED=False`），避免把"不可得"计成"抓取失败"或"零事件"。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from data_center.collectors.tradefin._classify import classify
from data_center.collectors.tradefin._guard import CircuitOpen, SourceGuard
from data_center.collectors.tradefin._http import get_text
from data_center.collectors.tradefin._result import CollectResult
from data_center.collectors.tradefin._util import (
    cn_time_iso,
    now_utc,
    split_title_body,
    to_iso,
)
from data_center.events.body_store import body_ref, make_body_id

logger = logging.getLogger(__name__)

SOURCE = "jin10"
FLASH_URL = "https://flash-api.jin10.com/get_flash_list"
CALENDAR_ENABLED = False  # 源站日历接口 2026-11-11 实测下线（502 / NoSuchKey）
HEADERS = {
    "x-app-id": "bVBF4FyRTn5NJF5n",
    "x-version": "1.0.0",
    "User-Agent": "dreambuddy-research admin@dreambuddy.local",
    "Referer": "https://www.jin10.com/",
}

guard = SourceGuard(SOURCE, min_interval=1.5)


def parse_flash(payload) -> list[dict]:
    rows = (payload or {}).get("data") or []
    return [row for row in rows if isinstance(row, dict)]


def items_to_result(
    items: list[dict], *, days: int = 2, now: datetime | None = None
) -> CollectResult:
    now = now or now_utc()
    start = now - timedelta(days=days)
    fetched_at = to_iso(now)
    result = CollectResult()

    for item in items:
        if (item.get("extras") or {}).get("ad"):
            continue
        data = item.get("data") or {}
        text = str(data.get("content") or data.get("title") or "").strip()
        if not text:
            continue
        try:
            published = cn_time_iso(item["time"])
        except (KeyError, ValueError, TypeError):
            continue
        ts = datetime.fromisoformat(published.replace("Z", "+00:00"))
        if not (start <= ts <= now):
            continue

        title, _ = split_title_body(text)
        type_, symbols = classify(title, text)
        important = bool(item.get("important"))
        url = f"https://flash.jin10.com/detail/{item.get('id')}"
        body_id = make_body_id(SOURCE, url, published)

        result.events.append(
            {
                "type": type_,
                "subtype": "important" if important else "flash",
                "symbols": symbols,
                "sector": "macro",
                "event_time": published,
                "available_at": published,
                "source": SOURCE,
                "source_url": url,
                "title": title,
                "body_ref": body_ref(body_id),
                "confidence": 0.75 if important else 0.6,
                "quality": "B",
            }
        )
        result.bodies.append(
            {
                "id": body_id,
                "source": SOURCE,
                "url": url,
                "title": title,
                "content_text": text,
                "date_published": published,
                "fetched_at": fetched_at,
                "fetch_ok": True,
                "lang": "zh",
            }
        )
    return result


def fetch(days: int = 2, now: datetime | None = None) -> CollectResult:
    now = now or now_utc()
    try:
        guard.before_request()
        text = get_text(
            FLASH_URL,
            headers=HEADERS,
            params={"channel": "-8200", "vip": "1"},
            timeout=20,
            retries=2,
            interval=0.0,
        )
        guard.record(True)
    except CircuitOpen as e:
        logger.warning("[jin10] %s，跳过", e)
        return CollectResult()
    except Exception as e:  # noqa: BLE001 — FAIL-OPEN
        guard.record(False)
        logger.warning("[jin10] 抓取失败：%s", e)
        return CollectResult()

    return items_to_result(parse_flash(json.loads(text)), days=days, now=now)


def guard_stats() -> dict:
    return guard.stats()
