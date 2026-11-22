#!/usr/bin/env python3
"""新闻监控通用组件（news-monitor）：云端只读。

数据通道:
    GET  {NEWS_ENDPOINT}/api/fundamental/news/snapshot[?days=N]
    POST {NEWS_ENDPOINT}/api/data/query  {"message": "<关键词> 最近<窗口>新闻"}

约定:
    - 默认 NEWS_ENDPOINT=https://www.neodrm.com，可用环境变量覆盖（仅换域名，不换协议）；
    - 本组件只读，不抓取全文正文、不写任何云端/本地数据；
    - 输出统一 data.v1 外壳（见 contracts/output.schema.json）。

只读边界:
    --endpoint 仅 auto / cloud 有效；local 直接返回 E_INPUT，避免伪造本地数据。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

VERSION = "0.1.0"
SKILL = "news-monitor"
DEFAULT_ENDPOINT = "https://www.neodrm.com"
SNAPSHOT_PATH = "/api/fundamental/news/snapshot"
SEARCH_PATH = "/api/data/query"
TIMEOUT = 25
LIMIT_MAX = 50
DAYS_MAX = 1825

WINDOW_WORDS = {"24h": "24小时", "7d": "", "30d": "30天"}
WINDOW_HOURS = {"24h": 24, "7d": 168, "30d": 720}

LIMITS = {
    "hot": "云端 24h 热点影响力榜 Top N；仅标题/主题/情绪/影响力/来源链接，非预测、非投资建议。",
    "metrics": "云端新闻情绪与主题指标快照；榜单口径为近 24h，无历史纵深。",
    "search": "云端榜单检索，支持 24h/7d/30d 窗口；返回热度榜内条目，不等于全量新闻库全文检索。",
    "snapshot": "云端新闻监控完整快照；字段随上游演进，下游应容忍新增字段。",
}

METHOD_IDS = {
    "hot": ["N01"],
    "metrics": ["N02"],
    "search": ["N03"],
    "snapshot": ["N04"],
}

SOURCES = [
    {
        "name": "DreamBuddy 云端新闻监控快照",
        "url": "https://www.neodrm.com/dashboard/news",
        "license": "内部聚合；原始新闻版权归各来源媒体，不再分发正文",
    }
]


class NewsError(Exception):
    """带 data.v1 missing.code 的云端/输入错误。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _base() -> str:
    return (os.environ.get("NEWS_ENDPOINT") or DEFAULT_ENDPOINT).rstrip("/")


def _http_json(
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
    timeout: int = TIMEOUT,
) -> Dict[str, Any]:
    url = _base() + path
    if params:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "", 0)})
        if query:
            url = "{}?{}".format(url, query)
    data = None
    headers = {
        "Accept": "application/json",
        "User-Agent": "dreambuddy-{}/{}".format(SKILL, VERSION),
    }
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise NewsError(
            "E_HTTP_4XX" if exc.code < 500 else "E_NET", "http {}".format(exc.code)
        ) from exc
    except urllib.error.URLError as exc:
        reason = exc.reason
        code = "E_TLS" if isinstance(reason, ssl.SSLError) else "E_NET"
        raise NewsError(code, "{}".format(reason)) from exc
    except (TimeoutError, OSError) as exc:
        raise NewsError("E_NET", "{}".format(exc)) from exc
    if not raw:
        raise NewsError("E_EMPTY", "空响应")
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise NewsError("E_SCHEMA", "JSON 解析失败：{}".format(exc.msg)) from exc
    if not isinstance(payload, dict):
        raise NewsError("E_SCHEMA", "响应不是对象")
    return payload


