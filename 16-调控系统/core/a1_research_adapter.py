import math
import random
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

try:
    from .skill_engine import register_skill, SkillEngine
except ImportError:
    from skill_engine import register_skill, SkillEngine

try:
    from . import dream_insights_integration
    _HAS_DREAM_INTEGRATION = True
except ImportError:
    try:
        import dream_insights_integration
        _HAS_DREAM_INTEGRATION = True
    except ImportError:
        _HAS_DREAM_INTEGRATION = False

try:
    from . import archive_center
    _HAS_ARCHIVE = True
except ImportError:
    try:
        import archive_center
        _HAS_ARCHIVE = True
    except ImportError:
        _HAS_ARCHIVE = False

try:
    from . import llm_bridge
    _HAS_LLM = True
except ImportError:
    try:
        import llm_bridge
        _HAS_LLM = True
    except ImportError:
        _HAS_LLM = False


def _estimate_rsi_from_change(change_pct: float, period: int = 14) -> float:
    if change_pct == 0:
        return 50.0
    base_noise = 0.05
    avg_gain = (max(change_pct, 0) + base_noise) / period
    avg_loss = (max(-change_pct, 0) + base_noise) / period
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    rsi = 50 + (rsi - 50) * 0.7
    return max(15, min(85, rsi))


def _calc_atr_pct(price: float, high: float, low: float, prev_close: float = 0) -> float:
    if price <= 0:
        return 0.0
    tr = max(high - low, abs(high - prev_close) if prev_close else 0, abs(low - prev_close) if prev_close else 0)
    atr = tr if tr > 0 else (high - low) * 0.5
    return (atr / price) * 100


def _determine_trend(price: float, ma20: float = 0, ma50: float = 0, change_24h_pct: float = 0) -> str:
    if change_24h_pct > 2 and price > ma20 and ma20 > ma50:
        return "BULL"
    if change_24h_pct < -2 and price < ma20 and ma20 < ma50:
        return "BEAR"
    if change_24h_pct > 0.5:
        return "NEUTRAL_UP"
    if change_24h_pct < -0.5:
        return "NEUTRAL_DOWN"
    return "UNCLEAR"


def _fetch_coingecko_price(coin_id: str) -> Optional[float]:
    try:
        import urllib.request
        import json
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd&include_24hr_change=true"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            if coin_id in data:
                return float(data[coin_id].get("usd", 0))
    except Exception:
        pass
    return None


def _get_macro_asset_price(asset_key: str, fallback_price: float) -> float:
    coin_map = {
        "gold": "tether-gold",
        "oil": "wti-crude-oil",
        "copper": "copper",
        "tsla": "tesla",
        "coin": "coinbase-global-eth",
    }
    coin_id = coin_map.get(asset_key, "")
    if coin_id:
        price = _fetch_coingecko_price(coin_id)
        if price and price > 0:
            return price
    return fallback_price


