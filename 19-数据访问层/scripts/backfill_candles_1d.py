#!/usr/bin/env python3
"""回填真实日线 OHLC：18 中心 1h K 线 CSV → 19-DAL `mm_metrics`（`*_1d` 指标）。

为什么需要：库内既有的 `{symbol}/USDT high/low` 是 ccxt ticker 的 24h 滚动高低点，
不是逐根 K 线极值；日线 OHLC 覆盖率不足以支撑 I 组技术指标（D-B04 ATR / D-B07 支撑压力）。

口径：
  - 输入 CSV 列：ts_ms,open,high,low,close,volume（UTC 小时线）
  - 按 UTC 日历日聚合：open=首根 open，high=max，low=min，close=末根 close，volume=sum
  - 输出 5 条指标（sub_category=`BTC/USDT`，source=`binance`）：
      open_1d / high_1d / low_1d / close_1d / volume_1d
    timestamp = 当日 UTC 00:00 的 unix 秒
  - 逐日校验：四腿为正、high>=max(open,close)、low<=min(open,close)，否则整天跳过（不伪造）
  - 幂等：mm_metrics 主键 (source, sub_category, metric_name, timestamp) INSERT OR REPLACE，
    云端可重复执行/挂定时任务

用法：
    python scripts/backfill_candles_1d.py --csv 18-数据获取中心/backfill/p3c1/btc_1h.csv \
                                          --dst 19-数据访问层/data/dreambuddy_core.db [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DST = REPO_ROOT / "19-数据访问层" / "data" / "dreambuddy_core.db"
DEFAULT_CSV = REPO_ROOT / "18-数据获取中心" / "backfill" / "p3c1" / "btc_1h.csv"
DAY_SEC = 86400
METRIC_SUFFIX = "_1d"
METRICS = ("open", "high", "low", "close", "volume")


def aggregate_daily(
    rows: Iterable[Tuple[int, float, float, float, float, float]],
) -> Dict[int, Dict[str, float]]:
    """小时线 → 日线（UTC）：返回 {day_unix: {open,high,low,close,volume}}。"""
    days: Dict[int, Dict[str, float]] = {}
    for ts_ms, o, h, lo, c, v in rows:
        if min(o, h, lo, c) <= 0:
            continue
        day = int(ts_ms) // 1000 // DAY_SEC * DAY_SEC
        slot = days.get(day)
        if slot is None:
            days[day] = {"open": o, "high": h, "low": lo, "close": c, "volume": max(0.0, v)}
            continue
        slot["high"] = max(slot["high"], h)
        slot["low"] = min(slot["low"], lo)
        slot["close"] = c  # 输入按时间升序，末根即收盘
        slot["volume"] += max(0.0, v)
    return days


def _valid(bar: Dict[str, float]) -> bool:
    return (
        bar["high"] >= max(bar["open"], bar["close"])
        and bar["low"] <= min(bar["open"], bar["close"])
        and bar["high"] >= bar["low"]
    )


def read_hourly(csv_path: Path) -> List[Tuple[int, float, float, float, float, float]]:
    rows: List[Tuple[int, float, float, float, float, float]] = []
    with csv_path.open(newline="", encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            try:
                rows.append(
                    (
                        int(rec["ts_ms"]),
                        float(rec["open"]),
                        float(rec["high"]),
                        float(rec["low"]),
                        float(rec["close"]),
                        float(rec["volume"] or 0.0),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
    rows.sort(key=lambda r: r[0])
    return rows


def build_metric_rows(
    days: Dict[int, Dict[str, float]], symbol: str, source: str
) -> Tuple[List[Tuple[str, str, str, float, int]], int]:
    """日线 → mm_metrics 行；返回 (rows, 被丢弃的无效天数)。"""
    out: List[Tuple[str, str, str, float, int]] = []
    dropped = 0
    for day in sorted(days):
        bar = days[day]
        if not _valid(bar):
            dropped += 1
            continue
        for name in METRICS:
            out.append((source, symbol, f"{name}{METRIC_SUFFIX}", round(float(bar[name]), 8), day))
    return out, dropped


def backfill(csv_path: Path, dst_db: Path, symbol: str, source: str, dry_run: bool) -> dict:
    hourly = read_hourly(csv_path)
    days = aggregate_daily(hourly)
    rows, dropped = build_metric_rows(days, symbol, source)
    stats = {
        "hourly_bars": len(hourly),
        "daily_bars": len(days),
        "dropped_invalid_days": dropped,
        "metric_rows": len(rows),
        "symbol": symbol,
        "source": source,
        "dry_run": dry_run,
    }
    if not rows:
        return stats
    first_day, last_day = min(days), max(days)
    stats["first_day"] = first_day
    stats["last_day"] = last_day
    if dry_run:
        return stats

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
        conn.executemany(
            "INSERT OR REPLACE INTO mm_metrics "
            "(source, sub_category, metric_name, metric_value, timestamp) VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        stats["db_daily_close_rows"] = conn.execute(
            "SELECT COUNT(*) FROM mm_metrics "
            "WHERE source = ? AND sub_category = ? AND metric_name = ?",
            (source, symbol, f"close{METRIC_SUFFIX}"),
        ).fetchone()[0]
    finally:
        conn.close()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="1h K线 CSV → mm_metrics 日线 OHLC（幂等）")
    parser.add_argument("--csv", default=str(DEFAULT_CSV))
    parser.add_argument("--dst", default=str(DEFAULT_DST))
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--source", default="binance")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"[ERROR] CSV 不存在: {csv_path}")
        sys.exit(1)
    dst_db = Path(args.dst)
    if not dst_db.exists():
        print(f"[ERROR] 目标库不存在: {dst_db}")
        sys.exit(1)

    print(f"[backfill_candles] csv={csv_path}")
    print(f"[backfill_candles] dst={dst_db} dry_run={args.dry_run}")
    stats = backfill(csv_path, dst_db, args.symbol, args.source, args.dry_run)
    print("\n=== 回填结果 ===")
    for key, value in stats.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
