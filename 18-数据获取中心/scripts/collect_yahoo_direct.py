#!/usr/bin/env python3
"""直接采集 Yahoo Finance 价格 — 绕过 yfinance 库（query1 被限流）。

使用 query2.finance.yahoo.com endpoint + proper User-Agent，
直接将结果写入 18-数据获取中心/data_center.db records 表。

用法：
    python collect_yahoo_direct.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "18-数据获取中心" / "data_center.db"

SYMBOLS = [
    "^VIX", "DX-Y.NYB", "GC=F", "^GSPC", "^IXIC", "^TNX", "CL=F", "BTC-USD",
]

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def fetch_yahoo(symbol: str) -> dict | None:
    """Fetch from query2.finance.yahoo.com."""
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        result = data["chart"]["result"][0]
        meta = result["meta"]
        closes = result["indicators"]["quote"][0]["close"]
        timestamps = result.get("timestamp", [])
        close = None
        date_str = ""
        for i in range(len(closes) - 1, -1, -1):
            if closes[i] is not None:
                close = float(closes[i])
                if i < len(timestamps):
                    from datetime import datetime as _dt
                    date_str = _dt.utcfromtimestamp(timestamps[i]).strftime("%Y-%m-%d")
                break
        if close is None:
            close = float(meta.get("regularMarketPrice", 0))
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return {
            "symbol": symbol,
            "price": close,
            "currency": meta.get("currency", ""),
            "date": date_str,
        }
    except Exception as e:
        print(f"  {symbol}: ERROR — {e}", file=sys.stderr)
        return None


def insert_record(conn: sqlite3.Connection, symbol: str, data: dict) -> None:
    """Insert into 18-layer records table (same schema as yfinance_collector)."""
    now_iso = datetime.now(timezone.utc).astimezone().isoformat()
    metrics = json.dumps(data)
    timeseries = json.dumps([{"date": data["date"], "close": data["price"]}])
    raw = json.dumps({"symbol": symbol, "period": "5d", "source": "yahoo_query2"})
    dedupe_key = f"yfinance|finance|{symbol}|{now_iso}"

    conn.execute(
        """
        INSERT OR REPLACE INTO records
            (dedupe_key, source, category, sub_category, timestamp,
             metrics, events, timeseries, raw, schema_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (dedupe_key, "yfinance", "finance", symbol, now_iso,
         metrics, "[]", timeseries, raw, "1.0"),
    )
    conn.commit()


def main() -> None:
    print(f"[collect_yahoo_direct] DB: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))

    success = 0
    for sym in SYMBOLS:
        time.sleep(2)  # 2s delay to avoid rate limit
        data = fetch_yahoo(sym)
        if data:
            insert_record(conn, sym, data)
            print(f"  {sym:12s}: price={data['price']:>12.4f}  date={data['date']}  OK")
            success += 1
        else:
            print(f"  {sym:12s}: FAILED")

    conn.close()
    print(f"\n[done] {success}/{len(SYMBOLS)} symbols collected")
    print("[next] Run: cd 19-数据访问层 && python scripts/backfill_18_records.py")


if __name__ == "__main__":
    main()
