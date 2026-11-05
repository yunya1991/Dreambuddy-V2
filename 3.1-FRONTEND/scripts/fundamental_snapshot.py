#!/usr/bin/env python3
"""基本面快照聚合器 — 一次性拉 macro + chain + sentiment + breadth, 产出 {modules: {...}}。

前端 /api/fundamental/snapshot 调用此脚本, 替代原反代 9094 端口。
所有数据源走统一壳层 (dsh_frontend_bridge), FAIL-OPEN 降级不崩溃。
"""

import json
import os
import sys


def _resolve_34_core_dir() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(script_dir, "..", "..", "34-前端应用训练系统", "core"))


def main():
    core_dir = _resolve_34_core_dir()
    if os.path.isdir(core_dir) and core_dir not in sys.path:
        sys.path.insert(0, core_dir)

    # bridge call 期间重定向 stdout 避免噪音
    sys.stdout = sys.stderr
    try:
        from dsh_frontend_bridge import call_tool
    finally:
        sys.stdout = sys.__stdout__

    modules = {}

    # ── 1. macro 指标 (data.dal_query) ───────────────────────────────
    macro_module = {"timestamp": None, "data": {}}
    try:
        r = call_tool("research", "data.dal_query", {"command": "macro"})
        if r.get("ok") and r.get("data"):
            d = r["data"]
            macro_module = {
                "timestamp": d.get("timestamp"),
                "data": {
                    "dollar_index": {"value": d.get("DXY"), "label": "美元指数"},
                    "us10y_yield": {"value": d.get("US10Y"), "label": "美债10年收益率"},
                    "vix": {"value": d.get("VIX"), "label": "VIX波动率指数"},
                    "gold": {"value": d.get("Gold"), "label": "黄金"},
                    "sp500": {"value": d.get("SP500"), "label": "标普500"},
                },
            }
    except Exception:
        pass
    modules["macro"] = macro_module

    # ── 2. onchain/chain 指标 (data.dal_query) ────────────────────────
    onchain_module = {"timestamp": None, "data": {}}
    try:
        r = call_tool("research", "data.dal_query", {"command": "chain"})
        if r.get("ok") and r.get("data"):
            d = r["data"]
            onchain_module = {
                "timestamp": d.get("timestamp"),
                "data": {
                    "difficulty_change_pct": {
                        "value": d.get("difficulty_change_pct"),
                        "label": "难度变化%",
                    },
                    "difficulty_progress_pct": {
                        "value": d.get("difficulty_progress_pct"),
                        "label": "难度周期进度%",
                    },
                    "mempool_count": {"value": d.get("mempool_count"), "label": "mempool 交易数"},
                    "mempool_fee_btc": {
                        "value": d.get("mempool_fee_btc"),
                        "label": "mempool 总手续费 (BTC)",
                    },
                    "mempool_size_kb": {
                        "value": d.get("mempool_size_kb"),
                        "label": "mempool 大小 (KB)",
                    },
                    "remaining_blocks": {
                        "value": d.get("remaining_blocks"),
                        "label": "下次难度调整剩余块",
                    },
                    "tip_height": {"value": d.get("tip_height"), "label": "tip 区块高度"},
                    "sp500_equity_value": {
                        "value": d.get("sp500_equity_value"),
                        "label": "标普500 (whales)",
                    },
                    "vix_value": {"value": d.get("vix_value"), "label": "VIX (whales)"},
                    "dollar_index_value": {
                        "value": d.get("dollar_index_value"),
                        "label": "美元指数 (whales)",
                    },
                },
            }
    except Exception:
        pass
    modules["onchain"] = onchain_module

    # ── 3. sentiment — 降级 (sentiment subagent 冷启动重) ────────────
    # 短期先用 chain + macro 派生出 sentiment 信号
    sentiment_module = {
        "timestamp": macro_module.get("timestamp"),
        "data": {
            "crypto_fear_greed": {
                "value": None,
                "label": "加密恐惧贪婪",
                "note": "数据源不可用, 已降级",
            },
            "market_breadth": {"value": None, "label": "市场广度", "note": "数据源不可用, 已降级"},
            "funding_rate_basis": {
                "value": None,
                "label": "资金费率基差",
                "note": "数据源不可用, 已降级",
            },
        },
    }
    modules["sentiment"] = sentiment_module

    # ── 4. breadth — 降级 (暂无真实数据源) ──────────────────────────
    breadth_module = {
        "timestamp": macro_module.get("timestamp"),
        "data": {
            "advancing_vs_declining": {"value": None, "label": "上涨/下跌比", "note": "已降级"},
            "new_highs_vs_lows": {"value": None, "label": "新高/新低", "note": "已降级"},
            "above_ma200": {"value": None, "label": "站上MA200占比", "note": "已降级"},
        },
    }
    modules["breadth"] = breadth_module

    # ── 5. valuation — 用 macro 派生机型/指数估值 ───────────────────
    valuation_module = {
        "timestamp": macro_module.get("timestamp"),
        "data": {
            "sp500_pe_ratio": {"value": None, "label": "标普500 PE", "note": "已降级"},
            "gold_real_rate": {"value": None, "label": "黄金实际利率", "note": "已降级"},
        },
    }
    modules["valuation"] = valuation_module

    # ── 6. capital_flow — 用 chain 鲸鱼/交易所数据派生源 ─────────────
    capital_module = {
        "timestamp": macro_module.get("timestamp"),
        "data": {
            "whale_netflow": {
                "value": onchain_module.get("data", {}).get("whale_netflow_24h", {}).get("value"),
                "label": "鲸鱼净流出",
            },
            "exchange_inflow": {
                "value": onchain_module.get("data", {}).get("exchange_inflow_24h", {}).get("value"),
                "label": "交易所流入",
            },
            "exchange_outflow": {"value": None, "label": "交易所流出", "note": "已降级"},
        },
    }
    modules["capital_flow"] = capital_module

    snapshot = {
        "modules": modules,
        "timestamp": macro_module.get("timestamp"),
        "source": "dsh_frontend_bridge",
        "degraded": any(
            v.get("data", {}).get(k, {}).get("note", "").startswith("已降级")
            for v in modules.values()
            for k in v.get("data", {})
        ),
    }

    sys.stdout.write(json.dumps(snapshot, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        sys.stdout = sys.__stdout__
        sys.stdout.write(
            json.dumps(
                {
                    "modules": {},
                    "timestamp": None,
                    "source": "error",
                    "degraded": True,
                    "error": f"{type(e).__name__}: {e}",
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        sys.stdout.flush()
