#!/usr/bin/env python3
"""P0 回填脚本：18-数据获取中心 records.chart_{coin_id} timeseries → 19-DAL mm_metrics 展平。

将 18 的 data_center.db.records 中所有 coingecko coin_chart 的 720+ 点时序，
按 (source, sub_category, metric_name, timestamp) 主键展平写入 19-DAL 的
mm_metrics 表，使 query_valuation_percentile 可通过 MarketMacroRepository
统一读取，不再直连 18-DB。

用法：
    cd 19-数据访问层
    python scripts/backfill_chart_to_mm_metrics.py [--src 18-数据获取中心/data_center.db]
                                                   [--dst 19-数据访问层/data/dreambuddy_core.db]
                                                   [--dry-run]

设计要点：
  - 只处理 source='coingecko' AND category='coin' AND sub_category LIKE 'chart_%'
  - timeseries 每个点展平为一条 mm_metrics 记录
  - metric_name='market_cap'（当前 query_valuation_percentile 唯一消费字段）
  - date 'YYYY-MM-DD' → 补 T00:00:00Z → unix 秒
  - 幂等（主键 INSERT OR REPLACE）
  - 跳过 market_cap<=0 或非数值的点（数据缺失）
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# 路径设置
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
DAL_ROOT = REPO_ROOT / "19-数据访问层"
if str(DAL_ROOT) not in sys.path:
    sys.path.insert(0, str(DAL_ROOT))

DEFAULT_SRC = REPO_ROOT / "18-数据获取中心" / "data_center.db"
DEFAULT_DST = DAL_ROOT / "data" / "dreambuddy_core.db"


def _date_to_unix_sec(date_str: str) -> int | None:
    """'YYYY-MM-DD' → unix 秒（UTC 00:00:00）。"""
    if not date_str:
        return None
    try:
        # 补全 ISO 格式：'2026-09-07' → '2026-09-07T00:00:00+00:00'
        txt = date_str.replace("Z", "+00:00")
        if "T" not in txt:
            txt = f"{txt}T00:00:00+00:00"
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return None


def _is_numeric(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _iter_chart_metric_rows(src_db: str) -> Iterable[tuple]:
    """从 18 records 的 chart_{coin_id} timeseries 展平产出 mm_metrics 行。

    每行：(source='coingecko', sub_category, metric_name='market_cap', value, unix_ts)

    注：coingecko_collector 第 146 行 `.date().isoformat()` 丢弃了小时信息，
    720 小时点的 date 字段只有 31 个唯一值。为避免主键 (source,sub_category,
    metric_name,timestamp) 去重丢失数据，对同一币的 timeseries 用全局索引 i
    生成唯一 timestamp = unix(date) + i 秒。这样 720 点全部保留，且同一天的点
    timestamp 接近（差几秒），不影响 query_valuation_percentile（取所有点）。
    """
    conn = sqlite3.connect(src_db)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT sub_category, timeseries
        FROM records
        WHERE source='coingecko' AND category='coin'
          AND sub_category LIKE 'chart_%'
          AND timeseries IS NOT NULL AND timeseries != ''
        ORDER BY sub_category, timestamp DESC
        """
    )
    seen_subcats: set[str] = set()
    for sub_category, ts_json in cur:
        if not sub_category or sub_category in seen_subcats:
            # 同一币只取最新一条 chart 记录（避免重复导入历史快照）
            continue
        seen_subcats.add(sub_category)
        try:
            ts_list = json.loads(ts_json)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(ts_list, list):
            continue
        for i, point in enumerate(ts_list):
            if not isinstance(point, dict):
                continue
            date_str = point.get("date")
            mc = point.get("market_cap")
            if not _is_numeric(mc) or float(mc) <= 0:
                continue
            base_unix = _date_to_unix_sec(date_str)
            if base_unix is None:
                continue
            # 合成唯一 timestamp：base + i 秒（i 是该币 timeseries 全局索引）
            unix_ts = base_unix + i
            yield ("coingecko", sub_category, "market_cap", float(mc), unix_ts)
    conn.close()


def backfill(src_db: str, dst_db: str, dry_run: bool = False) -> dict:
    """执行回填，返回统计信息。"""
    rows = list(_iter_chart_metric_rows(src_db))
    total = len(rows)
    subcats = {r[1] for r in rows}

    if dry_run:
        return {
            "total_metric_rows": total,
            "chart_subcategories": len(subcats),
            "sample_subcats": sorted(subcats)[:5],
            "dry_run": True,
            "dst_db": str(dst_db),
        }

    Path(dst_db).parent.mkdir(parents=True, exist_ok=True)
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
        # 索引：加速 query_metric_by_time 的 sub_category+metric_name+timestamp 查询
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_mm_metrics_query
            ON mm_metrics (sub_category, metric_name, timestamp)
            """
        )
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
        cur = conn.execute(
            "SELECT COUNT(*) FROM mm_metrics WHERE metric_name='market_cap' AND sub_category LIKE 'chart_%'"
        )
        db_count = cur.fetchone()[0]
    finally:
        conn.close()

    return {
        "total_metric_rows": total,
        "inserted_or_replaced": inserted,
        "chart_subcategories": len(subcats),
        "db_chart_market_cap_rows": db_count,
        "dry_run": False,
        "dst_db": str(dst_db),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill 18 records.chart_* timeseries into 19-DAL mm_metrics (flattened)"
    )
    parser.add_argument("--src", default=str(DEFAULT_SRC), help="18 data_center.db 路径")
    parser.add_argument("--dst", default=str(DEFAULT_DST), help="19 dreambuddy_core.db 路径")
    parser.add_argument("--dry-run", action="store_true", help="仅统计不写入")
    args = parser.parse_args()

    if not Path(args.src).exists():
        print(f"[ERROR] 源库不存在: {args.src}")
        sys.exit(1)

    print(f"[backfill_chart] src = {args.src}")
    print(f"[backfill_chart] dst = {args.dst}")
    print(f"[backfill_chart] dry_run = {args.dry_run}")

    stats = backfill(args.src, args.dst, dry_run=args.dry_run)
    print("\n=== 回填结果 ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    if not args.dry_run and stats.get("db_chart_market_cap_rows", 0) > 0:
        print("\n[OK] 18 chart_ timeseries → 19-DAL mm_metrics 展平回填完成。")


if __name__ == "__main__":
    main()
