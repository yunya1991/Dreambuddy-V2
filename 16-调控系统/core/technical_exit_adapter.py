#!/usr/bin/env python3
"""
技术离场适配器 — 16-调控系统 Phase 3

接入 ClassicExitSystem（技术离场 SSOT），与宏观战略离场融合。

融合架构：
  宏观离场（A1/A2/A3 + A9四层）  ──┐
                                    ├─→  融合决策引擎  ──→  最终建议
  技术离场（ClassicExitSystem）  ──┘

融合逻辑：
  - P0 安全硬退出（技术）→ 一票否决，直接执行
  - 技术离场信号 + 宏观确认 → 强化建议
  - 技术离场信号 vs 宏观矛盾 → 降级为观察，降低置信度
  - 宏观离场信号 + 技术支持 → 强化
  - 宏观离场信号 + 技术不支持 → 降级（减仓而非平仓）
"""

import math
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass

try:
    from .skill_engine import register_skill
    from .strategy_exit_adapter import (
        evaluate_exit_rationality,
        get_strategy_exit_design,
        ExitDesignPhilosophy,
        MacroExitInfluenceLevel,
    )
except ImportError:
    from skill_engine import register_skill
    from strategy_exit_adapter import (
        evaluate_exit_rationality,
        get_strategy_exit_design,
        ExitDesignPhilosophy,
        MacroExitInfluenceLevel,
    )


@dataclass
class TechnicalExitSignal:
    """技术离场信号"""
    action: str = "HOLD"
    urgency: str = "LOW"
    confidence: float = 0.5
    reason: str = ""
    source_layers: Dict[str, Any] = None


