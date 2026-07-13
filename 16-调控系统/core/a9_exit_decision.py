"""
A9 离场决策模块 — 16-调控系统 Phase 2

基于 A1/A2/A3 宏观战略分析，对每个持仓进行四态离场评估：
CLOSE / REDUCE / HOLD / RAISE_TP

四层决策链：
  Layer 1: 战略方向一致性检查
  Layer 2: 置信度加权
  Layer 3: 市场状态修正
  Layer 4: 最终合成 + 紧急度评级
"""

import math
from typing import Dict, List, Any
from datetime import datetime, timezone

try:
    from .skill_engine import register_skill
except ImportError:
    from skill_engine import register_skill


@register_skill("dream-exit-skill-v2", "6-TRADING/skills/dream-exit-skill-v2/SKILL.md", "2.2.0")
def a9_exit_decision_handler(inputs: Dict[str, Any], engine) -> Dict[str, Any]:
    positions = inputs.get("positions", [])
    a1_result = inputs.get("a1_result", {})
    a2_result = inputs.get("a2_result", {})
    a3_result = inputs.get("a3_result", {})
    market = inputs.get("market", {})

    evaluations = []
    for pos in positions:
        ev = _evaluate_single_position(pos, a1_result, a2_result, a3_result, market)
        evaluations.append(ev)

    stats = _calc_stats(evaluations)

    return {
        "exit_evaluations": evaluations,
        "overall_summary": stats,
        "decision_layers": {
            "layer1_strategy_alignment": "strategic direction vs position direction",
            "layer2_confidence_weighting": "A2 path_confidence weight",
            "layer3_regime_correction": "market regime adjustment",
            "layer4_final_synthesis": "urgency + final action",
        },
    }


def _evaluate_single_position(
    position: Dict,
    a1: Dict,
    a2: Dict,
    a3: Dict,
    market: Dict,
) -> Dict:
    direction = position.get("direction", "UNKNOWN").upper()
    unrealized_pnl = float(position.get("unrealized_pnl", 0))
    entry_price = float(position.get("entry_price", 0))
    symbol = position.get("symbol", "")

    research = a1.get("research_report", {})
    fp = a2.get("first_principles_analysis", {})
    directive = a3.get("strategy_directive", {})

    market_state = research.get("market_state", {})
    strategy_direction = directive.get("directive_bias", "HOLD")
    path_confidence = fp.get("synthesis", {}).get("path_confidence", 0.5)
    least_resistance = fp.get("synthesis", {}).get("least_resistance_path", "NEUTRAL")
    regime = a2.get("market_regime_classification", {}).get("regime", "RANGE_BOUND")
    trend_phase = fp.get("trend_analysis", {}).get("trend_phase", "盘整")

    position_direction_num = 1 if direction == "LONG" else (-1 if direction == "SHORT" else 0)

    strategy_num = 0
    if strategy_direction in ("LONG", "PROBE_LONG", "DIP_BUY"):
        strategy_num = 1
    elif strategy_direction in ("SHORT", "PROBE_SHORT", "HEDGE"):
        strategy_num = -1

    alignment_score = position_direction_num * strategy_num
    lr_num = {"UP": 1, "DOWN": -1, "NEUTRAL": 0}.get(least_resistance, 0)
    lr_alignment = position_direction_num * lr_num

    trend_strength = fp.get("trend_analysis", {}).get("trend_strength", 5) / 10.0

    base_score = alignment_score * 0.5 + lr_alignment * 0.3 + trend_strength * lr_alignment * 0.2

    confidence_weight = 0.5 + path_confidence * 0.5
    weighted_score = base_score * confidence_weight

    regime_bonus = 0.0
    if regime in ("TREND_STRONG", "BREAKOUT_PENDING"):
        regime_bonus = 0.15 * lr_alignment
    elif regime in ("TREND_EXHAUSTION", "FALSE_BREAKOUT_RISK"):
        regime_bonus = -0.2 * lr_alignment
    elif regime == "EXTREME":
        regime_bonus = -0.3

    final_score = weighted_score + regime_bonus

    action, urgency = _score_to_action(final_score, direction, trend_phase, unrealized_pnl, entry_price)

    reason = _generate_reason(
        action, direction, strategy_direction, least_resistance,
        path_confidence, regime, trend_phase, unrealized_pnl,
    )

    current_price = entry_price * (1 + unrealized_pnl / 100) if entry_price > 0 else 0

    new_tp_price = 0.0
    new_tp_pct = 0.0
    if action == "RAISE_TP":
        atr_pct = market_state.get("atr_pct", 0.02)
        new_tp_pct = min(atr_pct * 4.0, 0.08)
        if current_price > 0:
            new_tp_price = current_price * (1 + new_tp_pct * position_direction_num)

    reduce_frac = 0.0
    if action == "REDUCE":
        reduce_frac = max(0.25, min(0.5, 1.0 - path_confidence))

    return {
        "position": {
            "symbol": symbol,
            "system": position.get("system", ""),
            "direction": direction,
            "size": position.get("size", 0),
            "entry_price": entry_price,
            "current_price": round(current_price, 4) if current_price else 0,
            "unrealized_pnl": unrealized_pnl,
        },
        "recommended_action": action,
        "reason": reason,
        "urgency": urgency,
        "confidence": round(path_confidence, 2),
        "scoring": {
            "alignment_score": round(alignment_score, 3),
            "lr_alignment": round(lr_alignment, 3),
            "weighted_score": round(weighted_score, 3),
            "regime_bonus": round(regime_bonus, 3),
            "final_score": round(final_score, 3),
        },
        "parameters": {
            "new_tp_price": round(new_tp_price, 4) if new_tp_price else 0,
            "new_tp_pct": round(new_tp_pct * 100, 2),
            "reduce_fraction": round(reduce_frac, 2),
        },
        "layers": {
            "layer1_alignment": {
                "position_direction": direction,
                "strategy_direction": strategy_direction,
                "alignment_score": round(alignment_score, 3),
            },
            "layer2_confidence": {
                "path_confidence": round(path_confidence, 2),
                "confidence_weight": round(confidence_weight, 3),
            },
            "layer3_regime": {
                "regime": regime,
                "trend_phase": trend_phase,
                "regime_bonus": round(regime_bonus, 3),
            },
            "layer4_synthesis": {
                "final_score": round(final_score, 3),
                "action": action,
                "urgency": urgency,
            },
        },
    }


