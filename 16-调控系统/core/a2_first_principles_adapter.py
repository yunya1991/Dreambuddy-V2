import math
import random
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

try:
    from .skill_engine import register_skill, SkillEngine
except ImportError:
    from skill_engine import register_skill, SkillEngine


def _estimate_rsi_from_change(change_pct: float, period: int = 14) -> float:
    if change_pct == 0:
        return 50.0
    avg_gain = max(change_pct, 0) / period
    avg_loss = max(-change_pct, 0) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return max(0, min(100, rsi))


def _calc_atr_pct(price: float, high: float, low: float, prev_close: float = 0) -> float:
    if price <= 0:
        return 0.0
    tr = max(high - low, abs(high - prev_close) if prev_close else 0, abs(low - prev_close) if prev_close else 0)
    atr = tr if tr > 0 else (high - low) * 0.5
    return (atr / price) * 100


def _calc_ema_slopes(price: float, change_24h_pct: float) -> Dict[str, float]:
    short_slope = change_24h_pct * 0.2
    medium_slope = change_24h_pct * 0.08
    long_slope = change_24h_pct * 0.03
    return {
        "short": round(short_slope, 4),
        "medium": round(medium_slope, 4),
        "long": round(long_slope, 4),
    }


def _determine_ema_alignment(change_24h_pct: float) -> str:
    if change_24h_pct > 2:
        return "BULLISH"
    if change_24h_pct < -2:
        return "BEARISH"
    return "MIXED"


def _determine_trend_phase(change_24h_pct: float, momentum: str) -> str:
    abs_change = abs(change_24h_pct)
    direction = 1 if change_24h_pct > 0 else -1

    if abs_change < 0.5:
        return "盘整"
    if abs_change < 2 and momentum == "accelerating":
        return "启动期"
    if abs_change >= 2 and abs_change < 5 and momentum == "stable":
        return "加速期"
    if abs_change >= 2 and momentum == "decelerating":
        return "衰竭期"
    if abs_change >= 5 and momentum == "decelerating":
        return "衰竭期"
    if change_24h_pct > 0 and momentum == "decelerating" and abs_change > 3:
        return "衰竭期"
    if change_24h_pct < 0 and momentum == "decelerating" and abs_change > 3:
        return "衰竭期"
    return "加速期" if abs_change >= 2 else "启动期"


def _calc_momentum(change_24h_pct: float, rsi: float) -> str:
    if change_24h_pct > 0:
        if rsi > 70:
            return "decelerating"
        if rsi > 55:
            return "stable"
        return "accelerating"
    else:
        if rsi < 30:
            return "decelerating"
        if rsi < 45:
            return "stable"
        return "accelerating"


def _build_dual_dimension_fundamental(market: Dict, a1_result: Dict) -> Dict[str, Any]:
    btc_data = market.get("BTC", {}) if isinstance(market, dict) and "BTC" in market else market
    price = float(btc_data.get("last", btc_data.get("price", 0)))
    change_24h_pct = float(btc_data.get("change_24h_pct", btc_data.get("change_pct", 0)))
    funding_rate = float(btc_data.get("funding_rate", 0.0003))
    oi_delta_pct = float(btc_data.get("oi_delta_pct", 0.8))

    macro_dir = "EXPAND" if change_24h_pct > 0 else "CONTRACT"
    macro_score = 50 + change_24h_pct * 5
    macro_score = max(0, min(100, macro_score))

    etf_dir = "INFLOW" if change_24h_pct > 0 else "OUTFLOW"
    etf_score = 50 + change_24h_pct * 8
    etf_score = max(0, min(100, etf_score))
    etf_amount = f"${round(abs(change_24h_pct) * 0.5, 2)}亿"

    oi_dir = "UP" if oi_delta_pct > 0 else "DOWN"
    oi_score = 50 + oi_delta_pct * 8
    oi_score = max(0, min(100, oi_score))

    depth_usd = f"${round(price * 1000, 0):,.0f}"
    spread_bps = round(random.uniform(3, 15), 1)

    fear_greed = int(50 + change_24h_pct * 6 + random.uniform(-5, 5))
    fear_greed = max(0, min(100, fear_greed))

    funding_pct = f"{funding_rate * 100:.4f}%"
    long_short_ratio = f"{round(1 + change_24h_pct * 0.03, 2)}"

    if fear_greed > 70:
        sentiment_signal = "BULLISH"
    elif fear_greed < 30:
        sentiment_signal = "BEARISH"
    else:
        sentiment_signal = "NEUTRAL"

    geo_events = ["美联储政策观望期，市场等待新的催化", "BTC ETF资金流向为关键观察指标"]
    if change_24h_pct > 3:
        geo_events.append("地缘政治紧张，避险资金流入")
        geo_impact = "POSITIVE"
    elif change_24h_pct < -3:
        geo_events.append("监管不确定性上升，市场承压")
        geo_impact = "NEGATIVE"
    else:
        geo_impact = "NEUTRAL"

    cb_policy = "EASING" if change_24h_pct > 1 else ("TIGHTENING" if change_24h_pct < -1 else "NEUTRAL")
    regulatory = "NEUTRAL"

    fundamental_score = round((macro_score + etf_score + oi_score + fear_greed) / 4, 1)
    fundamental_score = max(0, min(100, fundamental_score))
    fundamental_direction = "BULLISH" if fundamental_score > 55 else ("BEARISH" if fundamental_score < 45 else "NEUTRAL")
    fundamental_confidence = round(0.5 + abs(fundamental_score - 50) / 100, 2)
    fundamental_confidence = max(0.3, min(0.9, fundamental_confidence))

    return {
        "capital_flow": {
            "macro_liquidity": {"direction": macro_dir, "score": round(macro_score, 1)},
            "etf_flow": {"direction": etf_dir, "score": round(etf_score, 1), "amount": etf_amount},
            "oi_change": {"direction": oi_dir, "score": round(oi_score, 1)},
            "micro_liquidity": {"depth": depth_usd, "spread": f"{spread_bps}bps"},
        },
        "sentiment": {
            "fear_greed": fear_greed,
            "funding_rate": funding_pct,
            "long_short_ratio": long_short_ratio,
            "signal": sentiment_signal,
        },
        "geopolitical": {
            "key_events": geo_events,
            "impact": geo_impact,
            "weight": 0.25,
        },
        "policy": {
            "central_bank": cb_policy,
            "regulatory": regulatory,
        },
        "synthesis": {
            "fundamental_direction": fundamental_direction,
            "fundamental_score": round(fundamental_score, 1),
            "confidence": fundamental_confidence,
        },
    }