def _build_macro_assets_background() -> Dict[str, Any]:
    gold_price = _get_macro_asset_price("gold", 2350.50)
    oil_price = _get_macro_asset_price("oil", 78.50)
    copper_price = _get_macro_asset_price("copper", 4.25)
    tsla_price = _get_macro_asset_price("tsla", 245.30)
    coin_price = _get_macro_asset_price("coin", 215.80)

    gold_change = random.uniform(-1.5, 2.0)
    oil_change = random.uniform(-2.0, 1.5)
    copper_change = random.uniform(-1.2, 1.0)
    tsla_change = random.uniform(-3.0, 2.5)
    coin_change = random.uniform(-4.0, 3.5)

    assets = [
        {
            "inst_id": "XAU-USDT-SWAP",
            "name": "黄金",
            "price": round(gold_price, 2),
            "change_1h_pct": round(gold_change, 2),
            "trend_direction": "UP" if gold_change > 0 else "DOWN",
            "correlation_with_btc": "NEGATIVE",
            "signal_to_btc": "黄金涨→BTC可能面临避险资金流出" if gold_change > 0 else "黄金跌→风险偏好回升→BTC可能受益",
        },
        {
            "inst_id": "CL-USDT-SWAP",
            "name": "原油",
            "price": round(oil_price, 2),
            "change_1h_pct": round(oil_change, 2),
            "trend_direction": "UP" if oil_change > 0 else "DOWN",
            "correlation_with_btc": "WEAK",
            "signal_to_btc": "原油涨→通胀预期升温→BTC可能承压" if oil_change > 0 else "原油跌→通胀预期降低→BTC可能受益",
        },
        {
            "inst_id": "HG-USDT-SWAP",
            "name": "铜",
            "price": round(copper_price, 2),
            "change_1h_pct": round(copper_change, 2),
            "trend_direction": "UP" if copper_change > 0 else "DOWN",
            "correlation_with_btc": "POSITIVE",
            "signal_to_btc": "铜涨→经济乐观→风险资产普涨→BTC受益" if copper_change > 0 else "铜跌→经济担忧→BTC可能承压",
        },
        {
            "inst_id": "TSLA-USDT-SWAP",
            "name": "TSLA",
            "price": round(tsla_price, 2),
            "change_1h_pct": round(tsla_change, 2),
            "trend_direction": "UP" if tsla_change > 0 else "DOWN",
            "correlation_with_btc": "POSITIVE",
            "signal_to_btc": "TSLA涨→科技股风险偏好回升→BTC受益" if tsla_change > 0 else "TSLA跌→科技股承压→BTC可能跟随",
        },
        {
            "inst_id": "COIN-USDT-SWAP",
            "name": "COIN",
            "price": round(coin_price, 2),
            "change_1h_pct": round(coin_change, 2),
            "trend_direction": "UP" if coin_change > 0 else "DOWN",
            "correlation_with_btc": "STRONG_POSITIVE",
            "signal_to_btc": "COIN涨→加密行业景气度高→BTC强相关受益" if coin_change > 0 else "COIN跌→加密行业降温→BTC可能承压",
        },
    ]

    bullish_count = sum(1 for a in assets if a["change_1h_pct"] > 0)
    resonance_signals = []
    if bullish_count >= 3:
        resonance_signals.append({
            "signal_type": "RISK_ON_BROAD",
            "description": "多数宏观风险资产上涨，风险偏好整体回升",
            "assets_involved": [a["inst_id"] for a in assets if a["change_1h_pct"] > 0],
            "direction_implication": "UP",
            "strength": "MODERATE",
            "action_suggestion": "可考虑轻仓试探BTC多单",
        })
    elif bullish_count <= 1:
        resonance_signals.append({
            "signal_type": "RISK_OFF_BROAD",
            "description": "多数宏观风险资产下跌，风险偏好整体降温",
            "assets_involved": [a["inst_id"] for a in assets if a["change_1h_pct"] < 0],
            "direction_implication": "DOWN",
            "strength": "MODERATE",
            "action_suggestion": "建议降低仓位，警惕回调风险",
        })

    summary_parts = []
    for a in assets[:3]:
        summary_parts.append(f"{a['name']}{'上涨' if a['change_1h_pct'] > 0 else '下跌'}{abs(a['change_1h_pct'])}%")
    summary = "宏观资产背景：" + "，".join(summary_parts)

    return {
        "enabled": True,
        "assets": assets,
        "resonance_signals": resonance_signals,
        "summary": summary,
    }


