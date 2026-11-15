# -*- coding: utf-8 -*-
"""`trading.db` 建表迁移与 signal 追加（SPEC-54 §4.6 / L1D-02）。

设计边界：
  - **signal / fill 只追加**：SQLite 触发器直接拒绝 UPDATE/DELETE，不是文档约定；
  - **迁移幂等**：仅 `CREATE ... IF NOT EXISTS` + `PRAGMA user_version`，可重复执行；
  - **不持有下单客户端**：本库只落内部记录，执行由 22 执行引擎中心完成；
  - 不进信封：`visibility=internal` 的能力在 manifest 阶段已被拒绝外露（ADR-V14）。
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3
from typing import Any, Dict, List, Mapping, Optional, Sequence

_MODULE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.normpath(os.path.join(_MODULE_ROOT, "..", "data", "trading.db"))
DB_ENV_VAR = "L1_TRADING_DB"
SCHEMA_VERSION = 2

TABLES: Sequence[str] = ("signal", "order", "fill", "position", "comparison")
SIGNAL_COLUMNS: Sequence[str] = (
    "id",
    "as_of",
    "symbol",
    "rule_version",
    "params_hash",
    "direction",
    "strength",
    "slope_signs",
    "adx_band",
    "ema_order",
    "p_adj",
    "flags",
    "seasonality",
    "inputs_snapshot",
    "weights_version",
    "weights_hash",
    "weights_effective_date",
    "axis_weights",
    "weight_sources",
    "created_at",
)
_SIGNAL_REQUIRED = (
    "as_of",
    "symbol",
    "rule_version",
    "params_hash",
    "direction",
    "strength",
    "inputs_snapshot",
)
_SIGNAL_JSON_FIELDS = (
    "slope_signs",
    "flags",
    "seasonality",
    "inputs_snapshot",
    "axis_weights",
    "weight_sources",
)
# v2 迁移（SPEC §4.13 落库字段）：幂等 ALTER，历史库直接补列
_SIGNAL_V2_COLUMNS: Sequence[tuple] = (
    ("weights_version", "TEXT"),
    ("weights_hash", "TEXT"),
    ("weights_effective_date", "TEXT"),
    ("axis_weights", "TEXT"),
    ("weight_sources", "TEXT"),
)

_DDL: Sequence[str] = (
    """
    CREATE TABLE IF NOT EXISTS signal (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        as_of           TEXT    NOT NULL,
        symbol          TEXT    NOT NULL,
        rule_version    TEXT    NOT NULL,
        params_hash     TEXT    NOT NULL,
        direction       INTEGER NOT NULL CHECK (direction IN (-1, 0, 1)),
        strength        REAL    NOT NULL CHECK (strength >= 0 AND strength <= 1),
        slope_signs     TEXT,
        adx_band        TEXT,
        ema_order       TEXT    CHECK (ema_order IS NULL OR ema_order IN ('bull', 'bear', 'mixed')),
        p_adj           REAL,
        flags           TEXT,
        seasonality     TEXT,
        inputs_snapshot TEXT    NOT NULL,
        weights_version TEXT,
        weights_hash    TEXT,
        weights_effective_date TEXT,
        axis_weights    TEXT,
        weight_sources  TEXT,
        created_at      TEXT    NOT NULL,
        UNIQUE (as_of, symbol, rule_version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS "order" (
        order_id      TEXT    PRIMARY KEY,
        signal_id     INTEGER NOT NULL REFERENCES signal(id),
        symbol        TEXT    NOT NULL,
        side          TEXT    NOT NULL CHECK (side IN ('buy', 'sell')),
        qty           REAL    NOT NULL,
        notional      REAL,
        td_mode       TEXT,
        reduce_only   INTEGER NOT NULL DEFAULT 0 CHECK (reduce_only IN (0, 1)),
        status        TEXT    NOT NULL,
        reject_reason TEXT,
        created_at    TEXT    NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fill (
        fill_id  TEXT    PRIMARY KEY,
        order_id TEXT    NOT NULL REFERENCES "order"(order_id),
        price    REAL    NOT NULL,
        qty      REAL    NOT NULL,
        fee      REAL    NOT NULL DEFAULT 0,
        ts       TEXT    NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS position (
        symbol       TEXT PRIMARY KEY,
        qty          REAL NOT NULL,
        avg_price    REAL NOT NULL,
        unrealized   REAL,
        exposure_usd REAL,
        updated_at   TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS comparison (
        as_of        TEXT    NOT NULL,
        symbol       TEXT    NOT NULL,
        l1_direction INTEGER CHECK (l1_direction IN (-1, 0, 1)),
        l1_strength  REAL,
        l2_verdict   TEXT,
        realized_ret REAL,
        scored_at    TEXT,
        PRIMARY KEY (as_of, symbol)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_signal_symbol_asof ON signal (symbol, as_of)",
    'CREATE INDEX IF NOT EXISTS idx_order_signal ON "order" (signal_id)',
    "CREATE INDEX IF NOT EXISTS idx_fill_order ON fill (order_id)",
    """
    CREATE TRIGGER IF NOT EXISTS signal_append_only_update
    BEFORE UPDATE ON signal
    BEGIN SELECT RAISE(ABORT, 'signal is append-only'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS signal_append_only_delete
    BEFORE DELETE ON signal
    BEGIN SELECT RAISE(ABORT, 'signal is append-only'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS fill_append_only_update
    BEFORE UPDATE ON fill
    BEGIN SELECT RAISE(ABORT, 'fill is append-only'); END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS fill_append_only_delete
    BEFORE DELETE ON fill
    BEGIN SELECT RAISE(ABORT, 'fill is append-only'); END
    """,
)


class TradingStoreError(ValueError):
    """signal 字段/取值不合契约。"""


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def resolve_db(db_path: Optional[str] = None) -> str:
    return os.path.abspath(db_path or os.environ.get(DB_ENV_VAR) or DEFAULT_DB)


def connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    """打开（并在需要时创建）`trading.db`；父目录自动创建。"""
    target = resolve_db(db_path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate(db_path: Optional[str] = None) -> Dict[str, Any]:
    """幂等建表；返回本次实际新建的表/触发器（重复执行应为空）。"""
    target = resolve_db(db_path)
    conn = connect(target)
    try:
        before = set(_existing(conn, "table"))
        for statement in _DDL:
            conn.execute(statement)
        # v1 → v2：历史库补 weights_* 列（幂等；列已存在则跳过）
        existing_columns = {
            row[1] for row in conn.execute('PRAGMA table_info("signal")').fetchall()
        }
        for name, kind in _SIGNAL_V2_COLUMNS:
            if name not in existing_columns:
                conn.execute(f'ALTER TABLE signal ADD COLUMN "{name}" {kind}')
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
        after = set(_existing(conn, "table"))
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
    return {
        "db": target,
        "schema_version": int(version),
        "tables": [name for name in TABLES if name in after],
        "created": sorted(after - before),
    }


def _existing(conn: sqlite3.Connection, kind: str) -> List[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type=? AND name NOT LIKE 'sqlite_%'", (kind,)
    ).fetchall()
    return [row[0] for row in rows]


def table_columns(db_path: Optional[str] = None, table: str = "signal") -> List[str]:
    conn = connect(db_path)
    try:
        rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    finally:
        conn.close()
    return [row["name"] for row in rows]


def _encode(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return value


def append_signal(
    signal: Mapping[str, Any],
    db_path: Optional[str] = None,
    *,
    created_at: Optional[str] = None,
) -> int:
    """追加一条方向记录；同 `(as_of, symbol, rule_version)` 重复写会被 UNIQUE 拒绝。"""
    missing = [key for key in _SIGNAL_REQUIRED if signal.get(key) is None]
    if missing:
        raise TradingStoreError(f"signal 缺少字段: {','.join(missing)}")
    direction = int(signal["direction"])
    if direction not in (-1, 0, 1):
        raise TradingStoreError("direction 必须 ∈ {-1,0,1}")
    strength = float(signal["strength"])
    if not 0.0 <= strength <= 1.0:
        raise TradingStoreError("strength 必须 ∈ [0,1]")
    payload = {
        "as_of": str(signal["as_of"]),
        "symbol": str(signal["symbol"]),
        "rule_version": str(signal["rule_version"]),
        "params_hash": str(signal["params_hash"]),
        "direction": direction,
        "strength": strength,
        "slope_signs": _encode(signal.get("slope_signs")),
        "adx_band": signal.get("adx_band"),
        "ema_order": signal.get("ema_order"),
        "p_adj": float(signal["p_adj"]) if signal.get("p_adj") is not None else None,
        "flags": _encode(signal.get("flags")),
        "seasonality": _encode(signal.get("seasonality")),
        "inputs_snapshot": _encode(signal.get("inputs_snapshot")),
        "weights_version": signal.get("weights_version"),
        "weights_hash": signal.get("weights_hash"),
        "weights_effective_date": signal.get("weights_effective_date"),
        "axis_weights": _encode(signal.get("axis_weights")),
        "weight_sources": _encode(signal.get("weight_sources")),
        "created_at": created_at or _now(),
    }
    conn = connect(db_path)
    try:
        columns = ", ".join(payload)
        holders = ", ".join("?" for _ in payload)
        cursor = conn.execute(
            f"INSERT INTO signal ({columns}) VALUES ({holders})", tuple(payload.values())
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def list_signals(
    db_path: Optional[str] = None,
    *,
    symbol: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """仅供回放/测试读取（对外无路由）。"""
    conn = connect(db_path)
    try:
        if symbol:
            rows = conn.execute(
                "SELECT * FROM signal WHERE symbol = ? ORDER BY as_of, id LIMIT ?",
                (symbol, int(limit)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM signal ORDER BY as_of, id LIMIT ?", (int(limit),)
            ).fetchall()
    finally:
        conn.close()
    out: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for field in _SIGNAL_JSON_FIELDS:
            if item.get(field):
                item[field] = json.loads(item[field])
        out.append(item)
    return out
