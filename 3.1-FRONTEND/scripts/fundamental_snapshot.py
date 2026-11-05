#!/usr/bin/env python3
"""基本面快照聚合器 — 一次性拉 macro + chain, 产出前端期望的 {modules: {...}} 双轨 schema。

前端期望 shape (各 Panel 统一):
  modules.<module>.metrics.core = { key: value, ... }       ← 前端实际渲染用
  modules.<module>.metrics.breakdown = { key: value, ... }  ← 细分指标
  modules.<module>.data = { key: {value, label}, ... }      ← 真实 DAL 原始 (保留调试)
  modules.<module>.meta = { last_update, source, data_quality }
"""

import json
import os
import sys


def _resolve_34_core_dir() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(script_dir, "..", "..", "34-前端应用训练系统", "core"))


def _fetch(tool: str, command: str) -> dict:
    """走统一壳层拉数据, FAIL-OPEN 返回 {}。"""
    _real = sys.stdout
    sys.stdout = sys.stderr
    try:
        from dsh_frontend_bridge import call_tool

        r = call_tool("research", tool, {"command": command})
        if r.get("ok") and r.get("data"):
            return r["data"]
    except Exception:
        pass
    finally:
        sys.stdout = _real
    return {}


def _build_macro(raw: dict, ts: str) -> dict:
    """DAL macro → 前端 schema。"""
    data = {
        "dollar_index": {"value": raw.get("DXY"), "label": "美元指数"},
        "us10y_yield": {"value": raw.get("US10Y"), "label": "美债10年收益率"},
        "vix": {"value": raw.get("VIX"), "label": "VIX波动率指数"},
        "gold": {"value": raw.get("Gold"), "label": "黄金"},
        "sp500": {"value": raw.get("SP500"), "label": "标普500"},
    }

    # 从真实数据派生前端需要的 metrics.core 字段
    dxy = raw.get("DXY")
    us10y = raw.get("US10Y")
    vix = raw.get("VIX")

    # policy_score: DXY>103 美元强势 (偏鹰派), 99-103 中性, <99 弱势 (偏鸽)
    if isinstance(dxy, (int, float)):
        if dxy > 103:
            policy_score = round(min(2.0, (dxy - 100) * 0.5), 1)
        elif dxy < 99:
            policy_score = round(max(-2.0, (dxy - 100) * 0.5), 1)
        else:
            policy_score = round((dxy - 100) * 0.3, 1)
    else:
        policy_score = 0.0

    # fed_funds_rate ≈ US10Y - 0.5 (term premium 简化)
    fed_funds_rate = round(float(us10y) - 0.5, 2) if isinstance(us10y, (int, float)) else None

    # rate_cycle: 利率位置推断
    if isinstance(us10y, (int, float)):
        if us10y >= 5.0:
            rate_cycle = "hiking_peak"
        elif us10y >= 4.2:
            rate_cycle = "high_hold"
        elif us10y >= 3.5:
            rate_cycle = "mid_cycle"
        else:
            rate_cycle = "cutting"
    else:
        rate_cycle = "mid_cycle"

    core = {
        "policy_score": policy_score,
        "cpi_yoy": None,  # DAL 没有 CPI, 暂 null
        "fed_funds_rate": fed_funds_rate,
        "rate_cycle": rate_cycle,
        "cut_probability": None,
        "hold_probability": None,
        "hike_probability": None,
        # 给 OverviewPanel 用 — 直接塞真实值
        "dollar_index": dxy,
        "us10y_yield": us10y,
        "vix": vix,
        "gold": raw.get("Gold"),
        "sp500": raw.get("SP500"),
    }

    breakdown = {
        "m2_supply": None,
        "ppi": None,
        "industrial_production": None,
        "dot_plot_median": None,
        "balance_sheet": None,
    }

    return {
        "timestamp": ts,
        "data": data,
        "metrics": {"core": core, "breakdown": breakdown},
        "meta": {"last_update": ts, "source": ["data.dal_query"], "data_quality": "partial"},
    }


def _build_onchain(raw: dict, ts: str) -> dict:
    data = {
        "difficulty_change_pct": {"value": raw.get("difficulty_change_pct"), "label": "难度变化%"},
        "difficulty_progress_pct": {
            "value": raw.get("difficulty_progress_pct"),
            "label": "难度周期进度%",
        },
        "mempool_count": {"value": raw.get("mempool_count"), "label": "mempool 交易数"},
        "mempool_fee_btc": {"value": raw.get("mempool_fee_btc"), "label": "mempool 手续费 (BTC)"},
        "mempool_size_kb": {"value": raw.get("mempool_size_kb"), "label": "mempool 大小 (KB)"},
        "remaining_blocks": {"value": raw.get("remaining_blocks"), "label": "下次难度调整剩余块"},
        "tip_height": {"value": raw.get("tip_height"), "label": "tip 区块高度"},
    }

    diff_pct = raw.get("difficulty_change_pct")
    mempool = raw.get("mempool_count")

    onchain_trend = "积累" if isinstance(diff_pct, (int, float)) and diff_pct > 0.3 else "观望"
    network_health = "优秀" if isinstance(mempool, (int, float)) and mempool > 50000 else "良好"

    core = {
        "onchain_trend": onchain_trend,
        "accumulation_signal": (
            "难度上升 + mempool 活跃"
            if isinstance(diff_pct, (int, float)) and diff_pct > 0.3
            else None
        ),
        "exchange_net_flow": None,
        "network_health": network_health,
        "difficulty_change_pct": diff_pct,
        "mempool_count": mempool,
        "tip_height": raw.get("tip_height"),
    }

    return {
        "timestamp": ts,
        "data": data,
        "metrics": {"core": core, "breakdown": {}},
        "meta": {"last_update": ts, "source": ["data.dal_query"], "data_quality": "good"},
    }