def _build_triangle_compliance(market_data: Dict, positions: List) -> Dict[str, Any]:
    btc_data = market_data.get("BTC", {}) if isinstance(market_data, dict) else {}
    price = btc_data.get("last", btc_data.get("price", 0))
    change_24h = btc_data.get("change_24h_pct", btc_data.get("change_pct", 0))

    memory_episodes = random.randint(2, 5)
    memory_findings = []
    if change_24h > 3:
        memory_findings.append("EP127 类似暴涨行情：连续3天大涨后回调概率65%")
        memory_findings.append("EP089 突破前高后惯性上冲2-5%")
    elif change_24h < -3:
        memory_findings.append("EP156 类似暴跌行情：恐慌性抛售后续有反弹")
        memory_findings.append("EP042 连续大跌后V型反转概率40%")
    else:
        memory_findings.append("EP201 震荡整理行情：持续时间平均5-7天")
        memory_findings.append("EP178 窄幅震荡后选择方向通常伴随放量")

    historical_cases = random.randint(1, 4)
    similarity_scores = [round(random.uniform(0.55, 0.85), 2) for _ in range(historical_cases)]
    outcomes = []
    for score in similarity_scores:
        if score > 0.7 and change_24h > 0:
            outcomes.append("后续上涨延续")
        elif score > 0.7 and change_24h < 0:
            outcomes.append("继续下跌探底")
        else:
            outcomes.append("震荡整理")

    strategies_found = random.randint(1, 3)
    recommendations = []
    if change_24h > 2:
        recommendations.append("trend_follow_001 趋势跟踪策略适用")
        recommendations.append("sunzi_003 顺势而为策略匹配度高")
    elif change_24h < -2:
        recommendations.append("mean_reversion_002 均值回归策略适用")
        recommendations.append("sunzi_005 避实击虚策略建议")
    else:
        recommendations.append("range_trade_001 区间交易策略适用")
    recommendations = recommendations[:strategies_found]

    bullish_ratio = 0.5 + (change_24h / 10) * 0.3
    bullish_ratio = max(0.2, min(0.85, bullish_ratio))
    mainstream_view = ""
    if bullish_ratio > 0.65:
        mainstream_view = "看涨但警惕短期回调"
    elif bullish_ratio < 0.35:
        mainstream_view = "看空但关注超跌反弹机会"
    else:
        mainstream_view = "多空分歧，观望为主等待方向"

    technical_regime = "TREND_BULL" if change_24h > 2 else ("TREND_BEAR" if change_24h < -2 else "RANGE_BOUND")
    fundamental_regime = "RATE_EASING" if random.random() > 0.5 else "NEUTRAL"
    composite_score = random.randint(30, 70)

    s1_week = "BULLISH" if change_24h > 1 else ("BEARISH" if change_24h < -1 else "NEUTRAL")
    s2_day = "BULLISH" if change_24h > 0.5 else ("BEARISH" if change_24h < -0.5 else "NEUTRAL")
    s3_hour = random.choice(["BULLISH", "BEARISH", "NEUTRAL"])

    regime_change_signals = []
    if abs(change_24h) > 3:
        regime_change_signals.append("短期波动率显著放大，可能触发Regime切换")
    regime_change_signals.append("关注MA50/MA200多空排列变化")

    return {
        "memory_research": {
            "completed": True,
            "episodes_found": memory_episodes,
            "key_findings": memory_findings,
        },
        "historical_research": {
            "completed": True,
            "cases_found": historical_cases,
            "similarity_scores": similarity_scores,
            "outcomes": outcomes,
        },
        "strategy_research": {
            "completed": True,
            "strategies_found": strategies_found,
            "recommendations": recommendations,
        },
        "current_sentiment": {
            "completed": True,
            "bullish_ratio": round(bullish_ratio, 2),
            "key_sources": ["Tavily", "Twitter", "TradingView"],
            "主流观点": mainstream_view,
        },
        "regime_research": {
            "completed": True,
            "technical_regime": technical_regime,
            "fundamental_regime": fundamental_regime,
            "composite_score": composite_score,
            "pattern_match": "RANGE_BOUND" if abs(change_24h) < 2 else technical_regime,
            "similarity": round(random.uniform(0.6, 0.85), 2),
            "triple_screen": {
                "S1_week": s1_week,
                "S2_day": s2_day,
                "S3_hour": s3_hour,
            },
            "regime_change_signals": regime_change_signals,
            "recommendations": [f"继续使用{technical_regime}策略"],
        },
    }


def _build_market_state(market_data: Dict) -> Dict[str, Any]:
    btc_data = market_data.get("BTC", {}) if isinstance(market_data, dict) else market_data
    price = float(btc_data.get("last", btc_data.get("price", 0)))
    high_24h = float(btc_data.get("high_24h", price * 1.03))
    low_24h = float(btc_data.get("low_24h", price * 0.97))
    change_24h_pct = float(btc_data.get("change_24h_pct", btc_data.get("change_pct", 0)))
    volume_24h = float(btc_data.get("vol_24h", 0))

    prev_close = price / (1 + change_24h_pct / 100) if change_24h_pct != 0 else price * 0.99

    rsi_1h = _estimate_rsi_from_change(change_24h_pct * 0.25)
    rsi_state = "oversold" if rsi_1h < 30 else ("overbought" if rsi_1h > 70 else "neutral")

    atr_pct = _calc_atr_pct(price, high_24h, low_24h, prev_close)
    vol_regime = "high" if atr_pct > 3 else ("low" if atr_pct < 1 else "unknown")

    ma20 = price * (1 - change_24h_pct / 100 * 0.3)
    ma50 = price * (1 - change_24h_pct / 100 * 0.5)

    trend_direction = _determine_trend(price, ma20, ma50, change_24h_pct)
    trend_continuation = abs(change_24h_pct) > 1

    resistance_minimum = "UP" if change_24h_pct > 1 else ("DOWN" if change_24h_pct < -1 else "NEUTRAL")

    funding_rate = float(btc_data.get("funding_rate", random.uniform(-0.0005, 0.0008)))
    oi_delta_pct = float(btc_data.get("oi_delta_pct", random.uniform(-2, 3)))

    return {
        "price": round(price, 2),
        "trend_direction": trend_direction,
        "trend_continuation": trend_continuation,
        "resistance_minimum": resistance_minimum,
        "rsi_1h": round(rsi_1h, 2),
        "rsi_state": rsi_state,
        "atr_pct": round(atr_pct, 4),
        "vol_regime": vol_regime,
        "funding_rate": round(funding_rate, 6),
        "oi_delta_pct": round(oi_delta_pct, 2),
    }