def _calc_simple_technical_signals(
    position: Dict[str, Any],
    market_data: Dict[str, Any],
    market_state: Dict[str, Any],
) -> TechnicalExitSignal:
    """
    计算简化版技术离场信号

    当 ClassicExitSystem 不可用时，使用内置简化技术分析作为降级方案。
    覆盖 P0-P2 核心逻辑：
      - P0: 最大亏损、强平缓冲、持仓时间
      - P1: RSI 超买超卖、ATR 止损止盈
      - P2: 三重屏障（简化版）
    """
    symbol = position.get("symbol", "").upper()
    direction = position.get("direction", "UNKNOWN").upper()
    entry_price = float(position.get("entry_price", 0))
    unrealized_pnl_pct = float(position.get("upl_ratio", 0))
    leverage = float(position.get("leverage", 1))
    open_time_str = position.get("open_time", "")

    sym_data = market_data.get(symbol, {}) if isinstance(market_data, dict) else {}
    current_price = float(sym_data.get("current_price", sym_data.get("price", 0)))
    if current_price <= 0 and entry_price > 0:
        current_price = entry_price * (1 + unrealized_pnl_pct / 100)

    atr_pct = float(market_state.get("atr_pct", 2.0)) if isinstance(market_state, dict) else 2.0
    rsi = float(market_state.get("rsi_1h", market_state.get("rsi_14", 50))) if isinstance(market_state, dict) else 50

    signals = []
    p0_triggered = False
    p1_triggered = False
    final_action = "HOLD"
    final_urgency = "LOW"
    final_confidence = 0.5
    primary_reason = ""

    pnl_eff = unrealized_pnl_pct * leverage

    max_loss_pct = -8.0 * leverage
    if pnl_eff <= max_loss_pct:
        p0_triggered = True
        signals.append({
            "layer": "P0",
            "type": "max_loss",
            "action": "CLOSE",
            "urgency": "CRITICAL",
            "confidence": 0.95,
            "detail": f"有效盈亏 {pnl_eff:.1f}% 触及最大亏损阈值 {max_loss_pct:.1f}%",
        })

    liq_buffer_pct = 3.0 * leverage
    if pnl_eff <= -(100 - liq_buffer_pct):
        p0_triggered = True
        signals.append({
            "layer": "P0",
            "type": "liquidation_risk",
            "action": "CLOSE",
            "urgency": "CRITICAL",
            "confidence": 0.99,
            "detail": f"接近强平价，缓冲不足 {liq_buffer_pct:.1f}%",
        })

    if open_time_str:
        try:
            open_dt = datetime.fromisoformat(open_time_str.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            hold_hours = (now - open_dt).total_seconds() / 3600
            max_hold_hours = 24 * 7

            if hold_hours > max_hold_hours:
                p0_triggered = True
                signals.append({
                    "layer": "P0",
                    "type": "max_hold_time",
                    "action": "CLOSE",
                    "urgency": "HIGH",
                    "confidence": 0.7,
                    "detail": f"持仓 {hold_hours:.1f}h 超过最大持仓时间 {max_hold_hours}h",
                })
        except (ValueError, TypeError):
            pass

    stop_loss_atr = 2.0 * atr_pct
    if pnl_eff <= -stop_loss_atr * leverage:
        p1_triggered = True
        signals.append({
            "layer": "P1",
            "type": "atr_stop_loss",
            "action": "CLOSE",
            "urgency": "HIGH",
            "confidence": 0.75,
            "detail": f"有效盈亏 {pnl_eff:.1f}% 触发 ATR 止损 (2×ATR={stop_loss_atr:.1f}%)",
        })

    take_profit_atr = 3.0 * atr_pct
    if pnl_eff >= take_profit_atr * leverage:
        p1_triggered = True
        signals.append({
            "layer": "P1",
            "type": "atr_take_profit",
            "action": "REDUCE",
            "urgency": "MEDIUM",
            "confidence": 0.65,
            "detail": f"有效盈亏 {pnl_eff:.1f}% 触发 ATR 止盈 (3×ATR={take_profit_atr:.1f}%)",
        })

    if direction == "LONG":
        if rsi >= 75:
            p1_triggered = True
            signals.append({
                "layer": "P1",
                "type": "rsi_overbought",
                "action": "REDUCE",
                "urgency": "MEDIUM",
                "confidence": 0.6,
                "detail": f"RSI={rsi:.1f} 超买区域，多头持仓考虑减仓",
            })
        elif rsi <= 25 and unrealized_pnl_pct < 0:
            p1_triggered = True
            signals.append({
                "layer": "P1",
                "type": "rsi_oversold_loss",
                "action": "HOLD",
                "urgency": "LOW",
                "confidence": 0.55,
                "detail": f"RSI={rsi:.1f} 超卖，亏损持仓不宜再割",
            })
    elif direction == "SHORT":
        if rsi <= 25:
            p1_triggered = True
            signals.append({
                "layer": "P1",
                "type": "rsi_oversold_short",
                "action": "REDUCE",
                "urgency": "MEDIUM",
                "confidence": 0.6,
                "detail": f"RSI={rsi:.1f} 超卖区域，空头持仓考虑减仓",
            })
        elif rsi >= 75 and unrealized_pnl_pct < 0:
            p1_triggered = True
            signals.append({
                "layer": "P1",
                "type": "rsi_overbought_loss",
                "action": "HOLD",
                "urgency": "LOW",
                "confidence": 0.55,
                "detail": f"RSI={rsi:.1f} 超买，亏损空单不宜再追",
            })

    if p0_triggered:
        p0_signals = [s for s in signals if s["layer"] == "P0"]
        worst = max(p0_signals, key=lambda s: {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}[s["urgency"]])
        final_action = worst["action"]
        final_urgency = worst["urgency"]
        final_confidence = worst["confidence"]
        primary_reason = f"[P0 硬退出] {worst['detail']}"
    elif p1_triggered:
        close_signals = [s for s in signals if s["action"] == "CLOSE"]
        reduce_signals = [s for s in signals if s["action"] == "REDUCE"]

        if close_signals:
            best = max(close_signals, key=lambda s: s["confidence"])
            final_action = "CLOSE"
            final_urgency = best["urgency"]
            final_confidence = best["confidence"]
            primary_reason = f"[P1 技术] {best['detail']}"
        elif reduce_signals:
            best = max(reduce_signals, key=lambda s: s["confidence"])
            final_action = "REDUCE"
            final_urgency = best["urgency"]
            final_confidence = best["confidence"]
            primary_reason = f"[P1 技术] {best['detail']}"
    else:
        primary_reason = "[技术] 无明确技术离场信号"

    return TechnicalExitSignal(
        action=final_action,
        urgency=final_urgency,
        confidence=final_confidence,
        reason=primary_reason,
        source_layers={
            "p0_triggered": p0_triggered,
            "p1_triggered": p1_triggered,
            "all_signals": signals,
        },
    )


def fuse_macro_technical(
    macro_evaluation: Dict[str, Any],
    technical_signal: TechnicalExitSignal,
    position_info: Dict[str, Any] = None,
    strategy_id: str = "",
) -> Dict[str, Any]:
    """
    融合宏观离场与技术离场信号（策略感知版）

    融合架构（三层）：
    第1层：策略合理性检查（strategy_exit_adapter）
      - 检查宏观建议是否符合该策略的离场设计原则
      - 如果是策略自身设计导致的状态（如马丁浮亏），则不干预
      - 调整置信度权重（不同策略宏观权重不同）

    第2层：P0 硬退出（技术）
      - 一票否决，直接执行（除非策略明确允许覆盖且宏观置信度极高）

    第3层：宏观+技术融合
      - 同向 → 强化
      - 反向 → 降级
      - 单方有信号 → 降权输出
    """
    position_info = position_info or {}
    strategy_id = strategy_id or position_info.get("system", "")

    macro_action = macro_evaluation.get("recommended_action", "HOLD")
    macro_urgency = macro_evaluation.get("urgency", "LOW")
    macro_confidence = float(macro_evaluation.get("confidence", 0.5))

    tech_action = technical_signal.action
    tech_urgency = technical_signal.urgency
    tech_confidence = technical_signal.confidence

    tech_layers = technical_signal.source_layers or {}
    p0_triggered = tech_layers.get("p0_triggered", False)

    urgency_rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    action_rank = {"CLOSE": 3, "REDUCE": 2, "HOLD": 1, "RAISE_TP": 0}

    # ==========================================
    # 第1层：策略合理性检查
    # ==========================================
    strategy_design = get_strategy_exit_design(strategy_id) if strategy_id else None
    rationality_result = None

    if strategy_id and strategy_design:
        pnl_pct = float(position_info.get("upl_ratio", 0))
        hold_hours = 0
        open_time_str = position_info.get("open_time", "")
        if open_time_str:
            try:
                open_dt = datetime.fromisoformat(open_time_str.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                hold_hours = (now - open_dt).total_seconds() / 3600
            except (ValueError, TypeError):
                pass

        addon_count = int(position_info.get("addon_count", 0))

        macro_for_ration = {
            "suggested_action": macro_action.lower(),
            "confidence": macro_confidence,
            "reduce_fraction": macro_evaluation.get("parameters", {}).get("reduce_fraction", 0.3),
        }
        tech_for_ration = {
            "confidence": tech_confidence,
            "p0_triggered": p0_triggered,
        }
        pos_for_ration = {
            "pnl_pct": pnl_pct,
            "hold_hours": hold_hours,
            "addon_count": addon_count,
            "direction": position_info.get("direction", "UNKNOWN"),
        }

        rationality_result = evaluate_exit_rationality(
            strategy_id,
            pos_for_ration,
            macro_for_ration,
            tech_for_ration,
        )

        adjusted_macro_action = rationality_result["adjusted_action"].upper()
        adjusted_macro_confidence = rationality_result["adjusted_confidence"]

    else:
        adjusted_macro_action = macro_action
        adjusted_macro_confidence = macro_confidence

    final_action = "HOLD"
    final_urgency = "LOW"
    final_confidence = 0.5
    fusion_reason = ""
    fusion_mode = ""

    # ==========================================
    # 第2层：P0 硬退出检查
    # ==========================================
    if p0_triggered:
        if strategy_design and strategy_design.allow_macro_override_p0:
            if adjusted_macro_confidence >= 0.9 and adjusted_macro_action in ("HOLD", "RAISE_TP"):
                final_action = adjusted_macro_action
                final_urgency = "HIGH"
                final_confidence = adjusted_macro_confidence
                fusion_mode = "macro_overrides_p0"
                fusion_reason = f"P0触发但宏观置信度{adjusted_macro_confidence:.0%}≥90%，策略允许覆盖，宏观优先"
            else:
                final_action = tech_action
                final_urgency = tech_urgency
                final_confidence = tech_confidence
                fusion_mode = "technical_p0_veto"
                fusion_reason = f"技术P0硬退出触发，宏观置信度不足覆盖，执行P0。{technical_signal.reason}"
        else:
            final_action = tech_action
            final_urgency = tech_urgency
            final_confidence = tech_confidence
            fusion_mode = "technical_p0_veto"
            fusion_reason = f"技术P0硬退出触发，策略不允许宏观覆盖，一票否决。{technical_signal.reason}"

    # ==========================================
    # 第3层：宏观+技术融合
    # ==========================================
    else:
        macro_action_final = adjusted_macro_action
        macro_conf_final = adjusted_macro_confidence

        same_direction = (
            (macro_action_final == tech_action) or
            (macro_action_final in ("CLOSE", "REDUCE") and tech_action in ("CLOSE", "REDUCE")) or
            (macro_action_final in ("HOLD", "RAISE_TP") and tech_action in ("HOLD", "RAISE_TP"))
        )

        if same_direction:
            if macro_action_final == "HOLD" and tech_action == "HOLD":
                final_action = "HOLD"
                final_urgency = "LOW"
                final_confidence = min(0.9, (macro_conf_final + tech_confidence) / 2)
                fusion_mode = "mutual_confirm_hold"
                fusion_reason = "宏观+技术均无离场信号，相互确认持有"
            else:
                final_action = macro_action_final if action_rank[macro_action_final] >= action_rank[tech_action] else tech_action
                final_urgency = macro_urgency if urgency_rank[macro_urgency] >= urgency_rank[tech_urgency] else tech_urgency
                final_confidence = min(0.95, (macro_conf_final + tech_confidence) / 2 + 0.1)
                fusion_mode = "mutual_confirm_strengthen"
                fusion_reason = f"宏观({macro_action_final})与技术({tech_action})方向一致，信号强化"
        else:
            macro_strength = action_rank[macro_action_final] * urgency_rank[macro_urgency] * macro_conf_final
            tech_strength = action_rank[tech_action] * urgency_rank[tech_urgency] * tech_confidence

            if macro_strength > tech_strength:
                final_action = _downgrade_action(macro_action_final)
                final_urgency = _downgrade_urgency(macro_urgency)
                final_confidence = max(0.3, macro_conf_final - 0.2)
                fusion_mode = "macro_primary_tech_contradict"
                fusion_reason = f"宏观({macro_action_final})主导但与技术({tech_action})矛盾，建议降级执行"
            elif tech_strength > macro_strength:
                final_action = _downgrade_action(tech_action)
                final_urgency = _downgrade_urgency(tech_urgency)
                final_confidence = max(0.3, tech_confidence - 0.2)
                fusion_mode = "tech_primary_macro_contradict"
                fusion_reason = f"技术({tech_action})主导但与宏观({macro_action_final})矛盾，建议降级执行"
            else:
                final_action = "HOLD"
                final_urgency = "LOW"
                final_confidence = 0.4
                fusion_mode = "contradict_hold"
                fusion_reason = f"宏观({macro_action_final})与技术({tech_action})矛盾，信号抵消，建议观望"

    params = macro_evaluation.get("parameters", {})
    if final_action == "REDUCE":
        macro_reduce = params.get("reduce_fraction", 0.3)
        tech_reduce = 0.3 if tech_action == "REDUCE" else 0.2

        if strategy_design:
            max_reduce = strategy_design.max_macro_reduce_fraction
            avg_reduce = (macro_reduce + tech_reduce) / 2
            final_reduce = min(avg_reduce, max_reduce)
        else:
            final_reduce = (macro_reduce + tech_reduce) / 2

        params = dict(params)
        params["reduce_fraction"] = round(final_reduce, 2)

    result = {
        "recommended_action": final_action,
        "urgency": final_urgency,
        "confidence": round(final_confidence, 2),
        "reason": fusion_reason,
        "fusion_mode": fusion_mode,
        "macro_input": {
            "original_action": macro_action,
            "adjusted_action": adjusted_macro_action if strategy_id else macro_action,
            "urgency": macro_urgency,
            "original_confidence": macro_confidence,
            "adjusted_confidence": adjusted_macro_confidence if strategy_id else macro_confidence,
        },
        "technical_input": {
            "action": tech_action,
            "urgency": tech_urgency,
            "confidence": tech_confidence,
            "p0_triggered": p0_triggered,
            "reason": technical_signal.reason,
        },
        "strategy_context": {
            "strategy_id": strategy_id,
            "strategy_name": strategy_design.strategy_name if strategy_design else "未知策略",
            "philosophy": strategy_design.philosophy.value if strategy_design else "unknown",
            "macro_influence_level": strategy_design.macro_influence_level.value if strategy_design else "unknown",
            "macro_weight": strategy_design.macro_signal_weight if strategy_design else 0.5,
            "technical_weight": strategy_design.technical_signal_weight if strategy_design else 0.5,
        },
        "rationality_check": rationality_result,
        "parameters": params,
    }

    return result


def _downgrade_action(action: str) -> str:
    """降级动作（平仓→减仓→持有）"""
    if action == "CLOSE":
        return "REDUCE"
    elif action == "REDUCE":
        return "HOLD"
    elif action == "RAISE_TP":
        return "HOLD"
    return action


def _downgrade_urgency(urgency: str) -> str:
    """降级紧急度"""
    if urgency == "CRITICAL":
        return "HIGH"
    elif urgency == "HIGH":
        return "MEDIUM"
    elif urgency == "MEDIUM":
        return "LOW"
    return urgency


@register_skill("technical-exit-adapter", "10-经典指标系统/classic_exit_system.py", "1.0.0")
def technical_exit_handler(inputs: Dict[str, Any], engine) -> Dict[str, Any]:
    """
    技术离场适配器入口

    Args:
        inputs:
            - positions: 持仓列表
            - market: 市场数据
            - a1_result: A1 调研结果（用于获取 market_state）

    Returns:
        技术离场评估结果
    """
    positions = inputs.get("positions", [])
    market = inputs.get("market", {})
    a1_result = inputs.get("a1_result", {})

    research = a1_result.get("research_report", {}) if isinstance(a1_result, dict) else {}
    market_state = research.get("market_state", {}) if isinstance(research, dict) else {}

    evaluations = []
    for pos in positions:
        tech_signal = _calc_simple_technical_signals(pos, market, market_state)
        evaluations.append({
            "position": {
                "symbol": pos.get("symbol", ""),
                "system": pos.get("system", ""),
                "direction": pos.get("direction", ""),
            },
            "technical_action": tech_signal.action,
            "technical_urgency": tech_signal.urgency,
            "technical_confidence": tech_signal.confidence,
            "technical_reason": tech_signal.reason,
            "signal_layers": tech_signal.source_layers,
        })

    return {
        "technical_evaluations": evaluations,
        "summary": {
            "total_positions": len(evaluations),
            "p0_triggered_count": sum(1 for e in evaluations if e["signal_layers"].get("p0_triggered")),
            "p1_triggered_count": sum(1 for e in evaluations if e["signal_layers"].get("p1_triggered")),
            "close_count": sum(1 for e in evaluations if e["technical_action"] == "CLOSE"),
            "reduce_count": sum(1 for e in evaluations if e["technical_action"] == "REDUCE"),
            "hold_count": sum(1 for e in evaluations if e["technical_action"] == "HOLD"),
        },
        "meta": {
            "version": "1.0.0-phase3",
            "source": "simplified_technical_analysis",
            "note": "ClassicExitSystem 完整集成需导入对应模块，当前为内置简化版",
        },
    }


if __name__ == "__main__":
    test_pos = {
        "symbol": "BTC",
        "direction": "LONG",
        "entry_price": 65000,
        "upl_ratio": -15.0,
        "leverage": 3.0,
        "system": "agent_a",
    }
    test_market = {
        "BTC": {"current_price": 55250, "change_24h_pct": -5.0},
    }
    test_state = {"rsi_1h": 22.5, "atr_pct": 4.5}

    signal = _calc_simple_technical_signals(test_pos, test_market, test_state)
    print(f"技术离场信号: {signal.action} ({signal.urgency})")
    print(f"置信度: {signal.confidence:.0%}")
    print(f"原因: {signal.reason}")
    print(f"P0触发: {signal.source_layers.get('p0_triggered')}")
    print(f"P1触发: {signal.source_layers.get('p1_triggered')}")
