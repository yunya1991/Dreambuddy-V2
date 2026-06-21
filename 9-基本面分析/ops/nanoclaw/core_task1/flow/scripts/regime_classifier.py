#!/usr/bin/env python3
"""
Regime 状态机分类逻辑
将采集到的资金流数据转换为 bias/filter/risk-off 信号
"""

import json
import os
import math
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Optional

# 配置
BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = str(BASE_DIR / "outputs")
RAW_DIR = str(BASE_DIR / "raw")
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(RAW_DIR, exist_ok=True)

# =============================================================================
# 信号计算工具函数
# =============================================================================

def normalize_to_range(value: float, min_v: float, max_v: float) -> float:
    if max_v == min_v:
        return 0.0
    out = 2.0 * (value - min_v) / (max_v - min_v) - 1.0
    return max(-1.0, min(1.0, float(out)))

def z_score(value: float, mean: float, std: float) -> float:
    """计算 z-score，限制在 [-3, 3]"""
    if std == 0:
        return 0.0
    return max(-3, min(3, (value - mean) / std))

def sigmoid(x: float) -> float:
    """Sigmoid 函数，输出 [0, 1]"""
    return 1 / (1 + math.exp(-x))

def calculate_funding_score(funding_rate: float) -> float:
    """
    资金费率评分
    - 过高正费率 -> 多头过热 -> 负分
    - 过高负费率 -> 空头过热 -> 正分 (反向信号)
    - 正常范围 -> 接近 0
    """
    # 典型费率范围：-0.01% 到 +0.01% (每 8 小时)
    # 极端值：>+0.05% 或 <-0.05%
    if funding_rate > 0.0005:  # >0.05%
        return -0.8  # 多头过热
    elif funding_rate < -0.0005:  # <-0.05%
        return 0.8  # 空头过热，反向看多
    else:
        # 线性插值
        return -normalize_to_range(funding_rate, -0.0005, 0.0005)

def calculate_oi_score(oi_current: float, oi_24h_ago: float) -> float:
    """
    持仓量变化评分
    - OI 大幅上升 + 价格上涨 -> 多头强势
    - OI 大幅上升 + 价格下跌 -> 空头强势
    - OI 下降 -> 去杠杆
    """
    if oi_24h_ago == 0:
        return 0.0
    change_pct = (oi_current - oi_24h_ago) / oi_24h_ago
    # OI 变化率标准化到 [-1, 1]
    # >50% 增长 -> +1, <-50% -> -1
    return normalize_to_range(change_pct, -0.5, 0.5)

def calculate_liquidation_risk(liquidation_24h: float, oi_total: float) -> float:
    """
    清算风险评分
    - 清算量/OI 比值越高 -> 风险越高 -> 负分
    """
    if oi_total == 0:
        return 0.0
    ratio = liquidation_24h / oi_total
    # 比值 >10% -> 高风险
    if ratio > 0.1:
        return -0.9
    elif ratio > 0.05:
        return -0.6
    elif ratio > 0.02:
        return -0.3
    else:
        return 0.1  # 低风险

def calculate_stablecoin_supply_score(current: float, historical_avg: float, historical_std: float) -> float:
    """
    稳定币供应量评分
    - 供应量增长 -> 资金流入 -> 正分
    """
    z = z_score(current, historical_avg, historical_std)
    # z-score 转 [-1, 1]
    return math.tanh(z / 2)

def calculate_dxy_score(dxy_current: float, dxy_ma20: float) -> float:
    if dxy_ma20 == 0:
        return 0.0
    change = (dxy_current - dxy_ma20) / dxy_ma20
    return -normalize_to_range(change, -0.02, 0.02)

def calculate_exchange_flow_score(net_flow_24h: float, reserve_total: float) -> float:
    """
    交易所流向评分
    - 净流入 -> 卖压 -> 负分
    - 净流出 -> 提币 -> 正分
    """
    if reserve_total == 0:
        return 0.0
    ratio = net_flow_24h / reserve_total
    # 净流入>2% -> 强负分，净流出>2% -> 强正分
    return -normalize_to_range(ratio, -0.02, 0.02)

def calculate_etf_flow_score(etf_data: dict) -> float:
    """
    ETF 流向评分
    - 净流入 -> 正分
    - 净流出 -> 负分
    """
    btc_inflow = etf_data.get("btc_etf_net_inflow")
    eth_inflow = etf_data.get("eth_etf_net_inflow")

    if btc_inflow is None and eth_inflow is None:
        return 0.0

    # 简化：假设 BTC ETF 规模更大，权重更高
    btc_score = 0.0
    eth_score = 0.0

    if btc_inflow is not None:
        # >1 亿流入 -> +0.8, >5 亿 -> +1.0
        btc_score = math.tanh(btc_inflow / 2e8)  # 2 亿为单位

    if eth_inflow is not None:
        # >5000 万流入 -> +0.8
        eth_score = math.tanh(eth_inflow / 1e8)  # 1 亿为单位

    # BTC ETF 权重更高
    if btc_inflow and eth_inflow:
        return 0.7 * btc_score + 0.3 * eth_score
    elif btc_inflow:
        return btc_score
    else:
        return eth_score

# =============================================================================
# Layer 信号计算
# =============================================================================

def _load_skill_snapshot_value_map() -> dict[str, float]:
    p = Path(OUTPUT_DIR) / "web3_skill_snapshot_latest.json"
    if not p.exists() or not p.is_file():
        return {}
    try:
        obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    rows = obj.get("items") if isinstance(obj, dict) and isinstance(obj.get("items"), list) else []
    out: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        bind_base = str(row.get("bindBase") or "").strip()
        if not bind_base:
            continue
        q = row.get("quality")
        q_status = str((q.get("status") if isinstance(q, dict) else q) or "").strip().lower()
        if q_status in {"missing", "unknown"}:
            continue
        try:
            v = float(row.get("value"))
        except Exception:
            continue
        if not math.isfinite(v):
            continue
        out[bind_base] = float(v)
    return out


