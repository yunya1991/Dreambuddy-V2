# -*- coding: utf-8 -*-
"""B18 vintage 追加工具（SPEC-54 §4.12 第 7 条 / ADR-V20）。

`mm_metrics` 主键含 `timestamp`，`INSERT OR REPLACE` 会让同周期重采覆盖旧值；
回放看到修订后数字即为前视。本模块提供最小 vintage 能力：

  - `ensure_vintage_table(conn)`：幂等建表（PK 含 `observed_at`）+ 回放索引；
  - `append_vintages(conn, rows, observed_at=None)`：批量追加观测，主键冲突忽略。

约定：`observed_at` 为采集时刻（epoch 秒），As-Of 回放只读
`observed_at <= as_of`；历史回填无法还原真实发布时刻，统一记「回填时刻」。
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from typing import Iterable, Optional, Sequence, Tuple

VINTAGE_TABLE = "mm_metric_vintages"

_DDL = f"""
CREATE TABLE IF NOT EXISTS {VINTAGE_TABLE} (
    source       TEXT    NOT NULL,
    sub_category TEXT    NOT NULL,
    metric_name  TEXT    NOT NULL,
    period_ts    INTEGER NOT NULL,
    observed_at  INTEGER NOT NULL,
    metric_value REAL,
    PRIMARY KEY (source, sub_category, metric_name, period_ts, observed_at)
) WITHOUT ROWID
"""

_INDEX_DDL = (
    f"CREATE INDEX IF NOT EXISTS idx_vintages_replay "
    f"ON {VINTAGE_TABLE} (sub_category, metric_name, period_ts, observed_at)"
)


def ensure_vintage_table(conn: sqlite3.Connection) -> None:
    """幂等建表 + 建回放索引（调用方负责 commit）。"""
    conn.execute(_DDL)
    conn.execute(_INDEX_DDL)


_LAST_VALUE_SQL = f"""
SELECT k.source, k.sub_category, k.metric_name, k.period_ts,
       (SELECT v.metric_value FROM {VINTAGE_TABLE} v
         WHERE v.source = k.source
           AND v.sub_category = k.sub_category
           AND v.metric_name = k.metric_name
           AND v.period_ts = k.period_ts
         ORDER BY v.observed_at DESC LIMIT 1) AS last_value
FROM _vk_batch k
"""


def _drop_unchanged(
    conn: sqlite3.Connection, payload: list[Tuple[str, str, str, int, int, float]]
) -> list[Tuple[str, str, str, int, int, float]]:
    """过滤掉「取值与本序列最新一条 vintage 相同」的行（幂等写入）。

    回填脚本每轮都会把整段历史重放一遍，若照单全收，同一个 `(period_ts, value)`
    会随轮询线性累积（云端 mm_metric_vintages 膨胀的主因）。取值不变即非新观测，
    删除它不会改变 As-Of 回放取到的任何时点取值。
    """
    keys = {(p[0], p[1], p[2], p[3]) for p in payload}
    conn.execute("DROP TABLE IF EXISTS temp._vk_batch")
    conn.execute(
        "CREATE TEMP TABLE _vk_batch ("
        " source TEXT NOT NULL, sub_category TEXT NOT NULL, metric_name TEXT NOT NULL,"
        " period_ts INTEGER NOT NULL,"
        " PRIMARY KEY (source, sub_category, metric_name, period_ts)) WITHOUT ROWID"
    )
    try:
        conn.executemany("INSERT OR IGNORE INTO _vk_batch VALUES (?, ?, ?, ?)", keys)
        last = {(r[0], r[1], r[2], r[3]): r[4] for r in conn.execute(_LAST_VALUE_SQL)}
    finally:
        conn.execute("DROP TABLE IF EXISTS temp._vk_batch")
    out = []
    for row in payload:
        prev = last.get((row[0], row[1], row[2], row[3]))
        if prev is not None and float(prev) == row[5]:
            continue
        out.append(row)
    return out


def append_vintages(
    conn: sqlite3.Connection,
    rows: Iterable[Sequence],
    observed_at: Optional[int] = None,
) -> int:
    """批量追加 `(source, sub_category, metric_name, metric_value, period_ts)` 观测。

    返回追加条数（重复主键被 IGNORE，不计入）。`rows` 的列顺序与 `mm_metrics`
    写入顺序一致，便于回填脚本在同一批次上复用。取值与本序列最新观测相同的行
    直接跳过（幂等），因此整段历史重放不会重复累积。
    """
    ensure_vintage_table(conn)
    stamp = int(
        observed_at if observed_at is not None else _dt.datetime.now(_dt.timezone.utc).timestamp()
    )
    payload: list[Tuple[str, str, str, int, int, float]] = []
    for row in rows:
        source, sub_category, metric_name, metric_value, period_ts = row[:5]
        payload.append(
            (
                str(source),
                str(sub_category),
                str(metric_name),
                int(period_ts),
                stamp,
                float(metric_value),
            )
        )
    if not payload:
        return 0
    payload = _drop_unchanged(conn, payload)
    if not payload:
        return 0
    before = conn.total_changes
    conn.executemany(
        f"INSERT OR IGNORE INTO {VINTAGE_TABLE}"
        " (source, sub_category, metric_name, period_ts, observed_at, metric_value)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        payload,
    )
    return conn.total_changes - before


__all__ = ["VINTAGE_TABLE", "append_vintages", "ensure_vintage_table"]
