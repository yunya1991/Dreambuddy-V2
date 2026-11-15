"""历史宏观事件回填入库 —— history JSONL → 19-DAL mm_events（无时间窗裁剪）。

与 `sync_events_to_dal.py` 的分工：
  - 本脚本只做历史回填，不做窗口过滤、不 DELETE，纯 `INSERT OR REPLACE`（幂等）；
  - `sync_events_to_dal.py` 负责日常 [-60d,+90d] 窗口刷新，已改为只删窗口内行，
    避免把回填的历史行清空。

用法（云端唯一生产写入口执行，写前先 `sqlite3 .backup`）：
    cd 19-数据访问层
    python scripts/backfill_events_history.py \
        --history ../18-数据获取中心/data_center/events/macro_calendar_history.jsonl \
        --dst data/dreambuddy_core.db
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from sync_events_to_dal import _DDL, _INDEX  # noqa: E402

REPO_ROOT = _SCRIPTS_DIR.parents[1]
DEFAULT_HISTORY = (
    REPO_ROOT / "18-数据获取中心" / "data_center" / "events" / "macro_calendar_history.jsonl"
)
DST_DB = REPO_ROOT / "19-数据访问层" / "data" / "dreambuddy_core.db"


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


def _load_rows(history_path: Path) -> list[tuple]:
    if not history_path.is_file():
        return []
    rows: dict[str, tuple] = {}
    with history_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_id = str(ev.get("event_id") or "")
            ts = _to_unix(ev.get("event_time") or "")
            if not event_id or ts is None:
                continue
            symbols = ev.get("symbols")
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


def backfill(
    history_path: str | Path = DEFAULT_HISTORY,
    dst_db: str | Path = DST_DB,
    dry_run: bool = False,
) -> dict:
    history_path = Path(history_path)
    dst_db = Path(dst_db)
    if not history_path.is_file():
        return {"ok": False, "reason": f"history_not_found: {history_path}"}

    rows = _load_rows(history_path)
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "candidate_rows": len(rows),
            "dst_db": str(dst_db),
        }

    dst_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(dst_db)
    try:
        conn.execute(_DDL)
        conn.execute(_INDEX)
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
    finally:
        conn.close()
    return {
        "ok": True,
        "upserted": len(rows),
        "db_row_count": total,
        "history_path": str(history_path),
        "dst_db": str(dst_db),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="历史宏观事件 → 19-DAL mm_events")
    parser.add_argument("--history", default=str(DEFAULT_HISTORY))
    parser.add_argument("--dst", default=str(DST_DB))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = backfill(args.history, args.dst, args.dry_run)
    print(f"[backfill_events_history] {json.dumps(result, ensure_ascii=False)}")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
