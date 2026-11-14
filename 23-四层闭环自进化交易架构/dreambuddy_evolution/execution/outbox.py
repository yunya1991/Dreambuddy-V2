"""23 执行发件箱（Outbox）— decision_id 级幂等。

职责：
- 以 ``decision_id`` 为唯一键固化 23 的发单意图，避免重试/重启/重复回调导致重复下单；
- 状态机 ``pending → submitting → submitted → filled``，失败落 ``failed`` 可重试；
- 纯本地 SQLite，不依赖交易所，不改变 22 网关执行路径（幂等是附加保护）；
- 任何 outbox 异常都由调用方 FAIL-OPEN 回退直提，绝不阻断交易。

环境变量：
- ``EVOLUTION_OUTBOX_ENABLED``    默认 on（off 时 ``default_outbox()`` 返回 None）
- ``EVOLUTION_OUTBOX_DB``         默认 ``23/runtime/execution_outbox.db``
- ``EVOLUTION_OUTBOX_MAX_ATTEMPTS`` 默认 5
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_DEFAULT_DB = Path(__file__).resolve().parents[2] / "runtime" / "execution_outbox.db"

STATE_PENDING = "pending"
STATE_SUBMITTING = "submitting"
STATE_SUBMITTED = "submitted"
STATE_FILLED = "filled"
STATE_FAILED = "failed"

# 成功终态：重复决策直接返回缓存结果，不再提交网关
SUCCESS_STATES = (STATE_SUBMITTED, STATE_FILLED)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS execution_outbox (
    decision_id    TEXT PRIMARY KEY,
    signal_id      TEXT DEFAULT '',
    source         TEXT DEFAULT '',
    symbol         TEXT DEFAULT '',
    direction      TEXT DEFAULT '',
    action         TEXT DEFAULT '',
    sz             REAL,
    notional_usdt  REAL DEFAULT 0,
    sl_px          REAL,
    tp_px          REAL,
    decision_json  TEXT NOT NULL,
    state          TEXT NOT NULL,
    attempts       INTEGER NOT NULL DEFAULT 0,
    broker_ord_id  TEXT,
    result_json    TEXT,
    last_error     TEXT DEFAULT '',
    created_at     REAL NOT NULL,
    updated_at     REAL NOT NULL,
    submitted_at   REAL
);
CREATE INDEX IF NOT EXISTS idx_outbox_state ON execution_outbox(state, updated_at);
"""


def _env_flag(name: str, default: str = "on") -> bool:
    return str(os.getenv(name, default)).strip().lower() in ("1", "true", "on", "yes")


def _now() -> float:
    return time.time()


