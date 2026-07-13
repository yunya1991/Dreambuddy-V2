from typing import Dict, Any

try:
    from .skill_engine import register_skill
except ImportError:
    from skill_engine import register_skill


@register_skill(
    "dream-strategy-designer",
    "6-TRADING/skills/dream-strategy-designer/SKILL.md",
    "2.7.0"
)
def a3_strategy_designer_handler(inputs: Dict[str, Any], engine) -> Dict[str, Any]:
    a1_result = inputs.get("a1_result", {})
    a2_result = inputs.get("a2_result", {})
    positions = inputs.get("positions", {})
    market = inputs.get("market", {})

    least_resistance_path = a2_result.get("least_resistance_path", "NEUTRAL")
    confidence = a2_result.get("confidence", 0.5)
    regime = a2_result.get("market_regime_classification", {}).get("regime", "RANGE_BOUND")
    trend_direction = a2_result.get("trend_analysis", {}).get("trend_direction", "NEUTRAL")
    main_contradiction = a2_result.get("main_contradiction", {}).get("primary", "")
    a0_analysis = a2_result.get("a0_contradiction_analysis", {})

    directive_bias = _determine_directive_bias(least_resistance_path, confidence, regime, a0_analysis)

    position_modifier = _calculate_position_modifier(confidence, a0_analysis, regime)

    leverage_cap = _calculate_leverage_cap(regime, confidence)

    target_coins = _determine_target_coins(market, a1_result)

    exit_conditions = _build_exit_conditions(directive_bias, regime, confidence)

    risk_rules = _build_risk_rules(leverage_cap, position_modifier)

    timing_guidance = _build_timing_guidance(regime, directive_bias, confidence)

    contradiction_handling = _build_contradiction_handling(a0_analysis, main_contradiction, directive_bias)

    strategy_directive = {
        "directive_bias": directive_bias,
        "position_modifier": position_modifier,
        "leverage_cap": leverage_cap,
        "target_coins": target_coins,
        "exit_conditions": exit_conditions,
        "risk_rules": risk_rules,
        "timing_guidance": timing_guidance,
        "contradiction_handling": contradiction_handling,
    }

    a1_inputs = {
        "research_summary": a1_result.get("research_report", {}).get("summary", ""),
        "key_findings": a1_result.get("research_report", {}).get("key_findings", []),
        "market_state": a1_result.get("market_state", {}),
    }

    a2_inputs = {
        "regime": regime,
        "least_resistance_path": least_resistance_path,
        "trend_direction": trend_direction,
        "main_contradiction": main_contradiction,
        "confidence": confidence,
    }

    feature_distillation = _distill_features(a1_result, a2_result, market)

    evidence_chain = {
        "a1_inputs": a1_inputs,
        "a2_inputs": a2_inputs,
        "feature_distillation": feature_distillation,
    }

    return {
        "strategy_directive": strategy_directive,
        "evidence_chain": evidence_chain,
    }


def _determine_directive_bias(path: str, confidence: float, regime: str, a0_analysis: Dict) -> str:
    clarity = a0_analysis.get("contradiction_clarity", "MODERATE")

    if clarity == "FUZZY" or confidence < 0.3:
        return "PROBE"

    if regime in ("TREND_EXHAUSTION", "FALSE_BREAKOUT_RISK") and confidence < 0.6:
        return "WAIT"

    if regime == "EXTREME":
        return "REDUCE"

    if path == "UP":
        if confidence >= 0.7:
            return "LONG"
        elif confidence >= 0.4:
            return "PROBE"
        else:
            return "HOLD"
    elif path == "DOWN":
        if confidence >= 0.7:
            return "SHORT"
        elif confidence >= 0.4:
            return "PROBE"
        else:
            return "HOLD"
    else:
        if confidence >= 0.6:
            return "HOLD"
        else:
            return "WAIT"


