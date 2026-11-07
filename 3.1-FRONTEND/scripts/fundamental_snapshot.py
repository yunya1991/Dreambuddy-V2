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

    # fed_funds_rate: 优先 DAL 真实值 (FEDFUNDS), 缺失时回退 US10Y - 0.5 简化推导
    fed_rate_raw = raw.get("Fed_rate")
    if isinstance(fed_rate_raw, (int, float)):
        fed_funds_rate = round(float(fed_rate_raw), 2)
    elif isinstance(us10y, (int, float)):
        fed_funds_rate = round(float(us10y) - 0.5, 2)
    else:
        fed_funds_rate = None

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
        "cpi": raw.get("CPI"),  # CPI 指数水平 (CPIAUCSL, DAL 真实值)
        "cpi_yoy": raw.get("CPI_yoy"),  # CPI 同比% (DAL macro: 最新 vs ~1年前)
        "fed_funds_rate": fed_funds_rate,
        "rate_cycle": rate_cycle,
        "cut_probability": raw.get("cut_probability"),  # CME FedWatch (fedwatch/cut_prob)
        "hold_probability": raw.get("hold_probability"),  # CME FedWatch (fedwatch/hold_prob)
        "hike_probability": raw.get("hike_probability"),  # CME FedWatch (fedwatch/hike_prob)
        # 给 OverviewPanel 用 — 直接塞真实值
        "dollar_index": dxy,
        "us10y_yield": us10y,
        "vix": vix,
        "gold": raw.get("Gold"),
        "sp500": raw.get("SP500"),
    }

    breakdown = {
        "m2_supply": None,  # DAL macro 未暴露 M2NS
        "ppi": raw.get("PPI"),  # PPIACO 真实值
        "industrial_production": None,  # DAL macro 未暴露 INDPRO
        "dot_plot_median": None,
        "balance_sheet": raw.get("Fed_liquidity"),  # WALCL 真实值
        "nasdaq": raw.get("NASDAQ"),  # NASDAQCOM 真实值
        "wti_oil": raw.get("WTI"),  # DCOILWTICO 真实值
    }

    return {
        "timestamp": ts,
        "data": data,
        "metrics": {"core": core, "breakdown": breakdown},
        "meta": {
            "last_update": ts,
            "source": ["data.dal_query"],
            "data_quality": (
                "good"
                if isinstance(raw.get("CPI"), (int, float))
                and isinstance(fed_rate_raw, (int, float))
                else "partial"
            ),
        },
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
        # 收口 P2: btc_basics 链上基础指标 (OnchainPanel)
        "hash_rate": raw.get("hash_rate"),
        "active_addresses": raw.get("active_addresses"),
        "tx_count_24h": raw.get("tx_count_24h"),
        "market_cap_usd": raw.get("market_cap_usd"),
        "total_btc": raw.get("total_btc"),
    }

    return {
        "timestamp": ts,
        "data": data,
        "metrics": {"core": core, "breakdown": {}},
        "meta": {"last_update": ts, "source": ["data.dal_query"], "data_quality": "good"},
    }


def _build_sentiment(sentiment_raw: dict, macro_raw: dict, ts: str) -> dict:
    """sentiment: 优先 DAL 真实 fear_greed (P1), 缺失时回退 VIX 派生。"""
    fg = sentiment_raw.get("crypto_fear_greed")
    source = ["data.dal_query"]
    quality = "good"
    if isinstance(fg, (int, float)):
        index = int(fg)
    else:
        vix = macro_raw.get("VIX")
        if isinstance(vix, (int, float)):
            index = max(0, min(100, int(100 - (vix - 15) * 5)))
        else:
            index = 50
        source = ["dollar_index.derive"]
        quality = "derived"
    classification = "贪婪" if index > 65 else "恐惧" if index < 35 else "中性"

    core = {
        "sentiment_index": index,
        "fear_greed_index": index,  # 收口 P2: SentimentPanel 字段名对齐
        "sentiment_classification": classification,
        "market_psychology": classification,  # 收口 P2: SentimentPanel 字段名对齐
        "sentiment_regime": "neutral",
        "social_volume": None,
    }

    return {
        "timestamp": ts,
        "data": {"crypto_fear_greed": {"value": index, "label": "加密恐惧贪婪"}},
        "metrics": {
            "core": core,
            "breakdown": {
                "fg_momentum": sentiment_raw.get("fg_momentum"),
                "fg_volatility": sentiment_raw.get("fg_volatility"),
                "fg_capital_flow": sentiment_raw.get("fg_capital_flow"),
                "fg_funding": sentiment_raw.get("fg_funding"),
            },
        },
        "meta": {"last_update": ts, "source": source, "data_quality": quality},
    }


