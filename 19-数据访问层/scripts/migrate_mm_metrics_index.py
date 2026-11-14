#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mm_metrics 索引迁移（S1.0-1，幂等）。

背景：mm_metrics 为 WITHOUT ROWID 表（PK = source, sub_category, metric_name, timestamp），
按 (sub_category, metric_name, timestamp) 的区间查询无法命中 PK 前缀；需二级索引。
该索引历史上只由 backfill 脚本创建，DAL 建表路径未保证 → 新建库/云端库可能缺失。

本脚本做三件事（全部幂等）：
  1. 确保 idx_mm_metrics_query (sub_category, metric_name, timestamp) 存在；
  2. 用 EXPLAIN QUERY PLAN 校验区间查询确实走该索引；
  3. 输出迁移前后「3 年日频区间查询」的 p50/p95（真实数据，仅只读基准）。

用法:
  python3 migrate_mm_metrics_index.py                 # 迁移默认库（19/data/dreambuddy_core.db）
  python3 migrate_mm_metrics_index.py --db /path/db   # 指定库（云端用）
  python3 migrate_mm_metrics_index.py --dry-run       # 只检查不建索引
  python3 migrate_mm_metrics_index.py --json          # 机器可读输出

退出码: 0 正常（含 table_missing 跳过）；1 索引不可用/校验失败。
"""

import argparse
import datetime
import json
import os
import sqlite3
import statistics
import sys
import time

_INDEX_NAME = "idx_mm_metrics_query"
_INDEX_DDL = (
    f"CREATE INDEX IF NOT EXISTS {_INDEX_NAME} "
    "ON mm_metrics (sub_category, metric_name, timestamp)"
)
_QUERY = (
    "SELECT source, metric_name, metric_value, timestamp FROM mm_metrics "
    "WHERE sub_category = ? AND metric_name = ? AND timestamp >= ? AND timestamp < ? "
    "ORDER BY timestamp ASC"
)
_BENCH_RUNS = 15
_MAX_P95_MS = 300.0
_DEFAULT_DB = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "dreambuddy_core.db"
)


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def _table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mm_metrics'"
    ).fetchone()
    return row is not None


def _index_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (_INDEX_NAME,)
    ).fetchone()
    return row is not None


def _plan_uses_index(conn: sqlite3.Connection, start_ts: int, end_ts: int) -> bool:
    plan = conn.execute(
        "EXPLAIN QUERY PLAN " + _QUERY, ("__probe__", "__probe__", start_ts, end_ts)
    ).fetchall()
    return any(_INDEX_NAME in str(row[3]) for row in plan)


def _pick_metrics(conn: sqlite3.Connection, limit: int = 3):
    """按样本量确定性选取基准指标（顺序稳定，便于跨机器对比）。"""
    return conn.execute(
        """
        SELECT sub_category, metric_name, COUNT(*) AS n FROM mm_metrics
        GROUP BY sub_category, metric_name HAVING n >= 200
        ORDER BY n DESC, sub_category ASC, metric_name ASC LIMIT ?
        """,
        (limit,),
    ).fetchall()


def _bench(conn: sqlite3.Connection, picks, start_ts: int, end_ts: int):
    out = []
    for sub_category, metric_name, total in picks:
        lat = []
        returned = 0
        for _ in range(_BENCH_RUNS):
            t0 = time.perf_counter()
            rows = conn.execute(_QUERY, (sub_category, metric_name, start_ts, end_ts)).fetchall()
            lat.append((time.perf_counter() - t0) * 1000.0)
            returned = len(rows)
        lat.sort()
        out.append(
            {
                "metric": f"{sub_category}/{metric_name}",
                "total_rows": total,
                "returned": returned,
                "p50_ms": round(statistics.median(lat), 2),
                "p95_ms": round(lat[max(0, int(len(lat) * 0.95) - 1)], 2),
            }
        )
    return out


def migrate(db_path: str, dry_run: bool = False) -> dict:
    result = {
        "db": os.path.abspath(db_path),
        "status": "ok",
        "table_exists": False,
        "index_existed": False,
        "index_created": False,
        "plan_uses_index": False,
        "rows": 0,
        "bench_before": [],
        "bench_after": [],
        "max_p95_ms": None,
        "dry_run": dry_run,
    }
    if not os.path.exists(db_path):
        result["status"] = "db_missing"
        return result

    now = int(time.time())
    start = int((datetime.datetime.now() - datetime.timedelta(days=365 * 3)).timestamp())

    with _connect(db_path) as conn:
        if not _table_exists(conn):
            result["status"] = "table_missing"
            return result

        result["table_exists"] = True
        result["rows"] = conn.execute("SELECT COUNT(*) FROM mm_metrics").fetchone()[0]
        result["index_existed"] = _index_exists(conn)
        picks = _pick_metrics(conn)
        result["bench_before"] = _bench(conn, picks, start, now)

        if not result["index_existed"] and not dry_run:
            conn.execute(_INDEX_DDL)
            conn.commit()
            result["index_created"] = True

        result["plan_uses_index"] = _plan_uses_index(conn, start, now)
        result["bench_after"] = _bench(conn, picks, start, now)
        if result["bench_after"]:
            result["max_p95_ms"] = max(b["p95_ms"] for b in result["bench_after"])

        if not result["plan_uses_index"]:
            result["status"] = "index_unusable"
        elif result["max_p95_ms"] is not None and result["max_p95_ms"] > _MAX_P95_MS:
            result["status"] = "slow"
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="mm_metrics 索引迁移（幂等）")
    parser.add_argument("--db", default=_DEFAULT_DB, help="SQLite 数据库路径")
    parser.add_argument("--dry-run", action="store_true", help="只检查，不创建索引")
    parser.add_argument("--json", action="store_true", help="仅输出 JSON")
    args = parser.parse_args(argv)

    result = migrate(args.db, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"[mm_metrics 索引迁移] db={result['db']}")
        print(
            f"  status={result['status']} rows={result['rows']} "
            f"existed={result['index_existed']} created={result['index_created']} "
            f"plan_uses_index={result['plan_uses_index']}"
        )
        for tag in ("bench_before", "bench_after"):
            for b in result[tag]:
                print(
                    f"  {tag}: {b['metric']} ret={b['returned']} "
                    f"p50={b['p50_ms']}ms p95={b['p95_ms']}ms"
                )
        if result["max_p95_ms"] is not None:
            print(f"  max_p95={result['max_p95_ms']}ms (阈值 {_MAX_P95_MS}ms)")

    return 0 if result["status"] in ("ok", "table_missing", "db_missing") else 1


if __name__ == "__main__":
    sys.exit(main())