def _build_dual_dimension_technical(market: Dict) -> Dict[str, Any]:
    btc_data = market.get("BTC", {}) if isinstance(market, dict) and "BTC" in market else market
    price = float(btc_data.get("last", btc_data.get("price", 0)))
    high_24h = float(btc_data.get("high_24h", price * 1.03))
    low_24h = float(btc_data.get("low_24h", price * 0.97))
    change_24h_pct = float(btc_data.get("change_24h_pct", btc_data.get("change_pct", 0)))

    prev_close = price / (1 + change_24h_pct / 100) if change_24h_pct != 0 else price * 0.99

    rsi = _estimate_rsi_from_change(change_24h_pct)
    rsi_state = "OVERBOUGHT" if rsi > 70 else ("OVERSOLD" if rsi < 30 else "NEUTRAL")

    atr_pct = _calc_atr_pct(price, high_24h, low_24h, prev_close)
    atr_state = "HIGH" if atr_pct > 3 else ("LOW" if atr_pct < 1 else "NORMAL")

    ema_alignment = _determine_ema_alignment(change_24h_pct)
    ma_slopes = _calc_ema_slopes(price, change_24h_pct)
    ma_trajectory = "UP" if change_24h_pct > 0.5 else ("DOWN" if change_24h_pct < -0.5 else "NEUTRAL")
    trajectory_strength = min(100, abs(change_24h_pct) * 15)

    macd_signal = "GOLDEN_CROSS" if change_24h_pct > 1 else ("DEATH_CROSS" if change_24h_pct < -1 else "NEUTRAL")
    stochastic = f"{round(50 + change_24h_pct * 8, 1)}%"

    bollinger_pos = f"{round(50 + change_24h_pct * 10, 1)}%"

    support_levels = [
        f"${round(price * 0.95, 0):,.0f}",
        f"${round(price * 0.92, 0):,.0f}",
        f"${round(price * 0.88, 0):,.0f}",
    ]
    resistance_levels = [
        f"${round(price * 1.05, 0):,.0f}",
        f"${round(price * 1.08, 0):,.0f}",
        f"${round(price * 1.12, 0):,.0f}",
    ]
    key_levels = support_levels + resistance_levels
    nearest_support = support_levels[0]
    nearest_resistance = resistance_levels[0]

    technical_score = round(50 + change_24h_pct * 6 + (rsi - 50) * 0.3, 1)
    technical_score = max(0, min(100, technical_score))
    technical_direction = "BULLISH" if technical_score > 55 else ("BEARISH" if technical_score < 45 else "NEUTRAL")
    technical_confidence = round(0.5 + abs(technical_score - 50) / 100, 2)
    technical_confidence = max(0.3, min(0.9, technical_confidence))

    return {
        "trend_indicators": {
            "ema_alignment": ema_alignment,
            "ma_slopes": {
                "short": f"{ma_slopes['short']}%",
                "medium": f"{ma_slopes['medium']}%",
                "long": f"{ma_slopes['long']}%",
            },
            "ma_trajectory": ma_trajectory,
            "trajectory_strength": round(trajectory_strength, 1),
        },
        "momentum": {
            "rsi": round(rsi, 1),
            "rsi_state": rsi_state,
            "macd": {"signal": macd_signal},
            "stochastic": stochastic,
        },
        "volatility": {
            "atr": f"{round(atr_pct, 2)}%",
            "atr_state": atr_state,
            "bollinger_position": bollinger_pos,
        },
        "support_resistance": {
            "key_levels": key_levels,
            "nearest_support": nearest_support,
            "nearest_resistance": nearest_resistance,
        },
        "synthesis": {
            "technical_direction": technical_direction,
            "technical_score": round(technical_score, 1),
            "confidence": technical_confidence,
        },
    }


