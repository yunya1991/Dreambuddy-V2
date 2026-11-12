#!/usr/bin/env python3
"""18 events.jsonl → 19-DAL mm_events 事件日历表。

背景：经济日历（前端 fundamental/calendar）需要结构化的日程事件（FOMC/CPI/非农/
利率决议等）。18 层 collect_events 产出 JSONL（append-only），本脚本把「日历类」
事件同步进 19-DAL SQLite 的 mm_events 表，供 dsh_frontend_bridge 的
`data.dal_query --command calendar` 读取。

入库范围（白名单，避免把 500+ 条快讯塞进日历）：
  - source ∈ {fed_calendar, macro_calendar}
  - 数据来自 events.jsonl（历史已发生）+ calendar_schedule.jsonl（未来已公布日程）

用法：
    cd 19-数据访问层
    python scripts/sync_events_to_dal.py [--events <jsonl>] [--dst <db>] [--dry-run]

设计：幂等（event_id 主键 INSERT OR REPLACE），时间窗裁剪（过去 60 天 / 未来 90 天）。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EVENTS_PATH = REPO_ROOT / "18-数据获取中心" / "data_center" / "events" / "events.jsonl"
SCHEDULE_PATH = REPO_ROOT / "18-数据获取中心" / "data_center" / "events" / "calendar_schedule.jsonl"
DST_DB = REPO_ROOT / "19-数据访问层" / "data" / "dreambuddy_core.db"

CALENDAR_SOURCES = {"fed_calendar", "macro_calendar"}

_WINDOW_BACK_DAYS = 60
_WINDOW_AHEAD_DAYS = 90

_DDL = """
CREATE TABLE IF NOT EXISTS mm_events (
    event_id TEXT PRIMARY KEY,
    event_time INTEGER NOT NULL,
    event_type TEXT,
    subtype TEXT,
    source TEXT,
    title TEXT,
    symbols TEXT,
    confidence REAL,
    quality TEXT
)
"""
_INDEX = "CREATE INDEX IF NOT EXISTS idx_mm_events_time ON mm_events(event_time)"


def _to_unix(ts_text: str) -> int | None:
    if not ts_text:
        return None
    try:
        dt = datetime.fromisoformat(str(ts_text).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _iter_calendar_events(events_paths: list[Path], now: float) -> list[tuple]:
    lo = int(now) - _WINDOW_BACK_DAYS * 86400
    hi = int(now) + _WINDOW_AHEAD_DAYS * 86400
    rows: dict[str, tuple] = {}
    for path in events_paths:
        if not path.is_file():
            continue
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("source") not in CALENDAR_SOURCES:
                    continue
                ts = _to_unix(ev.get("event_time") or "")
                if ts is None or not (lo <= ts <= hi):
                    continue
                symbols = ev.get("symbols")
                event_id = str(ev.get("event_id") or "")
                if not event_id:
                    continue
                rows[event_id] = (
                    event_id,
                    ts,
                    ev.get("type") or "",
                    ev.get("subtype") or "",
                    ev.get("source") or "",
                    ev.get("title") or "",
                    json.dumps(symbols, ensure_ascii=False) if symbols else "",
                    (
                        float(ev["confidence"])
                        if isinstance(ev.get("confidence"), (int, float))
                        else None
                    ),
                    ev.get("quality") or "",
                )
    return list(rows.values())


def sync(
    events_path: str | Path | list[str | Path] = (EVENTS_PATH, SCHEDULE_PATH),
    dst_db: str | Path = DST_DB,
    dry_run: bool = False,
) -> dict:
    paths = [
        Path(p) for p in (events_path if isinstance(events_path, (list, tuple)) else [events_path])
    ]
    dst_db = Path(dst_db)

    now = datetime.now(timezone.utc).timestamp()
    rows = _iter_calendar_events(paths, now)
    if not any(p.is_file() for p in paths):
        return {"ok": False, "reason": f"events_not_found: {[str(p) for p in paths]}"}
    if dry_run:
        return {"ok": True, "dry_run": True, "candidate_rows": len(rows), "dst_db": str(dst_db)}

    dst_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(dst_db)
    try:
        conn.execute(_DDL)
        conn.execute(_INDEX)
        # 全量重建日历（表规模 <100 行）：避免历史脏行/已删日程残留
        conn.execute("DELETE FROM mm_events")
        conn.executemany(
            """
            INSERT OR REPLACE INTO mm_events
                (event_id, event_time, event_type, subtype, source, title, symbols, confidence, quality)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM mm_events").fetchone()[0]
        upcoming = conn.execute(
            "SELECT COUNT(*) FROM mm_events WHERE event_time >= ?", (int(now),)
        ).fetchone()[0]
    finally:
        conn.close()
    return {
        "ok": True,
        "synced_rows": len(rows),
        "db_row_count": total,
        "upcoming": upcoming,
        "dst_db": str(dst_db),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="同步 18 事件流 → 19-DAL mm_events")
    parser.add_argument(
        "--events",
        default="",
        help="自定义事件 JSONL（默认 events.jsonl + calendar_schedule.jsonl）",
    )
    parser.add_argument("--dst", default=str(DST_DB))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sources = [args.events] if args.events else [EVENTS_PATH, SCHEDULE_PATH]
    result = sync(sources, args.dst, args.dry_run)
    print(f"[sync_events_to_dal] {json.dumps(result, ensure_ascii=False)}")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