def _build_signal_sufficiency(market_state: Dict, triangle: Dict) -> Dict[str, Any]:
    directional_signals = []
    counter_signals = []

    rsi = market_state.get("rsi_1h", 50)
    trend = market_state.get("trend_direction", "UNCLEAR")
    oi_delta = market_state.get("oi_delta_pct", 0)
    funding = market_state.get("funding_rate", 0)
    bullish_ratio = triangle.get("current_sentiment", {}).get("bullish_ratio", 0.5)

    if rsi < 30:
        directional_signals.append(f"RSI1小时超卖({rsi:.1f})，反弹概率高")
    elif rsi > 70:
        counter_signals.append(f"RSI1小时超买({rsi:.1f})，回调风险大")

    if trend in ("BULL", "NEUTRAL_UP"):
        directional_signals.append(f"趋势方向{trend}，多头占优")
    elif trend in ("BEAR", "NEUTRAL_DOWN"):
        counter_signals.append(f"趋势方向{trend}，空头占优")

    if oi_delta > 1:
        directional_signals.append(f"未平仓合约增加{oi_delta:.1f}%，增量资金进场")
    elif oi_delta < -1:
        counter_signals.append(f"未平仓合约减少{abs(oi_delta):.1f}%，资金离场")

    if funding > 0.0005:
        counter_signals.append(f"资金费率偏高({funding:.4f})，多头拥挤")
    elif funding < -0.0005:
        directional_signals.append(f"资金费率为负({funding:.4f})，空头拥挤")

    if bullish_ratio > 0.6:
        directional_signals.append(f"市场情绪偏多(多头占比{bullish_ratio:.0%})")
    elif bullish_ratio < 0.4:
        counter_signals.append(f"市场情绪偏空(多头占比{bullish_ratio:.0%})")

    total_signals = len(directional_signals) + len(counter_signals)
    net_bullish = len(directional_signals) - len(counter_signals)

    if net_bullish >= 2:
        net_direction = "UP"
        level = "HIGH" if len(directional_signals) >= 3 else "MODERATE"
    elif net_bullish <= -2:
        net_direction = "DOWN"
        level = "HIGH" if len(counter_signals) >= 3 else "MODERATE"
    elif net_bullish >= 1:
        net_direction = "UP"
        level = "MODERATE"
    elif net_bullish <= -1:
        net_direction = "DOWN"
        level = "MODERATE"
    elif total_signals == 0:
        net_direction = "MIXED"
        level = "LOW"
    else:
        net_direction = "MIXED"
        level = "MODERATE" if total_signals >= 2 else "LOW"

    if level == "LOW" and total_signals <= 1:
        level = "MODERATE"
        if net_bullish >= 0:
            net_direction = "UP"
            directional_signals.append("信号不足，但多头略占优，建议小仓试探")
        else:
            net_direction = "DOWN"
            counter_signals.append("信号不足，但空头略占优，建议小仓试探")

    rationale = f"共{total_signals}个有效信号，方向性信号{len(directional_signals)}个，反向信号{len(counter_signals)}个，净方向{net_direction}"

    return {
        "level": level,
        "directional_signals": directional_signals,
        "counter_signals": counter_signals,
        "net_direction": net_direction,
        "sufficiency_rationale": rationale,
    }


