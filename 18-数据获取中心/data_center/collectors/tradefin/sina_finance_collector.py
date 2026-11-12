"""新浪财经 7×24 快讯采集器 — SPEC §3.2 P1-A。

数据源：`https://zhibo.sina.com.cn/api/zhibo/feed`（公开 JSON，兼容 callback 包裹）
实测 2026-11-11：`zhibo_id=152` 财经频道，返回 `rich_text` / `docurl` /
`create_time`（北京时间，无时区）。

输出（SPEC §3.1）：
  - `event_time = available_at = create_time`（Asia/Shanghai → UTC）
  - `body_ref = bodies.jsonl#<id>`，正文为快讯全文（point-in-time 快照）
  - `quality=B`：门户快讯属转载源，不是官方一手
限频/熔断：`_guard.SourceGuard`（1.5s 间隔，滑动窗口失败率 >30% 熔断）。
"""

from __future__ import annotations

import json
import logging
import re
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

SOURCE = "sina_finance"
FEED_URL = "https://zhibo.sina.com.cn/api/zhibo/feed"
PAGE_SIZE = 100
HEADERS = {
    "User-Agent": "dreambuddy-research admin@dreambuddy.local",
    "Referer": "https://finance.sina.com.cn/7x24/",
}
FALLBACK_URL = "https://finance.sina.com.cn/7x24/"

guard = SourceGuard(SOURCE, min_interval=1.5)

_JSONP_RE = re.compile(r"^[^(]*\((.*)\)\s*;?\s*$", re.S)


def _loads(text: str):
    raw = str(text or "").strip()
    m = _JSONP_RE.match(raw)
    if m:
        raw = m.group(1)
    return json.loads(raw)


def parse_feed(payload) -> list[dict]:
    """从 API 响应（dict 或 JSONP 文本）抽取快讯条目。"""
    if isinstance(payload, str):
        payload = _loads(payload)
    data = ((payload or {}).get("result") or {}).get("data") or {}
    items = (data.get("feed") or {}).get("list") or []
    return [item for item in items if isinstance(item, dict)]


def items_to_result(
    items: list[dict], *, days: int = 7, now: datetime | None = None
) -> CollectResult:
    now = now or now_utc()
    start = now - timedelta(days=days)
    fetched_at = to_iso(now)
    result = CollectResult()

    for item in items:
        text = str(item.get("rich_text") or "").strip()
        if not text:
            continue
        try:
            published = cn_time_iso(item["create_time"])
        except (KeyError, ValueError, TypeError):
            continue
        ts = datetime.fromisoformat(published.replace("Z", "+00:00"))
        if not (start <= ts <= now):
            continue

        title, _ = split_title_body(text)
        type_, symbols = classify(title, text)
        url = str(item.get("docurl") or "").strip() or FALLBACK_URL
        body_id = make_body_id(SOURCE, url, published)
        revision = None
        if item.get("update_time"):
            try:
                revision = cn_time_iso(item["update_time"])
            except (ValueError, TypeError):
                revision = None

        result.events.append(
            {
                "type": type_,
                "subtype": ",".join(
                    str(tag.get("name")) for tag in (item.get("tag") or []) if tag.get("name")
                )
                or None,
                "symbols": symbols,
                "sector": "macro",
                "event_time": published,
                "available_at": published,
                "source": SOURCE,
                "source_url": url,
                "title": title,
                "body_ref": body_ref(body_id),
                "confidence": 0.6,
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
                "revision_time": revision,
                "fetch_ok": True,
                "lang": "zh",
            }
        )
    return result


def fetch(days: int = 7, now: datetime | None = None, pages: int = 1) -> CollectResult:
    now = now or now_utc()
    result = CollectResult()
    for page in range(1, int(pages) + 1):
        try:
            guard.before_request()
        except CircuitOpen as e:
            logger.warning("[sina_finance] %s，跳过", e)
            break
        try:
            text = get_text(
                FEED_URL,
                headers=HEADERS,
                params={
                    "page": str(page),
                    "page_size": str(PAGE_SIZE),
                    "zhibo_id": "152",
                    "tag_id": "0",
                    "dire": "f",
                    "dpc": "1",
                },
                timeout=20,
                retries=2,
                interval=0.0,
            )
            guard.record(True)
        except Exception as e:  # noqa: BLE001 — 单页失败 FAIL-OPEN
            guard.record(False)
            logger.warning("[sina_finance] 第 %d 页抓取失败：%s", page, e)
            continue
        chunk = items_to_result(parse_feed(text), days=days, now=now)
        result.events.extend(chunk.events)
        result.bodies.extend(chunk.bodies)
        if not chunk.events:
            break  # 本页无窗口内新条目，后续页更旧
    return result


def guard_stats() -> dict:
    return guard.stats()
