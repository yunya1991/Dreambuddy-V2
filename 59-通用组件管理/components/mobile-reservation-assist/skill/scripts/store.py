"""SQLite 存储：预约作业、执行结果、事件与游标；带幂等、并发参数与 TTL。

支持网关多线程访问：连接 `check_same_thread=False`，所有读写经同一 RLock 串行化。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = "1"

DDL = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    adapter TEXT NOT NULL,
    task_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    at INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    device_id TEXT,
    dispatched_at INTEGER,
    updated_at INTEGER NOT NULL,
    UNIQUE(task_id, fingerprint)
);
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    device_id TEXT,
    state TEXT NOT NULL,
    detail_json TEXT,
    at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at INTEGER NOT NULL,
    level TEXT NOT NULL,
    code TEXT NOT NULL,
    task_id TEXT,
    payload_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);
CREATE INDEX IF NOT EXISTS idx_events_at ON events(at);
CREATE INDEX IF NOT EXISTS idx_results_job ON results(job_id);
"""

TERMINAL_STATES = ("done", "failed", "unknown", "cooldown")


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        # 网关在子线程访问同一连接，需关闭同线程检查；并发由 _lock 串行化
        self.conn = sqlite3.connect(str(self.path), isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA secure_delete=ON")
        self._migrate()

    # --- 基础设施 ---------------------------------------------------------
    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @contextmanager
    def tx(self):
        with self._lock:
            last: Exception | None = None
            for _ in range(3):
                try:
                    self.conn.execute("BEGIN IMMEDIATE")
                except sqlite3.OperationalError as exc:  # 并发写冲突重试
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

    def _fetchall(self, sql: str, params=()) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, params).fetchall()

    def _fetchone(self, sql: str, params=()):
        with self._lock:
            return self.conn.execute(sql, params).fetchone()

    def _migrate(self) -> None:
        with self._lock:
            self.conn.executescript(DDL)
        with self.tx() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
                (SCHEMA_VERSION,),
            )
            conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('paused', '0')")

    # --- meta -------------------------------------------------------------
    def get_meta(self, key: str, default: str = "") -> str:
        row = self._fetchone("SELECT value FROM meta WHERE key=?", (key,))
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    # --- 作业 -------------------------------------------------------------
    def enqueue_job(self, job: dict) -> bool:
        """插入作业；已存在同 (task_id, fingerprint) 返回 False。"""
        now = int(time.time() * 1000)
        with self.tx() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO jobs(adapter, task_id, fingerprint, at, payload_json,"
                " state, updated_at) VALUES(?, ?, ?, ?, ?, 'pending', ?)",
                (
                    job["adapter"],
                    job["task_id"],
                    job["fingerprint"],
                    int(job.get("at") or now),
                    json.dumps(job, ensure_ascii=False),
                    now,
                ),
            )
            return cursor.rowcount == 1

    @staticmethod
    def _job_row(row: sqlite3.Row) -> dict:
        payload = json.loads(row["payload_json"] or "{}")
        payload["_id"] = row["id"]
        payload["_state"] = row["state"]
        payload["_device_id"] = row["device_id"]
        return payload

    def list_jobs(self, state: str | None = None) -> list[dict]:
        if state:
            rows = self._fetchall("SELECT * FROM jobs WHERE state=? ORDER BY id", (state,))
        else:
            rows = self._fetchall("SELECT * FROM jobs ORDER BY id")
        return [self._job_row(row) for row in rows]

    def get_job(self, job_id: int) -> dict | None:
        row = self._fetchone("SELECT * FROM jobs WHERE id=?", (int(job_id),))
        return self._job_row(row) if row else None

    def claim_pending(self, device_id: str, limit: int = 10) -> list[dict]:
        """原子认领：把 pending 置为 dispatched 并回传作业列表。"""
        now = int(time.time() * 1000)
        claimed: list[dict] = []
        with self.tx() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE state='pending' ORDER BY id LIMIT ?", (int(limit),)
            ).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE jobs SET state='dispatched', device_id=?, dispatched_at=?, updated_at=?"
                    " WHERE id=? AND state='pending'",
                    (device_id, now, now, row["id"]),
                )
                claimed.append(
                    self._job_row(
                        conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
                    )
                )
        return claimed

    def set_job_state(self, job_id: int, state: str, device_id: str | None = None) -> bool:
        now = int(time.time() * 1000)
        with self.tx() as conn:
            if device_id:
                cursor = conn.execute(
                    "UPDATE jobs SET state=?, device_id=?, updated_at=? WHERE id=?",
                    (state, device_id, now, int(job_id)),
                )
            else:
                cursor = conn.execute(
                    "UPDATE jobs SET state=?, updated_at=? WHERE id=?",
                    (state, now, int(job_id)),
                )
            return cursor.rowcount > 0

    def has_terminal(self, task_id: str, fingerprint: str) -> bool:
        row = self._fetchone(
            "SELECT state FROM jobs WHERE task_id=? AND fingerprint=?",
            (task_id, fingerprint),
        )
        return bool(row and row["state"] in TERMINAL_STATES)

    # --- 结果 -------------------------------------------------------------
    def add_result(
        self, job_id: int, device_id: str, state: str, detail: dict | None = None
    ) -> int:
        now = int(time.time() * 1000)
        with self.tx() as conn:
            cursor = conn.execute(
                "INSERT INTO results(job_id, device_id, state, detail_json, at) VALUES(?, ?, ?, ?, ?)",
                (int(job_id), device_id, state, json.dumps(detail or {}, ensure_ascii=False), now),
            )
            return cursor.lastrowid or 0

    def list_results(self) -> list[dict]:
        rows = self._fetchall("SELECT * FROM results ORDER BY id")
        return [
            {
                "job_id": row["job_id"],
                "device_id": row["device_id"],
                "state": row["state"],
                "detail": json.loads(row["detail_json"] or "{}"),
                "at": row["at"],
            }
            for row in rows
        ]

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

    def list_events(self) -> list[dict]:
        rows = self._fetchall("SELECT * FROM events ORDER BY at")
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

    # --- TTL --------------------------------------------------------------
    def purge(self, now: int | None = None, results_days: int = 30, events_days: int = 90) -> dict:
        now = int(now or time.time() * 1000)
        results_before = now - results_days * 86400 * 1000
        events_before = now - events_days * 86400 * 1000
        with self.tx() as conn:
            results = conn.execute("DELETE FROM results WHERE at<?", (results_before,)).rowcount
            events = conn.execute("DELETE FROM events WHERE at<?", (events_before,)).rowcount
        return {"results": results, "events": events}