def _calculate_position_modifier(confidence: float, a0_analysis: Dict, regime: str) -> float:
    base = max(0.1, min(1.0, confidence))

    clarity = a0_analysis.get("contradiction_clarity", "MODERATE")
    if clarity == "CLEAR":
        base = min(1.0, base + 0.15)
    elif clarity == "FUZZY":
        base = max(0.1, base - 0.3)

    consensus_count = a0_analysis.get("contradiction_consensus_count", 0)
    if consensus_count >= 3:
        base = min(1.0, base + 0.1)

    transformation_risk = a0_analysis.get("transformation_risk", "LOW")
    if transformation_risk == "HIGH":
        base = max(0.1, base - 0.25)
    elif transformation_risk == "MODERATE":
        base = max(0.1, base - 0.1)

    if regime in ("EXTREME", "FALSE_BREAKOUT_RISK"):
        base = max(0.1, base * 0.5)
    elif regime == "TREND_EXHAUSTION":
        base = max(0.1, base * 0.7)

    return round(base, 2)


def _calculate_leverage_cap(regime: str, confidence: float) -> int:
    if regime == "EXTREME":
        return 1
    elif regime in ("FALSE_BREAKOUT_RISK", "TREND_EXHAUSTION"):
        return 2
    elif regime == "RANGE_BOUND":
        if confidence >= 0.7:
            return 3
        else:
            return 2
    elif regime in ("TREND_STRONG", "BREAKOUT_PENDING"):
        if confidence >= 0.8:
            return 5
        elif confidence >= 0.6:
            return 3
        else:
            return 2
    else:
        return 2


def _determine_target_coins(market: Dict, a1_result: Dict) -> list:
    coins = market.get("top_coins", [])
    if coins:
        return coins[:3]

    a1_coins = a1_result.get("research_report", {}).get("target_coins", [])
    if a1_coins:
        return a1_coins

    return ["BTC", "ETH"]


def _build_exit_conditions(directive_bias: str, regime: str, confidence: float) -> list:
    conditions = []

    if directive_bias in ("LONG", "SHORT"):
        stop_pct = 0.05 if confidence >= 0.7 else 0.03
        take_profit_pct = 0.10 if confidence >= 0.7 else 0.06
        conditions.append({
            "type": "stop_loss",
            "trigger": f"亏损达到{int(stop_pct * 100)}%",
            "action": "全部平仓",
            "enforcement": "HARD",
        })
        conditions.append({
            "type": "take_profit",
            "trigger": f"盈利达到{int(take_profit_pct * 100)}%",
            "action": "分批止盈，先平50%",
            "enforcement": "SOFT",
        })
    elif directive_bias == "PROBE":
        conditions.append({
            "type": "stop_loss",
            "trigger": "亏损达到3%",
            "action": "全部平仓",
            "enforcement": "HARD",
        })
        conditions.append({
            "type": "take_profit",
            "trigger": "盈利达到5%",
            "action": "全部止盈",
            "enforcement": "SOFT",
        })

    if regime == "RANGE_BOUND":
        conditions.append({
            "type": "timeout",
            "trigger": "持仓超过48小时未突破区间",
            "action": "减仓50%",
            "enforcement": "SOFT",
        })
    elif regime in ("TREND_STRONG", "BREAKOUT_PENDING"):
        conditions.append({
            "type": "trailing_stop",
            "trigger": "从最高点回撤5%",
            "action": "逐步止盈",
            "enforcement": "SOFT",
        })

    conditions.append({
        "type": "timeout",
        "trigger": "持仓超过72小时方向未明",
        "action": "评估是否离场",
        "enforcement": "SOFT",
    })

    return conditions


def _build_risk_rules(leverage_cap: int, position_modifier: float) -> list:
    max_loss_pct = 2 + int(position_modifier * 3)

    rules = [
        {
            "rule": f"单币种最大亏损不超过总资金的{max_loss_pct}%",
            "enforcement": "HARD",
        },
        {
            "rule": f"杠杆上限 {leverage_cap}x",
            "enforcement": "HARD",
        },
        {
            "rule": "总仓位不超过总资金的60%",
            "enforcement": "HARD",
        },
        {
            "rule": "禁止无止损开仓",
            "enforcement": "HARD",
        },
        {
            "rule": "单日亏损超过5%强制停止交易",
            "enforcement": "HARD",
        },
    ]

    return rules