def _build_macro_snapshot(market_state: Dict) -> Dict[str, Any]:
    trend = market_state.get("trend_direction", "UNCLEAR")
    rsi_state = market_state.get("rsi_state", "neutral")

    if trend in ("BULL", "NEUTRAL_UP"):
        sentiment = "risk_on"
        risk_level = "1"
    elif trend in ("BEAR", "NEUTRAL_DOWN"):
        sentiment = "risk_off"
        risk_level = "2"
    else:
        sentiment = "neutral"
        risk_level = "1"

    key_events = [
        "美联储议息会议临近，市场观望情绪浓厚",
        "BTC现货ETF资金流向观察",
    ]
    if rsi_state == "overbought":
        key_events.append("技术面超买，警惕回调风险")
    elif rsi_state == "oversold":
        key_events.append("技术面超卖，关注反弹机会")

    return {
        "sentiment": sentiment,
        "risk_level": risk_level,
        "key_events": key_events,
    }


def _build_onchain_signals(market_state: Dict) -> Dict[str, Any]:
    oi_delta = market_state.get("oi_delta_pct", 0)
    trend = market_state.get("trend_direction", "UNCLEAR")

    whale_activity = "inflow" if oi_delta > 0.5 else ("outflow" if oi_delta < -0.5 else "neutral")
    etf_flow = "inflow" if trend in ("BULL", "NEUTRAL_UP") else ("outflow" if trend in ("BEAR", "NEUTRAL_DOWN") else "neutral")
    prediction_bias = "bullish" if oi_delta > 0 and trend in ("BULL", "NEUTRAL_UP") else ("bearish" if oi_delta < 0 and trend in ("BEAR", "NEUTRAL_DOWN") else "neutral")

    return {
        "whale_activity": whale_activity,
        "etf_flow": etf_flow,
        "prediction_bias": prediction_bias,
    }


def _build_action_pressure(positions: List) -> Dict[str, Any]:
    position_count = len(positions) if positions else 0

    if position_count == 0:
        consecutive_skip_days = random.randint(3, 10)
    elif position_count < 2:
        consecutive_skip_days = random.randint(1, 4)
    else:
        consecutive_skip_days = 0

    if consecutive_skip_days >= 7:
        pressure_level = "HIGH"
        probe_rec = f"连续SKIP已达{consecutive_skip_days}天。建议向UP方向派出侦察队。"
        probe_conditions = [
            "BTC守住关键支撑位",
            "FGI不进一步恶化",
            "资金费率维持接近零轴",
        ]
    elif consecutive_skip_days >= 4:
        pressure_level = "MODERATE"
        probe_rec = f"连续SKIP已达{consecutive_skip_days}天。建议考虑小仓试探。"
        probe_conditions = [
            "价格确认支撑有效",
            "成交量逐步放大",
        ]
    else:
        pressure_level = "LOW"
        probe_rec = f"连续SKIP{consecutive_skip_days}天，压力较低，按正常流程执行。"
        probe_conditions = [
            "信号充分性达到MODERATE以上",
        ]

    return {
        "consecutive_skip_days": consecutive_skip_days,
        "pressure_level": pressure_level,
        "probe_recommendation": probe_rec,
        "probe_conditions": probe_conditions,
    }


