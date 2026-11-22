"""SQLite 存储：预约作业、执行结果、事件与游标；带幂等、并发参数与 TTL。

支持网关多线程访问：连接 `check_same_thread=False`，所有读写经同一 RLock 串行化。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = "9"

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
    trace_id TEXT,
    preferred_device TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    UNIQUE(task_id, fingerprint)
);
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    device_id TEXT,
    state TEXT NOT NULL,
    detail_json TEXT,
    trace_id TEXT,
    stage TEXT,
    screenshot TEXT,
    order_id TEXT,
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
CREATE TABLE IF NOT EXISTS knowledge_cache (
    fingerprint TEXT PRIMARY KEY,
    app TEXT,
    question TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS explorations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    app TEXT NOT NULL,
    goal TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'recording',
    device_id TEXT,
    started_at INTEGER NOT NULL,
    stopped_at INTEGER
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exploration_id INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    at INTEGER NOT NULL,
    package TEXT,
    activity TEXT,
    page_text TEXT,
    screenshot TEXT,
    nodes_json TEXT,
    signature TEXT
);
CREATE INDEX IF NOT EXISTS idx_snapshots_exp ON snapshots(exploration_id, seq);
CREATE TABLE IF NOT EXISTS adapter_baselines (
    name TEXT PRIMARY KEY,
    app TEXT,
    exploration_id INTEGER,
    steps_json TEXT,
    assertions_json TEXT,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS regression_cases (
    case_id TEXT PRIMARY KEY,
    baseline_name TEXT NOT NULL,
    exploration_id INTEGER NOT NULL,
    expect_compatible INTEGER NOT NULL DEFAULT 1,
    tags TEXT,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS regression_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at INTEGER NOT NULL,
    report_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    last_state TEXT
);
CREATE TABLE IF NOT EXISTS phone_job_links (
    command_id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL,
    trace_id TEXT,
    device_id TEXT,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS twitter_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    media_json TEXT,
    scheduled_at INTEGER NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    tweet_url TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    posted_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_twitter_due ON twitter_posts(state, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_phone_links_job ON phone_job_links(job_id);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);
CREATE INDEX IF NOT EXISTS idx_events_at ON events(at);
CREATE INDEX IF NOT EXISTS idx_results_job ON results(job_id);
"""

TERMINAL_STATES = ("done", "failed", "unknown", "cooldown")
# 等待人工/人工接管/订单未知：不属终态，但必须阻断重复入队与自动重派
HUMAN_STATES = ("pending_human", "takeover")
RECONCILE_STATES = ("order_unknown",)
BLOCKING_STATES = TERMINAL_STATES + HUMAN_STATES + RECONCILE_STATES
STATES = ("pending", "dispatched") + BLOCKING_STATES

# 禁止的状态迁移：不确定性/人工态不得直接回到可重派状态（禁止「响应不确定就重试」）
FORBIDDEN_TRANSITIONS = {
    ("order_unknown", "pending"),
    ("order_unknown", "dispatched"),
    ("pending_human", "pending"),
    ("pending_human", "dispatched"),
    ("takeover", "pending"),
    ("takeover", "dispatched"),
}

