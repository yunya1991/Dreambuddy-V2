#!/usr/bin/env python3
"""
macro_data_query.py — 从 19-数据访问层 mm_metrics 表查询宏观经济指标
供 /api/data/macro Next.js API Route 调用
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
        # DXY (美元指数)
        dxy = query_latest("DX-Y.NYB", "value")
        if dxy:
            output["dxy"] = dxy["value"]

        # US 10Y 国债收益率
        tnx = query_latest("^TNX", "value")
        if tnx:
            output["us10y_yield"] = tnx["value"]
        else:
            # 备选: macro_us_stocks
            dgs10 = query_latest("macro_us_stocks", "us_DGS10_value")
            if dgs10:
                output["us10y_yield"] = dgs10["value"]

        # VIX
        vix = query_latest("^VIX", "value")
        if vix:
            output["vix"] = vix["value"]
        else:
            vixcls = query_latest("macro_us_stocks", "us_VIXCLS_value")
            if vixcls:
                output["vix"] = vixcls["value"]

        # 黄金 (GC=F 期货)
        gold = query_latest("GC=F", "value")
        if gold:
            output["gold"] = gold["value"]

        # S&P 500
        sp500 = query_latest("macro_us_stocks", "us_SP500_value")
        if sp500:
            output["sp500"] = sp500["value"]
        else:
            spy = query_latest("SPY", "value")
            if spy:
                output["sp500"] = spy["value"]

        # 联邦基金利率
        dff = query_latest("macro_us_stocks", "us_DFF_value")
        if dff:
            output["fed_funds_rate"] = dff["value"]

        # NASDAQ
        ndq = query_latest("macro_us_stocks", "us_NASDAQCOM_value")
        if ndq:
            output["nasdaq"] = ndq["value"]

        # M2 货币供应
        m2 = query_latest("macro", "m2_sl")
        if m2:
            output["m2_supply"] = m2["value"]

        output["timestamp"] = datetime.now(timezone.utc).isoformat()
        output["source"] = "dal"

    except Exception as e:
        output["degraded"] = True
        output["error"] = str(e)

    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