def _build_flow(flow_raw: dict, ts: str) -> dict:
    """flow: DAL flow 命令真实数据 (P1)。"""
    core = {
        "etf_total_flow": flow_raw.get("etf_total_flow"),
        "fund_flow_score": None,
        "stablecoin_dominance_usdt": flow_raw.get("stablecoin_dominance_usdt"),
        "stablecoin_dominance_usdc": flow_raw.get("stablecoin_dominance_usdc"),  # 收口 P2
        "flow_regime": None,
    }
    has_real = any(isinstance(v, (int, float)) for v in core.values())
    return {
        "timestamp": ts,
        "data": {
            "etf_total_flow": {
                "value": flow_raw.get("etf_total_flow"),
                "label": "ETF 总净流入(百万美元)",
            },
            "usdt_circulating_bln": {
                "value": flow_raw.get("usdt_circulating_bln"),
                "label": "USDT 流通量(十亿)",
            },
            "usdc_circulating_bln": {
                "value": flow_raw.get("usdc_circulating_bln"),
                "label": "USDC 流通量(十亿)",
            },
        },
        "metrics": {
            "core": core,
            "breakdown": {
                # ETF 分发行商明细 (farside per-issuer, 百万美元)
                "etf_issuer_flows": {
                    k[4:]: flow_raw.get(k)
                    for k in (
                        "etf_ibit",
                        "etf_fbtc",
                        "etf_arkb",
                        "etf_gbtc",
                        "etf_btco",
                        "etf_bitb",
                        "etf_ezbc",
                        "etf_btcw",
                        "etf_brrr",
                        "etf_hodl",
                        "etf_msbt",
                        "etf_btc",
                    )
                    if isinstance(flow_raw.get(k), (int, float))
                },
            },
        },
        "meta": {
            "last_update": ts,
            "source": ["data.dal_query"] if has_real else [],
            "data_quality": "good" if has_real else "empty",
        },
    }


def _build_valuation(macro_raw: dict, chain_raw: dict, ts: str) -> dict:
    sp500 = macro_raw.get("SP500")
    gold = macro_raw.get("Gold")
    # 收口 P2: 优先 bgeometrics 真实 MVRV (DAL chain → btc_metrics/mvrv)
    real_mvrv = chain_raw.get("mvrv")
    mvrv = real_mvrv if isinstance(real_mvrv, (int, float)) else None
    valuation_zone = None
    if mvrv is not None:
        # 真实 MVRV 区间: >2 偏高, <1 低估
        if mvrv > 2:
            valuation_zone = "偏高"
        elif mvrv < 1:
            valuation_zone = "低估"
        else:
            valuation_zone = "合理"
    elif isinstance(sp500, (int, float)):
        # 回退: SP500 历史高位 >7500 偏高, <6500 低估
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
        "metrics": {
            "core": core,
            "breakdown": {
                "sopr": chain_raw.get("sopr"),  # bgeometrics 真实 SOPR (收口 P2)
                "nupl": chain_raw.get("nupl"),  # bgeometrics 真实 NUPL (收口 P2)
                "puell_multiple": chain_raw.get("puell_multiple"),  # bgeometrics 深度指标
                "realized_price": chain_raw.get("realized_price"),  # bgeometrics 深度指标
                "nvt_ratio": chain_raw.get("nvt_ratio"),  # bgeometrics 深度指标
            },
        },
        "meta": {
            "last_update": ts,
            "source": ["data.dal_query"],
            "data_quality": "good" if isinstance(real_mvrv, (int, float)) else "derived",
        },
    }


def _build_breadth(breadth_raw: dict, ts: str) -> dict:
    """breadth: DAL breadth 命令真实数据 (P1)。"""
    core = {
        "btc_dominance": breadth_raw.get("btc_dominance_pct"),  # panewslab overview_market 真实值
        "breadth_confirmation": None,
        "global_change_24h": None,
        "market_participation_index": None,
        "social_volume": breadth_raw.get("social_volume"),
        "news_count_24h": breadth_raw.get("news_count_24h"),
        "defi_tvl_bln": breadth_raw.get("defi_tvl_bln"),  # 收口 P2: DeFi TVL
    }
    has_real = any(isinstance(v, (int, float)) for v in core.values())
    return {
        "timestamp": ts,
        "data": {
            "usdt_bln": {"value": breadth_raw.get("usdt_bln"), "label": "USDT 市值(十亿)"},
            "usdc_bln": {"value": breadth_raw.get("usdc_bln"), "label": "USDC 市值(十亿)"},
            "social_volume": {"value": breadth_raw.get("social_volume"), "label": "社交讨论量"},
        },
        "metrics": {"core": core, "breakdown": {}},
        "meta": {
            "last_update": ts,
            "source": ["data.dal_query"] if has_real else [],
            "data_quality": "good" if has_real else "empty",
        },
    }


