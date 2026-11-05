#!/usr/bin/env python3
"""交易榜单聚合器 — orchestrator 输出 → TradingRankingItem[] 前端格式。

前端 /api/trading-ranking/today 调用此脚本, 替代 mock 数据。
走统一壳层 (dsh_frontend_bridge), FAIL-OPEN 降级返回空列表。
"""

import json
import os
import sys
from datetime import datetime, timezone


def _resolve_34_core_dir() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(script_dir, "..", "..", "34-前端应用训练系统", "core"))


def _score_to_signal(score: float) -> str:
    """0-1 score → TradingRankingItem.signal。"""
    if score >= 0.75:
        return "STRONG_BUY"
    if score >= 0.6:
        return "BUY"
    if score >= 0.52:
        return "WEAK_BUY"
    if score <= 0.25:
        return "STRONG_SELL"
    if score <= 0.4:
        return "SELL"
    if score <= 0.48:
        return "WEAK_SELL"
    return "NEUTRAL"


def _symbol_category(symbol: str) -> str:
    """symbol → category。"""
    s = symbol.upper()
    if (
        s
        in ("BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "LINK", "LTC", "ZEC", "HYPE")
        or "/USDT" in s
        or "/USDC" in s
    ):
        return "crypto"
    if s in ("GC=F", "CL=F", "SI=F", "HG=F", "WTI", "BRENT"):
        return "commodity"
    if s in ("SPY", "QQQ", "IWM", "DIA", "^GSPC", "^IXIC", "^DJI", "NASDAQ", "SP500"):
        return "index"
    return "crypto"  # default


def _orchestrator_to_items(orch_data: dict) -> list:
    """orchestrator 输出 → TradingRankingItem[]。

    orchestrator 输出结构 (可能两种):
      A (扁平): selection: { long_pool: [...], short_pool: [...] }
      B (嵌套): selection: { pools: { long_pool: [...], short_pool: [...] }, status: "OK" }
      signal: { symbol, direction, confidence, ... }
      execution: { position: { status, ... } }
    """
    items = []
    selection = orch_data.get("selection", {}) or {}
    signal = orch_data.get("signal", {}) or {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 同时支持扁平结构和嵌套 pools 结构
    pools = selection.get("pools") or selection
    long_pool = pools.get("long_pool", []) or []
    short_pool = pools.get("short_pool", []) or []

    # 合并两个池, score 高的优先
    candidates = []
    for entry in long_pool:
        symbol = entry.get("symbol", "")
        score = float(entry.get("score", 0))
        candidates.append(
            {
                "symbol": symbol,
                "score": score,
                "direction": "BUY",
                "reasons": entry.get("reasons", []),
            }
        )
    for entry in short_pool:
        symbol = entry.get("symbol", "")
        score = float(entry.get("score", 0))
        candidates.append(
            {
                "symbol": symbol,
                "score": score,
                "direction": "SELL",
                "reasons": entry.get("reasons", []),
            }
        )

    # 如果 orchestrator 只给了单一 signal, 也加进去
    if signal and signal.get("symbol") and not candidates:
        sym = signal["symbol"]
        conf = float(signal.get("confidence", 0.5))
        candidates.append(
            {
                "symbol": sym,
                "score": conf,
                "direction": signal.get("direction", "HOLD"),
                "reasons": [],
            }
        )

    # 排序 + Top10
    candidates.sort(key=lambda c: c["score"], reverse=True)
    candidates = candidates[:10]

    for i, c in enumerate(candidates):
        symbol = c["symbol"]
        score = c["score"]
        direction = c["direction"]
        category = _symbol_category(symbol)
        signal_type = (
            _score_to_signal(score) if direction != "SELL" else _score_to_signal(1 - score)
        )

        # 决策卡 (简化版 — 真实入场价/止损需要实时行情)
        decision = {
            "entry": {
                "price": None,  # 行情驱动, 暂 null
                "range": [None, None],
                "batches": [],
            },
            "stopLoss": None,
            "takeProfit": [],
            "events": [],
            "riskLevel": "intermediate",
            "historicalAnalogy": "",
            "logic": {
                "bullish": c.get("reasons", [])[:3],
                "bearish": [],
                "confidence": round(score, 2),
            },
        }

        items.append(
            {
                "rank": i + 1,
                "symbol": symbol,
                "category": category,
                "score": round(score, 3),
                "signal": signal_type,
                "confidence": round(score, 2),
                "decisionCard": decision,
                "date": today,
            }
        )

    return items


def main():
    core_dir = _resolve_34_core_dir()
    if os.path.isdir(core_dir) and core_dir not in sys.path:
        sys.path.insert(0, core_dir)

    # 抑制 orchestrator/call_handler 内部所有 print/日志到 stdout
    # (它们会污染 execFileAsync 捕获的 JSON 输出)
    _real_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        from dsh_frontend_bridge import call_handler

        items = []
        orch_ok = False
        try:
            r = call_handler("orchestrator", {"node_output": {"symbol": "BTC"}})
            if r.get("ok") and r.get("output"):
                orch_ok = True
                items = _orchestrator_to_items(r["output"])
        except Exception:
            pass
    finally:
        sys.stdout = _real_stdout

    # 兜底: 如果 orchestrator 没数据, 返回空 items (前端已有 mock 降级)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    result = {
        "success": orch_ok and len(items) > 0,
        "items": items,
        "metrics": {
            "date": today,
            "satisfaction": None,
            "conversionRate": None,
            "abandonRate": None,
            "pushReachRate": None,
            "unsubscribeRate": None,
            "matu": None,
            "kFactor": None,
        },
        "source": "orchestrator" if orch_ok else "fallback",
        "degraded": not orch_ok,
    }

    sys.stdout.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        sys.stdout = sys.__stdout__
        sys.stdout.write(
            json.dumps(
                {
                    "success": False,
                    "items": [],
                    "metrics": {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d")},
                    "source": "error",
                    "degraded": True,
                    "error": f"{type(e).__name__}: {e}",
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        sys.stdout.flush()
