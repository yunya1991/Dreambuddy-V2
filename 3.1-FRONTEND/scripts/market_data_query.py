#!/usr/bin/env python3
"""
market_data_query.py — 从 19-数据访问层 mm_metrics 表查询市场指标
供 /api/data/market Next.js API Route 调用
只读读操作，返回 JSON
"""
import json
import sqlite3
import sys
from datetime import datetime, timezone, timedelta

DB_PATH = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/19-数据访问层/data/dreambuddy_core.db"


def query_latest(sub_category: str, metric_names: list[str]) -> dict:
    """查询指定 sub_category 下各 metric 的最新值"""
    result = {}
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        for metric in metric_names:
            row = conn.execute(
                """
                SELECT metric_value, timestamp
                FROM mm_metrics
                WHERE sub_category = ? AND metric_name = ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (sub_category, metric),
            ).fetchone()
            if row:
                result[metric] = {"value": row[0], "ts": row[1]}
        conn.close()
    except Exception as e:
        result["_error"] = str(e)
    return result


def main():
    output = {
        "funding_rate": {},
        "fear_greed": {},
        "long_short_ratio": {},
        "degraded": False,
    }

    try:
        # 资金费率
        fr = query_latest("funding_rate", ["funding_rate_pct", "funding_rate_annualized_pct"])
        if "funding_rate_pct" in fr:
            output["funding_rate"]["rate_pct"] = fr["funding_rate_pct"]["value"]
            output["funding_rate"]["ts"] = fr["funding_rate_pct"]["ts"]
        if "funding_rate_annualized_pct" in fr:
            output["funding_rate"]["annualized_pct"] = fr["funding_rate_annualized_pct"]["value"]

        # 恐惧贪婪
        fg = query_latest("crypto_fear_greed", ["value"])
        if "value" in fg:
            val = fg["value"]["value"]
            output["fear_greed"]["value"] = val
            output["fear_greed"]["ts"] = fg["value"]["ts"]
            if val <= 25:
                output["fear_greed"]["classification"] = "Extreme Fear"
            elif val <= 45:
                output["fear_greed"]["classification"] = "Fear"
            elif val <= 55:
                output["fear_greed"]["classification"] = "Neutral"
            elif val <= 75:
                output["fear_greed"]["classification"] = "Greed"
            else:
                output["fear_greed"]["classification"] = "Extreme Greed"

        # 多空比
        lsr = query_latest("long_short_ratio", ["long_short_ratio", "long_account_pct", "short_account_pct"])
        if "long_short_ratio" in lsr:
            output["long_short_ratio"]["ratio"] = lsr["long_short_ratio"]["value"]
            output["long_short_ratio"]["ts"] = lsr["long_short_ratio"]["ts"]
        if "long_account_pct" in lsr:
            output["long_short_ratio"]["long_pct"] = lsr["long_account_pct"]["value"]
        if "short_account_pct" in lsr:
            output["long_short_ratio"]["short_pct"] = lsr["short_account_pct"]["value"]

    except Exception as e:
        output["degraded"] = True
        output["error"] = str(e)

    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
