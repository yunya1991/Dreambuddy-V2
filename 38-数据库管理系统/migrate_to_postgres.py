"""SQLite → PostgreSQL 数据迁移脚本（方案 4 阶段 3）。

迁移 data_center.db 四张表到 PostgreSQL data_center 库，逐表校验行数一致。
用法：DATA_CENTER_PG_PASSWORD=... python migrate_to_postgres.py
"""
from __future__ import annotations

import os
import sqlite3
import sys

import psycopg2

SQLITE_PATH = "/home/luke/dreambuddy/18-数据获取中心/data_center.db"

PG_PARAMS = {
    "host": os.environ.get("DATA_CENTER_PG_HOST", "127.0.0.1"),
    "port": int(os.environ.get("DATA_CENTER_PG_PORT", "5432")),
    "user": os.environ.get("DATA_CENTER_PG_USER", "dreambuddy"),
    "password": os.environ.get("DATA_CENTER_PG_PASSWORD", ""),
    "dbname": os.environ.get("DATA_CENTER_PG_DB", "data_center"),
}

# 表名 -> (列名列表, 是否保留原 id)
TABLES = {
    "records": (
        ["id", "dedupe_key", "source", "category", "sub_category", "timestamp",
         "metrics", "events", "timeseries", "raw", "schema_version"],
        True,
    ),
    "metrics": (
        ["id", "invocation_id", "ts", "source", "category", "status",
         "duration_ms", "records_count", "error_type", "error_msg"],
        True,
    ),
    "quality_issues": (
        ["id", "ts", "source", "category", "code", "message", "invocation_id", "extra"],
        True,
    ),
    "alerts": (["id", "ts", "level", "title", "message", "tags"], True),
}


def main() -> int:
    lite = sqlite3.connect(SQLITE_PATH)
    pg = psycopg2.connect(**PG_PARAMS)
    ok = True
    try:
        with pg:
            with pg.cursor() as cur:
                for table, (cols, keep_id) in TABLES.items():
                    col_list = ", ".join(cols)
                    placeholders = ", ".join(["%s"] * len(cols))
                    target_cols = col_list if keep_id else ", ".join(cols[1:])
                    target_ph = placeholders if keep_id else ", ".join(["%s"] * (len(cols) - 1))
                    rows = lite.execute(f"SELECT {col_list} FROM {table}").fetchall()
                    insert_sql = (
                        f"INSERT INTO {table} ({target_cols}) VALUES ({target_ph}) "
                        f"ON CONFLICT DO NOTHING"
                    )
                    for row in rows:
                        cur.execute(insert_sql, row if keep_id else row[1:])
                    # 校验行数一致
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    pg_count = cur.fetchone()[0]
                    lite_count = len(rows)
                    status = "OK" if pg_count == lite_count else "MISMATCH"
                    if pg_count != lite_count:
                        ok = False
                    print(f"{table}: sqlite={lite_count} postgres={pg_count} [{status}]")
        # 重置序列，避免后续自增 id 冲突
        with pg:
            with pg.cursor() as cur:
                for table in TABLES:
                    cur.execute(
                        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {table}), 1))"
                    )
        print("序列已重置")
    finally:
        lite.close()
        pg.close()
    if not ok:
        print("校验失败：存在行数不一致的表，请检查")
        return 1
    print("迁移完成，全部校验通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
