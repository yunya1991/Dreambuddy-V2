#!/usr/bin/env python3
"""P2 资产轮动模块 — 美林时钟定位 + 资产动量印证（40-SPEC.md v0.4 §3.2）"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

# R-42-04/P1-03：DREAMBUDDY_ROOT 环境变量统一模块根路径；未设置时按 __file__ 推导（仓库内模块同级布局）
_DREAMBUDDY_ROOT = os.environ.get("DREAMBUDDY_ROOT") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

OUT = os.path.join(_DREAMBUDDY_ROOT, "40-周期神经网络系统", "asset_rotation.json")

# 2026-11-10 修复：数据源跟随 DATA_CENTER_BACKEND（postgres|sqlite），统一走 db_access
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db_access  # noqa: E402

GROWTH_THRESHOLD = 1.5
INFLATION_THRESHOLD = 2.5


def load_series(sid):
    rows = db_access.query_fred_series(sid)
    return {r[0][:7]: float(r[1]) for r in rows if r[1] is not None}


def yoy(series, month):
    y = int(month[:4]) - 1
    m = month[5:7]
    prev = series.get(f"{y}-{m}")
    cur = series.get(month)
    if prev is None or cur is None or prev == 0:
        return None
    return (cur - prev) / prev * 100


def latest_common_month(s1, s2):
    common = [m for m in set(s1) & set(s2) if yoy(s1, m) is not None and yoy(s2, m) is not None]
    if not common:
        return None
    return sorted(common)[-1]


def clock_quadrant(growth, inflation):
    if growth is None or inflation is None:
        return None
    if growth >= GROWTH_THRESHOLD and inflation >= INFLATION_THRESHOLD:
        return "overheat"
    if growth >= GROWTH_THRESHOLD and inflation < INFLATION_THRESHOLD:
        return "recovery"
    if growth < GROWTH_THRESHOLD and inflation >= INFLATION_THRESHOLD:
        return "stagflation"
    return "reflation"


def asset_momentum():
    """3 个月资产动量（%）。
    2026-11-10 修复：原走 Yahoo 行情被限流（HTTP 429），四个传统资产切换数据源——
    黄金走 OKX XAU/USDT 永续（ccxt 公共接口，无需鉴权），
    标普/美元/10Y 收益率走 FRED 已回填序列（SP500/DTWEXBGS/DGS10），
    键名对齐下游消费方（p2_divergence / p3_fund_flow）。
    """
    mom = {}
    try:
        import ccxt

        ex = ccxt.binance({"enableRateLimit": True})
        for sym, name in (("BTC/USDT", "crypto_btc"), ("ETH/USDT", "crypto_eth")):
            o = ex.fetch_ohlcv(sym, "1d", limit=91)
            if len(o) >= 90:
                mom[name] = round((o[-1][4] / o[0][4] - 1) * 100, 2)
    except Exception as e:
        mom["crypto_error"] = str(e)[:100]
    # 黄金：OKX XAU/USDT 永续（ccxt 公共行情，无需鉴权）
    try:
        import ccxt

        okx = ccxt.okx({"enableRateLimit": True})
        o = okx.fetch_ohlcv("XAU/USDT:USDT", "1d", limit=91)
        if len(o) >= 60:
            mom["gold_xaut"] = round((o[-1][4] / o[0][4] - 1) * 100, 2)
    except Exception as e:
        mom["gold_error"] = str(e)[:100]
    # 标普/美元/10Y 收益率：FRED 已回填序列（db_access，跟随 DATA_CENTER_BACKEND）
    def _fred_momentum(sid):
        from datetime import datetime, timedelta
        rows = db_access.query_fred_series(sid)
        pts = [(r[0][:10], float(r[1])) for r in rows if r[1] is not None]
        if len(pts) < 60:
            return None
        latest_d, latest_v = pts[-1]
        try:
            cutoff = (datetime.strptime(latest_d, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")
            base = next((v for d, v in pts if d >= cutoff), None)
        except ValueError:
            base = None
        if base in (None, 0):
            return None
        return round((latest_v / base - 1) * 100, 2)
    for sid, name in (("SP500", "equity_spx"), ("DTWEXBGS", "usd_dxy"), ("DGS10", "rates_10y")):
        m = _fred_momentum(sid)
        if m is not None:
            mom[name] = m
    return mom


def main():
    indpro = load_series("INDPRO")
    cpi = load_series("CPIAUCSL")
    month = latest_common_month(indpro, cpi)
    if month is None:
        raise SystemExit("时钟数据不足")
    growth = yoy(indpro, month)
    inflation = yoy(cpi, month)
    quadrant = clock_quadrant(growth, inflation)
    mom = asset_momentum()
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "merrill_clock": {
            "month": month,
            "growth_yoy_pct": round(growth, 2) if growth is not None else None,
            "inflation_yoy_pct": round(inflation, 2) if inflation is not None else None,
            "quadrant": quadrant,
            "thresholds": {"growth": GROWTH_THRESHOLD, "inflation": INFLATION_THRESHOLD},
        },
        "asset_momentum_3m_pct": mom,
        "data_coverage": {"indpro": len(indpro), "cpi": len(cpi)},
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("saved:", OUT)


if __name__ == "__main__":
    main()