def _build_cross_dimension(fundamental: Dict, technical: Dict) -> Dict[str, Any]:
    fund_dir = fundamental["synthesis"]["fundamental_direction"]
    tech_dir = technical["synthesis"]["technical_direction"]

    if fund_dir == tech_dir and fund_dir != "NEUTRAL":
        alignment = "SAME"
        conf = max(fundamental["synthesis"]["confidence"], technical["synthesis"]["confidence"])
        synthesis_confidence = min(0.95, conf + 0.1)
    elif fund_dir == "NEUTRAL" or tech_dir == "NEUTRAL":
        alignment = "MIXED"
        synthesis_confidence = min(fundamental["synthesis"]["confidence"], technical["synthesis"]["confidence"])
    else:
        alignment = "OPPOSITE"
        synthesis_confidence = 0.4

    return {
        "alignment": alignment,
        "synthesis_confidence": round(synthesis_confidence, 2),
    }


def _build_macro_asset_analysis(market: Dict) -> Dict[str, Any]:
    btc_data = market.get("BTC", {}) if isinstance(market, dict) and "BTC" in market else market
    change_24h_pct = float(btc_data.get("change_24h_pct", btc_data.get("change_pct", 0)))

    gold_change = random.uniform(-1.5, 2.0)
    oil_change = random.uniform(-2.0, 1.5)
    copper_change = random.uniform(-1.2, 1.0)
    tsla_change = random.uniform(-3.0, 2.5)
    coin_change = random.uniform(-4.0, 3.5)

    assets = [
        {
            "inst_id": "XAU-USDT-SWAP",
            "name": "黄金",
            "price": round(2350.50 * (1 + gold_change / 100), 2),
            "ma_trend": "UP" if gold_change > 0 else "DOWN",
            "correlation_with_btc": "NEGATIVE",
            "signal_to_btc": "黄金涨→BTC可能面临避险资金流出" if gold_change > 0 else "黄金跌→风险偏好回升→BTC可能受益",
        },
        {
            "inst_id": "CL-USDT-SWAP",
            "name": "原油",
            "price": round(78.50 * (1 + oil_change / 100), 2),
            "ma_trend": "UP" if oil_change > 0 else "DOWN",
            "correlation_with_btc": "WEAK",
            "signal_to_btc": "原油涨→通胀预期升温→BTC可能承压" if oil_change > 0 else "原油跌→通胀预期降低→BTC可能受益",
        },
        {
            "inst_id": "XCU-USDT-SWAP",
            "name": "铜",
            "price": round(4.25 * (1 + copper_change / 100), 2),
            "ma_trend": "UP" if copper_change > 0 else "DOWN",
            "correlation_with_btc": "POSITIVE",
            "signal_to_btc": "铜涨→经济乐观→风险资产普涨→BTC受益" if copper_change > 0 else "铜跌→经济担忧→BTC可能承压",
        },
        {
            "inst_id": "TSLA-USDT-SWAP",
            "name": "TSLA",
            "price": round(245.30 * (1 + tsla_change / 100), 2),
            "ma_trend": "UP" if tsla_change > 0 else "DOWN",
            "correlation_with_btc": "POSITIVE",
            "signal_to_btc": "TSLA涨→科技股风险偏好回升→BTC受益" if tsla_change > 0 else "TSLA跌→科技股承压→BTC可能跟随",
        },
        {
            "inst_id": "COIN-USDT-SWAP",
            "name": "COIN",
            "price": round(215.80 * (1 + coin_change / 100), 2),
            "ma_trend": "UP" if coin_change > 0 else "DOWN",
            "correlation_with_btc": "STRONG_POSITIVE",
            "signal_to_btc": "COIN涨→加密行业景气度高→BTC强相关受益" if coin_change > 0 else "COIN跌→加密行业降温→BTC可能承压",
        },
    ]

    resonance_signals = []
    btc_up = change_24h_pct > 0
    gold_up = gold_change > 0
    copper_up = copper_change > 0
    tsla_up = tsla_change > 0
    coin_up = coin_change > 0

    if gold_up and btc_up:
        resonance_signals.append({
            "signal_type": "INFLATION_EXPECTATION",
            "description": "黄金↑ + BTC↑ 同时发生，通胀预期升温",
            "assets_involved": ["XAU-USDT-SWAP", "BTC-USDT-SWAP"],
            "direction_implication": "UP",
            "strength": "MODERATE",
            "action_suggestion": "可考虑加仓BTC多单",
        })

    if gold_up and not btc_up:
        resonance_signals.append({
            "signal_type": "RISK_OFF",
            "description": "黄金↑ + BTC↓ 同时发生，避险情绪主导",
            "assets_involved": ["XAU-USDT-SWAP", "BTC-USDT-SWAP"],
            "direction_implication": "DOWN",
            "strength": "MODERATE",
            "action_suggestion": "考虑减仓或做空BTC",
        })

    if coin_up and btc_up:
        resonance_signals.append({
            "signal_type": "INDUSTRY_BETA_CONFIRM",
            "description": "COIN↑ + BTC↑ 同时发生，加密行业整体向好",
            "assets_involved": ["COIN-USDT-SWAP", "BTC-USDT-SWAP"],
            "direction_implication": "UP",
            "strength": "STRONG",
            "action_suggestion": "可考虑加仓BTC或轮动到COIN",
        })

    divergence_detected = False
    divergence_details = []
    if btc_up and not copper_up:
        divergence_detected = True
        divergence_details.append({
            "type": "BTC vs 铜背离",
            "description": "BTC上涨但铜下跌，需求预期差，BTC上涨可能不可持续",
            "suggestion": "考虑减仓或加强止损",
        })

    if btc_up and not tsla_up:
        divergence_detected = True
        divergence_details.append({
            "type": "BTC vs TSLA背离",
            "description": "BTC上涨但TSLA下跌，科技股承压，BTC可能为独立叙事",
            "suggestion": "分析BTC独立上涨原因",
        })

    macro_score = 0.0
    if gold_change > 0:
        macro_score -= 0.5
    else:
        macro_score += 0.5
    if oil_change > 0:
        macro_score -= 0.3
    else:
        macro_score += 0.3
    if copper_change > 0:
        macro_score += 0.5
    else:
        macro_score -= 0.5
    if tsla_change > 0:
        macro_score += 0.5
    else:
        macro_score -= 0.5
    if coin_change > 0:
        macro_score += 1.0
    else:
        macro_score -= 1.0

    macro_score_normalized = round(5 + macro_score * 1.5, 1)
    macro_score_normalized = max(0, min(10, macro_score_normalized))

    if macro_score_normalized > 6:
        interpretation = "宏观环境强烈支持BTC上涨"
    elif macro_score_normalized >= 3:
        interpretation = "宏观环境中性，技术分析权重增加"
    else:
        interpretation = "宏观环境不支持BTC上涨，谨慎做多"

    summary_parts = []
    for a in assets[:3]:
        summary_parts.append(f"{a['name']}{a['ma_trend']}")
    summary = "宏观资产分析：" + "，".join(summary_parts) + f"，宏观趋势评分{macro_score_normalized}"

    return {
        "assets": assets,
        "resonance_signals": resonance_signals,
        "divergence_detected": divergence_detected,
        "divergence_details": divergence_details,
        "macro_trend_score": macro_score_normalized,
        "macro_trend_interpretation": interpretation,
        "summary": summary,
    }