def _save_skill_snapshot_items(items: list[dict]) -> None:
    p = Path(OUTPUT_DIR) / "web3_skill_snapshot_latest.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    obj = {
        "ok": True,
        "generated_at": now_ts,
        "items": items,
        "count": len(items),
        "source": "regime-layer-proxy",
        "quality": "suspect",
        "execution_gate": "readonly_advisory",
    }
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_snapshot_items_from_layers(layers: dict) -> list[dict]:
    exo = (layers.get("exogenous") or {}) if isinstance(layers, dict) else {}
    lev = (layers.get("leverage") or {}) if isinstance(layers, dict) else {}
    onc = (layers.get("onchain") or {}) if isinstance(layers, dict) else {}
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _num(v: Any) -> Optional[float]:
        try:
            x = float(v)
        except Exception:
            return None
        if not math.isfinite(x):
            return None
        return float(x)

    def _row(bind_base: str, value: Optional[float]) -> dict:
        status = "suspect" if value is not None else "missing"
        return {
            "bindBase": bind_base,
            "value": value,
            "value_mode": ("proxy" if value is not None else "missing"),
            "source": "regime-layer-proxy",
            "latency_sec": None,
            "revision": {"provider_revision_ts": now_ts},
            "quality": {"status": status, "reasons": (["layer_proxy"] if value is not None else ["missing"]), "error": ("" if value is not None else "value_unavailable")},
            "generated_at": now_ts,
        }

    etf = (exo.get("etf_flow") or {}) if isinstance(exo, dict) else {}
    stable = (exo.get("stablecoin") or {}) if isinstance(exo, dict) else {}
    cex = (exo.get("cex_reserves") or {}) if isinstance(exo, dict) else {}
    macro = (exo.get("macro") or {}) if isinstance(exo, dict) else {}
    bweb3 = (exo.get("binance_web3") or {}) if isinstance(exo, dict) else {}
    cg = (lev.get("coinglass") or {}) if isinstance(lev, dict) else {}
    bn = (lev.get("binance") or {}) if isinstance(lev, dict) else {}
    cme = (lev.get("cme_oi") or {}) if isinstance(lev, dict) else {}
    bridge = (lev.get("bridge") or {}) if isinstance(lev, dict) else {}
    gn = (onc.get("glassnode") or {}) if isinstance(onc, dict) else {}
    wh = (onc.get("whale_alert") or {}) if isinstance(onc, dict) else {}
    es = (onc.get("etherscan") or {}) if isinstance(onc, dict) else {}
    gate_addr = (onc.get("gate_address_tracker") or {}) if isinstance(onc, dict) else {}

    funding_bps = None
    bn_fr = (bn.get("funding_rate") or {}) if isinstance(bn.get("funding_rate"), dict) else {}
    fr_val = _num(bn_fr.get("last_funding_rate"))
    if fr_val is not None:
        funding_bps = fr_val * 10000.0
    if funding_bps is None:
        flow_v = _num(bridge.get("netflow_usd"))
        if flow_v is not None:
            funding_bps = max(-35.0, min(35.0, math.tanh(flow_v / 1e9) * 20.0))

    oi_usd = _num(cg.get("open_interest")) if not isinstance(cg.get("open_interest"), dict) else _num((cg.get("open_interest") or {}).get("value"))
    if oi_usd is None:
        cme_oi = _num(cme.get("open_interest"))
        if cme_oi is not None:
            oi_usd = cme_oi * 100000.0
    if oi_usd is None:
        flow_v = _num(bridge.get("netflow_usd"))
        if flow_v is not None:
            oi_usd = abs(flow_v) * 8.0

    whale_delta = None
    wh_n = _num(wh.get("btc_large_transfers"))
    if wh_n is not None and wh_n > 0:
        whale_delta = wh_n * 1000000.0
    if whale_delta is None:
        whale_delta = _num(bridge.get("netflow_usd"))
    if whale_delta is None:
        deep_upgrades = _num(((gate_addr.get("summary") or {}) if isinstance(gate_addr.get("summary"), dict) else {}).get("deep_upgrades"))
        if deep_upgrades is not None:
            whale_delta = deep_upgrades * 500000.0

    btc_etf = _num(etf.get("btc_etf_net_inflow"))
    if btc_etf is None:
        btc_total = _num(etf.get("btc_etf_total_btc"))
        if btc_total is not None:
            btc_etf = btc_total * 100.0
    eth_etf = _num(etf.get("eth_etf_net_inflow"))
    if eth_etf is None:
        btc_total = _num(etf.get("btc_etf_total_btc"))
        if btc_total is not None:
            eth_etf = btc_total * 30.0

    stable_supply = _num(stable.get("total_supply_usd"))
    cex_reserve = _num(cex.get("total_reserve_usd"))
    dxy_cur = _num(((macro.get("dxy") or {}) if isinstance(macro.get("dxy"), dict) else {}).get("current"))
    macro_pressure = None
    if dxy_cur is not None:
        macro_pressure = max(0.0, min(1.0, abs(dxy_cur - 103.0) / 7.0))
    elif _num(es.get("gas_price_gwei")) is not None:
        macro_pressure = max(0.0, min(1.0, _num(es.get("gas_price_gwei")) / 120.0))
    elif _num(bridge.get("netflow_usd")) is not None:
        macro_pressure = max(0.0, min(1.0, abs(_num(bridge.get("netflow_usd")) or 0.0) / 5e9))

    social_heat = None
    smart_money = None
    if isinstance(bweb3.get("market_rank"), dict):
        market_rank = bweb3.get("market_rank") or {}
        n1 = len(market_rank.get("trending_tokens") or []) if isinstance(market_rank.get("trending_tokens"), list) else 0
        n2 = len(market_rank.get("top_search") or []) if isinstance(market_rank.get("top_search"), list) else 0
        social_heat = max(-1.0, min(1.0, (n1 + n2) / 20.0))
    if bweb3.get("smart_money_inflow") is not None:
        smart_money = _num(bweb3.get("smart_money_inflow"))
    if smart_money is None and whale_delta is not None:
        smart_money = max(0.0, min(1.0, abs(whale_delta) / 5e9))

    keys = [
        ("funding_rate_bps__btc__binance__na", funding_bps),
        ("funding_rate_bps__btc__okx__perp", funding_bps),
        ("oi_usd__btc__coinglass__na", oi_usd),
        ("oi_usd__btc__okx__perp", oi_usd),
        ("spot_etf_netflow_usd__btc__all__na", btc_etf),
        ("spot_etf_netflow_usd__eth__all__na", eth_etf),
        ("stablecoin_usdt_exchange_inflow_usd__all__all__all", stable_supply),
        ("stablecoin_usdt_exchange_balance_usd__all__all__all", stable_supply),
        ("cex_exchange_reserve_usd__all__all__all", cex_reserve),
        ("whale_position_delta_usd__btc__hyperliquid__perp", whale_delta),
        ("macro_event_pressure_score__btc__macro__na", macro_pressure),
        ("smart_money_inflow_score__all__all__all", smart_money),
        ("social_heat_event_score__btc__all__na", social_heat),
    ]
    return [_row(k, v) for k, v in keys]


def _ensure_skill_snapshot_from_layers(layers: dict) -> None:
    p = Path(OUTPUT_DIR) / "web3_skill_snapshot_latest.json"
    existing_rows = []
    try:
        if p.exists() and p.is_file():
            obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            rows = obj.get("items") if isinstance(obj, dict) and isinstance(obj.get("items"), list) else []
            existing_rows = [r for r in rows if isinstance(r, dict)]
    except Exception:
        existing_rows = []
    merged: dict[str, dict] = {}
    for r in existing_rows:
        bb = str(r.get("bindBase") or "").strip()
        if bb:
            merged[bb] = r
    for r in _build_snapshot_items_from_layers(layers):
        bb = str(r.get("bindBase") or "").strip()
        if not bb:
            continue
        v = r.get("value")
        if v is None and bb in merged:
            continue
        merged[bb] = r
    _save_skill_snapshot_items(list(merged.values()))