def _build_timing_guidance(regime: str, directive_bias: str, confidence: float) -> str:
    if directive_bias == "WAIT":
        return "观望为主，等待更明确的信号，优先关注关键支撑/阻力位的反应"

    if directive_bias == "PROBE":
        return "小仓试探为主，不要一次性满仓，分2-3批次入场，设置严格止损"

    if regime == "TREND_STRONG":
        return "顺势操作，回踩关键均线时入场，不要追高，让利润奔跑"
    elif regime == "BREAKOUT_PENDING":
        return "等待突破确认后入场，突破时需配合放量，假突破立即止损"
    elif regime == "TREND_EXHAUSTION":
        return "谨慎操作，轻仓参与，注意动能衰竭信号，随时准备离场"
    elif regime == "RANGE_BOUND":
        return "区间操作，高抛低吸，靠近支撑位买，靠近阻力位卖，突破则顺势"
    elif regime == "FALSE_BREAKOUT_RISK":
        return "警惕假突破，等确认后再入场，或者反向操作，严格止损"
    elif regime == "EXTREME":
        return "极端行情，优先风控，降低仓位，不要盲目抄底或摸顶"
    else:
        return "根据市场变化灵活调整，保持谨慎，控制仓位"


def _build_contradiction_handling(a0_analysis: Dict, main_contradiction: str, directive_bias: str) -> Dict:
    clarity = a0_analysis.get("contradiction_clarity", "MODERATE")
    monitoring_points = a0_analysis.get("monitoring_points", [])
    transformation_risk = a0_analysis.get("transformation_risk", "LOW")

    if not main_contradiction:
        main_contradiction = "市场多空力量相对均衡，缺乏明确的主要矛盾"

    response_map = {
        "LONG": "顺主要矛盾方向做多，用矛盾转化条件作为止盈/止损参考",
        "SHORT": "顺主要矛盾方向做空，密切关注矛盾是否有转化迹象",
        "PROBE": "矛盾清晰度不足，用小仓试探方向，验证矛盾判断",
        "WAIT": "等待矛盾进一步明朗，不急于入场",
        "REDUCE": "矛盾趋于转化，降低仓位锁定利润，准备应对新方向",
        "HOLD": "持有现有仓位，监控矛盾变化，不主动加仓",
    }

    strategic_response = response_map.get(directive_bias, "根据矛盾演变灵活调整策略")

    return {
        "primary_contradiction": main_contradiction,
        "contradiction_clarity": clarity,
        "strategic_response": strategic_response,
        "monitoring_points": monitoring_points,
        "transformation_risk": transformation_risk,
    }


def _distill_features(a1_result: Dict, a2_result: Dict, market: Dict) -> Dict:
    trend_direction = a2_result.get("trend_analysis", {}).get("trend_direction", "NEUTRAL")
    momentum = a2_result.get("trend_analysis", {}).get("momentum", "STABLE")
    volatility = a2_result.get("volatility_analysis", {}).get("level", "NORMAL")
    regime = a2_result.get("market_regime_classification", {}).get("regime", "RANGE_BOUND")
    sentiment = a1_result.get("market_state", {}).get("sentiment", "NEUTRAL")
    capital_flow = a1_result.get("market_state", {}).get("capital_flow", "NEUTRAL")

    direction = "BULL" if trend_direction == "BULL" else "BEAR" if trend_direction == "BEAR" else "NEUTRAL"

    return {
        "direction": direction,
        "momentum": momentum,
        "resistance": _infer_resistance(regime),
        "volatility": volatility,
        "sentiment": sentiment,
        "capital": capital_flow,
        "regime": regime,
        "timing": _infer_timing(regime, momentum),
    }


def _infer_resistance(regime: str) -> str:
    if regime in ("TREND_STRONG",):
        return "EASY"
    elif regime in ("BREAKOUT_PENDING", "TREND_EXHAUSTION"):
        return "MIXED"
    elif regime in ("FALSE_BREAKOUT_RISK", "EXTREME"):
        return "HARD"
    else:
        return "MIXED"


def _infer_timing(regime: str, momentum: str) -> str:
    if regime == "TREND_STRONG" and momentum == "ACCELERATING":
        return "MID"
    elif regime == "TREND_EXHAUSTION" or momentum == "DECELERATING":
        return "LATE"
    elif regime == "BREAKOUT_PENDING":
        return "EARLY"
    else:
        return "MID"