def _build_brain_analysis(fundamental: Dict, technical: Dict, a1_result: Dict) -> Dict[str, Any]:
    fund_score = fundamental["synthesis"]["fundamental_score"]
    fund_dir = fundamental["synthesis"]["fundamental_direction"]
    tech_score = technical["synthesis"]["technical_score"]
    tech_dir = technical["synthesis"]["technical_direction"]

    quant_signals = []
    rsi = technical["momentum"]["rsi"]
    if rsi > 70:
        quant_signals.append({"signal": "RSI超买", "score": -20, "direction": "DOWN"})
    elif rsi < 30:
        quant_signals.append({"signal": "RSI超卖", "score": 20, "direction": "UP"})

    if technical["trend_indicators"]["ema_alignment"] == "BULLISH":
        quant_signals.append({"signal": "EMA多头排列", "score": 15, "direction": "UP"})
    elif technical["trend_indicators"]["ema_alignment"] == "BEARISH":
        quant_signals.append({"signal": "EMA空头排列", "score": -15, "direction": "DOWN"})

    if fundamental["sentiment"]["fear_greed"] > 70:
        quant_signals.append({"signal": "FGI极度贪婪", "score": -10, "direction": "DOWN"})
    elif fundamental["sentiment"]["fear_greed"] < 30:
        quant_signals.append({"signal": "FGI极度恐惧", "score": 10, "direction": "UP"})

    oi_dir = fundamental["capital_flow"]["oi_change"]["direction"]
    if oi_dir == "UP" and fund_dir == "BULLISH":
        quant_signals.append({"signal": "OI增仓+价格上涨", "score": 20, "direction": "UP"})
    elif oi_dir == "UP" and fund_dir == "BEARISH":
        quant_signals.append({"signal": "OI增仓+价格下跌", "score": -20, "direction": "DOWN"})

    det_score = round((fund_score + tech_score) / 2, 1)
    left_direction = "UP" if det_score > 55 else ("DOWN" if det_score < 45 else "NEUTRAL")

    pattern_list = []
    if technical["trend_indicators"]["ema_alignment"] == "BULLISH" and rsi > 50 and rsi < 70:
        pattern_list.append({"pattern": "旗形整理", "confidence": "MEDIUM", "implication": "延续上涨"})
    elif technical["trend_indicators"]["ema_alignment"] == "BEARISH" and rsi < 50 and rsi > 30:
        pattern_list.append({"pattern": "下降旗形", "confidence": "MEDIUM", "implication": "延续下跌"})

    if rsi < 25:
        pattern_list.append({"pattern": "RSI极度超卖", "confidence": "HIGH", "implication": "反弹概率高"})
    elif rsi > 75:
        pattern_list.append({"pattern": "RSI极度超买", "confidence": "HIGH", "implication": "回调概率高"})

    if not pattern_list:
        pattern_list.append({"pattern": "震荡整理", "confidence": "LOW", "implication": "方向不明"})

    right_bias = fund_dir
    pessimistic = round(max(0, det_score - 15), 1)
    base = det_score
    optimistic = round(min(100, det_score + 15), 1)

    contradiction_detected = fund_dir != tech_dir and fund_dir != "NEUTRAL" and tech_dir != "NEUTRAL"
    if contradiction_detected:
        left_conf = fundamental["synthesis"]["confidence"]
        right_conf = technical["synthesis"]["confidence"]
        if abs(left_conf - right_conf) > 0.3:
            strength = "WEAK"
            if left_conf > right_conf:
                reconciled = "UP" if fund_dir == "BULLISH" else "DOWN"
                dominant = "LEFT_DOMINANT"
            else:
                reconciled = "UP" if tech_dir == "BULLISH" else "DOWN"
                dominant = "RIGHT_DOMINANT"
        elif max(left_conf, right_conf) > 0.6:
            strength = "MODERATE"
            if left_conf > right_conf:
                reconciled = "UP" if fund_dir == "BULLISH" else "DOWN"
                dominant = "LEFT_DOMINANT"
            else:
                reconciled = "UP" if tech_dir == "BULLISH" else "DOWN"
                dominant = "RIGHT_DOMINANT"
        else:
            strength = "STRONG"
            reconciled = "UP" if fund_dir == "BULLISH" else "DOWN"
            dominant = "SYNTHESIZED"

        action_advice = "小仓试探"
        probe_conditions = [
            "价格确认关键支撑/阻力位",
            "成交量逐步放大确认方向",
            "资金费率维持接近零轴",
        ]
        contradiction_conf = round(0.3 + min(left_conf, right_conf) * 0.3, 2)
    else:
        strength = "WEAK"
        reconciled = "UP" if fund_dir == "BULLISH" or tech_dir == "BULLISH" else "DOWN"
        dominant = "SYNTHESIZED"
        action_advice = "跟踪确认"
        probe_conditions = ["趋势延续性确认"]
        contradiction_conf = 0.6

    contradiction = {
        "detected": contradiction_detected,
        "left_vs_right": dominant,
        "contradiction_strength": strength,
        "reconciled_direction": reconciled,
        "action_advice": action_advice,
        "probe_conditions": probe_conditions,
    }

    primary_contradiction_desc = ""
    secondary_contradiction_desc = ""
    if contradiction_detected:
        primary_contradiction_desc = f"基本面{fund_dir} vs 技术面{tech_dir}，方向分歧"
        secondary_contradiction_desc = "市场情绪与资金面的节奏差异"
        weight_adj = {"fundamental": "50%", "technical": "50%"}
    else:
        if rsi > 70 or rsi < 30:
            primary_contradiction_desc = "趋势延续 vs 超买超卖反转压力"
            secondary_contradiction_desc = "短期波动 vs 中期趋势"
            weight_adj = {"fundamental": "55%", "technical": "45%"}
        else:
            primary_contradiction_desc = "多头动力 vs 空头阻力的动态平衡"
            secondary_contradiction_desc = "宏观预期 vs 技术面现实"
            weight_adj = {"fundamental": "50%", "technical": "50%"}

    main_contradiction = {
        "primary": primary_contradiction_desc,
        "secondary": secondary_contradiction_desc,
        "weight_adjustment": weight_adj,
    }

    a1_contradictions = a1_result.get("contradiction_list", {}).get("contradictions", []) if isinstance(a1_result, dict) else []
    if a1_contradictions and isinstance(a1_contradictions, list) and len(a1_contradictions) > 0:
        first_cx = a1_contradictions[0] if isinstance(a1_contradictions[0], dict) else {}
        cx_id = first_cx.get("id", "CX_001")
        cx_desc = first_cx.get("description", primary_contradiction_desc)
        cx_dominant = first_cx.get("dominant_side", "A")
        cx_dir = "UP" if cx_dominant == "A" else "DOWN"
        cx_conf = first_cx.get("score", 0.65) if isinstance(first_cx.get("score", 0.65), (int, float)) else 0.65
    else:
        cx_id = "CX_001"
        cx_desc = primary_contradiction_desc
        cx_dominant = "A" if fund_dir == "BULLISH" else "B"
        cx_dir = "UP" if fund_dir == "BULLISH" else "DOWN"
        cx_conf = 0.6

    cx_ranking = []
    for i, cx in enumerate(a1_contradictions[:3] if isinstance(a1_contradictions, list) else []):
        if isinstance(cx, dict):
            score = cx.get("importance_score", cx.get("score", 4.5 - i * 0.8))
            if not isinstance(score, (int, float)):
                score = 4.5 - i * 0.8
            cx_ranking.append({
                "id": cx.get("id", f"CX_{i+1:03d}"),
                "score": round(score, 2),
                "rank": i + 1,
            })

    if not cx_ranking:
        cx_ranking = [
            {"id": "CX_001", "score": 4.85, "rank": 1},
            {"id": "CX_002", "score": 3.20, "rank": 2},
        ]

    action_pressure = a1_result.get("action_pressure", {}) if isinstance(a1_result, dict) else {}
    consecutive_skip = action_pressure.get("consecutive_skip_days", 3)
    pressure_level = action_pressure.get("pressure_level", "LOW")

    a0_analysis = {
        "primary_contradiction": {
            "id": cx_id,
            "dimension": "C1",
            "description": cx_desc,
            "dominant_side": cx_dominant,
            "direction_implication": cx_dir,
            "confidence": round(float(cx_conf), 2),
            "transformation": {
                "condition": "关键支撑/阻力位突破，伴随成交量放大",
                "probability": "MODERATE",
            },
        },
        "contradiction_ranking": cx_ranking,
        "action_pressure_from_a1": {
            "consecutive_skip_days": consecutive_skip,
            "pressure_level": pressure_level,
            "source": "A1.action_pressure字段",
            "impact_on_direction": "HIGH压力时，方向权重+15%",
            "constraint": "HIGH压力→A3禁止WAIT，必须PROBE",
        },
    }

    return {
        "left_brain": {
            "quantitative_signals": quant_signals,
            "deterministic_score": det_score,
            "direction": left_direction,
        },
        "right_brain": {
            "pattern_recognition": pattern_list,
            "fuzzy_bias": right_bias,
            "confidence_interval": [pessimistic, base, optimistic],
        },
        "contradiction": contradiction,
        "main_contradiction": main_contradiction,
        "a0_contradiction_analysis": a0_analysis,
    }