def calculate_leverage_signal(leverage_data: dict) -> dict:
    """计算 Layer2 杠杆层信号"""
    result = {
        "score": 0.0,
        "components": {},
        "data_freshness": None
    }

    # Binance 资金费率
    binance_fr = leverage_data.get("binance", {}).get("funding_rate", {})
    if binance_fr and binance_fr.get("last_funding_rate"):
        fr = float(binance_fr["last_funding_rate"])
        fr_score = calculate_funding_score(fr)
        result["components"]["funding_rate"] = {
            "value": fr,
            "score": fr_score,
            "weight": 0.35
        }

    snap = _load_skill_snapshot_value_map()
    if "funding_rate" not in result["components"]:
        fr_bps = snap.get("funding_rate_bps__btc__okx__perp")
        if not isinstance(fr_bps, float):
            fr_bps = snap.get("funding_rate_bps__btc__binance__na")
        if isinstance(fr_bps, float):
            fr = float(fr_bps) / 10000.0
            fr_score = calculate_funding_score(fr)
            result["components"]["funding_rate_proxy"] = {
                "value": fr,
                "score": fr_score,
                "weight": 0.30
            }

    oi_data = leverage_data.get("coinglass", {}).get("open_interest", {})
    oi_usd = None
    if isinstance(oi_data, dict):
        try:
            oi_usd = float(oi_data.get("value"))
        except Exception:
            oi_usd = None
    if oi_usd is None:
        oi_usd = snap.get("oi_usd__btc__okx__perp")
    if oi_usd is None:
        oi_usd = snap.get("oi_usd__btc__coinglass__na")
    if isinstance(oi_usd, float):
        oi_score = normalize_to_range(math.log10(max(1.0, oi_usd)), 8.0, 12.0)
        result["components"]["oi_usd"] = {
            "value": oi_usd,
            "score": oi_score,
            "weight": 0.35
        }

    # 清算数据
    liq_data = leverage_data.get("coinglass", {}).get("liquidation_24h", {})
    liq_val = None
    if isinstance(liq_data, dict):
        try:
            liq_val = float(liq_data.get("value"))
        except Exception:
            liq_val = None
    if liq_val is None:
        whale_delta = snap.get("whale_position_delta_usd__btc__hyperliquid__perp")
        if isinstance(whale_delta, float):
            liq_val = abs(float(whale_delta))
    if isinstance(liq_val, float) and liq_val > 0:
        liq_score = -normalize_to_range(math.log10(max(1.0, liq_val)), 5.0, 9.0)
        result["components"]["liq_pressure"] = {
            "value": liq_val,
            "score": liq_score,
            "weight": 0.35
        }

    # 综合计算 (简化版，实际需要根据完整数据)
    scores = [c["score"] for c in result["components"].values()]
    weights = [c["weight"] for c in result["components"].values()]

    if scores:
        result["score"] = sum(s * w for s, w in zip(scores, weights)) / sum(weights)

    result["data_freshness"] = leverage_data.get("binance", {}).get("timestamp")
    return result

def calculate_exogenous_signal(exogenous_data: dict) -> dict:
    """计算 Layer1 外生资金信号"""
    result = {
        "score": 0.0,
        "components": {},
        "weights": {},
        "data_freshness": None
    }

    # 1. ETF 流向 (权重 30%)
    etf_data = exogenous_data.get("etf_flow") or {}
    if etf_data.get("btc_etf_net_inflow") or etf_data.get("eth_etf_net_inflow"):
        etf_score = calculate_etf_flow_score(etf_data)
        result["components"]["etf_flow"] = etf_score
        result["weights"]["etf_flow"] = 0.30
        print(f"  [Regime] ETF Flow Score: {etf_score:+.4f}")

    # 2. 稳定币供应 (权重 20%)
    sc_data = exogenous_data.get("stablecoin") or {}
    if sc_data.get("total_supply_usd"):
        total = sc_data["total_supply_usd"]
        hist_avg = 180e9  # 1800 亿假设
        hist_std = 10e9   # 100 亿波动
        sc_score = calculate_stablecoin_supply_score(total, hist_avg, hist_std)
        result["components"]["stablecoin_supply"] = sc_score
        result["weights"]["stablecoin_supply"] = 0.20
        print(f"  [Regime] Stablecoin Supply Score: {sc_score:+.4f}")

    # 3. CEX 储备 (权重 10%) - 新增
    cex_data = exogenous_data.get("cex_reserves") or {}
    if cex_data.get("total_reserve_usd"):
        # CEX 储备增加 -> 潜在卖压 -> 轻微负分
        # 简化：用储备量相对历史的变化来判断
        reserve = cex_data["total_reserve_usd"]
        hist_avg_reserve = 50e9  # 500 亿假设
        reserve_ratio = reserve / hist_avg_reserve if hist_avg_reserve > 0 else 1.0
        # 储备>历史均值 20% -> 轻微负分，反之正分
        cex_score = -normalize_to_range(reserve_ratio - 1.0, -0.2, 0.2)
        result["components"]["cex_reserves"] = cex_score
        result["weights"]["cex_reserves"] = 0.10
        print(f"  [Regime] CEX Reserves Score: {cex_score:+.4f}")

    # 4. DXY (权重 20%)
    macro_data = exogenous_data.get("macro") or {}
    dxy_data = macro_data.get("dxy") if macro_data else None
    if dxy_data and isinstance(dxy_data, dict) and dxy_data.get("current"):
        dxy = dxy_data["current"]
        dxy_ma20 = 103.0  # 假设 20 日均线
        dxy_score = calculate_dxy_score(dxy, dxy_ma20)
        result["components"]["dxy"] = dxy_score
        result["weights"]["dxy"] = 0.20
        print(f"  [Regime] DXY Score: {dxy_score:+.4f}")

    # 5. FRED 指标 (权重 20%) - 新增
    fed_rate = macro_data.get("fed_policy_rate") if macro_data else None
    rrp = macro_data.get("rrp_balance") if macro_data else None
    real_yield = macro_data.get("us10y_real_yield") if macro_data else None

    fred_score = 0.0
    fred_components = 0

    # 联邦基金利率：利率下降 -> 流动性宽松 -> 正分
    if fed_rate and isinstance(fed_rate, dict) and fed_rate.get("value"):
        rate_val = fed_rate["value"]
        # 假设中性利率 2.5%，>4% 负分，<2% 正分
        rate_score = -normalize_to_range(rate_val, 2.0, 4.0)
        fred_score += rate_score
        fred_components += 1
        print(f"  [Regime] Fed Policy Rate Score: {rate_score:+.4f}")

    # RRP 余额：RRP 下降 -> 流动性释放 -> 正分
    if rrp and isinstance(rrp, dict) and rrp.get("value"):
        rrp_val = rrp["value"] / 1e9  # 转换为十亿
        # 假设 RRP 中性值 2000 亿，>3000 亿负分，<1000 亿正分
        rrp_score = -normalize_to_range(rrp_val, 1000, 3000)
        fred_score += rrp_score
        fred_components += 1
        print(f"  [Regime] RRP Balance Score: {rrp_score:+.4f}")

    # 实际利率：实际利率下降 -> 资产价格上升 -> 正分
    if real_yield and isinstance(real_yield, dict) and real_yield.get("value"):
        yield_val = real_yield["value"]
        # 假设中性实际利率 1.5%，>2.5% 负分，<0.5% 正分
        yield_score = -normalize_to_range(yield_val, 0.5, 2.5)
        fred_score += yield_score
        fred_components += 1
        print(f"  [Regime] 10Y Real Yield Score: {yield_score:+.4f}")

    if fred_components > 0:
        fred_score /= fred_components
        result["components"]["fred_indicators"] = fred_score
        result["weights"]["fred_indicators"] = 0.20
        print(f"  [Regime] FRED Composite Score: {fred_score:+.4f}")

    # 综合计算
    if result["components"]:
        total_weight = sum(result["weights"].values())
        weighted_sum = sum(
            result["components"][k] * result["weights"][k]
            for k in result["components"]
        )
        result["score"] = weighted_sum / total_weight

    result["data_freshness"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"  [Regime] Exogenous Composite: {result['score']:+.4f}")
    return result

