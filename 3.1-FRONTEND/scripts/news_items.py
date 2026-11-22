#!/usr/bin/env python3
"""新闻明细只读查询（云端本地门禁接口的后端）。

数据源（只读，不写任何文件）:
    39-金融语义蒸馏系统/news_digest.json   全量 + 30 天去重检索库（优先）
    39-金融语义蒸馏系统/hot_news.json      24h top50 影响力榜（降级回退）

用法:
    python3 scripts/news_items.py --window 24h --limit 50 --offset 0
    python3 scripts/news_items.py --window 7d --topic crypto_reg --min-importance 60
    python3 scripts/news_items.py --window 30d --q BTC --sentiment 利空

输出: news_items/v1 JSON；只读，无副作用。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA = "news_items/v1"
REPO = Path(__file__).resolve().parents[2]
NEWS_DIR = REPO / "39-金融语义蒸馏系统"
HOT_PATH = Path(os.environ.get("HOT_NEWS_PATH") or NEWS_DIR / "hot_news.json")
DIGEST_PATH = Path(os.environ.get("NEWS_DIGEST_PATH") or NEWS_DIR / "news_digest.json")

WINDOW_HOURS = {"24h": 24, "7d": 168, "30d": 720}
LIMIT_MAX = 500
SENTIMENT_ALIASES = {
    "利好": "利好",
    "positive": "利好",
    "bullish": "利好",
    "利空": "利空",
    "negative": "利空",
    "bearish": "利空",
    "中性": "中性",
    "neutral": "中性",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _digest(*parts: Any) -> str:
    raw = "|".join("" if part is None else str(part) for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _load_json(path: Path) -> Tuple[Dict[str, Any], str]:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return {}, "missing:{}".format(path.name)
    except (OSError, json.JSONDecodeError) as exc:
        return {}, "invalid:{}:{}".format(path.name, exc)
    return (payload if isinstance(payload, dict) else {}), ""


def _sentiment(item: Dict[str, Any]) -> Dict[str, Any]:
    value = item.get("sentiment")
    if isinstance(value, dict):
        return {"label": value.get("label"), "score": value.get("score")}
    if isinstance(value, str):
        return {"label": value, "score": None}
    return {"label": None, "score": None}


def _normalize(item: Dict[str, Any]) -> Dict[str, Any]:
    sentiment = _sentiment(item)
    title = item.get("title") or item.get("title_short") or ""
    published = item.get("published_at") or item.get("ts")
    return {
        "event_id": item.get("event_id") or item.get("id") or _digest(published, title),
        "title": title,
        "title_short": item.get("title_short") or title,
        "topic": item.get("topic"),
        "event_type": item.get("event_type"),
        "symbols": item.get("symbols") or [],
        "sentiment": sentiment,
        "importance": item.get("importance"),
        "published_at": published,
        "origin": item.get("origin"),
        "source_url": item.get("source_url"),
        "source_count": item.get("source_count"),
        "dup_count": item.get("dup_count"),
        "rank": item.get("rank"),
    }


def _load_source(window: str) -> Dict[str, Any]:
    """优先全量 30 天检索库；缺失时回退 24h 热点榜。"""
    digest, digest_error = _load_json(DIGEST_PATH)
    digest_items = digest.get("items") if isinstance(digest.get("items"), list) else []
    if digest_items:
        return {
            "source": "news_digest",
            "payload": digest,
            "items": digest_items,
            "degraded": False,
            "degraded_reason": "",
        }
    hot, hot_error = _load_json(HOT_PATH)
    hot_items = hot.get("top") if isinstance(hot.get("top"), list) else []
    reason = digest_error or hot_error or "empty"
    return {
        "source": "hot_news",
        "payload": hot,
        "items": hot_items,
        "degraded": True,
        "degraded_reason": "news_digest 不可用，回退 hot_news top50（{}）".format(reason),
    }


def _in_window(item: Dict[str, Any], cutoff: datetime) -> bool:
    stamp = _parse_ts(item.get("published_at") or item.get("ts"))
    return stamp is not None and stamp >= cutoff


def _wanted_sentiment(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return SENTIMENT_ALIASES.get(value.strip().lower(), SENTIMENT_ALIASES.get(value.strip()))


def _topic_set(value: Optional[str]) -> set:
    if not value:
        return set()
    return {part.strip() for part in value.split(",") if part.strip()}


def query(
    window: str = "24h",
    limit: int = 50,
    offset: int = 0,
    topic: Optional[str] = None,
    q: Optional[str] = None,
    min_importance: Optional[float] = None,
    sentiment: Optional[str] = None,
) -> Dict[str, Any]:
    source = _load_source(window)
    items = [_normalize(item) for item in source["items"] if isinstance(item, dict)]
    cutoff = _now() - timedelta(hours=WINDOW_HOURS.get(window, 24))
    # hot_news 本身已是 24h 榜；digest 需要按窗口切片
    if source["source"] == "news_digest":
        items = [item for item in items if _in_window(item, cutoff)]

    topics = _topic_set(topic)
    wanted_sentiment = _wanted_sentiment(sentiment)
    keyword = (q or "").strip().lower()
    matched: List[Dict[str, Any]] = []
    for item in items:
        if topics and item.get("topic") not in topics:
            continue
        if wanted_sentiment and item.get("sentiment", {}).get("label") != wanted_sentiment:
            continue
        if min_importance is not None:
            importance = item.get("importance")
            if not isinstance(importance, (int, float)) or importance < min_importance:
                continue
        if keyword and keyword not in (item.get("title") or "").lower():
            continue
        matched.append(item)

    matched.sort(
        key=lambda item: (item.get("importance") or 0, item.get("published_at") or ""),
        reverse=True,
    )
    page_limit = max(1, min(int(limit), LIMIT_MAX))
    page_offset = max(0, int(offset))
    page = matched[page_offset : page_offset + page_limit]

    source_payload = source["payload"]
    return {
        "schema": SCHEMA,
        "generated_at": _iso(_now()),
        "source": source["source"],
        "source_generated_at": source_payload.get("generated_at"),
        "window": window,
        "window_hours": WINDOW_HOURS.get(window, 24),
        "total": len(items),
        "matched": len(matched),
        "offset": page_offset,
        "limit": page_limit,
        "returned": len(page),
        "has_more": page_offset + len(page) < len(matched),
        "degraded": source["degraded"],
        "degraded_reason": source["degraded_reason"],
        "stats": source_payload.get("stats") or {},
        "coverage": source_payload.get("coverage") or {},
        "items": page,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="新闻明细只读查询（云端本地门禁后端）")
    parser.add_argument("--window", choices=list(WINDOW_HOURS), default="24h")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--topic", default=None)
    parser.add_argument("--q", default=None)
    parser.add_argument("--min-importance", type=float, default=None)
    parser.add_argument("--sentiment", default=None)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    payload = query(
        window=args.window,
        limit=args.limit,
        offset=args.offset,
        topic=args.topic,
        q=args.q,
        min_importance=args.min_importance,
        sentiment=args.sentiment,
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