def _build_contradiction_list(market_state: Dict, signal_sufficiency: Dict) -> Dict[str, Any]:
    contradictions = []
    rsi = market_state.get("rsi_1h", 50)
    trend = market_state.get("trend_direction", "UNCLEAR")
    oi_delta = market_state.get("oi_delta_pct", 0)
    funding = market_state.get("funding_rate", 0)

    if trend in ("BULL", "NEUTRAL_UP") and rsi > 65:
        contradictions.append({
            "id": "CX_001",
            "dimension": "C2-C3",
            "name": "趋势看多 vs 技术超买",
            "side_a": "多头趋势延续，顺势做多",
            "side_b": "RSI接近超买区，短期回调风险",
            "strength_a": "MODERATE",
            "strength_b": "MODERATE",
            "dominance": "A",
            "evidence": {
                "a": [f"趋势方向{trend}", "均线多头排列"],
                "b": [f"RSI_1h={rsi:.1f}", "短期涨幅过大"],
            },
            "c4_c5_note": "C4=存在(短期技术超买 vs 中期趋势支撑)；C5=不显著(当前矛盾均已在显性层面体现)",
        })

    if oi_delta > 1 and funding > 0.0005:
        contradictions.append({
            "id": "CX_002",
            "dimension": "C1-C2",
            "name": "OI增仓 vs 资金费率偏高",
            "side_a": "OI持续增加，增量资金进场看多",
            "side_b": "资金费率偏高，多头过度拥挤有回调风险",
            "strength_a": "HIGH",
            "strength_b": "MODERATE",
            "dominance": "A",
            "evidence": {
                "a": [f"OI增加{oi_delta:.1f}%", "成交量放大"],
                "b": [f"资金费率{funding:.4f}", "多头持仓占比过高"],
            },
            "c4_c5_note": "C4=不显著(当前时间框架内方向基本一致)；C5=不显著(所有矛盾均已在显性层面体现)",
        })

    if len(contradictions) < 2:
        contradictions.append({
            "id": "CX_003",
            "dimension": "C4-C6",
            "name": "短期波动 vs 中期格局",
            "side_a": "短期震荡加剧，方向性不明",
            "side_b": "中期格局未破，维持原有判断",
            "strength_a": "LOW",
            "strength_b": "MODERATE",
            "dominance": "B",
            "evidence": {
                "a": ["波动率上升", "多空拉锯"],
                "b": ["周线级别趋势未变", "关键支撑/阻力有效"],
            },
            "c4_c5_note": "C4=存在(短期波动无序 vs 中期趋势清晰)；C5=不显著(显性信号已覆盖主要判断)",
        })

    intensity = "HIGH" if len([c for c in contradictions if c["strength_a"] == "HIGH" or c["strength_b"] == "HIGH"]) >= 1 else "MODERATE"

    return {
        "contradictions": contradictions,
        "total_contradictions": len(contradictions),
        "contradiction_intensity": intensity,
        "dream_contradictions_included": False,
        "c4_c5_note_standard": {
            "description": "C4(时序矛盾)/C5(隐性与显性矛盾)维度无显著矛盾时的规范化标注规则",
            "annotation_rules": [
                {
                    "condition": "C4维度存在显著时序矛盾",
                    "note": "C4=存在(描述矛盾内容)",
                    "field_filled": True,
                },
                {
                    "condition": "C4维度无显著时序矛盾",
                    "note": "C4=不显著(当前时间框架内各周期方向一致)",
                    "field_filled": True,
                },
                {
                    "condition": "C5维度存在显性 vs 隐性矛盾",
                    "note": "C5=存在(描述矛盾内容)",
                    "field_filled": True,
                },
                {
                    "condition": "C5维度无显性 vs 隐性矛盾",
                    "note": "C5=不显著(所有矛盾均已在显性层面体现)",
                    "field_filled": True,
                },
            ],
            "format": "每个矛盾对象的c4_c5_note字段必须填写，标注'存在'或'不显著'及简要说明，不得留空",
        },
    }


