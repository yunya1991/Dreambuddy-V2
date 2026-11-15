#!/usr/bin/env python3
"""一次性回填：DeFiLlama 历史 TVL → 19-DAL mm_metrics。

将 DeFi 总 TVL（/charts）和主要链的历史 TVL（/v2/historicalChainTvl/{chain}）
从 DefiLlama API 拉取全量历史（2017 至今，~3300 天），直接展平写入 mm_metrics，
使因子池纵深大幅达标（≥250 天）。

源：
  - https://api.llama.fi/charts                    → 全市场总 TVL（日）
  - https://api.llama.fi/v2/historicalChainTvl/{chain}  → 单链历史 TVL（日）

幂等：主键 (source, sub_category, metric_name, timestamp) → INSERT OR REPLACE。

用法：
    cd 19-数据访问层
    python scripts/backfill_defillama_history.py [--dst data/dreambuddy_core.db]
                                                 [--chains Ethereum BSC Solana ...]
                                                 [--dry-run]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
DAL_ROOT = REPO_ROOT / "19-数据访问层"
if str(DAL_ROOT) not in sys.path:
    sys.path.insert(0, str(DAL_ROOT))
from dreambuddy_dal.implementations.sqlite_unified.vintage import append_vintages  # noqa: E402

DEFAULT_DST = DAL_ROOT / "data" / "dreambuddy_core.db"

_BASE = "https://api.llama.fi"

# 默认回填的主要链（按 TVL 排名前 15）
DEFAULT_CHAINS = [
    "Ethereum",
    "BSC",
    "Solana",
    "Arbitrum",
    "Base",
    "Optimism",
    "Polygon",
    "Avalanche",
    "zkSync",
    "Linea",
    "Mantle",
    "Sui",
    "Aptos",
    "Near",
    "Celo",
]


def fetch_total_tvl() -> list[tuple[int, float]]:
    """拉取全市场总 TVL 历史，返回 [(unix_ts, tvl_usd), ...]。"""
    resp = requests.get(f"{_BASE}/charts", timeout=30)
    resp.raise_for_status()
    data = resp.json()
    out: list[tuple[int, float]] = []
    for p in data or []:
        if not isinstance(p, dict):
            continue
        d = p.get("date")
        v = p.get("totalLiquidityUSD")
        if not isinstance(d, (int, float, str)) or not isinstance(v, (int, float)):
            continue
        if isinstance(v, bool) or v <= 0:
            continue
        out.append((int(d), float(v)))
    return out


def fetch_chain_tvl(chain: str) -> list[tuple[int, float]]:
    """拉取单链历史 TVL，返回 [(unix_ts, tvl_usd), ...]。"""
    resp = requests.get(f"{_BASE}/v2/historicalChainTvl/{chain}", timeout=30)
    resp.raise_for_status()
    data = resp.json()
    out: list[tuple[int, float]] = []
    for p in data or []:
        if not isinstance(p, dict):
            continue
        d = p.get("date")
        v = p.get("tvl")
        if not isinstance(d, (int, float, str)) or not isinstance(v, (int, float)):
            continue
        if isinstance(v, bool) or v <= 0:
            continue
        out.append((int(d), float(v)))
    return out


def backfill(dst_db: str, chains: list[str], dry_run: bool = False) -> dict:
    rows: list[tuple] = []
    stats: dict[str, int] = {}

    # 1. 全市场总 TVL
    try:
        total_pts = fetch_total_tvl()
    except Exception as e:
        print(f"  [WARN] total TVL 抓取失败: {e}")
        total_pts = []
    stats["total_tvl"] = len(total_pts)
    for unix_ts, val in total_pts:
        rows.append(("defillama", "defillama_total", "total_tvl", val, unix_ts))
        rows.append(("defillama", "defillama_total", "total_tvl_bln", round(val / 1e9, 4), unix_ts))
    print(f"  total_tvl: {len(total_pts)} 点")

    # 2. 各链历史 TVL
    for chain in chains:
        try:
            pts = fetch_chain_tvl(chain)
        except Exception as e:
            print(f"  [WARN] {chain} 抓取失败: {e}")
            stats[f"chain_{chain}"] = 0
            continue
        stats[f"chain_{chain}"] = len(pts)
        sub = f"historical_tvl_{chain.lower()}"
        for unix_ts, val in pts:
            rows.append(("defillama", sub, "tvl", val, unix_ts))
            rows.append(("defillama", sub, "tvl_bln", round(val / 1e9, 4), unix_ts))
        print(f"  {chain:15s}: {len(pts)} 点")
        time.sleep(0.5)  # 礼貌限流

    total = len(rows)
    if dry_run:
        return {
            "total_metric_rows": total,
            "per_source_points": stats,
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
            append_vintages(conn, batch)
            inserted += len(batch)
        conn.commit()
        cur = conn.execute("SELECT COUNT(*) FROM mm_metrics WHERE source='defillama'")
        db_count = cur.fetchone()[0]
    finally:
        conn.close()

    return {
        "total_metric_rows": total,
        "inserted_or_replaced": inserted,
        "per_source_points": stats,
        "db_defillama_rows": db_count,
        "dry_run": False,
        "dst_db": dst_db,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill DeFiLlama historical TVL into 19-DAL mm_metrics"
    )
    parser.add_argument("--dst", default=str(DEFAULT_DST), help="19 dreambuddy_core.db 路径")
    parser.add_argument("--chains", nargs="+", default=DEFAULT_CHAINS, help="要回填的链列表")
    parser.add_argument("--dry-run", action="store_true", help="仅统计不写入")
    args = parser.parse_args()

    print(f"[backfill_defillama] dst = {args.dst}")
    print(f"[backfill_defillama] chains = {args.chains}")
    print(f"[backfill_defillama] dry_run = {args.dry_run}")
    print(f"[backfill_defillama] started = {datetime.now(timezone.utc).isoformat()}")

    stats = backfill(args.dst, args.chains, dry_run=args.dry_run)
    print("\n=== 回填结果 ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    if not args.dry_run and stats.get("db_defillama_rows", 0) > 0:
        print("\n[OK] DeFiLlama 历史 TVL → 19-DAL mm_metrics 回填完成。")


if __name__ == "__main__":
    main()
