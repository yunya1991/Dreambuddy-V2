# -*- coding: utf-8 -*-
"""B18 收尾：压缩 `mm_metric_vintages` 中的「重复观测」（语义保持 As-Of 回放）。

背景：`upsert_metric` 历史上每轮采集都追加一条 vintage，而 fred/panewslab 等源
每轮重采整段历史，导致同一 `(period_ts, value)` 在 180 天内被记录数百次
（云端 2026-11-25 实测：114.9M 行里 114.0M 行是与前一条取值相同的重复观测，
单日新增约 2000 万行，表体积约 18G）。

压缩规则（保守，只删「取值与前一条完全相同」的行）：

  - 保留每个序列（source, sub_category, metric_name, period_ts）的第一条观测；
  - 只有 metric_value 发生变化（真实修订）才保留；
  - `observed_at <= 0` 的脏数据不删，只在报告里计数；
  - As-Of 回放取 `observed_at <= as_of` 的最后一条，删掉重复观测不改变任何时点的取值。

写入侧幂等由 `upsert_metric`（同值不再追加）保证，本脚本只做一次性收敛。

用法（生产机用 `sudo -u luke -H`，先跑 dry-run）：

    python3 retain_metric_vintages.py --db <dreambuddy_core.db>            # 只统计
    python3 retain_metric_vintages.py --db <dreambuddy_core.db> --apply    # 重建表
    python3 retain_metric_vintages.py --db <dreambuddy_core.db> --apply --vacuum
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time

TABLE = "mm_metric_vintages"
REBUILD = "mm_metric_vintages__rebuild"

_DDL = """
CREATE TABLE {name} (
    source       TEXT    NOT NULL,
    sub_category TEXT    NOT NULL,
    metric_name  TEXT    NOT NULL,
    period_ts    INTEGER NOT NULL,
    observed_at  INTEGER NOT NULL,
    metric_value REAL,
    PRIMARY KEY (source, sub_category, metric_name, period_ts, observed_at)
) WITHOUT ROWID
"""

_INDEX = (
    "CREATE INDEX idx_vintages_replay ON {name} (sub_category, metric_name, period_ts, observed_at)"
)

# 窗口按主键顺序取上一条；主键索引天然满足 PARTITION BY + ORDER BY，无需额外排序
_WINDOW = f"""
SELECT source, sub_category, metric_name, period_ts, observed_at, metric_value
FROM (
    SELECT source, sub_category, metric_name, period_ts, observed_at, metric_value,
           lag(metric_value) OVER (
               PARTITION BY source, sub_category, metric_name, period_ts
               ORDER BY observed_at
           ) AS prev_value
    FROM {TABLE}
    WHERE observed_at > 0
)
WHERE prev_value IS NULL OR prev_value IS NOT metric_value
"""


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=300, isolation_level=None)
    conn.execute("PRAGMA temp_store=FILE")
    conn.execute("PRAGMA cache_size=-262144")
    return conn


def _db_size(db_path: str) -> int:
    total = 0
    for suffix in ("", "-wal"):
        p = db_path + suffix
        if os.path.exists(p):
            total += os.path.getsize(p)
    return total


def survey(db_path: str) -> dict:
    conn = _connect(db_path)
    try:
        before = conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
        dirty = conn.execute(f"SELECT COUNT(*) FROM {TABLE} WHERE observed_at <= 0").fetchone()[0]
        keep = conn.execute(f"SELECT COUNT(*) FROM ({_WINDOW})").fetchone()[0]
    finally:
        conn.close()
    return {
        "mode": "dry-run",
        "rows_before": before,
        "dirty_observed_at_le_0": dirty,
        "rows_keep": keep,
        "rows_delete": before - dirty - keep,
        "db_bytes": _db_size(db_path),
    }


def compress(db_path: str, vacuum: bool = False) -> dict:
    started = time.time()
    size_before = _db_size(db_path)
    conn = _connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        before = conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
        dirty = conn.execute(f"SELECT COUNT(*) FROM {TABLE} WHERE observed_at <= 0").fetchone()[0]
        conn.execute(f"DROP TABLE IF EXISTS {REBUILD}")
        conn.execute(_DDL.format(name=REBUILD))
        # 脏数据（observed_at <= 0）原样保留，只做标记不参与压缩
        conn.execute(f"INSERT INTO {REBUILD} SELECT * FROM {TABLE} WHERE observed_at <= 0")
        conn.execute(f"INSERT INTO {REBUILD} {_WINDOW}")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(f"DROP TABLE {TABLE}")
        conn.execute(f"ALTER TABLE {REBUILD} RENAME TO {TABLE}")
        conn.execute(_INDEX.format(name=TABLE))
        conn.execute("COMMIT")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        if vacuum:
            conn.execute("VACUUM")
        check = conn.execute("PRAGMA quick_check").fetchone()[0]
        after = conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
    finally:
        conn.close()
    return {
        "mode": "apply",
        "rows_before": before,
        "dirty_observed_at_le_0": dirty,
        "rows_after": after,
        "rows_deleted": before - after,
        "quick_check": check,
        "vacuum": vacuum,
        "db_bytes_before": size_before,
        "db_bytes_after": _db_size(db_path),
        "elapsed_sec": round(time.time() - started, 1),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="压缩 mm_metric_vintages 重复观测")
    parser.add_argument("--db", default="", help="dreambuddy_core.db 路径")
    parser.add_argument("--apply", action="store_true", help="真正重建表（默认只统计）")
    parser.add_argument("--vacuum", action="store_true", help="重建后执行 VACUUM 回收空间")
    args = parser.parse_args(argv)
    db_path = args.db or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "data", "dreambuddy_core.db"
    )
    if not os.path.isfile(db_path):
        raise FileNotFoundError(db_path)
    report = compress(db_path, vacuum=args.vacuum) if args.apply else survey(db_path)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report.get("quick_check", "ok") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
