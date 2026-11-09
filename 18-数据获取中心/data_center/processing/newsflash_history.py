"""newsflash 历史翻页回填逻辑 — SPEC-D1 §2.4 路径 2 补量（P2）。

实测口径（2026-11-10 探针验证，预注册冻结）：
  - 翻页参数 = page（cursor / pageNum 均被 API 忽略，永远返回首屏）
  - limit 固定 20/页（传 100 也只返 20）；totalPage ≈ 19169（2018-05 至今）
  - API 偶发 SSL EOF / 证书校验失败 → 重试 5 次指数退避，耗尽返回 []
  - 终止：页内最旧条目 published_ms < stop_ts（该页仍产出，边界包含）、
    空页、或超过 max_pages 安全上限

FAIL-OPEN：任何异常不抛，fetch 失败视为流终止。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Iterator

from data_center.collectors.news.odaily_newsflash import (
    _HTTP_HEADERS,
    _ODAILY_API,
    _classify_event_type,
)

logger = logging.getLogger("data_center.processing.newsflash_history")

_HTTP_TIMEOUT = 20
_MAX_RETRY = 5


def normalize_flash(item: Any) -> dict:
    """原始 API 条目 → 回填记录 {id,title,description,published_ms,od_event_type}。

    缺 id / publishTimestamp → {}（丢弃）。FAIL-OPEN。
    """
    try:
        if not isinstance(item, dict):
            return {}
        oid = int(item.get("id") or 0)
        ts = int(item.get("publishTimestamp") or 0)
        if oid <= 0 or ts <= 0:
            return {}
        title = str(item.get("title") or "")
        desc = str(item.get("description") or "")
        return {
            "id": oid,
            "title": title,
            "description": desc,
            "published_ms": ts,
            "is_important": bool(item.get("isImportant", False)),
            "od_event_type": _classify_event_type(title, desc),
        }
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] normalize_flash 异常 %s: %s", type(e).__name__, str(e)[:120])
        return {}


def fetch_page(session: Any, page: int) -> list[dict]:
    """真实 HTTP 拉一页（重试 5 次，耗尽返回 []）。FAIL-OPEN。"""
    for attempt in range(_MAX_RETRY):
        try:
            resp = session.get(
                f"{_ODAILY_API}/newsflash/page",
                params={"page": page, "limit": 20},
                headers=_HTTP_HEADERS,
                timeout=_HTTP_TIMEOUT,
            )
            data = resp.json()
            if not isinstance(data, dict):
                return []
            items = data.get("data", {}).get("list", []) or []
            return items if isinstance(items, list) else []
        except Exception as e:  # noqa: BLE003
            logger.info(
                "[FAIL-OPEN] fetch_page p=%d 第%d次 %s: %s",
                page,
                attempt + 1,
                type(e).__name__,
                str(e)[:120],
            )
            time.sleep(2 * (attempt + 1))
    logger.warning("[FAIL-OPEN] fetch_page p=%d 重试耗尽，返回 []", page)
    return []


def iter_pages(
    fetch_fn: Callable[[int], list],
    *,
    start_page: int = 1,
    stop_ts: int = 0,
    max_pages: int = 12000,
) -> Iterator[dict]:
    """翻页生成器：yield normalize 后的条目。

    终止：空页 / 页内最旧条目 < stop_ts（该页仍产出）/ max_pages / fetch 异常。
    fetch_fn 异常 → FAIL-OPEN 终止（不抛）。
    """
    page = start_page
    while page < start_page + max_pages:
        try:
            raw = fetch_fn(page)
        except Exception as e:  # noqa: BLE003  FAIL-OPEN
            logger.warning(
                "[FAIL-OPEN] iter_pages p=%d fetch 异常 %s: %s，终止",
                page,
                type(e).__name__,
                str(e)[:120],
            )
            return
        if not raw:
            return
        for item in raw:
            norm = normalize_flash(item)
            if not norm:
                continue
            yield norm
        ts_list = [
            int(x.get("publishTimestamp") or 0)
            for x in raw
            if isinstance(x, dict) and int(x.get("publishTimestamp") or 0) > 0
        ]
        if ts_list and min(ts_list) < stop_ts * 1000:
            return  # 本页已产出，边界包含后终止
        page += 1


def load_state(path: Any) -> int:
    """读取断点（上次完成的页码）。缺失/损坏 → 0。FAIL-OPEN。"""
    try:
        p = Path(path)
        if not p.exists():
            return 0
        return int(json.loads(p.read_text(encoding="utf-8")).get("last_page", 0))
    except Exception:  # noqa: BLE003
        return 0


def save_state(path: Any, page: int) -> None:
    """写断点。FAIL-OPEN。"""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"last_page": int(page)}), encoding="utf-8")
    except Exception as e:  # noqa: BLE003
        logger.warning("[FAIL-OPEN] save_state 异常 %s: %s", type(e).__name__, str(e)[:120])
