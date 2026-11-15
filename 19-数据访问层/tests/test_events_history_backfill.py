# -*- coding: utf-8 -*-
"""事件历史回填入库测试：长期行不被窗口同步清空 + 幂等写入。"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


history = _load("backfill_events_history")
sync = _load("sync_events_to_dal")

_OLD_EVENT = {
    "event_id": "hash20160120",
    "type": "cpi",
    "subtype": "cpi",
    "symbols": ["US500"],
    "event_time": "2016-01-20T13:30:00Z",
    "available_at": "2016-01-20T13:30:00Z",
    "source": "macro_calendar",
    "title": "Consumer Price Index for December 2015",
    "confidence": 1.0,
    "quality": "A",
}


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )


def test_history_backfill_writes_old_rows_and_is_idempotent(tmp_path):
    src = tmp_path / "history.jsonl"
    _write_jsonl(src, [_OLD_EVENT])
    db = tmp_path / "core.db"

    first = history.backfill(history_path=src, dst_db=db)
    assert first["ok"] is True and first["upserted"] == 1
    second = history.backfill(history_path=src, dst_db=db)
    assert second["db_row_count"] == first["db_row_count"] == 1

    conn = sqlite3.connect(db)
    try:
        ts = conn.execute("SELECT event_time FROM mm_events").fetchone()[0]
    finally:
        conn.close()
    assert ts == 1453296600  # 2016-01-20T13:30:00Z


def test_window_sync_preserves_out_of_window_history(tmp_path):
    src = tmp_path / "history.jsonl"
    _write_jsonl(src, [_OLD_EVENT])
    db = tmp_path / "core.db"
    history.backfill(history_path=src, dst_db=db)

    events_file = tmp_path / "events.jsonl"
    _write_jsonl(
        events_file,
        [
            {
                "event_id": "recent20261120",
                "type": "fomc",
                "subtype": "statement",
                "symbols": ["US500"],
                "event_time": "2026-11-20T19:00:00Z",
                "available_at": "2026-11-20T19:00:00Z",
                "source": "fed_calendar",
                "title": "FOMC statement 2026-11-20",
                "confidence": 1.0,
                "quality": "A",
            }
        ],
    )
    result = sync.sync(events_path=events_file, dst_db=db)
    assert result["ok"] is True

    conn = sqlite3.connect(db)
    try:
        ids = {r[0] for r in conn.execute("SELECT event_id FROM mm_events")}
    finally:
        conn.close()
    assert ids == {"hash20160120", "recent20261120"}
