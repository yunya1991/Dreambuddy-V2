#!/usr/bin/env python3
"""P2 资产轮动模块 — 美林时钟定位 + 资产动量印证（40-SPEC.md v0.4 §3.2）
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone

DB = "/home/luke/dreambuddy/18-数据获取中心/data_center.db"
OUT = "/home/luke/dreambuddy/40-周期神经网络系统/asset_rotation.json"

GROWTH_THRESHOLD = 1.5
INFLATION_THRESHOLD = 2.5

def load_series(sid):
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT timestamp, json_extract(metrics, ?) FROM records WHERE source = ? AND sub_category = ? ORDER BY timestamp",
        ("$.value", "fred", sid),
    ).fetchall()
    conn.close()
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
    try:
        import yfinance as yf
        for sym, name in (("GC=F", "gold"), ("DX-Y.NYB", "dollar"), ("^TNX", "treasury_yield"), ("^GSPC", "equity")):
            df = yf.download(sym, period="3mo", interval="1d", progress=False)
            if df is None or df.empty:
                continue
            try:
                closes = df["Close"].dropna()
            except Exception:
                closes = df.xs("Close", axis=1, level=-1).dropna()
            if len(closes) >= 60:
                mom[name] = round((float(closes.iloc[-1]) / float(closes.iloc[0]) - 1) * 100, 2)
    except Exception as e:
        mom["yf_error"] = str(e)[:100]
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