def _build_capital_flow(cf_raw: dict, ts: str) -> dict:
    """capital_flow: DAL capital_flow 命令真实数据 (P1)。"""
    core = {
        "long_short_ratio": cf_raw.get("long_short_ratio"),
        "long_account_pct": cf_raw.get("long_account_pct"),
        "funding_rate_pct": cf_raw.get("funding_rate_pct"),
        "funding_rate_annualized_pct": cf_raw.get("funding_rate_annualized_pct"),
        "open_interest_value": cf_raw.get("open_interest_value"),
        "open_interest_amount": cf_raw.get("open_interest_amount"),
    }
    has_real = any(isinstance(v, (int, float)) for v in core.values())
    return {
        "timestamp": ts,
        "data": {
            "long_short_ratio": {"value": cf_raw.get("long_short_ratio"), "label": "多空比"},
            "funding_rate_pct": {"value": cf_raw.get("funding_rate_pct"), "label": "资金费率%"},
            "open_interest_value": {
                "value": cf_raw.get("open_interest_value"),
                "label": "持仓量价值(USD)",
            },
        },
        "metrics": {"core": core, "breakdown": {}},
        "meta": {
            "last_update": ts,
            "source": ["data.dal_query"] if has_real else [],
            "data_quality": "good" if has_real else "empty",
        },
    }


def _build_intermarket(im_raw: dict, ts: str) -> dict:
    """intermarket: DAL intermarket 命令真实数据 (收口 P2: IntermarketPanel)。"""
    core = {
        "btc_price": im_raw.get("btc_price"),
        "dxy": im_raw.get("dxy"),
        "dxy_correlation": None,  # 待定义派生口径
        "risk_regime": None,  # 待定义派生口径
        "us10y_yield": im_raw.get("us10y_yield"),
        "spx_price": im_raw.get("spx_price"),
        "ndx": im_raw.get("ndx"),
        "vix": im_raw.get("vix"),
        "gold_price": im_raw.get("gold_price"),
        "wti": im_raw.get("wti"),
    }
    has_real = any(isinstance(v, (int, float)) for v in core.values())
    return {
        "timestamp": ts,
        "data": {
            "btc_price": {"value": im_raw.get("btc_price"), "label": "BTC 价格"},
            "dxy": {"value": im_raw.get("dxy"), "label": "美元指数"},
            "spx_price": {"value": im_raw.get("spx_price"), "label": "标普500"},
            "vix": {"value": im_raw.get("vix"), "label": "VIX"},
            "gold_price": {"value": im_raw.get("gold_price"), "label": "黄金"},
            "wti": {"value": im_raw.get("wti"), "label": "WTI 原油"},
        },
        "metrics": {"core": core, "breakdown": {}},
        "meta": {
            "last_update": ts,
            "source": ["data.dal_query"] if has_real else [],
            "data_quality": "good" if has_real else "empty",
        },
    }


def main():
    # ── 0. 初始化壳层 ────────────────────────────────────────────────
    core_dir = _resolve_34_core_dir()
    if os.path.isdir(core_dir) and core_dir not in sys.path:
        sys.path.insert(0, core_dir)

    # ── 1. 拉 macro + chain 原始数据 ─────────────────────────────────
    macro_raw = _fetch("data.dal_query", "macro")
    chain_raw = _fetch("data.dal_query", "chain")
    flow_raw = _fetch("data.dal_query", "flow")
    breadth_raw = _fetch("data.dal_query", "breadth")
    capital_flow_raw = _fetch("data.dal_query", "capital_flow")
    sentiment_raw = _fetch("data.dal_query", "sentiment")
    intermarket_raw = _fetch("data.dal_query", "intermarket")
    ts = macro_raw.get("timestamp") or chain_raw.get("timestamp")

    # ── 2. 构建各模块 (双轨 schema) ─────────────────────────────────
    modules = {
        "macro": _build_macro(macro_raw, ts),
        "onchain": _build_onchain(chain_raw, ts),
        "sentiment": _build_sentiment(sentiment_raw, macro_raw, ts),
        "valuation": _build_valuation(macro_raw, chain_raw, ts),
        "flow": _build_flow(flow_raw, ts),
        "breadth": _build_breadth(breadth_raw, ts),
        "capital_flow": _build_capital_flow(capital_flow_raw, ts),
        "intermarket": _build_intermarket(intermarket_raw, ts),
    }

    has_real = any(
        m.get("meta", {}).get("data_quality") in ("good", "partial") for m in modules.values()
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
