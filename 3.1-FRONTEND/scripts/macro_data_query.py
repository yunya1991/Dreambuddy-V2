#!/usr/bin/env python3
"""
macro_data_query.py — 从 19-数据访问层 mm_metrics 表查询宏观经济指标
供 /api/data/macro Next.js API Route 调用
只读，返回 JSON，FAIL-OPEN
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

# 3.1-FRONTEND/scripts/ → ../../ = 仓库根（此前写成 ../../.. 多退一级，
# 导致云端/本地都指向不存在的 DB，接口恒返回空值）；可被 DREAMBUDDY_CORE_DB 覆盖
DB_PATH = os.environ.get("DREAMBUDDY_CORE_DB") or os.path.normpath(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "19-数据访问层",
        "data",
        "dreambuddy_core.db",
    )
)


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


def query_cpi_yoy():
    """美国 CPI 同比（%）：优先 CPIAUCSL/yoy_pct，回退由月度指数 vs 去年同月计算。

    GDP 当前无入库数据源，不在此伪造；缺失时由调用方如实标注。
    """
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        row = conn.execute("""
            SELECT metric_value, timestamp
            FROM mm_metrics
            WHERE sub_category = 'CPIAUCSL' AND metric_name = 'yoy_pct'
            ORDER BY timestamp DESC
            LIMIT 1
            """).fetchone()
        if row and row[0] is not None:
            conn.close()
            return {"value": float(row[0]), "ts": int(row[1])}

        idx = conn.execute("""
            SELECT metric_value, timestamp
            FROM mm_metrics
            WHERE sub_category = 'CPIAUCSL' AND metric_name = 'value'
            ORDER BY timestamp DESC
            LIMIT 1
            """).fetchone()
        prev = (
            conn.execute(
                """
            SELECT metric_value
            FROM mm_metrics
            WHERE sub_category = 'CPIAUCSL' AND metric_name = 'value'
              AND timestamp <= ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
                (int(idx[1]) - 365 * 86400,),
            ).fetchone()
            if idx
            else None
        )
        conn.close()
        if idx and prev and prev[0]:
            yoy = (float(idx[0]) / float(prev[0]) - 1.0) * 100.0
            return {"value": round(yoy, 2), "ts": int(idx[1])}
    except Exception as e:
        print(f"query error: {e}", file=sys.stderr)
    return None


def main():
    output = {"degraded": False}

    try:
        # 优先级：FRED 日频序列（macro_us_stocks，最新）> 行情快照（price > value）
        # 此前只读 value，命中的是 10-23 的旧快照，比 FRED 慢近一个月。
        def latest_of(*candidates):
            for sub, name in candidates:
                row = query_latest(sub, name)
                if row and row.get("value") is not None:
                    return row["value"]
            return None

        # DXY (美元指数；DTWEXBGS 为广义美元指数)
        dxy = latest_of(
            ("macro_us_stocks", "us_DTWEXBGS_value"),
            ("DX-Y.NYB", "price"),
            ("DX-Y.NYB", "value"),
        )
        if dxy is not None:
            output["dxy"] = dxy

        # US 10Y 国债收益率
        us10y = latest_of(
            ("macro_us_stocks", "us_DGS10_value"),
            ("^TNX", "price"),
            ("^TNX", "value"),
        )
        if us10y is not None:
            output["us10y_yield"] = us10y

        # VIX
        vix = latest_of(
            ("macro_us_stocks", "us_VIXCLS_value"),
            ("^VIX", "price"),
            ("^VIX", "value"),
        )
        if vix is not None:
            output["vix"] = vix

        # 黄金 (GC=F 期货)
        gold = latest_of(("GC=F", "price"), ("GC=F", "value"))
        if gold is not None:
            output["gold"] = gold

        # S&P 500
        sp500 = latest_of(("macro_us_stocks", "us_SP500_value"), ("SPY", "close_usd"))
        if sp500 is not None:
            output["sp500"] = sp500

        # 联邦基金利率
        dff = latest_of(("macro_us_stocks", "us_DFF_value"))
        if dff is not None:
            output["fed_funds_rate"] = dff

        # NASDAQ
        ndq = latest_of(("macro_us_stocks", "us_NASDAQCOM_value"))
        if ndq is not None:
            output["nasdaq"] = ndq

        # M2 货币供应（FRED 序列名是 M2SL/M2NS；此前查 ("macro","m2_sl") 永远查不到）
        m2 = latest_of(("M2SL", "value"), ("M2NS", "value"), ("macro", "m2_sl"))
        if m2 is not None:
            output["m2_supply"] = m2

        # GDP 同比：库内没有 GDPC1，使用 INDPRO（工业生产指数）同比作为代理，
        # 并显式标注 gdp_is_proxy，避免把代理值当成官方 GDP 同比。
        gdp_proxy = latest_of(("INDPRO", "yoy_pct"))
        if gdp_proxy is not None:
            output["gdp_yoy"] = gdp_proxy
            output["gdp_source"] = "INDPRO_yoy_proxy"
            output["gdp_is_proxy"] = True

        # 美国 CPI 同比（宏观子代理的 cpi_yoy 输入）
        cpi = query_cpi_yoy()
        if cpi:
            output["cpi_yoy"] = cpi["value"]
            output["cpi_ts"] = cpi["ts"]

        output["timestamp"] = datetime.now(timezone.utc).isoformat()
        output["source"] = "dal"

        # 全部指标缺失时如实标 degraded，避免前端把空对象当「真实 0」
        if not any(k not in ("degraded", "timestamp", "source", "error") for k in output):
            output["degraded"] = True
            output["error"] = "no_metrics_in_dal"

    except Exception as e:
        output["degraded"] = True
        output["error"] = str(e)

    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
