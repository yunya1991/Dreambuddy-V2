#!/usr/bin/env python3
"""P0 回填脚本：18-数据获取中心 records → 19-DAL mm_metrics 通用指标表。

将 18 的 data_center.db.records 中所有数值型指标，批量写入 19-DAL 的
mm_metrics 表，使 9-基本面分析 / 23-自进化等可通过 MarketMacroRepository
统一读取真实数据。

用法：
    cd 19-数据访问层
    python scripts/backfill_18_records.py [--src 18-数据获取中心/data_center.db]
                                          [--dst 19-数据访问层/data/dreambuddy_core.db]
                                          [--dry-run]

设计要点：
  - 单次连接 + executemany 批量 INSERT OR REPLACE（性能优于逐条 upsert_metric）
  - 仅写入数值型 metric（str/bool/dict 跳过）
  - 跳过 newsflash_* 等纯文本 sub_category
  - 幂等（主键 source+sub_category+metric_name+timestamp）
  - 自动建表（mm_metrics WITHOUT ROWID）
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# 路径设置：确保能 import dreambuddy_dal，并定位源/目标库
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
DAL_ROOT = REPO_ROOT / "19-数据访问层"
if str(DAL_ROOT) not in sys.path:
    sys.path.insert(0, str(DAL_ROOT))

DEFAULT_SRC = REPO_ROOT / "18-数据获取中心" / "data_center.db"
DEFAULT_DST = DAL_ROOT / "data" / "dreambuddy_core.db"


def _to_unix_sec(ts_text: str) -> int | None:
    """把 18 records 的 timestamp 文本转成 unix 秒。"""
    if not ts_text:
        return None
    # 兼容 "2026-10-01T21:00:00Z" / "...+00:00" / 无时区
    txt = ts_text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _is_numeric(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _iter_metric_rows(src_db: str) -> Iterable[tuple]:
    """从 18 records 产出 (source, sub_category, metric_name, metric_value, unix_ts)。"""
    conn = sqlite3.connect(src_db)
    cur = conn.cursor()
    # 只取有 metrics 且非新闻类的记录
    cur.execute(
        """
        SELECT source, sub_category, timestamp, metrics
        FROM records
        WHERE metrics IS NOT NULL AND metrics != ''
          AND sub_category NOT LIKE 'newsflash%'
        """
    )
    for source, sub_category, ts_text, metrics_json in cur:
        if not sub_category:
            continue
        unix_ts = _to_unix_sec(ts_text)
        if unix_ts is None:
            continue
        try:
            metrics = json.loads(metrics_json)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(metrics, dict):
            continue
        for metric_name, value in metrics.items():
            if metric_name == "asset":
                continue
            if _is_numeric(value):
                yield (source, sub_category, metric_name, float(value), unix_ts)
    conn.close()


def backfill(src_db: str, dst_db: str, dry_run: bool = False) -> dict:
    """执行回填，返回统计信息。"""
    rows = list(_iter_metric_rows(src_db))
    total = len(rows)

    if dry_run:
        return {
            "total_metric_rows": total,
            "dry_run": True,
            "dst_db": dst_db,
        }

    # 建目标目录
    Path(dst_db).parent.mkdir(parents=True, exist_ok=True)

    # 单连接批量写入
    conn = sqlite3.connect(dst_db)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mm_metrics (
                source TEXT NOT NULL,
                sub_category TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                metric_value REAL,
                timestamp INTEGER NOT NULL,
                PRIMARY KEY (source, sub_category, metric_name, timestamp)
            ) WITHOUT ROWID
            """
        )
        # 分批 executemany
        batch_size = 5000
        inserted = 0
        for i in range(0, total, batch_size):
            batch = rows[i : i + batch_size]
            conn.executemany(
                """
                INSERT OR REPLACE INTO mm_metrics
                    (source, sub_category, metric_name, metric_value, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                batch,
            )
            inserted += len(batch)
        conn.commit()

        # 校验写入行数
        cur = conn.execute("SELECT COUNT(*) FROM mm_metrics")
        db_count = cur.fetchone()[0]
    finally:
        conn.close()

    return {
        "total_metric_rows": total,
        "inserted_or_replaced": inserted,
        "db_row_count": db_count,
        "dry_run": False,
        "dst_db": dst_db,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill 18 records into 19-DAL mm_metrics")
    parser.add_argument("--src", default=str(DEFAULT_SRC), help="18 data_center.db 路径")
    parser.add_argument("--dst", default=str(DEFAULT_DST), help="19 dreambuddy_core.db 路径")
    parser.add_argument("--dry-run", action="store_true", help="仅统计不写入")
    args = parser.parse_args()

    if not Path(args.src).exists():
        print(f"[ERROR] 源库不存在: {args.src}")
        sys.exit(1)

    print(f"[backfill] src = {args.src}")
    print(f"[backfill] dst = {args.dst}")
    print(f"[backfill] dry_run = {args.dry_run}")

    stats = backfill(args.src, args.dst, dry_run=args.dry_run)
    print("\n=== 回填结果 ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    if not args.dry_run and stats.get("db_row_count", 0) > 0:
        print("\n[OK] 18→19 回填完成，19-DAL mm_metrics 已可用。")


if __name__ == "__main__":
    main()
