#!/usr/bin/env python3
"""直接采集 Yahoo Finance 价格 — 绕过 yfinance 库（query1 被限流）。

使用 query2.finance.yahoo.com endpoint + proper User-Agent，
直接将结果写入 18-数据获取中心/data_center.db records 表。

用法：
    python collect_yahoo_direct.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "18-数据获取中心"))

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


def insert_record(sink, symbol: str, data: dict) -> None:
    """通过统一存储接口写入 records（跟随 DATA_CENTER_BACKEND 配置）。"""
    from data_center.core.contract import DataRecord
    now_iso = datetime.now(timezone.utc).astimezone().isoformat()
    sink.write([DataRecord(
        source="yfinance", category="finance", sub_category=symbol,
        timestamp=now_iso, metrics=data, events=[],
        timeseries=[{"date": data["date"], "close": data["price"]}],
        raw={"symbol": symbol, "period": "5d", "source": "yahoo_query2"},
    )])
def main() -> None:
    print("[collect_yahoo_direct] 存储后端: 统一存储接口（跟随 DATA_CENTER_BACKEND 配置）")
    from data_center.storage.sink_postgres import get_sink
    conn = get_sink()

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

    pass  # sink 无需关闭
    print(f"\n[done] {success}/{len(SYMBOLS)} symbols collected")
    print("[next] Run: cd 19-数据访问层 && python scripts/backfill_18_records.py")


if __name__ == "__main__":
    main()
