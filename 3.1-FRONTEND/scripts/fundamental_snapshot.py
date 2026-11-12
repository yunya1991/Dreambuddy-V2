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


def _clamp(v, lo, hi):
    """数值截断到 [lo, hi] 区间（计算规则移植自 9-基本面分析）。"""
    return max(lo, min(hi, v))


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
        "m2_supply": raw.get("m2_supply"),  # M2NS 真实值 (FRED)
        "ppi": raw.get("PPI"),  # PPIACO 真实值
        "industrial_production": raw.get("industrial_production"),  # INDPRO 真实值 (FRED)
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
    # 规则移植自 9-基本面分析 collect_onchain: 交易所余额 30 日变化 → 净流向/积累信号
    _chg30d = raw.get("ex_bal_btc_chg30d_pct")
    _ex_net_flow = round(-_chg30d * 10, 2) if isinstance(_chg30d, (int, float)) else None
    _acc_sig = (
        "积累"
        if isinstance(_ex_net_flow, (int, float)) and _ex_net_flow < -50
        else (
            "分发"
            if isinstance(_ex_net_flow, (int, float)) and _ex_net_flow > 50
            else "中性" if _ex_net_flow is not None else None
        )
    )
    network_health = "优秀" if isinstance(mempool, (int, float)) and mempool > 50000 else "良好"

    core = {
        "onchain_trend": onchain_trend,
        "accumulation_signal": _acc_sig,  # 规则移植自 9-基本面分析: 交易所余额30日变化判定
        "exchange_net_flow": _ex_net_flow,  # 规则移植自 9-基本面分析: -chg30d*10
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
        "metrics": {
            "core": core,
            "breakdown": {
                # P0 修复: UTXO 年龄分布 (DAL utxo_age_distribution 真实值)
                # OnchainPanel 用 hodl_waves_1y_plus / short_term_holder_supply 计算长中短期占比
                "hodl_waves_1y_plus": raw.get("hodl_waves_1y_plus_pct"),
                "long_term_holder_supply": raw.get("lth_supply_pct"),
                "mid_term_holder_supply": raw.get("mth_supply_pct"),
                "short_term_holder_supply": raw.get("sth_supply_pct"),
                "profit_supply": raw.get("profit_supply_pct"),
                "utxo_count": raw.get("utxo_count"),
            },
        },
        "meta": {"last_update": ts, "source": ["data.dal_query"], "data_quality": "good"},
    }


def _build_heatmap(
    sentiment_raw: dict,
    macro_raw: dict,
    flow_raw: dict,
    breadth_raw: dict,
    index: int,
) -> list:
    """P1: 情绪热力图 (指标 × 0-100 分), 每个 cell 仅由真实 DAL 指标派生, 无 mock。

    规则移植 9-基本面分析 dal_snapshot_provider.collect_sentiment 的 5 cell,
    并补充 OKX 多空比 / 市场 24h 动量 / VIX 三个跨市场维度。
    """
    cells = []

    def _add(name, score):
        if isinstance(score, (int, float)):
            cells.append({"category": name, "score": round(_clamp(float(score), 0.0, 100.0), 1)})

    _add("贪婪恐惧", index)

    # 增强 F&G 四子维度 (crypto.feargreedchart.com, 0-100 原始分)
    _add("波动率", sentiment_raw.get("fg_volatility"))
    _add("动量", sentiment_raw.get("fg_momentum"))
    _add("资金费率", sentiment_raw.get("fg_funding"))
    _add("资金流向", sentiment_raw.get("fg_capital_flow"))

    # 多空比 (OKX 优先): 1.0 中性, 每 0.1 偏离 ±1 分
    _ls = flow_raw.get("long_short_ratio_okx")
    if not isinstance(_ls, (int, float)):
        _ls = flow_raw.get("long_short_ratio")
    if isinstance(_ls, (int, float)):
        _add("多空比", 50 + (_ls - 1.0) * 10)

    # 加密市场 24h 动量 (panewslab global_change24_pct): ±5% 对应 ±25 分
    _chg = breadth_raw.get("global_change_24h")
    if isinstance(_chg, (int, float)):
        _add("市场动量", 50 + _chg * 5)

    # VIX (跨市场风险偏好): 20 中性, 每 +1 点风险偏好 -3 分
    _vix = macro_raw.get("VIX")
    if isinstance(_vix, (int, float)):
        _add("VIX", 50 - (_vix - 20) * 3)

    return cells


