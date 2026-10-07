"""一次性 backfill 脚本：拉取 SECTOR_MAP 全部 25 币的 CoinGecko market_chart 数据，
写入 data_center.db records 表（sub_category=chart_{coin_id}）。

供 query_valuation_percentile / sector_waterline 使用。

用法：
  cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/18-数据获取中心
  python backfill_coingecko_chart.py

CoinGecko 公共 API 限流 ~10-30 req/min，串行 + 间隔 5s 避免触发 429。
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone

# 让 data_center 包可导入
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from data_center.collectors.coin.coingecko_collector import CoinGeckoCollector
from data_center.core.errors import RateLimitError
from data_center.storage.sink_sqlite import SqliteSink

DB_PATH = os.path.join(_THIS_DIR, "data_center.db")

# 与 scheduler.py / coin_fundamental_crypto.py._SECTOR_COIN_META 对齐
COIN_IDS = [
    # DEX
    "uniswap", "curve-dao-token", "1inch", "pancakeswap-token", "sushi",
    # Lending
    "aave", "compound-governance-token", "maker",
    # L1
    "bitcoin", "ethereum", "solana", "binancecoin", "cardano", "zcash",
    # L2
    "optimism", "arbitrum", "matic-network", "blockstack",
    # Meme
    "pump-fun", "dogecoin", "shiba-inu", "pepe",
    # Perp DEX
    "hyperliquid", "gmx", "gains-network", "dydx",
]


def main() -> int:
    sink = SqliteSink(DB_PATH)
    collector = CoinGeckoCollector()

    if not collector.is_available():
        print("ERROR: CoinGeckoCollector 不可用（网络问题）", file=sys.stderr)
        return 1

    ok_count = 0
    fail_count = 0
    skip_count = 0

    print(f"[{datetime.now(timezone.utc).isoformat()}] 开始 backfill {len(COIN_IDS)} 个币的 chart 数据")
    print(f"DB: {DB_PATH}")

    for i, coin_id in enumerate(COIN_IDS, 1):
        # 限流：每个请求间隔 5s
        if i > 1:
            time.sleep(5.0)

        try:
            recs = collector.fetch({"route": "coin_chart", "coin_id": coin_id, "days": 30})
            if not recs:
                print(f"[{i:02d}/{len(COIN_IDS)}] {coin_id:30s} SKIP（无数据返回）")
                skip_count += 1
                continue

            sink.write(recs)
            ts = recs[0].timeseries
            ts_len = len(ts) if ts else 0
            latest_mcap = ts[-1].get("market_cap", 0) if ts else 0
            print(f"[{i:02d}/{len(COIN_IDS)}] {coin_id:30s} OK  points={ts_len} latest_mcap={latest_mcap:.2e}")
            ok_count += 1

        except RateLimitError as e:
            # 429 限流：等 60s 后重试一次
            print(f"[{i:02d}/{len(COIN_IDS)}] {coin_id:30s} 429 限流，等 60s 后重试一次...")
            time.sleep(60.0)
            try:
                recs = collector.fetch({"route": "coin_chart", "coin_id": coin_id, "days": 30})
                if recs:
                    sink.write(recs)
                    ts = recs[0].timeseries
                    ts_len = len(ts) if ts else 0
                    print(f"[{i:02d}/{len(COIN_IDS)}] {coin_id:30s} OK（重试）  points={ts_len}")
                    ok_count += 1
                else:
                    print(f"[{i:02d}/{len(COIN_IDS)}] {coin_id:30s} SKIP（重试后仍无数据）")
                    skip_count += 1
            except Exception as e2:
                print(f"[{i:02d}/{len(COIN_IDS)}] {coin_id:30s} FAIL（重试也失败）: {e2}")
                fail_count += 1

        except Exception as e:
            print(f"[{i:02d}/{len(COIN_IDS)}] {coin_id:30s} FAIL: {e}")
            fail_count += 1

    print()
    print(f"=== Backfill 完成 ===")
    print(f"  OK:   {ok_count}")
    print(f"  SKIP: {skip_count}")
    print(f"  FAIL: {fail_count}")
    return 0 if fail_count == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