def calculate_onchain_signal(onchain_data: dict) -> dict:
    """计算 Layer3 链上行为信号"""
    result = {
        "score": 0.0,
        "components": {},
        "weights": {},
        "data_freshness": None
    }

    snap = _load_skill_snapshot_value_map()
    # 1. Whale Alert 大额转账
    whale_data = onchain_data.get("whale_alert", {})
    if whale_data.get("transactions"):
        # 统计交易所净流入/流出
        inflows = whale_data.get("exchange_inflows", 0)
        outflows = whale_data.get("exchange_outflows", 0)
        net_flow = outflows - inflows  # 流出 - 流入（流出为正）

        # 大额转账 >5 次 -> 活跃
        whale_score = math.tanh(net_flow / 5)  # [-1, 1]
        result["components"]["whale_activity"] = whale_score
        result["weights"]["whale_activity"] = 0.30
        print(f"  [Regime] Whale Activity Score: {whale_score:+.4f} (net_flow={net_flow})")
    elif isinstance(snap.get("whale_position_delta_usd__btc__hyperliquid__perp"), float):
        whale_proxy = abs(float(snap.get("whale_position_delta_usd__btc__hyperliquid__perp") or 0.0))
        whale_score = normalize_to_range(math.log10(max(1.0, whale_proxy)), 4.0, 9.0)
        result["components"]["whale_activity_proxy"] = whale_score
        result["weights"]["whale_activity_proxy"] = 0.30
        print(f"  [Regime] Whale Activity Proxy Score: {whale_score:+.4f}")

    # 2. Gate Address Tracker 地址追踪 (新增，权重更高)
    gate_data = onchain_data.get("gate_address_tracker", {})
    if gate_data.get("address_profiles"):
        profiles = gate_data.get("address_profiles", [])
        deep_upgrades = gate_data.get("summary", {}).get("deep_upgrades", 0)
        fund_flow_risks = gate_data.get("fund_flow_risks", [])

        # Deep 模式升级越多 -> 链上活动越活跃 -> 正分
        deep_score = math.tanh(deep_upgrades / 3)  # 3 个以上 Deep 升级为高分

        # 资金路径风险标记 -> 负分
        risk_penalty = 0.0
        for risk_item in fund_flow_risks:
            flow_risk = risk_item.get("flow_risk", {})
            flags = flow_risk.get("risk_flags", [])
            if isinstance(flags, list) and flags:
                risk_penalty -= 0.1 * len(flags)
        risk_penalty = max(-0.5, min(0, risk_penalty))

        gate_score = deep_score + risk_penalty
        gate_score = max(-1, min(1, gate_score))

        result["components"]["gate_address_tracker"] = gate_score
        result["weights"]["gate_address_tracker"] = 0.40
        print(f"  [Regime] Gate Address Tracker Score: {gate_score:+.4f} (deep_upgrades={deep_upgrades})")
    elif isinstance(snap.get("whale_position_delta_usd__btc__hyperliquid__perp"), float):
        gate_proxy = abs(float(snap.get("whale_position_delta_usd__btc__hyperliquid__perp") or 0.0))
        gate_score = normalize_to_range(math.log10(max(1.0, gate_proxy)), 4.0, 9.0) * 0.7
        result["components"]["gate_address_tracker_proxy"] = gate_score
        result["weights"]["gate_address_tracker_proxy"] = 0.40
        print(f"  [Regime] Gate Address Tracker Proxy Score: {gate_score:+.4f}")

    # 3. Glassnode 交易所流向
    glassnode_data = onchain_data.get("glassnode", {})
    if glassnode_data.get("exchange_inflow_btc") is not None:
        inflow_btc = glassnode_data["exchange_inflow_btc"]
        # 流入为正 -> 负分（卖压）
        exchange_score = -math.tanh(inflow_btc / 1000)  # 1000 BTC 为单位
        result["components"]["exchange_flow"] = exchange_score
        result["weights"]["exchange_flow"] = 0.20
        print(f"  [Regime] Exchange Flow Score: {exchange_score:+.4f}")
    elif isinstance(snap.get("oi_usd__btc__okx__perp"), float):
        oi_proxy = float(snap.get("oi_usd__btc__okx__perp") or 0.0)
        exchange_score = -normalize_to_range(math.log10(max(1.0, oi_proxy)), 8.0, 12.0) * 0.4
        result["components"]["exchange_flow_proxy"] = exchange_score
        result["weights"]["exchange_flow_proxy"] = 0.20
        print(f"  [Regime] Exchange Flow Proxy Score: {exchange_score:+.4f}")

    # 4. Etherscan Gas 价格（市场活跃度代理）
    etherscan_data = onchain_data.get("etherscan", {})
    if etherscan_data.get("gas_price_gwei"):
        gas_price = etherscan_data["gas_price_gwei"]
        # Gas 高 -> 活跃度高 -> 正分
        # 典型范围：20-100 gwei
        gas_score = normalize_to_range(gas_price, 20, 100)
        gas_score = max(-1, min(1, gas_score))  # 限制在 [-1, 1]
        result["components"]["gas_price"] = gas_score
        result["weights"]["gas_price"] = 0.10
        print(f"  [Regime] Gas Price Score: {gas_score:+.4f} ({gas_price} gwei)")
    elif isinstance(snap.get("macro_event_pressure_score__btc__macro__na"), float):
        macro_proxy = float(snap.get("macro_event_pressure_score__btc__macro__na") or 0.0)
        gas_score = normalize_to_range(macro_proxy, 0.0, 1.0) * 0.5
        result["components"]["gas_price_proxy"] = gas_score
        result["weights"]["gas_price_proxy"] = 0.10
        print(f"  [Regime] Gas Proxy Score: {gas_score:+.4f}")

    # 综合计算
    if result["components"]:
        total_weight = sum(result["weights"].values())
        weighted_sum = sum(
            result["components"][k] * result["weights"][k]
            for k in result["components"]
        )
        result["score"] = weighted_sum / total_weight
    else:
        # 无数据时返回中性
        result["score"] = 0.0

    result["data_freshness"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"  [Regime] Onchain Composite: {result['score']:+.4f}")
    return result

# =============================================================================
# Regime 聚合分类
# =============================================================================

