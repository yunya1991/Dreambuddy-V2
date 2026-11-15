# -*- coding: utf-8 -*-
"""B18：慢频指标 vintage（修订留痕）迁移 + 回填。

背景（SPEC-54 §4.12 / ADR-V20）：`mm_metrics` 主键是 `(source, sub_category,
metric_name, timestamp)` 且回填用 `INSERT OR REPLACE`，同一统计期的修订值会覆盖
旧观测，导致 As-Of 回放读到"未来才知道"的数字（前视）。

本脚本做两件事（均幂等，可重复执行）：

1. 建追加式表 `mm_metric_vintages`，主键多一维 `observed_at`，同一 period 允许多版本；
2. 把现有 `mm_metrics` 全量灌进去（`observed_at := timestamp`，即"首次落库时刻"），
   之后新采集只要写 `observed_at=采集时刻`，修订就不会覆盖原值。

用法（生产机必须先在云端跑，且先做 .backup）：

    sudo -u luke -H python3 migrate_metric_vintage.py --db <dreambuddy_core.db>
    python3 migrate_metric_vintage.py --db ... --dry-run
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import sqlite3
import sys

TABLE_DDL = """
CREATE TABLE IF NOT EXISTS mm_metric_vintages (
    source       TEXT    NOT NULL,
    sub_category TEXT    NOT NULL,
    metric_name  TEXT    NOT NULL,
    period_ts    INTEGER NOT NULL,
    observed_at  INTEGER NOT NULL,
    metric_value REAL,
    PRIMARY KEY (source, sub_category, metric_name, period_ts, observed_at)
) WITHOUT ROWID
"""

INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_vintages_replay "
    "ON mm_metric_vintages (sub_category, metric_name, period_ts, observed_at)"
)


def migrate(db_path: str, *, dry_run: bool = False, backup: bool = True) -> dict:
    if not os.path.isfile(db_path):
        raise FileNotFoundError(db_path)
    backup_path = ""
    if backup and not dry_run:
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = f"{db_path}.{stamp}.pre-vintage.bak"
        src = sqlite3.connect(db_path)
        try:
            dst = sqlite3.connect(backup_path)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()

    conn = sqlite3.connect(db_path)
    try:
        before = (
            conn.execute("SELECT COUNT(*) FROM mm_metric_vintages").fetchone()[0]
            if _has_table(conn, "mm_metric_vintages")
            else 0
        )
        if dry_run:
            rows = conn.execute("SELECT COUNT(*) FROM mm_metrics").fetchone()[0]
            return {
                "dry_run": True,
                "mm_metrics_rows": rows,
                "vintage_before": before,
                "backup": "",
            }
        conn.execute(TABLE_DDL)
        conn.execute(INDEX_DDL)
        # 幂等：已存在的 (source, ..., period, observed_at) 不重复写
        conn.execute(
            "INSERT OR IGNORE INTO mm_metric_vintages "
            "(source, sub_category, metric_name, period_ts, observed_at, metric_value) "
            "SELECT source, sub_category, metric_name, timestamp, timestamp, metric_value "
            "FROM mm_metrics WHERE metric_value IS NOT NULL"
        )
        conn.commit()
        after = conn.execute("SELECT COUNT(*) FROM mm_metric_vintages").fetchone()[0]
    finally:
        conn.close()
    return {
        "dry_run": False,
        "vintage_before": before,
        "vintage_after": after,
        "inserted": after - before,
        "backup": backup_path,
    }


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return bool(row)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="mm_metrics → mm_metric_vintages 迁移/回填")
    parser.add_argument("--db", default="", help="dreambuddy_core.db 路径")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    parser.add_argument("--no-backup", action="store_true", help="跳过 .backup（不推荐）")
    args = parser.parse_args(argv)
    db_path = args.db or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "data", "dreambuddy_core.db"
    )
    report = migrate(db_path, dry_run=args.dry_run, backup=not args.no_backup)
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
