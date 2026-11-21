"""SQLite 存储：任务、命中、事件、grant；带幂等、TTL 与并发参数。"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = "2"

DDL = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    adapter TEXT NOT NULL,
    target_json TEXT NOT NULL,
    rule_json TEXT NOT NULL,
    window_start INTEGER,
    window_end INTEGER,
    interval_ms INTEGER,
    submit_enabled INTEGER DEFAULT 0,
    max_orders INTEGER DEFAULT 1,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS hits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    at INTEGER NOT NULL,
    snapshot_digest TEXT,
    notified_at INTEGER,
    submit_state TEXT,
    UNIQUE(task_id, fingerprint)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at INTEGER NOT NULL,
    level TEXT NOT NULL,
    code TEXT NOT NULL,
    task_id TEXT,
    payload_json TEXT
);
CREATE TABLE IF NOT EXISTS grants (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    issued_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    hmac TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    adapter TEXT NOT NULL,
    kind TEXT NOT NULL,
    at INTEGER NOT NULL,
    ok INTEGER NOT NULL DEFAULT 0,
    detail_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_hits_task ON hits(task_id);
CREATE INDEX IF NOT EXISTS idx_events_at ON events(at);
CREATE INDEX IF NOT EXISTS idx_drills_adapter ON drills(adapter, kind);
"""


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA secure_delete=ON")
        self._migrate()

    # --- 基础设施 ---------------------------------------------------------
    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @contextmanager
    def tx(self):
        last: Exception | None = None
        for _ in range(3):
            try:
                self.conn.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:  # 并发写冲突，重试 3 次
                last = exc
                time.sleep(0.05)
                continue
            try:
                yield self.conn
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
            else:
                self.conn.execute("COMMIT")
                return
        raise last if last else RuntimeError("BEGIN IMMEDIATE 失败")

    def _migrate(self) -> None:
        self.conn.executescript(DDL)
        with self.tx() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
                (SCHEMA_VERSION,),
            )
            conn.execute("UPDATE meta SET value=? WHERE key='schema_version'", (SCHEMA_VERSION,))
            conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('paused', '0')")

    # --- meta -------------------------------------------------------------
    def get_meta(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    # --- 任务 -------------------------------------------------------------
    def add_task(self, task: dict) -> str:
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO tasks(id, adapter, target_json, rule_json, window_start, window_end,"
                " interval_ms, submit_enabled, max_orders, created_at)"
                " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task["id"],
                    task["adapter"],
                    json.dumps(task.get("target") or {}, ensure_ascii=False),
                    json.dumps(task.get("rule") or {}, ensure_ascii=False),
                    task.get("window_start"),
                    task.get("window_end"),
                    task.get("interval_ms"),
                    int(bool(task.get("submit_enabled"))),
                    int(task.get("max_orders", 1)),
                    int(task.get("created_at") or time.time() * 1000),
                ),
            )
        return task["id"]

    @staticmethod
    def _task_row(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "adapter": row["adapter"],
            "target": json.loads(row["target_json"] or "{}"),
            "rule": json.loads(row["rule_json"] or "{}"),
            "window_start": row["window_start"],
            "window_end": row["window_end"],
            "interval_ms": row["interval_ms"],
            "submit_enabled": row["submit_enabled"],
            "max_orders": row["max_orders"],
            "created_at": row["created_at"],
            "status": "armed",
        }

    def list_tasks(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM tasks ORDER BY created_at").fetchall()
        return [self._task_row(row) for row in rows]

    def get_task(self, task_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return self._task_row(row) if row else None

    def delete_task(self, task_id: str) -> bool:
        with self.tx() as conn:
            conn.execute("DELETE FROM hits WHERE task_id=?", (task_id,))
            conn.execute("DELETE FROM grants WHERE task_id=?", (task_id,))
            cursor = conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        return cursor.rowcount > 0

    # --- 命中 -------------------------------------------------------------
    def upsert_hit(
        self, task_id: str, fingerprint: str, at: int, snapshot_digest: str = ""
    ) -> bool:
        """返回 True 表示首次命中（应通知），False 表示重复命中。"""
        with self.tx() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO hits(task_id, fingerprint, at, snapshot_digest)"
                " VALUES(?, ?, ?, ?)",
                (task_id, fingerprint, int(at), snapshot_digest),
            )
            return cursor.rowcount == 1

    def get_hit(self, task_id: str, fingerprint: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM hits WHERE task_id=? AND fingerprint=?", (task_id, fingerprint)
        ).fetchone()
        return dict(row) if row else None

    def mark_notified(self, task_id: str, fingerprint: str, at: int) -> None:
        with self.tx() as conn:
            conn.execute(
                "UPDATE hits SET notified_at=? WHERE task_id=? AND fingerprint=?",
                (int(at), task_id, fingerprint),
            )

    def set_submit_state(self, task_id: str, fingerprint: str, state: str) -> None:
        with self.tx() as conn:
            conn.execute(
                "UPDATE hits SET submit_state=? WHERE task_id=? AND fingerprint=?",
                (state, task_id, fingerprint),
            )

    def has_terminal_submit(self, task_id: str, fingerprint: str) -> bool:
        row = self.conn.execute(
            "SELECT submit_state FROM hits WHERE task_id=? AND fingerprint=?",
            (task_id, fingerprint),
        ).fetchone()
        return bool(row and row["submit_state"] in ("submitted", "unknown", "closed"))

    def list_hits(self, task_id: str | None = None) -> list[dict]:
        if task_id:
            rows = self.conn.execute(
                "SELECT * FROM hits WHERE task_id=? ORDER BY at", (task_id,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM hits ORDER BY at").fetchall()
        return [dict(row) for row in rows]

    # --- 事件 -------------------------------------------------------------
    def add_event(
        self, level: str, code: str, task_id: str | None = None, payload: dict | None = None
    ) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO events(at, level, code, task_id, payload_json) VALUES(?, ?, ?, ?, ?)",
                (
                    int(time.time() * 1000),
                    level,
                    code,
                    task_id,
                    json.dumps(payload or {}, ensure_ascii=False),
                ),
            )

    def list_events(self, since: int | None = None, task_id: str | None = None) -> list[dict]:
        sql = "SELECT * FROM events"
        clauses, params = [], []
        if since is not None:
            clauses.append("at>=?")
            params.append(int(since))
        if task_id:
            clauses.append("task_id=?")
            params.append(task_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY at"
        rows = self.conn.execute(sql, params).fetchall()
        return [
            {
                "at": row["at"],
                "level": row["level"],
                "code": row["code"],
                "task_id": row["task_id"],
                "payload": json.loads(row["payload_json"] or "{}"),
            }
            for row in rows
        ]

    # --- grant ------------------------------------------------------------
    def put_grant(self, grant: dict) -> None:
        with self.tx() as conn:
            conn.execute("DELETE FROM grants WHERE task_id=?", (grant["task_id"],))
            conn.execute(
                "INSERT INTO grants(id, task_id, fingerprint, issued_at, expires_at, hmac)"
                " VALUES(?, ?, ?, ?, ?, ?)",
                (
                    grant["id"],
                    grant["task_id"],
                    grant["fingerprint"],
                    int(grant["issued_at"]),
                    int(grant["expires_at"]),
                    grant["hmac"],
                ),
            )

    def get_grant(self, task_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM grants WHERE task_id=?", (task_id,)).fetchone()
        return dict(row) if row else None

    def revoke_grant(self, task_id: str) -> bool:
        with self.tx() as conn:
            cursor = conn.execute("DELETE FROM grants WHERE task_id=?", (task_id,))
        return cursor.rowcount > 0

    def set_task_notify(self, task_id: str, channels: str) -> bool:
        with self.tx() as conn:
            row = conn.execute("SELECT rule_json FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                return False
            rule = json.loads(row["rule_json"] or "{}")
            rule["notify"] = channels
            conn.execute(
                "UPDATE tasks SET rule_json=? WHERE id=?",
                (json.dumps(rule, ensure_ascii=False), task_id),
            )
        return True

    # --- 就绪实验 ---------------------------------------------------------
    def add_drill(
        self,
        adapter: str,
        kind: str,
        ok: bool,
        detail: dict | None = None,
        at: int | None = None,
    ) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO drills(adapter, kind, at, ok, detail_json) VALUES(?, ?, ?, ?, ?)",
                (
                    adapter,
                    kind,
                    int(at if at is not None else time.time() * 1000),
                    int(bool(ok)),
                    json.dumps(detail or {}, ensure_ascii=False),
                ),
            )

    def list_drills(self, adapter: str | None = None, kind: str | None = None) -> list[dict]:
        sql = "SELECT * FROM drills"
        clauses, params = [], []
        if adapter:
            clauses.append("adapter=?")
            params.append(adapter)
        if kind:
            clauses.append("kind=?")
            params.append(kind)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY at"
        rows = self.conn.execute(sql, params).fetchall()
        return [
            {
                "adapter": row["adapter"],
                "kind": row["kind"],
                "at": row["at"],
                "ok": row["ok"],
                "detail": json.loads(row["detail_json"] or "{}"),
            }
            for row in rows
        ]

    # --- TTL --------------------------------------------------------------
    def purge(self, now: int | None = None, hits_days: int = 30, events_days: int = 90) -> dict:
        now = int(now or time.time() * 1000)
        hits_before = now - hits_days * 86400 * 1000
        events_before = now - events_days * 86400 * 1000
        with self.tx() as conn:
            hits = conn.execute("DELETE FROM hits WHERE at<?", (hits_before,)).rowcount
            events = conn.execute("DELETE FROM events WHERE at<?", (events_before,)).rowcount
            grants = conn.execute("DELETE FROM grants WHERE expires_at<?", (now,)).rowcount
        return {"hits": hits, "events": events, "grants": grants}