class ExecutionOutbox:
    """SQLite 决策发件箱（线程安全，进程内每次操作独立连接）。"""

    def __init__(
        self,
        db_path: str | Path | None = None,
        max_attempts: int | None = None,
        enabled: bool | None = None,
    ) -> None:
        _env_db = os.getenv("EVOLUTION_OUTBOX_DB") or ""
        self._db_path = Path(db_path or _env_db or _DEFAULT_DB)
        self._max_attempts = int(
            max_attempts
            if max_attempts is not None
            else os.getenv("EVOLUTION_OUTBOX_MAX_ATTEMPTS", "5")
        )
        self._enabled = _env_flag("EVOLUTION_OUTBOX_ENABLED") if enabled is None else bool(enabled)
        self._lock = threading.Lock()
        if self._enabled:
            self._init_schema()

    # ── 基础 ──────────────────────────────────────────────────────
    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def max_attempts(self) -> int:
        return self._max_attempts

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            with self._lock:
                try:
                    yield conn
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._session() as conn:
            conn.executescript(_SCHEMA)

    # ── 写 ────────────────────────────────────────────────────────
    def enqueue(self, decision: dict[str, Any]) -> str:
        """登记决策意图。返回 ``enqueued``（首次）或 ``duplicate``（已存在）。"""
        did = str(decision.get("decision_id") or "").strip()
        if not did:
            raise ValueError("outbox.enqueue: decision_id is required")
        payload = decision.get("payload") if isinstance(decision.get("payload"), dict) else {}
        ts = _now()
        with self._session() as conn:
            cur = conn.execute(
                """INSERT OR IGNORE INTO execution_outbox
                   (decision_id, signal_id, source, symbol, direction, action, sz,
                    notional_usdt, sl_px, tp_px, decision_json, state, attempts,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)""",
                (
                    did,
                    str(decision.get("signal_id") or ""),
                    str(decision.get("source") or ""),
                    str(decision.get("symbol") or ""),
                    str(decision.get("direction") or ""),
                    str(decision.get("action") or ""),
                    decision.get("sz"),
                    float(payload.get("notional_usdt") or 0.0),
                    decision.get("sl_px"),
                    decision.get("tp_px"),
                    json.dumps(decision, ensure_ascii=False, default=str),
                    STATE_PENDING,
                    ts,
                    ts,
                ),
            )
            return "enqueued" if cur.rowcount > 0 else "duplicate"

    def try_acquire(self, decision_id: str) -> bool:
        """抢占提交权：pending/failed → submitting（attempts+1）。

        超过重试上限或已在途/已成功返回 False。
        """
        with self._session() as conn:
            cur = conn.execute(
                """UPDATE execution_outbox
                      SET state=?, attempts=attempts+1, updated_at=?
                    WHERE decision_id=? AND state IN (?, ?) AND attempts < ?""",
                (
                    STATE_SUBMITTING,
                    _now(),
                    decision_id,
                    STATE_PENDING,
                    STATE_FAILED,
                    self._max_attempts,
                ),
            )
            return cur.rowcount > 0

    def mark_submitted(self, decision_id: str, result: Any = None) -> None:
        self._update_terminal(decision_id, STATE_SUBMITTED, result=result)

    def mark_filled(
        self, decision_id: str, broker_ord_id: str | None = None, result: Any = None
    ) -> None:
        self._update_terminal(decision_id, STATE_FILLED, result=result, broker_ord_id=broker_ord_id)

    def mark_failed(self, decision_id: str, error: str = "") -> None:
        with self._session() as conn:
            conn.execute(
                """UPDATE execution_outbox
                      SET state=?, last_error=?, updated_at=?
                    WHERE decision_id=?""",
                (STATE_FAILED, str(error)[:500], _now(), decision_id),
            )

    def _update_terminal(
        self,
        decision_id: str,
        state: str,
        result: Any = None,
        broker_ord_id: str | None = None,
    ) -> None:
        _res = json.dumps(result, ensure_ascii=False, default=str) if result is not None else None
        ts = _now()
        with self._session() as conn:
            conn.execute(
                """UPDATE execution_outbox
                      SET state=?, result_json=?, broker_ord_id=COALESCE(?, broker_ord_id),
                          last_error='', submitted_at=COALESCE(submitted_at, ?), updated_at=?
                    WHERE decision_id=?""",
                (state, _res, broker_ord_id, ts, ts, decision_id),
            )

    def retry_pending(self, stale_seconds: float = 300.0) -> int:
        """把 failed / 僵死 submitting 重置为 pending（attempts 未超限）。返回重置条数。"""
        now = _now()
        cutoff = now - float(stale_seconds)
        with self._session() as conn:
            cur = conn.execute(
                """UPDATE execution_outbox
                      SET state=?, updated_at=?
                    WHERE attempts < ?
                      AND (state=? OR (state=? AND updated_at < ?))""",
                (STATE_PENDING, now, self._max_attempts, STATE_FAILED, STATE_SUBMITTING, cutoff),
            )
            return cur.rowcount

    # ── 读 ────────────────────────────────────────────────────────
    def get(self, decision_id: str) -> dict[str, Any] | None:
        with self._session() as conn:
            row = conn.execute(
                "SELECT * FROM execution_outbox WHERE decision_id=?", (decision_id,)
            ).fetchone()
        if row is None:
            return None
        out = dict(row)
        try:
            out["result"] = json.loads(out.pop("result_json") or "null")
        except (TypeError, ValueError):
            out["result"] = None
        return out


def default_outbox(db_path: str | Path | None = None) -> ExecutionOutbox | None:
    """按环境变量构造默认发件箱；``EVOLUTION_OUTBOX_ENABLED=off`` 时返回 None。"""
    box = ExecutionOutbox(db_path=db_path)
    return box if box.enabled else None