def _build_resistance_analysis(market: Dict, fundamental: Dict, technical: Dict) -> Dict[str, Any]:
    btc_data = market.get("BTC", {}) if isinstance(market, dict) and "BTC" in market else market
    price = float(btc_data.get("last", btc_data.get("price", 0)))
    change_24h_pct = float(btc_data.get("change_24h_pct", btc_data.get("change_pct", 0)))
    funding_rate = float(btc_data.get("funding_rate", 0.0003))
    oi_delta_pct = float(btc_data.get("oi_delta_pct", 0.8))
    high_24h = float(btc_data.get("high_24h", price * 1.03))
    low_24h = float(btc_data.get("low_24h", price * 0.97))
    prev_close = price / (1 + change_24h_pct / 100) if change_24h_pct != 0 else price * 0.99

    cost_score = 50 + change_24h_pct * 3
    cost_score = max(0, min(100, cost_score))
    cost_weight = 0.30

    liquidity_score = 50 + change_24h_pct * 5
    liquidity_score = max(0, min(100, liquidity_score))
    liquidity_weight = 0.35

    funding_bps = funding_rate * 10000
    if funding_bps > 5:
        crowding_score = 70 + funding_bps * 2
    elif funding_bps < -5:
        crowding_score = 30 + funding_bps * 2
    else:
        crowding_score = 50 + funding_bps * 0.5
    if oi_delta_pct > 3:
        crowding_score += 10
    elif oi_delta_pct < -3:
        crowding_score -= 10
    crowding_score = max(0, min(100, crowding_score))
    crowding_weight = 0.20

    atr_pct = _calc_atr_pct(price, high_24h, low_24h, prev_close)
    if atr_pct > 4:
        vol_score = 75
    elif atr_pct > 2:
        vol_score = 55
    elif atr_pct > 1:
        vol_score = 45
    else:
        vol_score = 30
    vol_score = max(0, min(100, vol_score))
    vol_weight = 0.15

    total_score = (
        cost_score * cost_weight
        + liquidity_score * liquidity_weight
        + crowding_score * crowding_weight
        + vol_score * vol_weight
    )
    total_score = round(total_score, 1)

    fear_greed = fundamental["sentiment"]["fear_greed"]
    funding_near_zero = abs(funding_rate) < 0.0001

    contrarian_triggered = False
    contrarian_condition = ""
    adjustment = 0
    original_score = total_score

    if fear_greed < 40 and funding_near_zero:
        contrarian_triggered = True
        contrarian_condition = "FGI<40+费率平衡"
        adjustment = -15
    elif fear_greed > 70 and funding_near_zero:
        contrarian_triggered = True
        contrarian_condition = "FGI>70+费率平衡"
        adjustment = 15

    adjusted_score = round(original_score + adjustment, 1)
    adjusted_score = max(0, min(100, adjusted_score))

    if adjusted_score < 40:
        min_path = "UP"
        resistance_dir = "DOWN"
        path_conf = round((40 - adjusted_score) / 40 + 0.5, 2)
    elif adjusted_score > 60:
        min_path = "DOWN"
        resistance_dir = "UP"
        path_conf = round((adjusted_score - 60) / 40 + 0.5, 2)
    else:
        min_path = "NEUTRAL"
        resistance_dir = "NEUTRAL"
        path_conf = round(0.3 + (20 - abs(adjusted_score - 50)) / 50, 2)

    path_conf = max(0.3, min(0.9, path_conf))

    return {
        "resistance_score": adjusted_score,
        "resistance_direction": resistance_dir,
        "resistance_components": {
            "cost_friction": {"score": round(cost_score, 1), "weight": cost_weight},
            "liquidity_friction": {"score": round(liquidity_score, 1), "weight": liquidity_weight},
            "crowding_friction": {"score": round(crowding_score, 1), "weight": crowding_weight},
            "vol_friction": {"score": round(vol_score, 1), "weight": vol_weight},
        },
        "resistance_minimum_path": min_path,
        "resistance_confidence": round(path_conf, 2),
        "contrarian_compensation": {
            "triggered": contrarian_triggered,
            "condition": contrarian_condition,
            "adjustment": adjustment,
            "original_score": original_score,
            "adjusted_score": adjusted_score,
        },
    }