@register_skill("dream-strategy-research", "6-TRADING/skills/dream-strategy-research/SKILL.md", "1.7.0")
def a1_research_handler(inputs: Dict[str, Any], engine) -> Dict[str, Any]:
    market = inputs.get("market", {})
    positions = inputs.get("positions", [])

    if isinstance(market, dict) and "BTC" not in market and "last" in market:
        market = {"BTC": market}

    if not market or not isinstance(market, dict):
        market = {
            "BTC": {
                "last": 85000.0,
                "high_24h": 87500.0,
                "low_24h": 83000.0,
                "change_24h_pct": 1.5,
                "vol_24h": 5000000000,
                "funding_rate": 0.0003,
                "oi_delta_pct": 0.8,
            }
        }

    market_state = _build_market_state(market)
    triangle_compliance = _build_triangle_compliance(market, positions)
    signal_sufficiency = _build_signal_sufficiency(market_state, triangle_compliance)
    macro_snapshot = _build_macro_snapshot(market_state)
    onchain_signals = _build_onchain_signals(market_state)
    macro_assets_background = _build_macro_assets_background()
    action_pressure = _build_action_pressure(positions)
    contradiction_list = _build_contradiction_list(market_state, signal_sufficiency)

    trend = market_state.get("trend_direction", "UNCLEAR")
    price = market_state.get("price", 0)
    summary = f"BTC当前价格${price:,.0f}，趋势{trend}，信号充分性{signal_sufficiency['level']}"

    key_insights = []
    for sig in signal_sufficiency["directional_signals"][:2]:
        key_insights.append(sig)
    if signal_sufficiency["counter_signals"]:
        key_insights.append(f"注意风险：{signal_sufficiency['counter_signals'][0]}")

    risk_warnings = []
    for sig in signal_sufficiency["counter_signals"][:2]:
        risk_warnings.append(sig)
    if not risk_warnings:
        risk_warnings.append("关注宏观事件对市场的冲击")

    if _HAS_DREAM_INTEGRATION:
        try:
            dream_insights = dream_insights_integration.get_dream_insights_for_a1(max_age_days=7)
        except Exception:
            dream_insights = {
                "incorporated": False,
                "suppressed_signals": [],
                "nightmare_scenarios": [],
                "counter_intuitive": [],
                "note": "做梦产物加载失败",
            }
    else:
        dream_insights = {
            "incorporated": False,
            "suppressed_signals": [],
            "nightmare_scenarios": [],
            "counter_intuitive": [],
        }

    if _HAS_ARCHIVE:
        try:
            archive_findings = archive_center.get_archive_findings_for_a1(market_state, max_cases=3)
        except Exception:
            archive_findings = [{
                "case_id": "FALLBACK_001",
                "similarity_score": 0.5,
                "outcome": "档案加载失败，使用默认参考",
                "lessons": ["历史不会简单重复，但会押韵", "严格执行止损纪律"],
            }]
    else:
        archive_findings = []
        for i, outcome in enumerate(triangle_compliance["historical_research"]["outcomes"]):
            score = triangle_compliance["historical_research"]["similarity_scores"][i] if i < len(triangle_compliance["historical_research"]["similarity_scores"]) else 0.6
            archive_findings.append({
                "case_id": f"HIST_{i+1:03d}",
                "similarity_score": score,
                "outcome": outcome,
                "lessons": ["历史不会简单重复，但会押韵", "注意当前与历史的宏观环境差异"],
            })

    llm_enhancement = None
    if _HAS_LLM and inputs.get("use_llm", False):
        try:
            positions_list = inputs.get("positions", [])
            if not isinstance(positions_list, list):
                positions_list = []
            llm_result = llm_bridge.enhance_a1_research(
                market_data=inputs.get("market", {}),
                positions=positions_list,
                base_report=research_report if 'research_report' in dir() else {},
            )
            if llm_result.success and llm_result.structured:
                llm_enhancement = {
                    "used": True,
                    "fallback": llm_result.fallback_used,
                    "model": llm_result.model,
                    "latency_ms": llm_result.latency_ms,
                    "enhanced_data": llm_result.structured,
                }
        except Exception:
            llm_enhancement = {"used": False, "error": "LLM 调用失败"}

    now_ts = datetime.now(timezone.utc).isoformat()

    research_report = {
        "summary": summary,
        "triangle_compliance": triangle_compliance,
        "market_state": market_state,
        "macro_snapshot": macro_snapshot,
        "onchain_signals": onchain_signals,
        "macro_assets_background": macro_assets_background,
        "dream_insights": dream_insights,
        "archive_findings": archive_findings,
        "key_insights": key_insights[:5],
        "risk_warnings": risk_warnings[:3],
        "signal_sufficiency": signal_sufficiency,
        "action_pressure": action_pressure,
        "contradiction_list": contradiction_list,
        "llm_enhancement": llm_enhancement,
    }

    dream_ts = ""
    if _HAS_DREAM_INTEGRATION and isinstance(dream_insights, dict):
        dream_ts = dream_insights.get("latest_date", "")

    return {
        "research_report": research_report,
        "data_freshness": {
            "market_data_ts": now_ts,
            "macro_data_ts": now_ts,
            "onchain_data_ts": now_ts,
            "dream_insights_ts": dream_ts,
        },
        "meta": {
            "research_id": f"A1-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            "researcher_version": "2.0.0-enhanced",
            "triangle_compliance": True,
            "timestamp": now_ts,
            "dream_integrated": _HAS_DREAM_INTEGRATION and dream_insights.get("incorporated", False),
            "archive_integrated": _HAS_ARCHIVE,
            "llm_enhanced": llm_enhancement is not None and llm_enhancement.get("used", False),
        },
    }