def _digest(*parts: Any) -> str:
    raw = "|".join("" if part is None else str(part) for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _envelope(
    command: str,
    rows: List[Dict[str, Any]],
    *,
    data_date: Optional[str] = None,
    missing: Optional[List[Dict[str, str]]] = None,
    detail: Optional[Dict[str, Any]] = None,
    ok: bool = True,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "skill": SKILL,
        "version": VERSION,
        "command": command,
        "generated_at": _now(),
        "data_date": data_date,
        "rows": rows,
        "missing": missing or [],
        "method_ids": METHOD_IDS.get(command, ["N00"]),
        "sources": SOURCES,
        "limits": LIMITS.get(command, LIMITS["hot"]),
        "data_route": "cloud",
        "ok": ok,
    }
    if detail is not None:
        payload["detail"] = detail
    return payload


def _emit(payload: Dict[str, Any], code: int = 0) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


def _fail(command: str, error: NewsError) -> int:
    missing = [{"key": command, "code": error.code, "detail": error.detail}]
    return _emit(
        _envelope(command, [], missing=missing, ok=False), 2 if error.code == "E_INPUT" else 1
    )


def _sentiment(item: Dict[str, Any]) -> Dict[str, Any]:
    value = item.get("sentiment")
    if isinstance(value, dict):
        return {"label": value.get("label"), "score": value.get("score")}
    if isinstance(value, str):
        return {"label": value, "score": None}
    return {"label": None, "score": None}


def normalize_hot(item: Dict[str, Any]) -> Dict[str, Any]:
    """把云端一条热点归一为 data.v1 事件行（必须带 event_id）。"""
    sentiment = _sentiment(item)
    title = item.get("title") or item.get("title_short") or ""
    return {
        "event_id": item.get("event_id") or _digest(item.get("published_at"), title),
        "title": title,
        "topic": item.get("topic"),
        "sentiment": sentiment["label"],
        "sentiment_score": sentiment["score"],
        "importance": item.get("importance"),
        "published_at": item.get("published_at"),
        "origin": item.get("origin"),
        "source_url": item.get("source_url"),
        "rank": item.get("rank"),
    }


def extract_hot(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    breakdown = (snapshot.get("metrics") or {}).get("breakdown") or {}
    return [normalize_hot(item) for item in breakdown.get("hot_news_top10") or []]


def extract_metrics(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    metrics = snapshot.get("metrics") or {}
    core = metrics.get("core") or {}
    breakdown = metrics.get("breakdown") or {}
    total = core.get("total_articles") or 0
    count_keys = {
        "total_articles",
        "positive_count",
        "negative_count",
        "neutral_count",
        "high_impact_count",
        "semantic_events_24h",
        "social_volume",
        "total_news_records",
    }
    rows: List[Dict[str, Any]] = []
    for key, value in core.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        sample = int(value) if key in count_keys else int(total)
        rows.append(
            {
                "metric": key,
                "value": value,
                "n": max(sample, 0),
                "unit": "条" if key in count_keys else "",
            }
        )
    for cluster in breakdown.get("theme_clusters") or []:
        count = int(cluster.get("count") or 0)
        rows.append(
            {
                "metric": "theme_cluster",
                "topic": cluster.get("topic"),
                "label": cluster.get("label"),
                "value": count,
                "n": max(count, 0),
                "avg_importance": cluster.get("avg_importance"),
            }
        )
    return rows


def normalize_search(item: Dict[str, Any]) -> Dict[str, Any]:
    sentiment = _sentiment(item)
    title = item.get("title") or ""
    return {
        "event_id": item.get("event_id") or _digest(item.get("ts"), title),
        "title": title,
        "topic": item.get("topic"),
        "sentiment": sentiment["label"],
        "sentiment_score": sentiment["score"],
        "importance": item.get("importance"),
        "published_at": item.get("ts"),
        "origin": item.get("origin"),
        "source_url": item.get("source_url"),
    }


def build_search_message(keyword: str, window: str) -> str:
    word = WINDOW_WORDS.get(window, "")
    window_part = "最近{}".format(word) if word else "最近"
    return "{} {}新闻".format(keyword.strip(), window_part).strip()


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(int(value), high))


def fetch_snapshot(days: int = 0) -> Dict[str, Any]:
    params = {"days": days} if days else None
    return _http_json("GET", SNAPSHOT_PATH, params=params)


def cmd_hot(args: argparse.Namespace) -> int:
    limit = _clamp(args.limit, 1, LIMIT_MAX)
    snapshot = fetch_snapshot()
    rows = extract_hot(snapshot)[:limit]
    summary = ((snapshot.get("metrics") or {}).get("breakdown") or {}).get("hot_news_summary") or {}
    return _emit(
        _envelope(
            "hot",
            rows,
            data_date=snapshot.get("ts"),
            detail={"window_h": summary.get("window_h"), "summary": summary},
        )
    )


def cmd_metrics(args: argparse.Namespace) -> int:
    snapshot = fetch_snapshot()
    rows = extract_metrics(snapshot)
    core = (snapshot.get("metrics") or {}).get("core") or {}
    breakdown = (snapshot.get("metrics") or {}).get("breakdown") or {}
    return _emit(
        _envelope(
            "metrics",
            rows,
            data_date=snapshot.get("ts"),
            detail={
                "sentiment": core.get("sentiment_score"),
                "themes": breakdown.get("semantic_top_themes") or {},
                "ts_quality": (snapshot.get("timeseries_meta") or {}).get("quality"),
            },
        )
    )


def cmd_search(args: argparse.Namespace) -> int:
    message = build_search_message(args.keyword, args.window)
    payload = _http_json("POST", SEARCH_PATH, body={"message": message})
    result = payload.get("data") or {}
    if result.get("handled") is False:
        reasons = (result.get("route_signal") or {}).get("reasons") or []
        raise NewsError(
            "E_EMPTY", "L1 未直答：{}".format("、".join(map(str, reasons)) or "handled=false")
        )
    data = result.get("data")
    if not isinstance(data, dict):
        raise NewsError("E_SCHEMA", "检索响应缺少 data 字段")
    items = data.get("items") or []
    rows = [normalize_search(item) for item in items if isinstance(item, dict)]
    stamps = [row.get("published_at") for row in rows if row.get("published_at")]
    return _emit(
        _envelope(
            "search",
            rows,
            data_date=max(stamps) if stamps else None,
            detail={
                "message": message,
                "answer": result.get("answer"),
                "window_h": data.get("window_h") or WINDOW_HOURS.get(args.window),
                "matched": data.get("matched"),
                "scanned": data.get("scanned"),
                "coverage_note": data.get("coverage_note"),
                "unclassified_ratio": data.get("unclassified_ratio"),
            },
        )
    )


def cmd_snapshot(args: argparse.Namespace) -> int:
    days = _clamp(args.days, 0, DAYS_MAX) if args.days else 0
    snapshot = fetch_snapshot(days)
    return _emit(
        _envelope(
            "snapshot",
            extract_hot(snapshot),
            data_date=snapshot.get("ts"),
            detail={"snapshot": snapshot},
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="新闻监控通用组件（云端只读）")
    sub = parser.add_subparsers(dest="cmd")

    p_hot = sub.add_parser("hot", help="云端 24h 热点新闻榜 Top N")
    p_hot.add_argument("--limit", type=int, default=10)
    p_hot.add_argument("--endpoint", choices=["auto", "cloud", "local"], default="auto")

    p_metrics = sub.add_parser("metrics", help="新闻情绪与主题指标")
    p_metrics.add_argument("--endpoint", choices=["auto", "cloud", "local"], default="auto")

    p_search = sub.add_parser("search", help="按关键词检索云端新闻")
    p_search.add_argument("--keyword", required=True)
    p_search.add_argument("--window", choices=["24h", "7d", "30d"], default="7d")
    p_search.add_argument("--endpoint", choices=["auto", "cloud", "local"], default="auto")

    p_snapshot = sub.add_parser("snapshot", help="云端新闻监控完整快照")
    p_snapshot.add_argument("--days", type=int, default=0)
    p_snapshot.add_argument("--endpoint", choices=["auto", "cloud", "local"], default="auto")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        parser.print_help()
        return 2
    if getattr(args, "endpoint", "auto") == "local":
        return _fail(
            args.cmd,
            NewsError(
                "E_INPUT", "news-monitor 仅支持云端通道（auto/cloud）；--endpoint local 不可用"
            ),
        )
    handlers = {
        "hot": cmd_hot,
        "metrics": cmd_metrics,
        "search": cmd_search,
        "snapshot": cmd_snapshot,
    }
    try:
        return handlers[args.cmd](args)
    except NewsError as exc:
        return _fail(args.cmd, exc)


if __name__ == "__main__":
    raise SystemExit(main())