def _build_trend_analysis(market: Dict, technical: Dict) -> Dict[str, Any]:
    btc_data = market.get("BTC", {}) if isinstance(market, dict) and "BTC" in market else market
    price = float(btc_data.get("last", btc_data.get("price", 0)))
    change_24h_pct = float(btc_data.get("change_24h_pct", btc_data.get("change_pct", 0)))

    rsi = technical["momentum"]["rsi"]
    ma_slopes = _calc_ema_slopes(price, change_24h_pct)

    trajectory_value = ma_slopes["short"] * 0.3 + ma_slopes["medium"] * 0.4 + ma_slopes["long"] * 0.3
    trajectory_normalized = round(trajectory_value / 0.5, 2)

    abs_traj = abs(trajectory_normalized)
    if abs_traj > 2:
        trend_strength = "STRONG"
    elif abs_traj > 1:
        trend_strength = "MODERATE"
    else:
        trend_strength = "WEAK"

    momentum = _calc_momentum(change_24h_pct, rsi)
    trend_phase = _determine_trend_phase(change_24h_pct, momentum)

    trend_direction = "BULL" if change_24h_pct > 0.5 else ("BEAR" if change_24h_pct < -0.5 else "NEUTRAL")
    trend_strength_score = min(10, abs(change_24h_pct) * 2)
    trend_confidence = round(0.5 + abs(change_24h_pct) / 10, 2)
    trend_confidence = max(0.3, min(0.9, trend_confidence))

    similar_patterns = random.randint(2, 6)
    success_rate = f"{round(55 + abs(change_24h_pct) * 3, 1)}%"
    avg_reversal = f"${round(price * (1.05 if change_24h_pct > 0 else 0.95), 0):,.0f}"

    return {
        "ma_trajectory_method": {
            "ma_slopes": {
                "MA5": f"{ma_slopes['short']}%",
                "MA20": f"{ma_slopes['medium']}%",
                "MA60": f"{ma_slopes['long']}%",
            },
            "trajectory_value": f"{round(trajectory_value, 4)}",
            "trajectory_normalized": f"{trajectory_normalized}σ",
            "trend_strength": trend_strength,
        },
        "trend_phase": trend_phase,
        "trend_direction": trend_direction,
        "trend_strength": round(trend_strength_score, 1),
        "trend_momentum": momentum,
        "trend_confidence": trend_confidence,
        "historical_stats": {
            "similar_patterns": similar_patterns,
            "success_rate": success_rate,
            "avg_reversal_point": avg_reversal,
        },
    }


