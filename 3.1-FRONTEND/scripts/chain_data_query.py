#!/usr/bin/env python3
"""
chain_data_query.py — 从 19-数据访问层 mm_metrics 表查询链上指标
供 /api/data/chain Next.js API Route 调用
只读，返回 JSON，FAIL-OPEN
"""
import json
import sqlite3
import sys
from datetime import datetime, timezone

DB_PATH = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/19-数据访问层/data/dreambuddy_core.db"


def query_latest(sub_category: str, metric_name: str):
    """查询单个指标最新值"""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        row = conn.execute(
            """
            SELECT metric_value, timestamp
            FROM mm_metrics
            WHERE sub_category = ? AND metric_name = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (sub_category, metric_name),
        ).fetchone()
        conn.close()
        if row:
            return {"value": row[0], "ts": row[1]}
    except Exception as e:
        print(f"query error: {e}", file=sys.stderr)
    return None


def main():
    output = {"degraded": False}

    try:
        # 活跃地址
        addr = query_latest("btc_onchain", "active_addresses")
        if addr:
            output["active_addresses_24h"] = int(addr["value"]) if addr["value"] else None
            output["active_addresses_ts"] = addr["ts"]

        # 算力
        hr = query_latest("btc_onchain", "hash_rate")
        if hr:
            output["hash_rate"] = hr["value"]

        # 难度变化
        diff = query_latest("btc_onchain", "difficulty_change_pct")
        if diff:
            output["difficulty_change_pct"] = diff["value"]

        # 内存池
        mempool = query_latest("btc_onchain", "mempool_count")
        if mempool:
            output["mempool_count"] = mempool["value"]

        # 交易所流入
        inflow = query_latest("exchanges_whales", "ex_summary_inflowUsd24h")
        if inflow:
            output["exchange_inflow_24h"] = inflow["value"]

        # 交易所余额
        ex_bal = query_latest("exchanges_whales", "ex_bal_BTC_total")
        if ex_bal:
            output["exchange_balance_btc"] = ex_bal["value"]

        # 鲸鱼转账数
        whale_count = query_latest("exchanges_whales", "whales_transfer_count")
        if whale_count:
            output["large_transfers_24h"] = int(whale_count["value"]) if whale_count["value"] else None

        # 鲸鱼净流入
        netflow = query_latest("exchanges_whales", "whale_netflow_to_ex_usd")
        if netflow:
            output["whale_netflow_24h"] = netflow["value"]

        output["timestamp"] = datetime.now(timezone.utc).isoformat()
        output["source"] = "dal"

    except Exception as e:
        output["degraded"] = True
        output["error"] = str(e)

    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
