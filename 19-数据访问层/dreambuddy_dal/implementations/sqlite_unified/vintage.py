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


def append_vintages(
    conn: sqlite3.Connection,
    rows: Iterable[Sequence],
    observed_at: Optional[int] = None,
) -> int:
    """批量追加 `(source, sub_category, metric_name, metric_value, period_ts)` 观测。

    返回追加条数（重复主键被 IGNORE，不计入）。`rows` 的列顺序与 `mm_metrics`
    写入顺序一致，便于回填脚本在同一批次上复用。
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
    before = conn.total_changes
    conn.executemany(
        f"INSERT OR IGNORE INTO {VINTAGE_TABLE}"
        " (source, sub_category, metric_name, period_ts, observed_at, metric_value)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        payload,
    )
    return conn.total_changes - before


__all__ = ["VINTAGE_TABLE", "append_vintages", "ensure_vintage_table"]
