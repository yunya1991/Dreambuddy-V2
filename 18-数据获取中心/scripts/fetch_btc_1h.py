#!/usr/bin/env python3
"""回补 BTC/USDT 1h K 线（2023-01-01 → 当前），供 P3-c1h 小时级事件研究。

为什么需要：P3-c1 日线粒度失败，24h 窗口把事件后的小时级反应全部糊掉。
本脚本只解决「原料」问题，不做任何统计判断。

数据源优先级：binance → okx → bybit（任一可用即成功；均不可用则 FAIL-OPEN 退出）。
输出：
  backfill/p3c1/btc_1h.csv         ts_ms,open,high,low,close,volume
  backfill/p3c1/btc_1h_meta.json   覆盖区间 / 缺口 / 数据源
"""

from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
OUT_DIR = _REPO / "18-数据获取中心" / "backfill" / "p3c1"
CSV_PATH = OUT_DIR / "btc_1h.csv"
META_PATH = OUT_DIR / "btc_1h_meta.json"

SINCE_MS = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
UNTIL_MS = int(datetime(2026, 11, 10, tzinfo=timezone.utc).timestamp() * 1000)
HOUR_MS = 3_600_000
EXCHANGES = ("binance", "okx", "bybit")


def _fetch(ex_id: str, bars: dict[int, list[float]] | None = None) -> dict[int, list[float]]:
    """增量拉取；单页失败重试 3 次，仍失败则保留已拉到的部分（不丢进度）。"""
    import ccxt

    ex = getattr(ccxt, ex_id)({"enableRateLimit": True, "timeout": 30000})
    bars = bars if bars is not None else {}
    cursor = max(bars) + HOUR_MS if bars else SINCE_MS
    pages = 0
    failures = 0
    while cursor < UNTIL_MS:
        rows = None
        for attempt in range(3):
            try:
                rows = ex.fetch_ohlcv("BTC/USDT", "1h", since=cursor, limit=1000)
                break
            except Exception as e:  # noqa: BLE001  FAIL-OPEN
                failures += 1
                print(
                    f"  [{ex_id}] page fail #{failures} ({type(e).__name__}), retry {attempt + 1}/3",
                    flush=True,
                )
                time.sleep(2.0 * (attempt + 1))
        if rows is None:
            print(f"  [{ex_id}] give up at {cursor} after 3 retries", flush=True)
            break
        if not rows:
            break
        for ts, o, h, lo, c, v in rows:
            if SINCE_MS <= ts < UNTIL_MS and ts <= int(time.time() * 1000):
                bars[int(ts)] = [float(o), float(h), float(lo), float(c), float(v or 0.0)]
        nxt = int(rows[-1][0]) + HOUR_MS
        if nxt <= cursor:
            break
        cursor = nxt
        pages += 1
        if pages % 10 == 0:
            print(
                f"  [{ex_id}] {pages} pages, {len(bars)} bars, "
                f"{datetime.fromtimestamp(cursor / 1000, timezone.utc):%Y-%m-%d}",
                flush=True,
            )
        time.sleep(ex.rateLimit / 1000.0)
    return bars


def _gaps(ts_sorted: list[int]) -> list[dict]:
    """返回缺失小时区间（长度 ≥2h 的缺口）。"""
    out: list[dict] = []
    for a, b in zip(ts_sorted, ts_sorted[1:], strict=False):
        miss = (b - a) // HOUR_MS - 1
        if miss > 0:
            out.append(
                {
                    "start": datetime.fromtimestamp(a / 1000, timezone.utc).isoformat(),
                    "end": datetime.fromtimestamp(b / 1000, timezone.utc).isoformat(),
                    "missing_hours": int(miss),
                }
            )
    return out


def _write_csv(bars: dict[int, list[float]]) -> None:
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts_ms", "open", "high", "low", "close", "volume"])
        for ts in sorted(bars):
            o, h, lo, c, v = bars[ts]
            w.writerow([ts, o, h, lo, c, v])


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    expected = int((UNTIL_MS - SINCE_MS) // HOUR_MS)
    bars: dict[int, list[float]] = {}
    used: list[str] = []
    for ex_id in EXCHANGES:
        before = len(bars)
        try:
            bars = _fetch(ex_id, bars)
        except Exception as e:  # noqa: BLE001  FAIL-OPEN
            print(f"[FAIL-OPEN] {ex_id}: {type(e).__name__}: {str(e)[:160]}", flush=True)
            continue
        if len(bars) > before:
            used.append(ex_id)
            _write_csv(bars)  # 每源结束即落盘，重跑可续
            print(f"[ok] {ex_id}: +{len(bars) - before} bars → total {len(bars)}", flush=True)
        if len(bars) >= expected * 0.99:
            break

    if not bars:
        print("[DEGRADED] no exchange returned data", flush=True)
        return 1

    _write_csv(bars)
    ts_sorted = sorted(bars)
    gaps = _gaps(ts_sorted)
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "exchanges_used": used,
        "symbol": "BTC/USDT",
        "interval": "1h",
        "n_bars": len(ts_sorted),
        "first_bar": datetime.fromtimestamp(ts_sorted[0] / 1000, timezone.utc).isoformat(),
        "last_bar": datetime.fromtimestamp(ts_sorted[-1] / 1000, timezone.utc).isoformat(),
        "expected_hours": int((UNTIL_MS - SINCE_MS) // HOUR_MS),
        "coverage_pct": round(len(ts_sorted) / max(1, (UNTIL_MS - SINCE_MS) // HOUR_MS) * 100, 2),
        "n_gaps": len(gaps),
        "missing_hours_total": sum(g["missing_hours"] for g in gaps),
        "gaps": gaps[:50],
    }
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                k: meta[k]
                for k in (
                    "exchanges_used",
                    "n_bars",
                    "first_bar",
                    "last_bar",
                    "coverage_pct",
                    "n_gaps",
                    "missing_hours_total",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
