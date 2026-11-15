# -*- coding: utf-8 -*-
"""L1-X outbox：幂等投递 + 失败重投（SPEC-54 §4.6 / L1X-03）。

边界：
  - **独立库** `data/outbox.db`，不改已验收的五表 `trading.db` 结构；
  - `dedup_key` 由 22 决策的 `decision_id`（缺省时用 `symbol/as_of/direction/rule_version/params_hash`）
    规范哈希而来：**同一决策只会入队一次、只会执行一次**；
  - 状态机 `queued → sent` / `queued → failed →(重投)→ sent`；`failed` 可无限重投，
    `attempts` 只增不减，`sent` 不再重复发送（断点重投不重复）。
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import sqlite3
from typing import Any, Callable, Dict, List, Mapping, Optional

_MODULE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.normpath(os.path.join(_MODULE_ROOT, "..", "data", "outbox.db"))
DB_ENV_VAR = "L1_OUTBOX_DB"

STATE_QUEUED = "queued"
STATE_SENT = "sent"
STATE_FAILED = "failed"

_DDL = """
CREATE TABLE IF NOT EXISTS outbox (
    dedup_key   TEXT    PRIMARY KEY,
    decision_id TEXT,
    symbol      TEXT    NOT NULL,
    payload     TEXT    NOT NULL,
    state       TEXT    NOT NULL CHECK (state IN ('queued', 'sent', 'failed')),
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
)
"""
_INDEX = "CREATE INDEX IF NOT EXISTS idx_outbox_state ON outbox (state, created_at)"


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def resolve_db(db_path: Optional[str] = None) -> str:
    return os.path.abspath(db_path or os.environ.get(DB_ENV_VAR) or DEFAULT_DB)


def _open(db_path: Optional[str] = None) -> sqlite3.Connection:
    target = resolve_db(db_path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.execute(_DDL)
    conn.execute(_INDEX)
    return conn


def _exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='outbox'"
    ).fetchone()
    return row is not None


def migrate(db_path: Optional[str] = None) -> Dict[str, Any]:
    """幂等建表；重复执行 `created=[]`。"""
    target = resolve_db(db_path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    conn = sqlite3.connect(target)
    try:
        created = not _exists(conn)
        conn.execute(_DDL)
        conn.execute(_INDEX)
        conn.commit()
    finally:
        conn.close()
    return {"db": target, "created": ["outbox"] if created else [], "tables": ["outbox"]}


def dedup_key(decision: Mapping[str, Any]) -> str:
    """22 决策 → 去重键（同决策恒等；换 `as_of`/方向/参数即变）。"""
    payload = decision.get("payload")
    payload = payload if isinstance(payload, Mapping) else {}
    decision_id = payload.get("decision_id") or decision.get("decision_id")
    if not decision_id:
        raw_id = decision.get("signal_id")
        if raw_id and "|" in str(raw_id):
            decision_id = str(raw_id).split("|", 1)[1]
        elif raw_id:
            decision_id = str(raw_id)
    if decision_id:
        material: Dict[str, Any] = {"decision_id": str(decision_id)}
    else:
        material = {
            "symbol": decision.get("symbol"),
            "as_of": decision.get("as_of") or payload.get("as_of"),
            "direction": decision.get("direction") or payload.get("l1_direction"),
            "rule_version": decision.get("rule_version") or payload.get("rule_version"),
            "params_hash": decision.get("params_hash") or payload.get("params_hash"),
        }
        if not material["symbol"] or material["as_of"] is None:
            raise ValueError("decision 缺少 symbol/as_of，无法生成 dedup_key")
    blob = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def enqueue(decision: Mapping[str, Any], *, db_path: Optional[str] = None) -> Dict[str, Any]:
    """入队；同 `dedup_key` 已存在则返回 `status=duplicate` 且**不改动已有行**。"""
    key = dedup_key(decision)
    raw_payload = decision.get("payload")
    payload = raw_payload if isinstance(raw_payload, Mapping) else {}
    decision_id = payload.get("decision_id")
    stamp = _now()
    conn = _open(db_path)
    try:
        conn.execute(
            "INSERT INTO outbox (dedup_key, decision_id, symbol, payload, state, attempts,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
            (
                key,
                None if decision_id is None else str(decision_id),
                str(decision.get("symbol") or ""),
                json.dumps(dict(decision), sort_keys=True, ensure_ascii=False),
                STATE_QUEUED,
                stamp,
                stamp,
            ),
        )
        conn.commit()
        return {"dedup_key": key, "status": STATE_QUEUED, "state": STATE_QUEUED}
    except sqlite3.IntegrityError:
        row = conn.execute("SELECT state FROM outbox WHERE dedup_key = ?", (key,)).fetchone()
        return {
            "dedup_key": key,
            "status": "duplicate",
            "state": row["state"] if row else None,
        }
    finally:
        conn.close()


def get(dedup_key: str, *, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = _open(db_path)
    try:
        row = conn.execute("SELECT * FROM outbox WHERE dedup_key = ?", (dedup_key,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    item = dict(row)
    item["payload"] = json.loads(item["payload"])
    return item


def mark_sent(key: str, *, db_path: Optional[str] = None) -> bool:
    """置为 `sent`；已发送过的行不再改动（返回 False 表示无需变更）。"""
    conn = _open(db_path)
    try:
        cur = conn.execute(
            "UPDATE outbox SET state = ?, last_error = NULL, updated_at = ?"
            " WHERE dedup_key = ? AND state != ?",
            (STATE_SENT, _now(), key, STATE_SENT),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def mark_failed(key: str, error: str, *, db_path: Optional[str] = None) -> bool:
    conn = _open(db_path)
    try:
        cur = conn.execute(
            "UPDATE outbox SET state = ?, attempts = attempts + 1, last_error = ?,"
            " updated_at = ? WHERE dedup_key = ?",
            (STATE_FAILED, str(error)[:500], _now(), key),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def pending(*, db_path: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """待投递/待重投队列（`queued` + `failed`），按入队时间升序。"""
    conn = _open(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM outbox WHERE state IN (?, ?) ORDER BY created_at, dedup_key LIMIT ?",
            (STATE_QUEUED, STATE_FAILED, int(limit)),
        ).fetchall()
    finally:
        conn.close()
    out: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["payload"] = json.loads(item["payload"])
        out.append(item)
    return out


def replay_pending(
    send: Callable[[Dict[str, Any]], Any],
    *,
    db_path: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, int]:
    """遍历待投递队列：`send(payload)` 返回 `False` 或抛异常即记失败，其余记成功。"""
    sent = failed = 0
    for row in pending(db_path=db_path, limit=limit):
        try:
            result = send(row["payload"])
        except Exception as exc:  # noqa: BLE001 - 重投必须把发送异常转成可重试状态
            mark_failed(row["dedup_key"], f"{type(exc).__name__}: {exc}", db_path=db_path)
            failed += 1
            continue
        if result is False:
            mark_failed(row["dedup_key"], "send_returned_false", db_path=db_path)
            failed += 1
        else:
            mark_sent(row["dedup_key"], db_path=db_path)
            sent += 1
    return {"sent": sent, "failed": failed}


__all__ = [
    "DB_ENV_VAR",
    "DEFAULT_DB",
    "STATE_FAILED",
    "STATE_QUEUED",
    "STATE_SENT",
    "dedup_key",
    "enqueue",
    "get",
    "mark_failed",
    "mark_sent",
    "migrate",
    "pending",
    "replay_pending",
    "resolve_db",
]