# 老库升级：补列（SQLite 不支持 ADD COLUMN IF NOT EXISTS）
MIGRATION_COLUMNS = {
    "jobs": {
        "trace_id": "TEXT",
        "preferred_device": "TEXT",
        "attempts": "INTEGER NOT NULL DEFAULT 0",
    },
    "results": {
        "trace_id": "TEXT",
        "stage": "TEXT",
        "screenshot": "TEXT",
        "order_id": "TEXT",
    },
}


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
            for table, columns in MIGRATION_COLUMNS.items():
                existing = {row[1] for row in conn.execute("PRAGMA table_info({})".format(table))}
                for name, decl in columns.items():
                    if name not in existing:
                        conn.execute("ALTER TABLE {} ADD COLUMN {} {}".format(table, name, decl))
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
                " state, preferred_device, attempts, updated_at) VALUES(?, ?, ?, ?, ?, 'pending', ?, 0, ?)",
                (
                    job["adapter"],
                    job["task_id"],
                    job["fingerprint"],
                    int(job.get("at") or now),
                    json.dumps(job, ensure_ascii=False),
                    str(job.get("preferred_device") or "") or None,
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
        payload["_trace_id"] = row["trace_id"] or ""
        payload["_preferred_device"] = row["preferred_device"] or ""
        payload["_attempts"] = int(row["attempts"] or 0)
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

    def get_job_by_task(self, task_id: str, fingerprint: str) -> dict | None:
        row = self._fetchone(
            "SELECT * FROM jobs WHERE task_id=? AND fingerprint=?", (task_id, fingerprint)
        )
        return self._job_row(row) if row else None

    def claim_pending(self, device_id: str, limit: int = 10) -> list[dict]:
        """原子认领：只领未绑定设备或绑定本机的 pending 作业；认领即 attempts+1。"""
        now = int(time.time() * 1000)
        claimed: list[dict] = []
        with self.tx() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE state='pending'"
                " AND (preferred_device IS NULL OR preferred_device='' OR preferred_device=?)"
                " ORDER BY id LIMIT ?",
                (device_id, int(limit)),
            ).fetchall()
            for row in rows:
                cursor = conn.execute(
                    "UPDATE jobs SET state='dispatched', device_id=?, dispatched_at=?, updated_at=?,"
                    " attempts=COALESCE(attempts, 0) + 1 WHERE id=? AND state='pending'",
                    (device_id, now, now, row["id"]),
                )
                if cursor.rowcount != 1:
                    continue
                claimed.append(
                    self._job_row(conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())
                )
        return claimed

    # --- 设备注册表（多设备并发）--------------------------------------------
    def touch_device(self, device_id: str, state: str = "polling", at: int | None = None) -> None:
        if not device_id:
            return
        now = int(at or time.time() * 1000)
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO devices(device_id, first_seen, last_seen, last_state) VALUES(?, ?, ?, ?)"
                " ON CONFLICT(device_id) DO UPDATE SET last_seen=excluded.last_seen,"
                " last_state=excluded.last_state",
                (device_id, now, now, state),
            )

    def get_device(self, device_id: str) -> dict | None:
        row = self._fetchone("SELECT * FROM devices WHERE device_id=?", (device_id,))
        if not row:
            return None
        return {
            "device_id": row["device_id"],
            "first_seen": row["first_seen"],
            "last_seen": row["last_seen"],
            "last_state": row["last_state"] or "",
        }

    def list_devices(self, offline_after: int = 60, now: int | None = None) -> list[dict]:
        """设备列表；超过 offline_after 秒未心跳视为离线。"""
        now_ms = int(now or time.time() * 1000)
        rows = self._fetchall(
            "SELECT d.*, (SELECT COUNT(*) FROM jobs j WHERE j.device_id=d.device_id"
            " AND j.state='dispatched') AS dispatched FROM devices d ORDER BY d.device_id"
        )
        devices = []
        for row in rows:
            devices.append(
                {
                    "device_id": row["device_id"],
                    "first_seen": row["first_seen"],
                    "last_seen": row["last_seen"],
                    "last_state": row["last_state"] or "",
                    "dispatched": row["dispatched"],
                    "online": (now_ms - row["last_seen"]) <= int(offline_after) * 1000,
                }
            )
        return devices

    # --- 旧协议桥接：PhoneCommand ↔ job 关联 -------------------------------
    def add_job_link(
        self, command_id: int, job_id: int, trace_id: str = "", device_id: str = ""
    ) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO phone_job_links(command_id, job_id, trace_id, device_id, created_at)"
                " VALUES(?, ?, ?, ?, ?)"
                " ON CONFLICT(command_id) DO UPDATE SET job_id=excluded.job_id,"
                " trace_id=excluded.trace_id, device_id=excluded.device_id",
                (int(command_id), int(job_id), trace_id, device_id, int(time.time() * 1000)),
            )

    def get_job_link(self, command_id: int) -> dict | None:
        row = self._fetchone("SELECT * FROM phone_job_links WHERE command_id=?", (int(command_id),))
        if not row:
            return None
        return {
            "command_id": row["command_id"],
            "job_id": row["job_id"],
            "trace_id": row["trace_id"] or "",
            "device_id": row["device_id"] or "",
            "created_at": row["created_at"],
        }

    def count_today_accept(self, now: int | None = None) -> int:
        """当日（Asia/Shanghai）已完成接单的作业数，用于 max_accept 硬上限。"""
        now_ms = int(now or time.time() * 1000)
        day_start = (now_ms + 8 * 3600 * 1000) // 86400000 * 86400000 - 8 * 3600 * 1000
        row = self._fetchone(
            "SELECT COUNT(DISTINCT r.job_id) AS n FROM results r JOIN jobs j ON j.id=r.job_id"
            " WHERE j.adapter='carpool' AND r.state='done' AND r.at>=?",
            (day_start,),
        )
        return int(row["n"] or 0) if row else 0

    def set_job_state(self, job_id: int, state: str, device_id: str | None = None) -> bool:
        if state not in STATES:
            raise ValueError("非法作业状态：{}".format(state))
        now = int(time.time() * 1000)
        with self.tx() as conn:
            current = conn.execute("SELECT state FROM jobs WHERE id=?", (int(job_id),)).fetchone()
            if current and (current["state"], state) in FORBIDDEN_TRANSITIONS:
                raise ValueError(
                    "禁止的状态迁移：{} → {}（需人工/对账收敛）".format(current["state"], state)
                )
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

    def update_job_trace(self, job_id: int, trace_id: str) -> bool:
        """记录下发用 trace_id，便于回执与作业一一对应。"""
        if not trace_id:
            return False
        with self.tx() as conn:
            cursor = conn.execute(
                "UPDATE jobs SET trace_id=?, updated_at=? WHERE id=?",
                (trace_id, int(time.time() * 1000), int(job_id)),
            )
            return cursor.rowcount > 0

    def list_stuck(self, seconds: int, now: int | None = None) -> list[dict]:
        """派发超过 seconds 秒仍无回执的作业（异步回执验收的输入）。"""
        deadline = int(now or time.time() * 1000) - int(seconds) * 1000
        rows = self._fetchall(
            "SELECT * FROM jobs WHERE state='dispatched' AND COALESCE(dispatched_at, updated_at) <= ?"
            " ORDER BY id",
            (deadline,),
        )
        return [self._job_row(row) for row in rows]

    def requeue_stale(
        self,
        device_ttl_seconds: int = 90,
        job_timeout_seconds: int = 0,
        max_attempts: int = 2,
        now: int | None = None,
    ) -> dict:
        """掉线/超时回收：设备心跳过期（或作业超时）的 dispatched 作业重新入队。

        与 P0 纪律一致：已有订单证据 → order_unknown 等待对账，绝不重派；
        认领次数达到 max_attempts → failed，避免死循环。
        """
        now_ms = int(now or time.time() * 1000)
        device_deadline = now_ms - int(device_ttl_seconds) * 1000
        job_deadline = now_ms - int(job_timeout_seconds) * 1000 if job_timeout_seconds > 0 else None
        reset: list[int] = []
        failed: list[int] = []
        unknown: list[int] = []
        events: list[tuple[str, str, dict]] = []

        rows = self._fetchall("SELECT * FROM jobs WHERE state='dispatched' ORDER BY id")
        with self.tx() as conn:
            for row in rows:
                device = None
                if row["device_id"]:
                    device = conn.execute(
                        "SELECT last_seen FROM devices WHERE device_id=?", (row["device_id"],)
                    ).fetchone()
                stale = device is None or device["last_seen"] <= device_deadline
                if not stale and job_deadline is not None:
                    stale = int(row["dispatched_at"] or row["updated_at"] or 0) <= job_deadline
                if not stale:
                    continue
                if self.has_order_evidence(row["id"]):
                    conn.execute(
                        "UPDATE jobs SET state='order_unknown', updated_at=? WHERE id=?",
                        (now_ms, row["id"]),
                    )
                    unknown.append(row["id"])
                    events.append(
                        (
                            "warn",
                            "order_unknown_pending_reconcile",
                            {"job_id": row["id"], "reason": "设备掉线且已有订单证据，等待对账"},
                        )
                    )
                    continue
                if int(row["attempts"] or 0) >= int(max_attempts):
                    conn.execute(
                        "UPDATE jobs SET state='failed', updated_at=? WHERE id=?", (now_ms, row["id"])
                    )
                    failed.append(row["id"])
                    events.append(
                        ("warn", "device_stale_failed", {"job_id": row["id"], "reason": "重试次数用尽"})
                    )
                    continue
                conn.execute(
                    "UPDATE jobs SET state='pending', dispatched_at=NULL, device_id=NULL, updated_at=?"
                    " WHERE id=?",
                    (now_ms, row["id"]),
                )
                reset.append(row["id"])
                events.append(
                    ("warn", "device_stale_reset", {"job_id": row["id"], "device_id": row["device_id"]})
                )

        for level, code, payload in events:
            self.add_event(level, code, None, payload)
        return {"reset": reset, "failed": failed, "order_unknown": unknown}

    def has_terminal(self, task_id: str, fingerprint: str) -> bool:
        row = self._fetchone(
            "SELECT state FROM jobs WHERE task_id=? AND fingerprint=?",
            (task_id, fingerprint),
        )
        return bool(row and row["state"] in TERMINAL_STATES)

    def blocks_reenqueue(self, task_id: str, fingerprint: str) -> bool:
        """一次性门禁：终态/等人工/人工接管/订单未知均不得重复入队。"""
        row = self._fetchone(
            "SELECT state FROM jobs WHERE task_id=? AND fingerprint=?",
            (task_id, fingerprint),
        )
        return bool(row and row["state"] in BLOCKING_STATES)

    # --- 结果 -------------------------------------------------------------
    def add_result(
        self,
        job_id: int,
        device_id: str,
        state: str,
        detail: dict | None = None,
        trace_id: str = "",
        stage: str = "",
        screenshot: str = "",
        order_id: str = "",
    ) -> int:
        now = int(time.time() * 1000)
        evidence = detail or {}
        # 结构化列可由 detail 兜底，避免调用方漏传导致证据查不到
        trace_id = trace_id or str(evidence.get("trace_id") or "")
        stage = stage or str(evidence.get("stage") or "")
        screenshot = screenshot or str(evidence.get("screenshot") or "")
        order_id = order_id or str(evidence.get("order_id") or "")
        with self.tx() as conn:
            cursor = conn.execute(
                "INSERT INTO results(job_id, device_id, state, detail_json, trace_id, stage,"
                " screenshot, order_id, at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    int(job_id),
                    device_id,
                    state,
                    json.dumps(detail or {}, ensure_ascii=False),
                    trace_id,
                    stage,
                    screenshot,
                    order_id,
                    now,
                ),
            )
            return cursor.lastrowid or 0

    @staticmethod
    def _result_row(row: sqlite3.Row) -> dict:
        return {
            "job_id": row["job_id"],
            "device_id": row["device_id"],
            "state": row["state"],
            "detail": json.loads(row["detail_json"] or "{}"),
            "trace_id": row["trace_id"] or "",
            "stage": row["stage"] or "",
            "screenshot": row["screenshot"] or "",
            "order_id": row["order_id"] or "",
            "at": row["at"],
        }

    def list_results(self) -> list[dict]:
        rows = self._fetchall("SELECT * FROM results ORDER BY id")
        return [self._result_row(row) for row in rows]

    def latest_result(self, job_id: int) -> dict | None:
        row = self._fetchone(
            "SELECT * FROM results WHERE job_id=? ORDER BY id DESC LIMIT 1", (int(job_id),)
        )
        return self._result_row(row) if row else None

    def has_order_evidence(self, job_id: int) -> bool:
        """是否存在订单证据（订单号或订单未知状态）——有证据就禁止自动重试。"""
        job = self._fetchone("SELECT state FROM jobs WHERE id=?", (int(job_id),))
        if job and job["state"] in RECONCILE_STATES:
            return True
        row = self._fetchone(
            "SELECT 1 FROM results WHERE job_id=? AND COALESCE(order_id, '') != '' LIMIT 1",
            (int(job_id),),
        )
        return bool(row)

    # --- 订单对账 ---------------------------------------------------------
    def list_order_unknown(self) -> list[dict]:
        rows = self._fetchall(
            "SELECT * FROM jobs WHERE state='order_unknown' ORDER BY id"
        )
        return [self._job_row(row) for row in rows]

    def reconcile(self, job_id: int, final_state: str, order_id: str = "", note: str = "") -> dict:
        """人工/对账收敛：order_unknown → done|failed；幂等，重复调用不重复记账。"""
        if final_state not in ("done", "failed"):
            raise ValueError("对账终态只能是 done/failed：{}".format(final_state))
        job = self.get_job(job_id)
        if job is None:
            raise ValueError("作业不存在：{}".format(job_id))
        if job.get("_state") == final_state:
            return {"job_id": int(job_id), "state": final_state, "resolved": False, "reason": "已是对账终态"}
        if job.get("_state") != "order_unknown":
            raise ValueError("仅 order_unknown 可对账：当前 {}".format(job.get("_state")))
        detail = {"reconciled": True, "order_id": order_id, "note": note}
        self.add_result(
            job_id,
            str(job.get("_device_id") or "reconcile"),
            final_state,
            detail,
            trace_id=str(job.get("_trace_id") or ""),
            stage="reconcile",
            order_id=order_id,
        )
        self.set_job_state(job_id, final_state)
        self.add_event(
            "info",
            "order_reconciled",
            job.get("task_id"),
            {"job_id": int(job_id), "state": final_state, "order_id": order_id},
        )
        return {"job_id": int(job_id), "state": final_state, "resolved": True}

    # --- 事件 -------------------------------------------------------------
    def add_event(self, level: str, code: str, task_id: str | None = None, payload: dict | None = None) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO events(at, level, code, task_id, payload_json) VALUES(?, ?, ?, ?, ?)",
                (int(time.time() * 1000), level, code, task_id, json.dumps(payload or {}, ensure_ascii=False)),
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

    # --- 知识缓存（knowledge.ask）------------------------------------------
    def get_knowledge(self, fingerprint: str, now: int | None = None) -> dict | None:
        """取未过期的知识缓存；过期视为未命中。"""
        now_ms = int(now or time.time() * 1000)
        row = self._fetchone("SELECT * FROM knowledge_cache WHERE fingerprint=?", (fingerprint,))
        if not row or row["expires_at"] <= now_ms:
            return None
        payload = json.loads(row["payload_json"] or "{}")
        payload["cached"] = True
        payload["expires_at"] = row["expires_at"]
        return payload

    def put_knowledge(
        self, fingerprint: str, app: str, question: str, payload: dict, ttl_seconds: int = 604800
    ) -> None:
        now = int(time.time() * 1000)
        expires = now + int(ttl_seconds) * 1000
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO knowledge_cache(fingerprint, app, question, payload_json, created_at,"
                " expires_at) VALUES(?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(fingerprint) DO UPDATE SET app=excluded.app,"
                " question=excluded.question, payload_json=excluded.payload_json,"
                " created_at=excluded.created_at, expires_at=excluded.expires_at",
                (fingerprint, app, question, json.dumps(payload, ensure_ascii=False), now, expires),
            )

    # --- 探索录制（mra explore）--------------------------------------------
    @staticmethod
    def _exploration_row(row: sqlite3.Row) -> dict:
        return {
            "_id": row["id"],
            "app": row["app"],
            "goal": row["goal"],
            "state": row["state"],
            "device_id": row["device_id"] or "",
            "started_at": row["started_at"],
            "stopped_at": row["stopped_at"],
        }

    def create_exploration(self, app: str, goal: str, device_id: str = "") -> int:
        now = int(time.time() * 1000)
        with self.tx() as conn:
            cursor = conn.execute(
                "INSERT INTO explorations(app, goal, state, device_id, started_at)"
                " VALUES(?, ?, 'recording', ?, ?)",
                (app, goal, device_id or None, now),
            )
            return cursor.lastrowid or 0

    def get_exploration(self, exploration_id: int) -> dict | None:
        row = self._fetchone("SELECT * FROM explorations WHERE id=?", (int(exploration_id),))
        return self._exploration_row(row) if row else None

    def get_active_exploration(self, device_id: str | None = None) -> dict | None:
        """当前录制中的会话；多设备时按 device_id 过滤。"""
        if device_id:
            row = self._fetchone(
                "SELECT * FROM explorations WHERE state='recording' AND device_id=?"
                " ORDER BY id DESC LIMIT 1",
                (device_id,),
            )
        else:
            row = self._fetchone(
                "SELECT * FROM explorations WHERE state='recording' ORDER BY id DESC LIMIT 1"
            )
        return self._exploration_row(row) if row else None

    def stop_exploration(self, exploration_id: int) -> dict | None:
        now = int(time.time() * 1000)
        with self.tx() as conn:
            conn.execute(
                "UPDATE explorations SET state='stopped', stopped_at=? WHERE id=? AND state='recording'",
                (now, int(exploration_id)),
            )
        return self.get_exploration(exploration_id)

    def list_explorations(self, state: str | None = None) -> list[dict]:
        if state:
            rows = self._fetchall("SELECT * FROM explorations WHERE state=? ORDER BY id", (state,))
        else:
            rows = self._fetchall("SELECT * FROM explorations ORDER BY id")
        return [self._exploration_row(row) for row in rows]

    @staticmethod
    def _snapshot_signature(package: str, activity: str, nodes: list[dict]) -> str:
        texts = []
        for node in nodes or []:
            for key in ("text", "desc"):
                value = str((node or {}).get(key) or "").strip()
                if value:
                    texts.append(value)
        raw = "\u0001".join([str(package or ""), str(activity or ""), "|".join(texts)])
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]

    def add_snapshot(
        self,
        exploration_id: int,
        package: str = "",
        activity: str = "",
        page_text: str = "",
        screenshot: str = "",
        nodes: list[dict] | None = None,
        at: int | None = None,
    ) -> dict:
        """追加页面快照；序号自增，签名与上一帧相同则标记 duplicate（仍保留轨迹）。"""
        nodes = list(nodes or [])[:200]
        signature = self._snapshot_signature(package, activity, nodes)
        now_ms = int(at or time.time() * 1000)
        with self.tx() as conn:
            row = conn.execute(
                "SELECT seq, signature FROM snapshots WHERE exploration_id=? ORDER BY seq DESC LIMIT 1",
                (int(exploration_id),),
            ).fetchone()
            seq = (row["seq"] + 1) if row else 1
            duplicate = bool(row and row["signature"] == signature)
            cursor = conn.execute(
                "INSERT INTO snapshots(exploration_id, seq, at, package, activity, page_text,"
                " screenshot, nodes_json, signature) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    int(exploration_id),
                    seq,
                    now_ms,
                    package,
                    activity,
                    str(page_text or "")[:4000],
                    screenshot,
                    json.dumps(nodes, ensure_ascii=False),
                    signature,
                ),
            )
            return {"id": cursor.lastrowid, "seq": seq, "signature": signature, "duplicate": duplicate}

    def list_snapshots(self, exploration_id: int) -> list[dict]:
        rows = self._fetchall(
            "SELECT * FROM snapshots WHERE exploration_id=? ORDER BY seq", (int(exploration_id),)
        )
        return [
            {
                "id": row["id"],
                "seq": row["seq"],
                "at": row["at"],
                "package": row["package"] or "",
                "activity": row["activity"] or "",
                "page_text": row["page_text"] or "",
                "screenshot": row["screenshot"] or "",
                "nodes": json.loads(row["nodes_json"] or "[]"),
                "signature": row["signature"] or "",
            }
            for row in rows
        ]

    # --- 适配器基线（回放兼容门禁）----------------------------------------
    def save_baseline(
        self, name: str, app: str, exploration_id: int, steps: list[dict], assertions: list[dict]
    ) -> None:
        now = int(time.time() * 1000)
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO adapter_baselines(name, app, exploration_id, steps_json, assertions_json,"
                " created_at) VALUES(?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(name) DO UPDATE SET app=excluded.app,"
                " exploration_id=excluded.exploration_id, steps_json=excluded.steps_json,"
                " assertions_json=excluded.assertions_json, created_at=excluded.created_at",
                (
                    name,
                    app,
                    int(exploration_id),
                    json.dumps(steps or [], ensure_ascii=False),
                    json.dumps(assertions or [], ensure_ascii=False),
                    now,
                ),
            )

    def get_baseline(self, name: str) -> dict | None:
        row = self._fetchone("SELECT * FROM adapter_baselines WHERE name=?", (name,))
        if not row:
            return None
        return {
            "schema": "explore.baseline.v1",
            "name": row["name"],
            "app": row["app"] or "",
            "exploration_id": row["exploration_id"],
            "steps": json.loads(row["steps_json"] or "[]"),
            "assertions": json.loads(row["assertions_json"] or "[]"),
            "created_at": row["created_at"],
        }

    def list_baselines(self) -> list[dict]:
        rows = self._fetchall("SELECT * FROM adapter_baselines ORDER BY name")
        return [
            {
                "name": row["name"],
                "app": row["app"] or "",
                "exploration_id": row["exploration_id"],
                "steps": len(json.loads(row["steps_json"] or "[]")),
                "assertions": len(json.loads(row["assertions_json"] or "[]")),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    # --- 回归任务集 -------------------------------------------------------
    def add_regression_case(
        self,
        case_id: str,
        baseline_name: str,
        exploration_id: int,
        expect_compatible: bool = True,
        tags: str = "",
    ) -> None:
        now = int(time.time() * 1000)
        with self.tx() as conn:
            conn.execute(
                "INSERT INTO regression_cases(case_id, baseline_name, exploration_id,"
                " expect_compatible, tags, created_at) VALUES(?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(case_id) DO UPDATE SET baseline_name=excluded.baseline_name,"
                " exploration_id=excluded.exploration_id, expect_compatible=excluded.expect_compatible,"
                " tags=excluded.tags, created_at=excluded.created_at",
                (case_id, baseline_name, int(exploration_id), 1 if expect_compatible else 0, tags, now),
            )

    def list_regression_cases(self, tag: str = "") -> list[dict]:
        rows = self._fetchall("SELECT * FROM regression_cases ORDER BY case_id")
        cases = [
            {
                "case_id": row["case_id"],
                "baseline_name": row["baseline_name"],
                "exploration_id": row["exploration_id"],
                "expect_compatible": bool(row["expect_compatible"]),
                "tags": row["tags"] or "",
                "created_at": row["created_at"],
            }
            for row in rows
        ]
        if tag:
            cases = [
                case
                for case in cases
                if tag in [item.strip() for item in case["tags"].split(",") if item.strip()]
            ]
        return cases

    def save_regression_run(self, report: dict) -> int:
        payload = dict(report)
        payload.pop("run_id", None)
        with self.tx() as conn:
            cursor = conn.execute(
                "INSERT INTO regression_runs(started_at, report_json) VALUES(?, ?)",
                (int(time.time() * 1000), json.dumps(payload, ensure_ascii=False)),
            )
            return cursor.lastrowid or 0

    def list_regression_runs(self, limit: int = 20) -> list[dict]:
        rows = self._fetchall(
            "SELECT * FROM regression_runs ORDER BY id DESC LIMIT ?", (int(limit),)
        )
        runs = []
        for row in rows:
            report = json.loads(row["report_json"] or "{}")
            runs.append(
                {
                    "_id": row["id"],
                    "started_at": row["started_at"],
                    "total": report.get("total", 0),
                    "passed": report.get("passed", 0),
                    "failed": report.get("failed", 0),
                    "errors": report.get("errors", 0),
                    "ok": bool(report.get("ok")),
                }
            )
        return runs

    def get_regression_run(self, run_id: int) -> dict | None:
        row = self._fetchone("SELECT * FROM regression_runs WHERE id=?", (int(run_id),))
        if not row:
            return None
        report = json.loads(row["report_json"] or "{}")
        report["run_id"] = row["id"]
        report["started_at"] = row["started_at"]
        return report

    # --- 推特定时发布队列 ---------------------------------------------------
    @staticmethod
    def _twitter_row(row: sqlite3.Row) -> dict:
        return {
            "_id": row["id"],
            "text": row["text"],
            "media": json.loads(row["media_json"] or "[]"),
            "scheduled_at": row["scheduled_at"],
            "state": row["state"],
            "attempts": row["attempts"],
            "last_error": row["last_error"] or "",
            "tweet_url": row["tweet_url"] or "",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "posted_at": row["posted_at"],
        }

    def enqueue_twitter_post(self, text: str, scheduled_at: int, media=None) -> int:
        """入队一条推文；scheduled_at 为毫秒时间戳。"""
        body = str(text or "").strip()
        if not body:
            raise ValueError("推文内容不能为空")
        if len(body) > 25000:
            raise ValueError("推文内容超出 X 长文上限")
        now = int(time.time() * 1000)
        with self.tx() as conn:
            cursor = conn.execute(
                "INSERT INTO twitter_posts(text, media_json, scheduled_at, state, created_at, updated_at)"
                " VALUES(?, ?, ?, 'pending', ?, ?)",
                (body, json.dumps(list(media or []), ensure_ascii=False), int(scheduled_at), now, now),
            )
            return int(cursor.lastrowid)

    def list_twitter_posts(self, state: str | None = None, limit: int = 50) -> list[dict]:
        if state:
            rows = self._fetchall(
                "SELECT * FROM twitter_posts WHERE state=? ORDER BY scheduled_at DESC LIMIT ?",
                (state, int(limit)),
            )
        else:
            rows = self._fetchall(
                "SELECT * FROM twitter_posts ORDER BY scheduled_at DESC LIMIT ?", (int(limit),)
            )
        return [self._twitter_row(row) for row in rows]

    def get_twitter_post(self, post_id: int) -> dict | None:
        row = self._fetchone("SELECT * FROM twitter_posts WHERE id=?", (int(post_id),))
        return self._twitter_row(row) if row else None

    def claim_due_twitter_post(self, now: int | None = None) -> dict | None:
        """原子认领一条到点推文：pending → posting，避免并发重复发布。"""
        now = int(now or time.time() * 1000)
        with self.tx() as conn:
            row = conn.execute(
                "SELECT id FROM twitter_posts WHERE state='pending' AND scheduled_at<=?"
                " ORDER BY scheduled_at, id LIMIT 1",
                (now,),
            ).fetchone()
            if not row:
                return None
            cursor = conn.execute(
                "UPDATE twitter_posts SET state='posting', attempts=attempts+1, updated_at=?"
                " WHERE id=? AND state='pending'",
                (now, row["id"]),
            )
            if cursor.rowcount != 1:
                return None
            claimed = conn.execute("SELECT * FROM twitter_posts WHERE id=?", (row["id"],)).fetchone()
            return self._twitter_row(claimed)

    def finish_twitter_post(
        self, post_id: int, state: str, error: str = "", tweet_url: str = ""
    ) -> dict | None:
        """收敛发布结果：posting → done/failed。"""
        if state not in ("done", "failed"):
            raise ValueError("推文终态只能是 done 或 failed")
        now = int(time.time() * 1000)
        with self.tx() as conn:
            cursor = conn.execute(
                "UPDATE twitter_posts SET state=?, last_error=?, tweet_url=?, updated_at=?,"
                " posted_at=? WHERE id=? AND state='posting'",
                (state, error or None, tweet_url or None, now, now if state == "done" else None, int(post_id)),
            )
            if cursor.rowcount != 1:
                return None
            row = conn.execute("SELECT * FROM twitter_posts WHERE id=?", (int(post_id),)).fetchone()
            return self._twitter_row(row)

    def cancel_twitter_post(self, post_id: int) -> dict:
        """取消待发推文；已进入发布中的不允许取消。"""
        now = int(time.time() * 1000)
        with self.tx() as conn:
            row = conn.execute(
                "SELECT state FROM twitter_posts WHERE id=?", (int(post_id),)
            ).fetchone()
            if not row:
                raise ValueError("推文不存在：{}".format(post_id))
            if row["state"] == "posting":
                raise ValueError("推文正在发布中，禁止取消；请先核对是否已发出")
            if row["state"] != "pending":
                raise ValueError("仅 pending 状态可取消，当前：{}".format(row["state"]))
            conn.execute(
                "UPDATE twitter_posts SET state='cancelled', updated_at=? WHERE id=? AND state='pending'",
                (now, int(post_id)),
            )
            updated = conn.execute("SELECT * FROM twitter_posts WHERE id=?", (int(post_id),)).fetchone()
            return self._twitter_row(updated)

    def recover_stale_twitter(self, seconds: int = 900, now: int | None = None) -> int:
        """发布中断恢复：超时仍处于 posting 的标记 failed，交人工核对，禁止自动重发。"""
        now = int(now or time.time() * 1000)
        cutoff = now - int(seconds) * 1000
        with self.tx() as conn:
            return conn.execute(
                "UPDATE twitter_posts SET state='failed', updated_at=?,"
                " last_error='发布中断，结果未知；请人工核对后再决定是否补发'"
                " WHERE state='posting' AND updated_at<?",
                (now, cutoff),
            ).rowcount

    def count_twitter_posts(self, state: str | None = None) -> int:
        if state:
            row = self._fetchone("SELECT COUNT(*) AS n FROM twitter_posts WHERE state=?", (state,))
        else:
            row = self._fetchone("SELECT COUNT(*) AS n FROM twitter_posts")
        return int(row["n"]) if row else 0

    # --- TTL --------------------------------------------------------------
    def purge(self, now: int | None = None, results_days: int = 30, events_days: int = 90) -> dict:
        now = int(now or time.time() * 1000)
        results_before = now - results_days * 86400 * 1000
        events_before = now - events_days * 86400 * 1000
        with self.tx() as conn:
            results = conn.execute("DELETE FROM results WHERE at<?", (results_before,)).rowcount
            events = conn.execute("DELETE FROM events WHERE at<?", (events_before,)).rowcount
            knowledge = conn.execute("DELETE FROM knowledge_cache WHERE expires_at<?", (now,)).rowcount
        return {"results": results, "events": events, "knowledge": knowledge}
