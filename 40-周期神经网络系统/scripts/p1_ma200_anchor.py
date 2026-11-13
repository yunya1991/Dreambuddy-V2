#!/usr/bin/env python3
"""P1 周期判定模块 — MA200 技术锚点（40-SPEC.md v0.4 §2.5）

标的域（DEC-BCL-07）：由 40/asset_classes.py 的 VALIDATION_UNIVERSE 派生，
覆盖加密 / 贵金属 / 能源 / 工业金属 / 美股指数与 ETF / 美股龙头 / 亚太 / 利率，
另补 8 币验证白名单的历史成员（UNI/AAVE/NEAR/ARB/LINK）与 SPX。
加密标的键保持 "X/USDT"（兼容 p3/p5/23/43/l1_trading 既有消费者），
其余标的使用基础符号键。单个标的失败只记录 error，不阻断整体产出。

产出物：合并写入 cycle_state.json 的 technical_anchor 部分
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

# R-42-04/P1-03：DREAMBUDDY_ROOT 环境变量统一模块根路径；未设置时按 __file__ 推导（仓库内模块同级布局）
_DREAMBUDDY_ROOT = os.environ.get("DREAMBUDDY_ROOT") or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

# G10：价格唯一来源（18 统一价格源，禁止本脚本直连交易所）
sys.path.insert(0, os.path.join(_DREAMBUDDY_ROOT, "18-数据获取中心"))
from data_center.market import price_source  # noqa: E402

# 40 自有注册表：标的域唯一事实源
sys.path.insert(0, os.path.join(_DREAMBUDDY_ROOT, "40-周期神经网络系统"))
from asset_classes import VALIDATION_UNIVERSE, class_of  # noqa: E402

STATE_FILE = os.path.join(_DREAMBUDDY_ROOT, "40-周期神经网络系统", "cycle_state.json")
MA_WINDOW = 200
# 8 币验证白名单中的加密标的（历史锚点，保持 "X/USDT" 键）
CRYPTO_EXTRA = ["ETH", "SOL", "UNI", "AAVE", "NEAR", "ARB", "LINK"]
SPX_SYMBOL = "^GSPC"


def anchor_targets():
    """返回 [(cycle_state 键, 18 价格源符号)]。

    加密标的键为 "BTC/USDT"（下游按此键读取）；非加密标的使用基础符号，
    由 18 统一价格源换算为 OKX -USDT-SWAP 永续。
    """
    out = []
    seen = set()

    def add(key):
        if key not in seen:
            seen.add(key)
            out.append((key, key))

    for sym in VALIDATION_UNIVERSE:
        cls = class_of(sym)
        if cls is None:
            continue
        add(f"{sym}/USDT" if cls == "crypto" else sym)
    # 8 币验证白名单的历史成员不在 asset_classes 的 crypto 成员表内，按加密标的补入
    for sym in CRYPTO_EXTRA:
        add(f"{sym}/USDT")
    return out


def fetch_daily_closes(symbol, limit=400):
    """日线收盘序列 (ts_ms, close)（G10 统一价格源：OKX 主源 + Binance 显式 fallback）。"""
    result = price_source.fetch_daily(symbol, days=limit)
    return [(bar["ts_ms"], bar["close"]) for bar in result["bars"]]


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
    for ts, val in zip(closes.index, closes.values):  # noqa: B905
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
    for key, fetch_sym in anchor_targets():
        try:
            closes = fetch_daily_closes(fetch_sym)
            r = calc_ma200(closes)
            if r:
                anchors[key] = r
            else:
                # 新上市合约不足 200 根日线：如实记录样本量，不用短样本伪造 MA200
                anchors[key] = {"error": "insufficient_samples", "samples": len(closes)}
        except Exception as e:
            anchors[key] = {"error": str(e)[:120]}
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