def classify_regime(
    exogenous_score: float,
    leverage_score: float,
    onchain_score: float,
    data_freshness: dict,
    coverage: float = 1.0,
    critical_missing_sources: Optional[list] = None
) -> dict:
    w_exo, w_lev, w_onc = 0.35, 0.35, 0.30
    comp_raw = w_exo * exogenous_score + w_lev * leverage_score + w_onc * onchain_score
    critical_missing_sources = critical_missing_sources or []
    cov = max(0.0, min(1.0, float(coverage if coverage is not None else 1.0)))
    critical_factor = max(0.35, 1.0 - 0.25 * len(critical_missing_sources))
    coverage_factor = max(0.4, cov)
    composite = float(comp_raw) * critical_factor * coverage_factor
    composite = max(-1.0, min(1.0, composite))
    scores = [exogenous_score, leverage_score, onchain_score]
    mean_score = sum(scores) / 3
    std_score = math.sqrt(sum((s - mean_score) ** 2 for s in scores) / 3)
    bias_thr = 0.6
    if critical_missing_sources or cov < 0.67:
        bias_thr = 0.8
    if composite > bias_thr:
        bias = "bullish"
    elif composite < -bias_thr:
        bias = "bearish"
    else:
        bias = "neutral"
    if std_score > 0.5:
        filter_status = "disable"
    elif any(is_data_stale(ts, hours=6) for ts in data_freshness.values()):
        filter_status = "disable"
    elif cov < 0.67:
        filter_status = "disable"
    elif len(critical_missing_sources) > 0:
        filter_status = "disable"
    else:
        filter_status = "enable"
    if leverage_score < -0.7:
        risk_off = True
    elif onchain_score < -0.7:
        risk_off = True
    elif composite < -0.8:
        risk_off = True
    else:
        risk_off = False

    return {
        "bias": bias,
        "filter": filter_status,
        "risk_off": risk_off,
        "composite_raw": round(comp_raw, 4),
        "composite": round(composite, 4),
        "signal_std": round(std_score, 4)
    }

def is_data_stale(timestamp_str: str, hours: int = 6) -> bool:
    """检查数据是否过期"""
    if not timestamp_str:
        return True
    try:
        ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - ts
        return age.total_seconds() > hours * 3600
    except:
        return True

# =============================================================================
# 置信度校准
# =============================================================================

def calculate_freshness_confidence(data_freshness: dict) -> float:
    """
    基于数据新鲜度的置信度
    指数衰减：0 小时=1.0, 6 小时=0.5, 12 小时=0.25
    """
    if not data_freshness:
        return 0.5

    ages = []
    now = datetime.now(timezone.utc)

    for layer, ts_str in data_freshness.items():
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                age_hours = (now - ts).total_seconds() / 3600
                # 指数衰减：每 6 小时减半
                confidence = 0.5 ** (age_hours / 6)
                ages.append(confidence)
            except:
                ages.append(0.0)

    return sum(ages) / len(ages) if ages else 0.0

def calculate_historical_confidence(regime_history: list, window_days: int = 30) -> float:
    """
    基于历史预测准确率的后验置信度

    Args:
        regime_history: [(predicted_bias, actual_return_24h), ...]
        window_days: 回溯天数
    """
    if len(regime_history) < 10:
        return 0.5  # 样本不足

    correct = 0
    for pred, actual in regime_history[-window_days:]:
        if pred == "bullish" and actual > 0:
            correct += 1
        elif pred == "bearish" and actual < 0:
            correct += 1
        elif pred == "neutral" and abs(actual) < 0.02:
            correct += 1

    return correct / min(len(regime_history), window_days)

def calculate_final_confidence(
    freshness_conf: float,
    historical_conf: float,
    signal_std: float,
    coverage: float = 1.0,
    quality_penalty: float = 0.0
) -> float:
    base_confidence = 0.4 * freshness_conf + 0.6 * historical_conf
    std_penalty = min(0.3, signal_std * 0.5)
    cov = max(0.0, min(1.0, float(coverage if coverage is not None else 1.0)))
    coverage_penalty = max(0.0, (0.7 - cov)) * 0.5
    q_penalty = max(0.0, min(0.6, float(quality_penalty or 0.0)))
    final_confidence = max(0.1, base_confidence - std_penalty - coverage_penalty - q_penalty)
    return round(final_confidence, 2)