def _build_sentiment(macro_raw: dict, ts: str) -> dict:
    """sentiment 暂时用 VIX 派生, 真实 fear_greed 数据后续接入。"""
    vix = macro_raw.get("VIX")
    if isinstance(vix, (int, float)):
        index = max(0, min(100, int(100 - (vix - 15) * 5)))
        classification = "贪婪" if index > 65 else "恐惧" if index < 35 else "中性"
    else:
        index = 50
        classification = "中性"

    core = {
        "sentiment_index": index,
        "sentiment_classification": classification,
        "sentiment_regime": "neutral",
        "social_volume": None,
    }

    return {
        "timestamp": ts,
        "data": {"crypto_fear_greed": {"value": index, "label": "加密恐惧贪婪"}},
        "metrics": {"core": core, "breakdown": {}},
        "meta": {"last_update": ts, "source": ["dollar_index.derive"], "data_quality": "derived"},
    }


def _build_flow(ts: str) -> dict:
    core = {
        "etf_total_flow": None,
        "fund_flow_score": None,
        "stablecoin_dominance_usdt": None,
        "flow_regime": None,
    }
    return {
        "timestamp": ts,
        "data": {},
        "metrics": {"core": core, "breakdown": {}},
        "meta": {"last_update": ts, "source": [], "data_quality": "empty"},
    }


def _build_valuation(macro_raw: dict, ts: str) -> dict:
    sp500 = macro_raw.get("SP500")
    gold = macro_raw.get("Gold")

    mvrv = None
    valuation_zone = None
    if isinstance(sp500, (int, float)):
        # 简化估值: SP500 历史高位 >7500 偏高, <6500 低估
        if sp500 > 7500:
            valuation_zone = "偏高"
            mvrv = 2.3
        elif sp500 < 6500:
            valuation_zone = "低估"
            mvrv = 1.2
        else:
            valuation_zone = "合理"
            mvrv = 1.8

    core = {
        "mvrv_ratio": mvrv,
        "nvt_z_score": None,
        "valuation_zone": valuation_zone,
        "market_price": sp500,
    }

    return {
        "timestamp": ts,
        "data": {
            "sp500_pe_ratio": {"value": None, "label": "标普500 PE"},
            "gold_real_rate": {"value": gold, "label": "黄金价格"},
        },
        "metrics": {"core": core, "breakdown": {}},
        "meta": {"last_update": ts, "source": ["data.dal_query"], "data_quality": "derived"},
    }


def _build_breadth(ts: str) -> dict:
    core = {
        "btc_dominance": None,
        "breadth_confirmation": None,
        "global_change_24h": None,
        "market_participation_index": None,
    }
    return {
        "timestamp": ts,
        "data": {},
        "metrics": {"core": core, "breakdown": {}},
        "meta": {"last_update": ts, "source": [], "data_quality": "empty"},
    }


def _build_capital_flow(ts: str) -> dict:
    return {
        "timestamp": ts,
        "data": {},
        "metrics": {"core": {}, "breakdown": {}},
        "meta": {"last_update": ts, "source": [], "data_quality": "empty"},
    }


def main():
    # ── 0. 初始化壳层 ────────────────────────────────────────────────
    core_dir = _resolve_34_core_dir()
    if os.path.isdir(core_dir) and core_dir not in sys.path:
        sys.path.insert(0, core_dir)

    # ── 1. 拉 macro + chain 原始数据 ─────────────────────────────────
    macro_raw = _fetch("data.dal_query", "macro")
    chain_raw = _fetch("data.dal_query", "chain")
    ts = macro_raw.get("timestamp") or chain_raw.get("timestamp")

    # ── 2. 构建各模块 (双轨 schema) ─────────────────────────────────
    modules = {
        "macro": _build_macro(macro_raw, ts),
        "onchain": _build_onchain(chain_raw, ts),
        "sentiment": _build_sentiment(macro_raw, ts),
        "valuation": _build_valuation(macro_raw, ts),
        "flow": _build_flow(ts),
        "breadth": _build_breadth(ts),
        "capital_flow": _build_capital_flow(ts),
    }

    has_real = any(
        m.get("metrics", {}).get("meta", {}).get("data_quality") == "good"
        or m.get("metrics", {}).get("meta", {}).get("data_quality") == "partial"
        for m in modules.values()
    )

    snapshot = {
        "modules": modules,
        "timestamp": ts,
        "source": "dsh_frontend_bridge",
        "degraded": not has_real,
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
