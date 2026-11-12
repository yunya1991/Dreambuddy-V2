"""华尔街见闻采集器 — SPEC §3.2 P1-A。

两个公开接口（同一 host，限频）：
  - 快讯：`/apiv1/content/lives?channel=global-channel`（含 content_text）
  - 深度：`/apiv1/content/articles?channel=global` 列表 + `/articles/{id}?extract=1` 详情正文

深度文章是本 SPEC 中最有价值的源（§8.2：F3 主导主张质量最高），因此正文必须入库：
  - 列表项先产出事件（title / display_time / uri）
  - 详情正文写入 bodies.jsonl（point-in-time 快照），事件只存 `body_ref`
  - `known_body_ids` 已存在时跳过详情请求（幂等 + 省流量）

quality=B（媒体源）；限频 1.2s/请求；失败率 >30% 熔断。
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
    html_to_text,
    now_utc,
    split_title_body,
    to_iso,
    unix_to_iso,
)
from data_center.events.body_store import body_ref, make_body_id

logger = logging.getLogger(__name__)

SOURCE = "wallstreetcn"
LIVES_URL = "https://api-one.wallstcn.com/apiv1/content/lives"
ARTICLES_URL = "https://api-one.wallstcn.com/apiv1/content/articles"
DETAIL_URL = "https://api-one.wallstcn.com/apiv1/content/articles/{id}"
HEADERS = {
    "User-Agent": "dreambuddy-research admin@dreambuddy.local",
    "Referer": "https://wallstreetcn.com/",
    "Accept": "application/json",
}

guard = SourceGuard(SOURCE, min_interval=1.2)


def _items(payload, key: str = "items") -> list[dict]:
    data = (payload or {}).get("data") or {}
    items = data.get(key) or []
    return [item for item in items if isinstance(item, dict)]


def parse_lives(payload) -> list[dict]:
    return _items(payload)


def parse_articles(payload) -> list[dict]:
    return _items(payload)


def _in_window(iso: str, start: datetime, now: datetime) -> bool:
    try:
        ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return False
    return start <= ts <= now


def lives_to_result(
    items: list[dict], *, days: int = 3, now: datetime | None = None
) -> CollectResult:
    now = now or now_utc()
    start = now - timedelta(days=days)
    fetched_at = to_iso(now)
    result = CollectResult()

    for item in items:
        text = str(item.get("content_text") or "").strip() or html_to_text(
            str(item.get("content") or "")
        )
        if not text:
            continue
        try:
            published = unix_to_iso(item.get("display_time"))
        except (ValueError, TypeError, OSError):
            continue
        if not _in_window(published, start, now):
            continue
        title, _ = split_title_body(str(item.get("title") or "") or text)
        type_, symbols = classify(title, text)
        url = str(item.get("uri") or "").strip() or "https://wallstreetcn.com/livenews"
        body_id = make_body_id(SOURCE, url, published)

        result.events.append(
            {
                "type": type_,
                "subtype": "livenews",
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
                "fetch_ok": True,
                "lang": "zh",
            }
        )
    return result


def articles_to_result(
    items: list[dict],
    *,
    days: int = 3,
    now: datetime | None = None,
    detail_fetcher=None,
    known_body_ids: set[str] | None = None,
) -> CollectResult:
    """列表项 → 事件；详情正文 → bodies。`detail_fetcher(article_id) -> str` 便于测试注入。"""
    now = now or now_utc()
    start = now - timedelta(days=days)
    fetched_at = to_iso(now)
    known = known_body_ids or set()
    result = CollectResult()

    for item in items:
        title = str(item.get("title") or "").strip()
        raw_time = item.get("display_time")
        try:
            published = unix_to_iso(raw_time)
        except (ValueError, TypeError, OSError):
            continue
        if not _in_window(published, start, now):
            continue
        url = (
            str(item.get("uri") or "").strip()
            or f"https://wallstreetcn.com/articles/{item.get('id')}"
        )
        body_id = make_body_id(SOURCE, url, published)
        short = html_to_text(str(item.get("content_short") or ""))

        body_text = short
        fetch_ok = bool(short)
        if body_id not in known:
            fetched = ""
            if detail_fetcher is not None:
                try:
                    fetched = detail_fetcher(int(item.get("id"))) or ""
                except Exception as e:  # noqa: BLE001 — 单篇失败不影响其他
                    logger.warning("[wallstreetcn] 文章 %s 详情失败：%s", item.get("id"), e)
            if fetched.strip():
                body_text, fetch_ok = fetched.strip(), True
            else:
                fetch_ok = bool(body_text)
        if not body_text:
            continue

        type_, symbols = classify(title, body_text)
        result.events.append(
            {
                "type": type_,
                "subtype": "article",
                "symbols": symbols,
                "sector": "macro",
                "event_time": published,
                "available_at": published,
                "source": SOURCE,
                "source_url": url,
                "title": title or split_title_body(body_text)[0],
                "body_ref": body_ref(body_id),
                "confidence": 0.7,
                "quality": "B",
            }
        )
        if body_id not in known:
            result.bodies.append(
                {
                    "id": body_id,
                    "source": SOURCE,
                    "url": url,
                    "title": title,
                    "content_text": body_text,
                    "date_published": published,
                    "fetched_at": fetched_at,
                    "fetch_ok": fetch_ok,
                    "lang": "zh",
                }
            )
    return result


def _fetch_detail(article_id: int) -> str:
    guard.before_request()
    try:
        text = get_text(
            DETAIL_URL.format(id=article_id),
            headers=HEADERS,
            params={"client": "pc", "extract": "1"},
            timeout=20,
            retries=2,
            interval=0.0,
        )
        guard.record(True)
    except Exception:  # noqa: BLE001 — 计数后抛出，由调用方单篇 FAIL-OPEN
        guard.record(False)
        raise
    data = (json.loads(text) or {}).get("data") or {}
    return html_to_text(str(data.get("content") or "")) or str(data.get("content_short") or "")


def fetch(
    days: int = 3,
    now: datetime | None = None,
    live_limit: int = 50,
    article_limit: int = 10,
    known_body_ids: set[str] | None = None,
) -> CollectResult:
    now = now or now_utc()
    result = CollectResult()

    # 1) 快讯
    try:
        guard.before_request()
        payload = json.loads(
            get_text(
                LIVES_URL,
                headers=HEADERS,
                params={"channel": "global-channel", "client": "pc", "limit": str(live_limit)},
                timeout=20,
                retries=2,
                interval=0.0,
            )
        )
        guard.record(True)
        lives = lives_to_result(parse_lives(payload), days=days, now=now)
        result.events.extend(lives.events)
        result.bodies.extend(lives.bodies)
    except CircuitOpen as e:
        logger.warning("[wallstreetcn] 快讯%s", e)
    except Exception as e:  # noqa: BLE001
        guard.record(False)
        logger.warning("[wallstreetcn] 快讯抓取失败：%s", e)

    # 2) 深度文章
    try:
        guard.before_request()
        payload = json.loads(
            get_text(
                ARTICLES_URL,
                headers=HEADERS,
                params={"channel": "global", "client": "pc", "limit": str(article_limit)},
                timeout=20,
                retries=2,
                interval=0.0,
            )
        )
        guard.record(True)
        articles = articles_to_result(
            parse_articles(payload),
            days=days,
            now=now,
            detail_fetcher=_fetch_detail,
            known_body_ids=known_body_ids,
        )
        result.events.extend(articles.events)
        result.bodies.extend(articles.bodies)
    except CircuitOpen as e:
        logger.warning("[wallstreetcn] 深度%s", e)
    except Exception as e:  # noqa: BLE001
        guard.record(False)
        logger.warning("[wallstreetcn] 深度列表抓取失败：%s", e)

    return result


def guard_stats() -> dict:
    return guard.stats()