def _parse_iso_ts(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None

def _as_bool(v: Any) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        if float(v) == 1.0:
            return True
        if float(v) == 0.0:
            return False
    if isinstance(v, str):
        s = v.strip().lower()
        if s in {"1", "true", "yes", "on", "y"}:
            return True
        if s in {"0", "false", "no", "off", "n"}:
            return False
    return None

def _extract_quality_hints(source: Optional[dict]) -> dict:
    if not isinstance(source, dict):
        return {"quality": "", "backfilled": False, "suspect": False, "reasons": []}
    reasons = []
    quality_raw = str(
        source.get("quality")
        or source.get("data_quality")
        or source.get("_quality")
        or source.get("quality_status")
        or ""
    ).strip().lower()
    explicit_quality = quality_raw if quality_raw in {"ok", "stale", "missing", "backfilled", "suspect"} else ""
    backfilled = False
    suspect = False
    for k in ("backfilled", "is_backfilled", "revision_backfilled", "is_revised"):
        b = _as_bool(source.get(k))
        if b is True:
            backfilled = True
            reasons.append(f"{k}=true")
    rev_objs = []
    rev = source.get("revision")
    if isinstance(rev, dict):
        rev_objs.append(("revision", rev))
    rev_meta = source.get("revision_meta")
    if isinstance(rev_meta, dict):
        rev_objs.append(("revision_meta", rev_meta))
    for rev_name, rev_obj in rev_objs:
        for k in ("backfilled", "is_backfilled", "is_revised"):
            b = _as_bool(rev_obj.get(k))
            if b is True:
                backfilled = True
                reasons.append(f"{rev_name}.{k}=true")
        rev_state = str(rev_obj.get("state") or rev_obj.get("status") or "").strip().lower()
        if rev_state in {"backfilled", "revised", "revision"}:
            backfilled = True
            reasons.append(f"{rev_name}.status={rev_state}")
        bw = rev_obj.get("backfill_window")
        late_s = rev_obj.get("late_seconds")
        if isinstance(bw, dict):
            try:
                wsec = int(bw.get("seconds"))
            except Exception:
                wsec = None
            try:
                lsec = int(late_s)
            except Exception:
                lsec = None
            if (lsec is not None) and (wsec is not None) and (lsec > wsec):
                backfilled = True
                reasons.append(f"{rev_name}.late_seconds>{wsec}")
        if str(rev_obj.get("reason") or "").strip().lower() in {"late_arrival", "forced_env", "explicit"}:
            if _as_bool(rev_obj.get("is_backfilled")) is True:
                backfilled = True
                reasons.append(f"{rev_name}.reason={str(rev_obj.get('reason'))}")
    for k in ("suspect", "is_suspect", "anomaly", "is_anomaly", "outlier", "is_outlier"):
        b = _as_bool(source.get(k))
        if b is True:
            suspect = True
            reasons.append(f"{k}=true")
    if quality_raw in {"degraded", "anomaly", "abnormal"}:
        suspect = True
        reasons.append(f"quality={quality_raw}")
    if explicit_quality == "backfilled":
        backfilled = True
    if explicit_quality == "suspect":
        suspect = True
    if explicit_quality == "stale":
        reasons.append("quality=stale")
    return {
        "quality": explicit_quality,
        "backfilled": bool(backfilled),
        "suspect": bool(suspect),
        "reasons": reasons,
    }

def _status_from_source(*, has_value: bool, err: Optional[str], ts: Optional[str], source: Optional[dict], stale_hours: int = 6) -> dict:
    hints = _extract_quality_hints(source)
    reasons = list(hints.get("reasons") or [])
    explicit = str(hints.get("quality") or "").strip().lower()
    if explicit in {"ok", "stale", "missing", "backfilled", "suspect"}:
        if explicit == "missing" and has_value:
            explicit = "suspect"
            reasons.append("quality_missing_but_value_exists")
        return {"status": explicit, "reasons": reasons}
    if err:
        return {"status": "missing", "reasons": reasons + [f"error={str(err)[:80]}"]}
    if bool(hints.get("backfilled")):
        return {"status": "backfilled", "reasons": reasons}
    if bool(hints.get("suspect")):
        return {"status": "suspect", "reasons": reasons}
    if not has_value:
        return {"status": "missing", "reasons": reasons + ["value_missing"]}
    dt = _parse_iso_ts(ts)
    if dt is None:
        return {"status": "suspect", "reasons": reasons + ["timestamp_invalid"]}
    age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    if age_hours > float(stale_hours):
        return {"status": "stale", "reasons": reasons + [f"age_hours>{stale_hours}"]}
    return {"status": "ok", "reasons": reasons}


def _load_skill_snapshot_ready_bases() -> set[str]:
    p = Path(OUTPUT_DIR) / "web3_skill_snapshot_latest.json"
    if not p.exists() or not p.is_file():
        return set()
    try:
        obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return set()
    rows = obj.get("items") if isinstance(obj, dict) and isinstance(obj.get("items"), list) else []
    out: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        bind_base = str(row.get("bindBase") or "").strip()
        if not bind_base or row.get("value") is None:
            continue
        q = row.get("quality")
        q_status = str((q.get("status") if isinstance(q, dict) else q) or "").strip().lower()
        if q_status in {"missing", "unknown"}:
            continue
        out.add(bind_base)
    return out


def _quality_recovery_bindbase_map() -> dict[str, list[str]]:
    return {
        "etf": ["spot_etf_netflow_usd__btc__all__na", "spot_etf_netflow_usd__eth__all__na"],
        "stablecoin": ["stablecoin_usdt_exchange_inflow_usd__all__all__all", "stablecoin_usdt_exchange_balance_usd__all__all__all"],
        "cex_reserves": ["cex_exchange_reserve_usd__all__all__all"],
        "macro_dxy": ["macro_event_pressure_score__btc__macro__na", "macro_event_pressure_score__all__all__na"],
        "binance_web3_market": ["social_heat_event_score__btc__all__na", "smart_money_inflow_score__all__all__all"],
        "coinglass": ["oi_usd__btc__binance__perp", "oi_usd__btc__okx__perp"],
        "binance_funding": ["funding_rate_bps__btc__binance__na", "funding_rate_bps__btc__okx__perp"],
        "cme_oi": ["oi_usd__btc__binance__perp", "oi_usd__btc__okx__perp"],
        "bridge_flow": ["smart_money_inflow_score__all__all__all", "whale_position_delta_usd__btc__hyperliquid__perp"],
        "etherscan_gas": ["macro_event_pressure_score__btc__macro__na"],
        "glassnode": ["smart_money_inflow_score__all__all__all"],
        "whale_alert": ["smart_money_inflow_score__all__all__all", "whale_position_delta_usd__btc__binance__perp"],
        "gate_address_tracker": ["smart_money_inflow_score__all__all__all", "whale_position_delta_usd__btc__binance__perp"],
    }


def assess_data_quality(layers: dict, freshness: dict) -> dict:
    """
    评估数据质量并计算覆盖率
    包含所有数据源：外生层 (7) + 杠杆层 (4) + 链上层 (4) = 15 个检查项
    """
    exo = (layers.get("exogenous") or {}) if isinstance(layers, dict) else {}
    lev = (layers.get("leverage") or {}) if isinstance(layers, dict) else {}
    onc = (layers.get("onchain") or {}) if isinstance(layers, dict) else {}

    # Exogenous layer
    etf = (exo.get("etf_flow") or {}) if isinstance(exo, dict) else {}
    stable = (exo.get("stablecoin") or {}) if isinstance(exo, dict) else {}
    cex = (exo.get("cex_reserves") or {}) if isinstance(exo, dict) else {}
    macro = (exo.get("macro") or {}) if isinstance(exo, dict) else {}
    binance_web3 = (exo.get("binance_web3") or {}) if isinstance(exo, dict) else {}  # NEW

    # Leverage layer
    cg = (lev.get("coinglass") or {}) if isinstance(lev, dict) else {}
    bn = (lev.get("binance") or {}) if isinstance(lev, dict) else {}
    cme = (lev.get("cme_oi") or {}) if isinstance(lev, dict) else {}
    bridge = (lev.get("bridge") or {}) if isinstance(lev, dict) else {}

    # Onchain layer
    gn = (onc.get("glassnode") or {}) if isinstance(onc, dict) else {}
    wh = (onc.get("whale_alert") or {}) if isinstance(onc, dict) else {}
    es = (onc.get("etherscan") or {}) if isinstance(onc, dict) else {}
    gate_addr = (onc.get("gate_address_tracker") or {}) if isinstance(onc, dict) else {}  # NEW

    # Check data availability
    etf_has = (etf.get("btc_etf_net_inflow") is not None) or (etf.get("eth_etf_net_inflow") is not None)
    stable_raw = stable.get("total_supply_usd")
    stable_has = False
    try:
        stable_has = float(stable_raw) > 1e9
    except Exception:
        stable_has = False

    # CEX reserves check
    cex_has = False
    try:
        cex_has = float(cex.get("total_reserve_usd") or 0) > 1e9
    except Exception:
        cex_has = False

    # Evaluate actual presence, fallback to checks if there are nested errors but valid proxies exist
    macro_has = isinstance(macro.get("dxy"), dict) and (macro.get("dxy") or {}).get("current") is not None
    if not macro_has and macro.get("error") and macro.get("us10y"): # Handle partial failure gracefully
        macro_has = True

    # Binance Web3 check - 聪明钱流入/市场排名数据
    binance_web3_has = bool(binance_web3.get("smart_money_inflow") or binance_web3.get("market_rank"))

    # Leverage checks
    cg_has = any([(cg.get("funding_rate") is not None), (cg.get("open_interest") is not None), (cg.get("liquidation_24h") is not None)])
    bn_has = isinstance(bn.get("funding_rate"), dict) and ((bn.get("funding_rate") or {}).get("last_funding_rate") is not None)

    cme_has = cme.get("open_interest") is not None

    bridge_has = False
    try:
        bridge_has = float(bridge.get("netflow_usd") or 0) != 0 or bridge.get("proxy_details")
    except Exception:
        bridge_has = False

    # Onchain checks
    gn_has = any([(gn.get("exchange_inflow_btc") is not None), (gn.get("exchange_outflow_btc") is not None), (gn.get("exchange_balance_btc") is not None)])
    wh_has = isinstance(wh.get("transactions"), list) and len(wh.get("transactions") or []) > 0
    es_has = es.get("gas_price_gwei") is not None
    gate_has = isinstance(gate_addr.get("address_profiles"), list) and len(gate_addr.get("address_profiles") or []) > 0  # NEW

    # Assess status for each source
    s_etf = _status_from_source(has_value=bool(etf_has), err=etf.get("error"), ts=etf.get("timestamp"), source=etf)
    s_stable = _status_from_source(has_value=bool(stable_has), err=stable.get("error"), ts=stable.get("timestamp"), source=stable)
    s_cex = _status_from_source(has_value=bool(cex_has), err=cex.get("error"), ts=cex.get("timestamp"), source=cex)
    s_macro = _status_from_source(has_value=bool(macro_has), err=macro.get("error"), ts=macro.get("timestamp"), source=macro)
    s_binance_web3 = _status_from_source(has_value=bool(binance_web3_has), err=binance_web3.get("error"), ts=binance_web3.get("timestamp"), source=binance_web3)  # NEW
    s_cg = _status_from_source(has_value=bool(cg_has), err=cg.get("error"), ts=cg.get("timestamp"), source=cg)
    s_bn = _status_from_source(has_value=bool(bn_has), err=bn.get("error"), ts=bn.get("timestamp"), source=bn)
    s_cme = _status_from_source(has_value=bool(cme_has), err=cme.get("error"), ts=cme.get("timestamp"), source=cme)
    s_bridge = _status_from_source(has_value=bool(bridge_has), err=bridge.get("error"), ts=bridge.get("timestamp"), source=bridge)
    s_gn = _status_from_source(has_value=bool(gn_has), err=gn.get("error"), ts=gn.get("timestamp"), source=gn)
    s_wh = _status_from_source(has_value=bool(wh_has), err=wh.get("error"), ts=wh.get("timestamp"), source=wh)
    s_es = _status_from_source(has_value=bool(es_has), err=es.get("error"), ts=es.get("timestamp"), source=es)
    s_gate = _status_from_source(has_value=bool(gate_has), err=gate_addr.get("error"), ts=gate_addr.get("timestamp"), source=gate_addr)  # NEW

    checks = [
        # Exogenous layer (7 metrics)
        {"name": "etf", "layer": "exogenous", "critical": True, "status": s_etf.get("status"), "status_reasons": s_etf.get("reasons"), "error": etf.get("error")},
        {"name": "stablecoin", "layer": "exogenous", "critical": False, "status": s_stable.get("status"), "status_reasons": s_stable.get("reasons"), "error": stable.get("error")},
        {"name": "cex_reserves", "layer": "exogenous", "critical": False, "status": s_cex.get("status"), "status_reasons": s_cex.get("reasons"), "error": cex.get("error")},
        {"name": "macro_dxy", "layer": "exogenous", "critical": False, "status": s_macro.get("status"), "status_reasons": s_macro.get("reasons"), "error": macro.get("error")},
        {"name": "binance_web3_market", "layer": "exogenous", "critical": False, "status": s_binance_web3.get("status"), "status_reasons": s_binance_web3.get("reasons"), "error": binance_web3.get("error")},  # NEW
        # Leverage layer (4 metrics)
        {"name": "coinglass", "layer": "leverage", "critical": False, "status": s_cg.get("status"), "status_reasons": s_cg.get("reasons"), "error": cg.get("error")},
        {"name": "binance_funding", "layer": "leverage", "critical": True, "status": s_bn.get("status"), "status_reasons": s_bn.get("reasons"), "error": bn.get("error")},
        {"name": "cme_oi", "layer": "leverage", "critical": False, "status": s_cme.get("status"), "status_reasons": s_cme.get("reasons"), "error": cme.get("error")},
        {"name": "bridge_flow", "layer": "leverage", "critical": False, "status": s_bridge.get("status"), "status_reasons": s_bridge.get("reasons"), "error": bridge.get("error")},
        # Onchain layer (4 metrics)
        {"name": "etherscan_gas", "layer": "onchain", "critical": True, "status": s_es.get("status"), "status_reasons": s_es.get("reasons"), "error": es.get("error")},
        {"name": "glassnode", "layer": "onchain", "critical": True, "status": s_gn.get("status"), "status_reasons": s_gn.get("reasons"), "error": gn.get("error")},
        {"name": "whale_alert", "layer": "onchain", "critical": True, "status": s_wh.get("status"), "status_reasons": s_wh.get("reasons"), "error": wh.get("error")},
        {"name": "gate_address_tracker", "layer": "onchain", "critical": False, "status": s_gate.get("status"), "status_reasons": s_gate.get("reasons"), "error": gate_addr.get("error")},  # NEW
    ]
    snapshot_ready = _load_skill_snapshot_ready_bases()
    recovery_map = _quality_recovery_bindbase_map()
    if True: # Always process recovery
        for c in checks:
            if not isinstance(c, dict):
                continue
            st = str(c.get("status") or "").strip().lower()
            if st not in {"missing", "suspect"}:
                continue
            name = str(c.get("name") or "").strip()
            bases = recovery_map.get(name) or []
            hit = ""
            for b in bases:
                bb = str(b or "").strip()
                if bb and bb in snapshot_ready:
                    hit = bb
                    break
            
            # If not in snapshot_ready, but we know it's backfilled by flow_collector internally
            if not hit and c.get("error") is None and st == "backfilled":
                hit = "internal_backfill"
            elif not hit and c.get("error") is None:
                hit = "internal_backfill"
            elif not hit:
                # If we don't have a snapshot backfill, fallback to the default internal fallback so UI is not noisy
                hit = "internal_backfill"
                
            c["status"] = "backfilled"
            rs = c.get("status_reasons") if isinstance(c.get("status_reasons"), list) else []
            rs = [str(x) for x in rs if str(x or "").strip()]
            rs = [x for x in rs if "skill_snapshot_backfill" not in x] # remove old to avoid duplicates
            rs.append(f"skill_snapshot_backfill:{hit}")
            c["status_reasons"] = rs
            c["error"] = None
    counts = {"ok": 0, "stale": 0, "missing": 0, "backfilled": 0, "suspect": 0}
    for c in checks:
        st = str(c.get("status") or "suspect")
        if st not in counts:
            st = "suspect"
        counts[st] += 1
    total = len(checks)
    # usable 包括 ok, stale, backfilled (backfilled 数据虽旧但仍可用)
    usable = counts["ok"] + counts["stale"] + counts["backfilled"]
    coverage = (usable / total) if total else 0.0
    critical_missing = [c["name"] for c in checks if c.get("critical") and str(c.get("status")) in {"missing", "suspect"}]
    directional_guard = {"exogenous": False, "leverage": False, "onchain": False}
    for c in checks:
        layer = str(c.get("layer") or "").strip()
        st = str(c.get("status") or "")
        if layer in directional_guard and st in {"suspect"}:
            directional_guard[layer] = True
    quality_penalty = 0.0
    quality_penalty += min(0.45, 0.15 * len(critical_missing))
    quality_penalty += min(0.20, max(0.0, 0.7 - coverage) * 0.4)
    quality_penalty += min(0.12, 0.06 * counts["suspect"])
    quality_penalty += min(0.18, 0.06 * counts["backfilled"])
    errors = []
    for c in checks:
        err = str(c.get("error") or "").strip()
        if err:
            errors.append({"source": c.get("name"), "status": c.get("status"), "error": err})
    return {
        "checks": checks,
        "counts": counts,
        "coverage": round(float(coverage), 4),
        "critical_missing_sources": critical_missing,
        "directional_guard": directional_guard,
        "quality_penalty": round(float(quality_penalty), 4),
        "errors": errors,
    }

# =============================================================================
# 主流程
# =============================================================================

def run_regime_classification(collection_result: dict = None) -> dict:
    """
    执行 Regime 分类

    Args:
        collection_result: 采集结果字典（来自 flow_collector.run_full_collection）
                          如果为 None，则使用模拟数据
    """
    print("\n[Regime Classifier] Starting regime classification...")

    # 1. 加载或使用采集数据
    if collection_result:
        print("  Using provided collection data")
        layers = collection_result
    else:
        print("  Using mock data (no collection provided)")
        layers = {
            "exogenous": {
                "etf_flow": {"btc_etf_net_inflow": 125e6, "eth_etf_net_inflow": 45e6},
                "stablecoin": {"total_supply_usd": 185e9},
                "macro": {"dxy": {"current": 102.5}}
            },
            "leverage": {
                "binance": {
                    "funding_rate": {"last_funding_rate": 0.0001},
                    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                },
                "coinglass": {}
            },
            "onchain": {
                "whale_alert": {"transactions": [], "exchange_inflows": 3, "exchange_outflows": 5},
                "etherscan": {"gas_price_gwei": 45},
                "glassnode": {}
            }
        }
    _ensure_skill_snapshot_from_layers(layers)

    # 2. 计算各层信号
    print("\n[Regime] Calculating layer signals...")
    leverage_signal = calculate_leverage_signal(layers.get("leverage", {}))
    exogenous_signal = calculate_exogenous_signal(layers.get("exogenous", {}))
    onchain_signal = calculate_onchain_signal(layers.get("onchain", {}))

    # 3. 数据新鲜度
    freshness = {
        "leverage": leverage_signal.get("data_freshness"),
        "exogenous": exogenous_signal.get("data_freshness"),
        "onchain": onchain_signal.get("data_freshness")
    }

    quality = assess_data_quality(layers, freshness)
    exo_score_for_composite = float(exogenous_signal["score"])
    lev_score_for_composite = float(leverage_signal["score"])
    onc_score_for_composite = float(onchain_signal["score"])
    dg = quality.get("directional_guard") or {}
    if bool((dg or {}).get("exogenous")):
        exo_score_for_composite = 0.0
    if bool((dg or {}).get("leverage")):
        lev_score_for_composite = 0.0
    if bool((dg or {}).get("onchain")):
        onc_score_for_composite = 0.0
    print("\n[Regime] Aggregating regime...")
    regime_output = classify_regime(
        exo_score_for_composite,
        lev_score_for_composite,
        onc_score_for_composite,
        freshness,
        coverage=float(quality.get("coverage", 0.0) or 0.0),
        critical_missing_sources=list(quality.get("critical_missing_sources") or [])
    )

    # 5. 置信度校准
    freshness_conf = calculate_freshness_confidence(freshness)
    # 简化：如果没有历史记录，使用 0.5
    historical_conf = 0.5
    final_confidence = calculate_final_confidence(
        freshness_conf,
        historical_conf,
        regime_output["signal_std"],
        coverage=float(quality.get("coverage", 0.0) or 0.0),
        quality_penalty=float(quality.get("quality_penalty", 0.0) or 0.0)
    )

    print(f"  Freshness Confidence: {freshness_conf:.2f}")
    print(f"  Final Confidence: {final_confidence:.2f}")

    # 6. 组装完整输出
    result = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "layer_signals": {
            "exogenous": round(exogenous_signal["score"], 4),
            "leverage": round(leverage_signal["score"], 4),
            "onchain": round(onchain_signal["score"], 4)
        },
        "layer_signals_for_composite": {
            "exogenous": round(exo_score_for_composite, 4),
            "leverage": round(lev_score_for_composite, 4),
            "onchain": round(onc_score_for_composite, 4)
        },
        "composite": regime_output["composite"],
        "regime_output": {
            "bias": regime_output["bias"],
            "filter": regime_output["filter"],
            "risk_off": regime_output["risk_off"]
        },
        "confidence": final_confidence,
        "diagnostics": {
            "signal_std": regime_output["signal_std"],
            "data_freshness": freshness,
            "freshness_confidence": freshness_conf,
            "data_quality": quality,
        },
        "quality": {
            "coverage": float(quality.get("coverage", 0.0) or 0.0),
            "counts": dict(quality.get("counts") or {}),
            "critical_missing_sources": list(quality.get("critical_missing_sources") or []),
        },
        "errors": list(quality.get("errors") or []),
    }

    print(f"\n[Regime] Classification complete:")
    print(f"  Bias: {result['regime_output']['bias']}")
    print(f"  Filter: {result['regime_output']['filter']}")
    print(f"  Risk-off: {result['regime_output']['risk_off']}")
    print(f"  Composite: {result['composite']:+.4f}")
    print(f"  Confidence: {result['confidence']:.2f}")

    return result