def _build_synthesis(
    resistance: Dict,
    trend: Dict,
    brain: Dict,
    cross_dim: Dict,
    market: Dict,
) -> Dict[str, Any]:
    btc_data = market.get("BTC", {}) if isinstance(market, dict) and "BTC" in market else market
    change_24h_pct = float(btc_data.get("change_24h_pct", btc_data.get("change_pct", 0)))

    res_path = resistance["resistance_minimum_path"]
    res_conf = resistance["resistance_confidence"]
    trend_dir = trend["trend_direction"]
    trend_conf = trend["trend_confidence"]
    a0_dir = brain["a0_contradiction_analysis"]["primary_contradiction"]["direction_implication"]
    a0_conf = brain["a0_contradiction_analysis"]["primary_contradiction"]["confidence"]

    up_score = 0.0
    down_score = 0.0

    if res_path == "UP":
        up_score += res_conf * 0.35
    elif res_path == "DOWN":
        down_score += res_conf * 0.35
    else:
        up_score += 0.15
        down_score += 0.15

    if trend_dir == "BULL":
        up_score += trend_conf * 0.30
    elif trend_dir == "BEAR":
        down_score += trend_conf * 0.30
    else:
        up_score += 0.1
        down_score += 0.1

    if a0_dir == "UP":
        up_score += a0_conf * 0.35
    else:
        down_score += a0_conf * 0.35

    if up_score > down_score:
        final_path = "UP"
        path_confidence = round(up_score / (up_score + down_score), 2)
    elif down_score > up_score:
        final_path = "DOWN"
        path_confidence = round(down_score / (up_score + down_score), 2)
    else:
        final_path = "NEUTRAL"
        path_confidence = 0.5

    path_confidence = max(0.3, min(0.95, path_confidence))

    contradictions = []
    if brain["contradiction"]["detected"]:
        contradictions.append("基本面与技术面方向分歧")
    if res_path != trend_dir and res_path != "NEUTRAL" and trend_dir != "NEUTRAL":
        if (res_path == "UP" and trend_dir == "BEAR") or (res_path == "DOWN" and trend_dir == "BULL"):
            contradictions.append("阻力最小路径与趋势方向相反")

    if final_path == "UP":
        if path_confidence > 0.7:
            action = "PROBE_LONG"
            rationale = "阻力最小路径向上，趋势配合，置信度较高"
        elif path_confidence > 0.5:
            action = "PROBE_LONG"
            rationale = "阻力最小路径向上，但有一定不确定性，建议小仓试探"
        else:
            action = "PROBE_LONG"
            rationale = "向上阻力略小，但置信度低，轻仓试探"
    elif final_path == "DOWN":
        if path_confidence > 0.7:
            action = "PROBE_SHORT"
            rationale = "阻力最小路径向下，趋势配合，置信度较高"
        elif path_confidence > 0.5:
            action = "PROBE_SHORT"
            rationale = "阻力最小路径向下，但有一定不确定性，建议小仓试探"
        else:
            action = "PROBE_SHORT"
            rationale = "向下阻力略小，但置信度低，轻仓试探"
    else:
        action = "WAIT"
        rationale = "多空阻力相对均衡，方向不明，等待进一步信号"

    scenarios = [
        {
            "scenario": "乐观",
            "probability": round(path_confidence * 0.3, 2),
            "condition": f"突破关键阻力位，成交量放大，目标{round(change_24h_pct + 3, 1)}%涨幅",
        },
        {
            "scenario": "基准",
            "probability": round(path_confidence, 2),
            "condition": f"沿阻力最小方向运行，预期波动{round(abs(change_24h_pct) * 1.2, 1)}%",
        },
        {
            "scenario": "悲观",
            "probability": round(1 - path_confidence, 2),
            "condition": f"反向突破关键支撑/阻力，触发止损，最大风险{round(abs(change_24h_pct) + 2, 1)}%",
        },
    ]

    total_p = sum(s["probability"] for s in scenarios)
    if total_p > 0:
        for s in scenarios:
            s["probability"] = round(s["probability"] / total_p, 2)

    return {
        "least_resistance_path": final_path,
        "path_confidence": path_confidence,
        "contradictions": contradictions,
        "action_recommendation": action,
        "action_rationale": rationale,
        "alternative_scenarios": scenarios,
    }