def _build_sentiment(
    sentiment_raw: dict, macro_raw: dict, flow_raw: dict, breadth_raw: dict, ts: str
) -> dict:
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
        "sentiment_regime": classification,  # P1: 由真实 F&G 派生, 不再硬编码 neutral
        "social_volume": sentiment_raw.get("social_volume"),  # social_volume 真实值
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
        "heatmap_data": _build_heatmap(sentiment_raw, macro_raw, flow_raw, breadth_raw, index),
        "meta": {"last_update": ts, "source": source, "data_quality": quality},
    }


def _build_flow(flow_raw: dict, ts: str) -> dict:
    """flow: DAL flow 命令真实数据 (P1)。"""
    _etf_flow = flow_raw.get("etf_total_flow")
    _ffs = (
        round(_clamp(_etf_flow / 1000.0, -1.0, 1.0), 4)
        if isinstance(_etf_flow, (int, float))
        else None
    )

    # P0: 资金费率 / 多空比 / 鲸鱼 / 清算 (OKX 优先, Binance/panewslab 回退)
    _funding_pct = flow_raw.get("funding_rate_pct_okx")
    _funding_src = "okx"
    if not isinstance(_funding_pct, (int, float)):
        _funding_pct = flow_raw.get("funding_rate_pct")
        _funding_src = "binance" if isinstance(_funding_pct, (int, float)) else None
    # 前端展示时 *100, 故这里传小数 (DAL 存储为百分数)
    _funding_rate = (
        round(_funding_pct / 100.0, 8) if isinstance(_funding_pct, (int, float)) else None
    )

    _ls_ratio = flow_raw.get("long_short_ratio_okx")
    if not isinstance(_ls_ratio, (int, float)):
        _ls_ratio = flow_raw.get("long_short_ratio")

    _whale_netflow = flow_raw.get("whale_netflow_to_ex_usd")
    _whale_activity = (
        round(_clamp(abs(_whale_netflow) / 1e8, 0.0, 100.0), 2)
        if isinstance(_whale_netflow, (int, float))
        else None
    )
    _liq_total = flow_raw.get("liquidations_24h_usd")
    _liq_pressure = (
        round(_clamp(_liq_total / 1e9 * 20.0, 0.0, 100.0), 2)
        if isinstance(_liq_total, (int, float))
        else None
    )
    # 规则移植自 9-基本面分析: 鲸鱼净流出交易所(负值)加分
    _smart_score = (_ffs or 0.0) + (
        0.2 if isinstance(_whale_netflow, (int, float)) and _whale_netflow < 0 else 0.0
    )
    _smart_score = round(_clamp(_smart_score, -1.0, 1.0), 4)

    core = {
        "etf_total_flow": _etf_flow,
        "fund_flow_score": _ffs,  # 规则移植自 9-基本面分析: ETF净流入/1000 截断 [-1,1]
        "stablecoin_dominance_usdt": flow_raw.get("stablecoin_dominance_usdt"),
        "stablecoin_dominance_usdc": flow_raw.get("stablecoin_dominance_usdc"),  # 收口 P2
        "flow_regime": (  # 规则移植自 9-基本面分析: ±50M 判定
            "流入"
            if isinstance(_etf_flow, (int, float)) and _etf_flow > 50
            else "流出" if isinstance(_etf_flow, (int, float)) and _etf_flow < -50 else "中性"
        ),
        "funding_rate": _funding_rate,
        "funding_rate_source": _funding_src,
        "long_short_ratio": _ls_ratio,
        "whale_activity": _whale_activity,
        "liquidation_pressure": _liq_pressure,
        "smart_money_direction": (
            "增持" if _smart_score > 0.15 else "减持" if _smart_score < -0.15 else "观望"
        ),
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
            "funding_rate_pct": {"value": _funding_pct, "label": "资金费率(%)"},
            "long_short_ratio": {"value": _ls_ratio, "label": "多空比"},
            "whale_netflow_to_ex_usd": {
                "value": _whale_netflow,
                "label": "鲸鱼净流入交易所(美元)",
            },
            "liquidations_24h_usd": {"value": _liq_total, "label": "24h 清算额(美元)"},
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
                # P0: 衍生品 / 鲸鱼明细
                "funding_rate_pct": _funding_pct,
                "long_short_ratio": _ls_ratio,
                "whale_netflow_to_ex_usd": _whale_netflow,
                "liquidations_24h_usd": _liq_total,
                "liquidations_long_24h_usd": flow_raw.get("liquidations_long_24h_usd"),
                "liquidations_short_24h_usd": flow_raw.get("liquidations_short_24h_usd"),
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
    # P0 修复: NVT 比率与 Z 分数分列 (此前把比率误写入 z_score)
    _nvt_ratio = chain_raw.get("nvt_ratio")
    _nvt_z = (
        round(_clamp((_nvt_ratio - 20.0) / 15.0, -3.0, 3.0), 2)
        if isinstance(_nvt_ratio, (int, float)) and 5 <= _nvt_ratio <= 100
        else None
    )
    core = {
        "mvrv_ratio": mvrv,
        "nvt_ratio": _nvt_ratio,
        "nvt_z_score": _nvt_z,
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
    _gchg = breadth_raw.get("global_change_24h")
    _adl = round(_clamp(_gchg * 10, -60, 70), 2) if isinstance(_gchg, (int, float)) else None
    core = {
        "btc_dominance": breadth_raw.get("btc_dominance_pct"),  # panewslab overview_market 真实值
        "breadth_confirmation": (  # 规则移植自 9-基本面分析: 广度线判定
            "确认趋势"
            if _adl is not None and _adl > 30
            else (
                "存在分歧"
                if _adl is not None and _adl > 0
                else "广度恶化" if _adl is not None else None
            )
        ),
        "global_change_24h": _gchg,
        "market_participation_index": (  # 规则移植自 9-基本面分析: 50 + ADL*0.3
            round(_clamp(50 + _adl * 0.3, 0, 100), 2) if _adl is not None else None
        ),
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
        "dxy_correlation": (  # 规则移植自 9-基本面分析: DXY 线性插值
            round(_clamp(-(im_raw.get("dxy") - 102.0) / 5.0, -1.0, 1.0), 4)
            if isinstance(im_raw.get("dxy"), (int, float))
            else None
        ),
        "risk_regime": (  # 规则移植自 9-基本面分析: SPX/黄金上涨 + VIX<20
            (
                "risk_on"
                if isinstance(im_raw.get("spx_price"), (int, float))
                and isinstance(im_raw.get("gold_price"), (int, float))
                and isinstance(im_raw.get("vix"), (int, float))
                and im_raw.get("spx_price") > 0
                and im_raw.get("gold_price") > 0
                and im_raw.get("vix") < 20
                else "risk_off"
            )
            if isinstance(im_raw.get("spx_price"), (int, float))
            else None
        ),
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


def _build_news(news_raw: dict, ts: str) -> dict:
    """news: 新闻监控 (DAL newsflash 情绪分布 + 39 层语义事件统计, 移植 9 层 collect_news)."""
    news_count = news_raw.get("news_count_24h") or 0
    social_volume = news_raw.get("social_volume") or 0
    pos = news_raw.get("positive_count") or 0
    neg = news_raw.get("negative_count") or 0
    neu = news_raw.get("neutral_count") or 0
    total = pos + neg + neu
    has_real = bool(news_count or social_volume or total)
    # 39 层语义事件统计 (24h 事件数 + 主题分布)
    sem_count = 0
    sem_themes = {}
    try:
        import json as _json
        from datetime import datetime as _dt
        from datetime import timedelta as _td
        from datetime import timezone as _tz

        p39 = os.environ.get("SEMANTIC_EVENTS_PATH") or os.path.join(
            os.path.dirname(_resolve_34_core_dir()),
            "..",
            "39-金融语义蒸馏系统",
            "semantic_events.jsonl",
        )
        p39 = os.path.normpath(p39)
        cutoff = _dt.now(_tz.utc) - _td(hours=24)
        with open(p39, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                try:
                    ev = _json.loads(line)
                except Exception:
                    continue
                try:
                    evt = _dt.fromisoformat(ev.get("timestamp", ""))
                except Exception:
                    continue
                if evt.tzinfo is None:
                    evt = evt.replace(tzinfo=_tz.utc)
                if evt >= cutoff:
                    sem_count += 1
                    theme = ev.get("term") or "other"
                    sem_themes[theme] = sem_themes.get(theme, 0) + 1
    except Exception:
        pass
    top_themes = dict(sorted(sem_themes.items(), key=lambda x: -x[1])[:5])
    t = total or 1
    avg_s = news_raw.get("avg_sentiment")
    if not isinstance(avg_s, (int, float)):
        avg_s = 0.5
    core = {
        "total_articles": int(news_count),
        "positive_count": pos,
        "negative_count": neg,
        "neutral_count": neu,
        "sentiment": round(float(avg_s), 3),
        "avg_sentiment": round(float(avg_s), 3),
        "high_impact_count": news_raw.get("high_impact_count") or 0,
        "positive_ratio": round(pos / t, 3),
        "negative_ratio": round(neg / t, 3),
        "neutral_ratio": round(neu / t, 3),
        "sentiment_score": round((pos - neg) / t, 3),
        "semantic_events_24h": sem_count,
    }
    return {
        "timestamp": ts,
        "data": {"news_count_24h": {"value": news_count, "label": "24h 新闻数"}},
        "metrics": {
            "core": core,
            "breakdown": {
                "social_volume": social_volume,
                "total_news_records": news_raw.get("total_news_records"),
                "semantic_top_themes": top_themes,
            },
        },
        "meta": {
            "last_update": ts,
            "source": ["data.dal_query", "semantic_distill"],
            "data_quality": "good" if has_real else "empty",
        },
    }


def _build_narrative(narrative_raw: dict, ts: str) -> dict:
    """narrative: 市场叙事 (fear_greed_enhanced 四子维度, 移植 9 层 collect_narrative)."""
    fg = narrative_raw.get("fg_value")
    subs = {
        "capital_flow": narrative_raw.get("capital_flow"),
        "funding": narrative_raw.get("funding"),
        "momentum": narrative_raw.get("momentum"),
        "volatility": narrative_raw.get("volatility"),
    }
    has_real = isinstance(fg, (int, float)) or any(
        isinstance(v, (int, float)) for v in subs.values()
    )
    fg_val = fg if isinstance(fg, (int, float)) else 50.0
    sm = {k: (v if isinstance(v, (int, float)) else 50.0) for k, v in subs.items()}
    bullish = sum(1 for v in sm.values() if v > 60)
    bearish = sum(1 for v in sm.values() if v < 40)
    neutral = 4 - bullish - bearish
    avg_sentiment = sum(v / 100.0 for v in sm.values()) / 4
    consensus = (fg_val / 100.0 + avg_sentiment) / 2
    narratives = []
    for name, val in sm.items():
        if val > 60:
            narratives.append({"theme": name, "sentiment": "bullish", "score": val})
        elif val < 40:
            narratives.append({"theme": name, "sentiment": "bearish", "score": val})
        else:
            narratives.append({"theme": name, "sentiment": "neutral", "score": val})
    core = {
        "total_narratives": 4,
        "bullish_narratives": bullish,
        "bearish_narratives": bearish,
        "neutral_narratives": neutral,
        "avg_sentiment": round(avg_sentiment, 3),
        "avg_momentum": round(sm["momentum"], 1),
        "consensus": round(consensus, 3),
        "market_consensus": round(consensus, 3),
    }
    return {
        "timestamp": ts,
        "data": {"fear_greed": {"value": fg_val, "label": "恐惧贪婪指数"}},
        "metrics": {
            "core": core,
            "breakdown": {n["theme"]: n["score"] for n in narratives},
        },
        "events": [
            {
                "title": "恐惧贪婪指数 %.0f，%d 项看多 %d 项看空" % (fg_val, bullish, bearish),
                "ts": ts,
            }
        ],
        "meta": {
            "last_update": ts,
            "source": ["data.dal_query"],
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
    news_raw = _fetch("data.dal_query", "news")
    narrative_raw = _fetch("data.dal_query", "narrative")
    intermarket_raw = _fetch("data.dal_query", "intermarket")
    ts = macro_raw.get("timestamp") or chain_raw.get("timestamp")

    # ── 2. 构建各模块 (双轨 schema) ─────────────────────────────────
    modules = {
        "macro": _build_macro(macro_raw, ts),
        "onchain": _build_onchain(chain_raw, ts),
        "sentiment": _build_sentiment(sentiment_raw, macro_raw, flow_raw, breadth_raw, ts),
        "valuation": _build_valuation(macro_raw, chain_raw, ts),
        "flow": _build_flow(flow_raw, ts),
        "breadth": _build_breadth(breadth_raw, ts),
        "capital_flow": _build_capital_flow(capital_flow_raw, ts),
        "intermarket": _build_intermarket(intermarket_raw, ts),
        "news": _build_news(news_raw, ts),
        "narrative": _build_narrative(narrative_raw, ts),
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