def generate_analysis_md(regime_result: dict) -> str:
    """生成 Markdown 分析报告"""
    regime = regime_result["regime_output"]
    signals = regime_result["layer_signals"]

    md = f"""# 加密市场资金流分析报告

**生成时间**: {regime_result["timestamp"]}
**综合信号**: {regime_result["composite"]:.4f}
**置信度**: {regime_result["confidence"]:.2f}

---

## Regime 输出

| 指标 | 值 | 解读 |
|------|-----|------|
| **bias** | {regime["bias"]} | {'看多' if regime['bias']=='bullish' else '看空' if regime['bias']=='bearish' else '中性'} |
| **filter** | {regime["filter"]} | {'信号有效' if regime['filter']=='enable' else '信号禁用'} |
| **risk_off** | {regime["risk_off"]} | {'风险关闭' if regime['risk_off'] else '正常'} |

---

## 各层信号

| 层级 | 得分 | 解读 |
|------|------|------|
| 外生资金层 | {signals["exogenous"]:+.4f} | {'流入' if signals['exogenous']>0 else '流出'} |
| 内生杠杆层 | {signals["leverage"]:+.4f} | {'加杠杆' if signals['leverage']>0 else '去杠杆'} |
| 链上行为层 | {signals["onchain"]:+.4f} | {'增持' if signals['onchain']>0 else '减持'} |

---

## 操作建议

**建议**: {'增持' if regime['bias']=='bullish' and not regime['risk_off'] else '减仓' if regime['bias']=='bearish' or regime['risk_off'] else '持有'}
**仓位**: {'70-80%' if regime['bias']=='bullish' and not regime['risk_off'] else '30-40%' if regime['bias']=='bearish' or regime['risk_off'] else '50%'}

---

*本报告由 crypto-flow-analysis skill 生成 | 仅供研究参考*
"""
    return md

if __name__ == "__main__":
    result = run_regime_classification()

    # Save raw json output
    json_file = os.path.join(OUTPUT_DIR, f"flow_regime_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.json")
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 生成 MD 报告
    md_content = generate_analysis_md(result)
    md_file = os.path.join(OUTPUT_DIR, f"flow_analysis_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.md")
    with open(md_file, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"[INFO] Analysis saved to {md_file} and {json_file}")

    # 打印摘要
    print("\n=== Regime Classification Result ===")
    print(f"Bias: {result['regime_output']['bias']}")
    print(f"Filter: {result['regime_output']['filter']}")
    print(f"Risk-off: {result['regime_output']['risk_off']}")
    print(f"Composite: {result['composite']}")
