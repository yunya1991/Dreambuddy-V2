#!/usr/bin/env python3
"""P1 周期判定模块 — MA200 技术锚点（40-SPEC.md v0.4 §2.5）
BTC/ETH/SOL + 赛道龙头 UNI/AAVE/NEAR/ARB/LINK 日线K线 + SPX 日线，计算 MA200 牛熊分界状态
产出物：合并写入 cycle_state.json 的 technical_anchor 部分
"""
from __future__ import annotations
import json
from datetime import datetime, timezone

STATE_FILE = "/home/luke/dreambuddy/40-周期神经网络系统/cycle_state.json"
MA_WINDOW = 200
CRYPTO_SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT",
    "UNI/USDT", "AAVE/USDT", "NEAR/USDT", "ARB/USDT", "LINK/USDT",
]
SPX_SYMBOL = "^GSPC"

def fetch_crypto_daily(symbol, limit=400):
    import ccxt
    ex = ccxt.binance({"enableRateLimit": True})
    ohlcv = ex.fetch_ohlcv(symbol, "1d", limit=limit)
    return [(c[0], c[4]) for c in ohlcv if c[4]]

def fetch_spx_daily():
    import yfinance as yf
    df = yf.download(SPX_SYMBOL, period="2y", interval="1d", progress=False)
    if df is None or df.empty:
        return []
    try:
        closes = df["Close"].dropna()
    except Exception:
        closes = df.xs("Close", axis=1, level=-1).dropna()
    out = []
    for ts, val in zip(closes.index, closes.values):
        out.append((int(ts.timestamp() * 1000), float(val)))
    return out

def calc_ma200(closes):
    if len(closes) < MA_WINDOW:
        return None
    window = [c for _, c in closes[-MA_WINDOW:]]
    ma = sum(window) / MA_WINDOW
    last = closes[-1][1]
    dist = (last - ma) / ma * 100
    return {
        "last_close": round(last, 2),
        "ma200": round(ma, 2),
        "above": last > ma,
        "distance_pct": round(dist, 2),
        "samples": len(closes),
    }

def main():
    anchors = {}
    for sym in CRYPTO_SYMBOLS:
        try:
            closes = fetch_crypto_daily(sym)
            r = calc_ma200(closes)
            if r:
                anchors[sym] = r
        except Exception as e:
            anchors[sym] = {"error": str(e)[:120]}
    try:
        closes = fetch_spx_daily()
        r = calc_ma200(closes)
        if r:
            anchors[SPX_SYMBOL] = r
    except Exception as e:
        anchors[SPX_SYMBOL] = {"error": str(e)[:120]}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)
    state["technical_anchor"] = {
        "type": "MA200",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "assets": anchors,
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print(json.dumps(anchors, ensure_ascii=False, indent=2))
    print("saved:", STATE_FILE)

if __name__ == "__main__":
    main()
