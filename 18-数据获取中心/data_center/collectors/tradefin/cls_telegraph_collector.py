"""财联社电报采集器 — SPEC §3.2 P1-A。

接口：`https://www.cls.cn/v1/roll/get_roll_list`（公开，但要求签名参数）
签名算法（财联社 Web 端公开实现）：
    sign = md5(sha1(urlencode(sorted(params_without_sign))))

实测 2026-11-11：`app=CailianpressWeb&os=web&sv=7.7.5&rn=N` + sign 返回
`{"errno":0,"data":{"roll_data":[...]}}`；不带 sign → `errno=10012 签名错误`。

输出：A 股/宏观电报 → canonical EventRecord；电报正文（content）写入 bodies.jsonl。
quality=B；限频 1.5s；失败率 >30% 熔断。不绕过登录墙/验证码（§3.2 红线 1）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import urllib.parse
from datetime import datetime, timedelta

from data_center.collectors.tradefin._classify import classify
from data_center.collectors.tradefin._guard import CircuitOpen, SourceGuard
from data_center.collectors.tradefin._http import get_text
from data_center.collectors.tradefin._result import CollectResult
from data_center.collectors.tradefin._util import (
    now_utc,
    split_title_body,
    to_iso,
    unix_to_iso,
)
from data_center.events.body_store import body_ref, make_body_id

logger = logging.getLogger(__name__)

SOURCE = "cls"
API_URL = "https://www.cls.cn/v1/roll/get_roll_list"
BASE_PARAMS = {"app": "CailianpressWeb", "os": "web", "sv": "7.7.5"}
HEADERS = {
    "User-Agent": "dreambuddy-research admin@dreambuddy.local",
    "Referer": "https://www.cls.cn/telegraph",
    "Accept": "application/json",
}

guard = SourceGuard(SOURCE, min_interval=1.5)


def make_sign(params: dict) -> str:
    """财联社签名：md5(sha1(urlencode(sorted(params))))。"""
    query = urllib.parse.urlencode(sorted((str(k), str(v)) for k, v in params.items()))
    return hashlib.md5(hashlib.sha1(query.encode("utf-8")).hexdigest().encode()).hexdigest()


def build_params(rn: int = 50, last_time: str | int | None = None) -> dict:
    params = {**BASE_PARAMS, "rn": str(rn)}
    if last_time:
        params["last_time"] = str(last_time)
    params["sign"] = make_sign({k: v for k, v in params.items() if k != "sign"})
    return params


def parse_roll(payload) -> list[dict]:
    data = (payload or {}).get("data") or {}
    rows = data.get("roll_data") or []
    return [row for row in rows if isinstance(row, dict) and not row.get("is_ad")]


def items_to_result(
    items: list[dict], *, days: int = 3, now: datetime | None = None
) -> CollectResult:
    now = now or now_utc()
    start = now - timedelta(days=days)
    fetched_at = to_iso(now)
    result = CollectResult()

    for item in items:
        text = str(item.get("content") or item.get("brief") or "").strip()
        if not text:
            continue
        try:
            published = unix_to_iso(item.get("ctime"))
        except (ValueError, TypeError, OSError):
            continue
        ts = datetime.fromisoformat(published.replace("Z", "+00:00"))
        if not (start <= ts <= now):
            continue

        given_title = str(item.get("title") or "").strip()
        title, _ = split_title_body(given_title or text)
        type_, symbols = classify(title, text)
        url = f"https://www.cls.cn/detail/{item.get('id')}"
        body_id = make_body_id(SOURCE, url, published)

        result.events.append(
            {
                "type": type_,
                "subtype": "telegraph",
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


def fetch(days: int = 3, now: datetime | None = None, rn: int = 50) -> CollectResult:
    now = now or now_utc()
    try:
        guard.before_request()
        text = get_text(
            API_URL,
            headers=HEADERS,
            params=build_params(rn),
            timeout=20,
            retries=2,
            interval=0.0,
        )
        guard.record(True)
    except CircuitOpen as e:
        logger.warning("[cls] %s，跳过", e)
        return CollectResult()
    except Exception as e:  # noqa: BLE001 — FAIL-OPEN
        guard.record(False)
        logger.warning("[cls] 抓取失败：%s", e)
        return CollectResult()

    return items_to_result(parse_roll(json.loads(text)), days=days, now=now)


def guard_stats() -> dict:
    return guard.stats()
