"""Hyperliquid 历史 K 线下载器

从 Hyperliquid API 直接下载 1h K 线，保存为 aggregated/futures/ 格式。
分批下载（每批 500 根），合并去重，按时间升序。

用法:
    cd 10-经典指标系统
    python user_data/scripts/download_history.py --days 90 --symbols BTC,ETH,SOL
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

API_URL = "https://api.hyperliquid.xyz/info"
BATCH_HOURS = 480  # 每批 480 小时 = 20 天（< 500 根限制）

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "aggregated" / "futures"


def fetch_batch(coin: str, interval: str, start_ms: int, end_ms: int) -> list:
    """单批下载"""
    payload = json.dumps({
        "type": "candleSnapshot",
        "req": {"coin": coin, "interval": interval,
                "startTime": start_ms, "endTime": end_ms},
    }).encode()
    req = urllib.request.Request(
        API_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    # 转为 [ts_ms, o, h, l, c, v]
    rows = []
    for k in data:
        rows.append([
            int(k["t"]),          # 开始时间 ms
            float(k["o"]),        # open
            float(k["h"]),        # high
            float(k["l"]),        # low
            float(k["c"]),        # close
            float(k.get("v", 0)), # volume
        ])
    return rows


def download_symbol(coin: str, interval: str, days: int) -> list:
    """分批下载指定币种的全部历史数据"""
    now = datetime.utcnow()
    start_dt = now - timedelta(days=days)
    end_ms = int(now.timestamp() * 1000)
    cur_ms = int(start_dt.timestamp() * 1000)

    all_rows: dict[int, list] = {}  # ts → row（自动去重）
    batch_idx = 0
    while cur_ms < end_ms:
        batch_end = min(cur_ms + BATCH_HOURS * 3600 * 1000, end_ms)
        try:
            rows = fetch_batch(coin, interval, cur_ms, batch_end)
        except Exception as e:
            print(f"  [!] 批次 {batch_idx} 失败: {e}，重试...")
            time.sleep(2)
            try:
                rows = fetch_batch(coin, interval, cur_ms, batch_end)
            except Exception as e2:
                print(f"  [!] 批次 {batch_idx} 再次失败: {e2}，跳过")
                cur_ms = batch_end
                batch_idx += 1
                continue
        for r in rows:
            all_rows[r[0]] = r
        print(f"  批次 {batch_idx}: {datetime.fromtimestamp(cur_ms/1000).date()} → "
              f"{datetime.fromtimestamp(batch_end/1000).date()} | +{len(rows)} 根 | 累计 {len(all_rows)}")
        cur_ms = batch_end
        batch_idx += 1
        time.sleep(0.3)  # 限流

    return [all_rows[ts] for ts in sorted(all_rows.keys())]


def main():
    parser = argparse.ArgumentParser(description="Hyperliquid 历史数据下载")
    parser.add_argument("--days", type=int, default=90, help="下载天数（默认 90）")
    parser.add_argument("--symbols", default="BTC,ETH,SOL", help="币种，逗号分隔")
    parser.add_argument("--interval", default="1h", choices=["1h", "30m", "5m", "4h", "15m"])
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    for sym in symbols:
        print(f"\n=== 下载 {sym} {args.interval}（{args.days} 天）===")
        rows = download_symbol(sym, args.interval, args.days)
        if not rows:
            print(f"  [!] {sym} 无数据")
            continue
        out_file = DATA_DIR / f"{sym}_USDT-{args.interval}-futures.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(rows, f)
        first_dt = datetime.fromtimestamp(rows[0][0] / 1000)
        last_dt = datetime.fromtimestamp(rows[-1][0] / 1000)
        span = (rows[-1][0] - rows[0][0]) / 1000 / 86400
        print(f"  ✓ 保存 {len(rows)} 根 → {out_file.name}")
        print(f"    时间: {first_dt} → {last_dt} | {span:.1f} 天")


if __name__ == "__main__":
    main()