def _score_to_action(
    score: float,
    direction: str,
    trend_phase: str,
    unrealized_pnl: float,
    entry_price: float,
) -> tuple:
    if score <= -0.55:
        return "CLOSE", "CRITICAL"
    elif score <= -0.30:
        return "CLOSE", "HIGH"
    elif score <= -0.10:
        return "REDUCE", "MEDIUM"
    elif score <= 0.10:
        return "HOLD", "LOW"
    elif score <= 0.30:
        if trend_phase in ("加速期", "启动期") and unrealized_pnl > 0:
            return "RAISE_TP", "LOW"
        return "HOLD", "LOW"
    else:
        if unrealized_pnl > 0 and trend_phase in ("加速期",):
            return "RAISE_TP", "MEDIUM"
        elif unrealized_pnl > 0:
            return "RAISE_TP", "LOW"
        else:
            return "HOLD", "LOW"


def _generate_reason(
    action: str,
    direction: str,
    strategy_direction: str,
    least_resistance: str,
    path_confidence: float,
    regime: str,
    trend_phase: str,
    unrealized_pnl: float,
) -> str:
    conf_label = "高" if path_confidence > 0.7 else ("中" if path_confidence > 0.4 else "低")

    if action == "CLOSE":
        return f"战略方向({strategy_direction})与持仓方向({direction})严重矛盾，阻力最小路径({least_resistance})反向，{conf_label}置信度，{regime}市场状态，建议平仓"
    elif action == "REDUCE":
        return f"战略方向({strategy_direction})与持仓方向({direction})矛盾，阻力最小路径({least_resistance})不利，{conf_label}置信度，建议减仓控制风险"
    elif action == "RAISE_TP":
        return f"战略方向({strategy_direction})与持仓方向一致，阻力最小路径({least_resistance})同向，{trend_phase}趋势阶段，建议提高止盈让利润奔跑"
    else:
        return f"战略方向中性，阻力最小路径({least_resistance})不明朗，{regime}市场状态，维持现有持仓"


def _calc_stats(evaluations: List[Dict]) -> Dict:
    close_count = sum(1 for e in evaluations if e["recommended_action"] == "CLOSE")
    reduce_count = sum(1 for e in evaluations if e["recommended_action"] == "REDUCE")
    hold_count = sum(1 for e in evaluations if e["recommended_action"] == "HOLD")
    raise_tp_count = sum(1 for e in evaluations if e["recommended_action"] == "RAISE_TP")

    if close_count > 0:
        overall_stance = "CLOSE"
        rationale = f"有 {close_count} 个持仓建议平仓，需紧急处理"
    elif reduce_count > 0:
        overall_stance = "REDUCE"
        rationale = f"有 {reduce_count} 个持仓建议减仓，注意风险控制"
    elif raise_tp_count > 0:
        overall_stance = "RAISE_TP"
        rationale = f"有 {raise_tp_count} 个持仓建议提高止盈，趋势向好"
    else:
        overall_stance = "HOLD"
        rationale = "所有持仓维持现状，市场中性"

    critical_count = sum(1 for e in evaluations if e.get("urgency") == "CRITICAL")
    high_count = sum(1 for e in evaluations if e.get("urgency") == "HIGH")

    return {
        "total_evaluated": len(evaluations),
        "close_count": close_count,
        "reduce_count": reduce_count,
        "hold_count": hold_count,
        "raise_tp_count": raise_tp_count,
        "overall_stance": overall_stance,
        "rationale": rationale,
        "urgency_breakdown": {
            "critical": critical_count,
            "high": high_count,
            "medium": sum(1 for e in evaluations if e.get("urgency") == "MEDIUM"),
            "low": sum(1 for e in evaluations if e.get("urgency") == "LOW"),
        },
    }