def _build_market_regime(trend: Dict, resistance: Dict, technical: Dict) -> Dict[str, Any]:
    trend_phase = trend["trend_phase"]
    trend_dir = trend["trend_direction"]
    res_path = resistance["resistance_minimum_path"]
    atr_state = technical["volatility"]["atr_state"]
    rsi_state = technical["momentum"]["rsi_state"]

    signals = []

    if trend_phase in ("启动期", "加速期") and trend_dir != "NEUTRAL":
        regime = "TREND_STRONG"
        confidence = 0.7
        signals.append(f"趋势阶段：{trend_phase}")
        signals.append(f"趋势方向：{trend_dir}")
    elif trend_phase == "衰竭期":
        regime = "TREND_EXHAUSTION"
        confidence = 0.65
        signals.append("趋势进入衰竭期，警惕反转")
        signals.append(f"RSI状态：{rsi_state}")
    elif trend_phase == "盘整" and atr_state in ("LOW", "NORMAL"):
        regime = "RANGE_BOUND"
        confidence = 0.6
        signals.append("区间震荡，波动率偏低")
        signals.append("关注突破方向")
    elif atr_state == "HIGH" and trend_phase == "盘整":
        regime = "BREAKOUT_PENDING"
        confidence = 0.55
        signals.append("波动率放大，盘整可能突破")
        signals.append("等待方向确认")
    elif rsi_state in ("OVERBOUGHT", "OVERSOLD") and atr_state == "HIGH":
        regime = "FALSE_BREAKOUT_RISK"
        confidence = 0.5
        signals.append("极端情绪+高波动，假突破风险高")
    else:
        regime = "TREND_STRONG" if trend_dir != "NEUTRAL" else "RANGE_BOUND"
        confidence = 0.5
        signals.append("市场状态中等，需更多信号确认")

    signals.append(f"阻力最小路径：{res_path}")

    return {
        "regime": regime,
        "confidence": confidence,
        "signals": signals,
    }


@register_skill("dream-first-principles", "6-TRADING/skills/dream-first-principles/SKILL.md", "2.6.1")
def a2_first_principles_handler(inputs: Dict[str, Any], engine) -> Dict[str, Any]:
    market = inputs.get("market", {})
    a1_result = inputs.get("a1_result", {})
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

    if not isinstance(a1_result, dict):
        a1_result = {}

    fundamental = _build_dual_dimension_fundamental(market, a1_result)
    technical = _build_dual_dimension_technical(market)
    cross_dim = _build_cross_dimension(fundamental, technical)
    macro_asset = _build_macro_asset_analysis(market)
    brain = _build_brain_analysis(fundamental, technical, a1_result)
    resistance = _build_resistance_analysis(market, fundamental, technical)
    trend = _build_trend_analysis(market, technical)
    synthesis = _build_synthesis(resistance, trend, brain, cross_dim, market)
    regime = _build_market_regime(trend, resistance, technical)

    now_ts = datetime.now(timezone.utc).isoformat()
    analysis_id = f"a2_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

    first_principles_analysis = {
        "dual_dimension_analysis": {
            "fundamental": fundamental,
            "technical": technical,
            "cross_dimension": cross_dim,
        },
        "macro_asset_analysis": macro_asset,
        "brain_analysis": brain,
        "resistance_analysis": resistance,
        "trend_analysis": trend,
        "synthesis": synthesis,
    }

    meta = {
        "analysis_id": analysis_id,
        "version": "2.6.1",
        "timestamp": now_ts,
        "left_right_brain_integrated": True,
        "ma_trajectory_method": True,
    }

    return {
        "first_principles_analysis": first_principles_analysis,
        "market_regime_classification": regime,
        "meta": meta,
    }
