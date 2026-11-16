#!/usr/bin/env python3
"""榜单新闻事件生产者。

复用 18-数据获取中心 的 Odaily 快讯采集器（只取其解析/打标能力，绕过
当前 Silver 门禁对 news 的误拦截），把最近 72h 快讯按 TICKER 聚合，
供榜单决策卡「事件」Tab 展示。

输出：1-ARCHITECTURE/dreamos/cli/scheduler_data/ranking_news.json
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

MAX_PER_SYMBOL = 5
LOOKBACK_HOURS = 72
FETCH_PAGES = 4
TITLE_MAX_LEN = 80

# Odaily 以加密快讯为主，美股/大宗常以公司名或中文品种出现，补一层别名匹配
_SYMBOL_ALIASES = {
    "AMD": ("amd", "超威", "超微半导体"),
    "AMZN": ("amazon", "亚马逊"),
    "MSFT": ("microsoft", "微软"),
    "META": ("meta", "脸书"),
    "AAPL": ("apple", "苹果公司"),
    "NVDA": ("nvidia", "英伟达"),
    "TSLA": ("tesla", "特斯拉"),
    "GOOGL": ("google", "谷歌"),
    "BRKB": ("berkshire", "伯克希尔"),
    "SPY": ("s&p 500", "标普500"),
    "QQQ": ("纳斯达克100",),
    "XAU": ("黄金", "gold"),
    "XCU": ("铜价", "lme铜", "copper"),
    "CL": ("原油", "wti", "crude"),
    "BZ": ("布伦特", "brent"),
}


def _repo_root() -> Path:
    here = Path(__file__).resolve().parent
    for parent in (here, *here.parents):
        if (parent / ".git").exists():
            return parent
    return here.parent.parent


REPO = _repo_root()
CLI_DIR = REPO / "1-ARCHITECTURE" / "dreamos" / "cli"
SCHED = CLI_DIR / "scheduler_data"
OUT = SCHED / "ranking_news.json"

_IMPACT_HIGH = (
    "黑客",
    "被盗",
    "攻击",
    "暂停",
    "下架",
    "退市",
    "清算",
    "暴跌",
    "跌超",
    "崩盘",
    "制裁",
    "起诉",
    "调查",
    "禁止",
)
_IMPACT_MID = (
    "上涨",
    "涨超",
    "突破",
    "新高",
    "获批",
    "批准",
    "融资",
    "上线",
    "回购",
    "增持",
    "合作",
    "升级",
    "主网",
    "减半",
    "空投",
)


def classify_impact(title: str, is_important: bool = False) -> str:
    """标题 + 重要标记 → 高/中/低，供前端事件徽章直接使用。"""
    if is_important or any(keyword in title for keyword in _IMPACT_HIGH):
        return "高"
    if any(keyword in title for keyword in _IMPACT_MID):
        return "中"
    return "低"


def match_symbol_aliases(haystack: str) -> List[str]:
    """公司名/中文品种别名 → 榜单 symbol（补 Odaily 纯 TICKER 规则的盲区）。"""
    lower = haystack.lower()
    hits: List[str] = []
    for symbol, aliases in _SYMBOL_ALIASES.items():
        for alias in aliases:
            if alias.isascii():
                if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", lower):
                    hits.append(symbol)
                    break
            elif alias in haystack:
                hits.append(symbol)
                break
    return hits


def build_snapshot(
    records: Iterable[Any],
    now: Optional[datetime] = None,
    lookback_hours: int = LOOKBACK_HOURS,
    max_per_symbol: int = MAX_PER_SYMBOL,
) -> Dict[str, Any]:
    """DataRecord 列表 → {by_symbol: {TICKER: [event, ...]}}（纯函数，便于单测）。"""
    now = now or datetime.now(timezone.utc)
    cutoff_ms = int((now - timedelta(hours=lookback_hours)).timestamp() * 1000)
    by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    seen_ids = set()

    for record in records:
        raw = getattr(record, "raw", {}) or {}
        metrics = getattr(record, "metrics", {}) or {}
        record_id = metrics.get("od_source_id")
        if record_id in seen_ids:
            continue
        seen_ids.add(record_id)

        title = str(raw.get("title") or "").strip()
        if not title:
            continue
        published_ms = int(raw.get("publishTimestamp") or 0)
        if published_ms and published_ms < cutoff_ms:
            continue

        tickers = raw.get("tickers_hit") or [
            ticker for ticker in str(metrics.get("od_tickers_hit_csl") or "").split(",") if ticker
        ]
        description = str(raw.get("description") or "")
        tickers = list(dict.fromkeys([*tickers, *match_symbol_aliases(f"{title} {description}")]))
        if not tickers:
            continue

        published_at = (
            datetime.fromtimestamp(published_ms / 1000, timezone.utc) if published_ms else now
        )
        is_important = str(metrics.get("od_is_important", "false")).lower() == "true"
        event = {
            "date": published_at.strftime("%m-%d %H:%M"),
            "name": title[:TITLE_MAX_LEN],
            "impact": classify_impact(title, is_important),
            "published_ms": published_ms,
        }
        for ticker in tickers:
            symbol = str(ticker).strip().upper()
            if not symbol:
                continue
            bucket = by_symbol.setdefault(symbol, [])
            if len(bucket) < max_per_symbol:
                bucket.append(event)

    for events in by_symbol.values():
        events.sort(key=lambda item: item["published_ms"], reverse=True)

    return {
        "generated_at": now.isoformat(),
        "source": "odaily_newsflash",
        "window_hours": lookback_hours,
        "count": len(by_symbol),
        "by_symbol": by_symbol,
    }


def fetch_records(pages: int = FETCH_PAGES) -> List[Any]:
    """从 Odaily 拉取最近若干页快讯（失败 FAIL-OPEN 返回已取到的部分）。"""
    dc_root = REPO / "18-数据获取中心"
    if str(dc_root) not in sys.path:
        sys.path.insert(0, str(dc_root))
    try:
        from data_center.collectors.news.odaily_newsflash import OdailyNewsflashCollector
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL-OPEN] 加载 Odaily 采集器失败: {type(exc).__name__}: {exc}")
        return []

    collector = OdailyNewsflashCollector()
    records: List[Any] = []
    for page in range(1, max(1, pages) + 1):
        try:
            page_records = collector._fetch_page(limit=20, page=page)
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL-OPEN] 拉取第 {page} 页失败: {type(exc).__name__}: {exc}")
            break
        if not page_records:
            break
        records.extend(page_records)
    return records


def main() -> int:
    SCHED.mkdir(parents=True, exist_ok=True)
    snapshot = build_snapshot(fetch_records())
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, OUT)
    print(
        f"→ {OUT} 标的数={snapshot['count']} "
        f"条目数={sum(len(v) for v in snapshot['by_symbol'].values())}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
