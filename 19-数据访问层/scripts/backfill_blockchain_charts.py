#!/usr/bin/env python3
"""一次性回填：Blockchain.com charts API 1 年历史 → 19-DAL mm_metrics。

将 btc_basics 的链上指标（difficulty / hashrate / tx_count / active_addresses /
output_volume）从 blockchain.com charts API 拉取 1 年日数据，直接展平写入
mm_metrics 表，使因子池纵深达标（≥250 天）。

源：https://api.blockchain.info/charts/{chart}?timespan=1years&format=json
格式：{"values": [{"x": <unix秒>, "y": <值>}, ...]}

幂等：主键 (source, sub_category, metric_name, timestamp) → INSERT OR REPLACE。

用法：
    cd 19-数据访问层
    python scripts/backfill_blockchain_charts.py [--dst data/dreambuddy_core.db]
                                                 [--timespan 1years]
                                                 [--dry-run]
"""

from __future__ import annotations

import argparse
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
DAL_ROOT = REPO_ROOT / "19-数据访问层"
DEFAULT_DST = DAL_ROOT / "data" / "dreambuddy_core.db"

_CHARTS = "https://api.blockchain.info/charts"

# chart 名 → mm_metrics metric_name
# sub_category 统一为 btc_basics，与 blockchain_info_collector 对齐
CHART_METRICS = {
    "difficulty": "difficulty",
    "hash-rate": "hashrate",
    "n-transactions": "tx_count_24h",
    "n-unique-addresses": "active_addresses",
    "output-volume": "output_volume_btc",
}


def fetch_chart(chart: str, timespan: str) -> list[tuple[int, float]]:
    """拉取单个 chart 的历史点，返回 [(unix_ts, value), ...]。"""
    resp = requests.get(
        f"{_CHARTS}/{chart}",
        params={"timespan": timespan, "format": "json"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    values = data.get("values", []) or []
    out: list[tuple[int, float]] = []
    for p in values:
        if not isinstance(p, dict):
            continue
        x = p.get("x")
        y = p.get("y")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            continue
        if isinstance(y, bool) or y <= 0:
            continue
        out.append((int(x), float(y)))
    return out


def backfill(dst_db: str, timespan: str, dry_run: bool = False) -> dict:
    rows: list[tuple] = []
    per_chart: dict[str, int] = {}
    for chart, metric_name in CHART_METRICS.items():
        try:
            points = fetch_chart(chart, timespan)
        except Exception as e:
            print(f"  [WARN] {chart} 抓取失败: {e}")
            per_chart[chart] = 0
            continue
        per_chart[chart] = len(points)
        for unix_ts, val in points:
            rows.append(("blockchain_info", "btc_basics", metric_name, val, unix_ts))
        print(f"  {chart:20s} → {metric_name:20s} {len(points)} 点")
        time.sleep(1.0)  # 礼貌限流

    total = len(rows)
    if dry_run:
        return {
            "total_metric_rows": total,
            "per_chart_points": per_chart,
            "dry_run": True,
            "dst_db": dst_db,
        }

    Path(dst_db).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(dst_db)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mm_metrics (
                source TEXT NOT NULL,
                sub_category TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                metric_value REAL,
                timestamp INTEGER NOT NULL,
                PRIMARY KEY (source, sub_category, metric_name, timestamp)
            ) WITHOUT ROWID
            """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_mm_metrics_query
            ON mm_metrics (sub_category, metric_name, timestamp)
            """)
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
        cur = conn.execute("SELECT COUNT(*) FROM mm_metrics WHERE sub_category='btc_basics'")
        db_count = cur.fetchone()[0]
    finally:
        conn.close()

    return {
        "total_metric_rows": total,
        "inserted_or_replaced": inserted,
        "per_chart_points": per_chart,
        "db_btc_basics_rows": db_count,
        "dry_run": False,
        "dst_db": dst_db,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill Blockchain.com charts (1y) into 19-DAL mm_metrics"
    )
    parser.add_argument("--dst", default=str(DEFAULT_DST), help="19 dreambuddy_core.db 路径")
    parser.add_argument(
        "--timespan", default="1years", help="blockchain.com timespan（1years/2years/all）"
    )
    parser.add_argument("--dry-run", action="store_true", help="仅统计不写入")
    args = parser.parse_args()

    print(f"[backfill_blockchain] dst = {args.dst}")
    print(f"[backfill_blockchain] timespan = {args.timespan}")
    print(f"[backfill_blockchain] dry_run = {args.dry_run}")
    print(f"[backfill_blockchain] started = {datetime.now(timezone.utc).isoformat()}")

    stats = backfill(args.dst, args.timespan, dry_run=args.dry_run)
    print("\n=== 回填结果 ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    if not args.dry_run and stats.get("db_btc_basics_rows", 0) > 0:
        print("\n[OK] blockchain.com charts → 19-DAL mm_metrics 回填完成。")


if __name__ == "__main__":
    main()
