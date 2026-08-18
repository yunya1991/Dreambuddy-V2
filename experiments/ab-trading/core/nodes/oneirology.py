"""
做梦部（Oneirology）节点
潜意识分析：检测强迫性重复模式，识别系统偏差

SKILL.md 调用路径: experiments/ab-trading/core/nodes/oneirology
"""

from typing import Dict, Any, List


def execute(mkt: Dict, memory: Dict, data: Dict) -> Dict[str, Any]:
    """
    执行做梦部潜意识分析

    Args:
        mkt: 市场数据
        memory: 记忆数据
        data: 节点间共享数据

    Returns:
        {
            "oneirology": True,  # 标记为做梦部执行
            "hold_streak": N,    # 连续 HOLD 次数
            "direction": "LONG" | "SHORT" | "HOLD",
            "confidence": 0.0-1.0,
            "rationale": [...],
            "pattern": {...}  # 强迫性重复模式详情
        }
    """
    reasoning = []

    # ── Step 1: 分析 recent_decisions ─────────────────────────────────
    recent = memory.get("recent_decisions", [])
    decisions = memory.get("decisions", [])

    # 合并两个来源，取最近 10 条
    all_decisions = recent[-10:] if recent else []
    if not all_decisions and decisions:
        all_decisions = decisions[-10:]

    hold_streak = 0
    decision_types = []

    for d in reversed(all_decisions):
        action = d.get("action", "UNKNOWN")
        decision_types.append(action)
        if action in ("HOLD", "hold", "HOLD_WAIT"):
            hold_streak += 1
        else:
            break

    reasoning.append(f"[做梦部] 分析近 {len(all_decisions)} 条决策记录")
    reasoning.append(f"  决策序列: {' → '.join(decision_types[:8])}")
    reasoning.append(f"  连续HOLD: {hold_streak} 次")

    # ── Step 2: 强迫性重复检测 ───────────────────────────────────────
    compulsive = hold_streak >= 3

    if compulsive:
        reasoning.append(f"⚠️ [强迫性重复] 连续{hold_streak}次HOLD，系统在回避什么？")
    else:
        reasoning.append(f"✅ 无强迫性重复模式")

    # ── Step 3: 反事实推演 ───────────────────────────────────────────
    suggestions = []
    confidence = 0.50
    direction = "HOLD"

    if compulsive:
        # 反事实分析：如果是趋势市场，系统应该怎么做？
        regime = mkt.get("regime", "RANGE")
        rsi = mkt.get("rsi14", 50)
        price = mkt.get("price", 0)
        ema20 = mkt.get("ema20", price)
        ema50 = mkt.get("ema50", price)

        if regime == "TREND_UP":
            suggestions.append("市场处于上升趋势，但系统连续HOLD，可能错失机会")
            if price > ema20:
                direction = "LONG"
                confidence = min(0.50 + hold_streak * 0.03, 0.75)
                reasoning.append(f"  → 反事实建议: 在上升趋势中应做多，当前价格>EMA20")
        elif regime == "TREND_DOWN":
            suggestions.append("市场处于下降趋势，但系统连续HOLD，可能是抄底冲动")
            if price < ema20:
                direction = "SHORT"
                confidence = min(0.50 + hold_streak * 0.03, 0.75)
                reasoning.append(f"  → 反事实建议: 在下降趋势中应做空，当前价格<EMA20")
        else:
            suggestions.append("震荡市中连续HOLD可能是合理的，但应关注突破信号")
            reasoning.append(f"  → 建议: 降低门禁门槛或切换策略类型")

        # RSI 分析
        if rsi > 60 and regime != "TREND_DOWN":
            suggestions.append("RSI偏高但系统未行动，可能过于保守")
            reasoning.append(f"  → RSI={rsi:.1f} 暗示上涨动能")

        # 资金费率分析
        fund_rate = mkt.get("funding_rate", 0)
        if fund_rate < -0.01:
            suggestions.append("负资金费率暗示空头拥挤，可能是做多机会")
            reasoning.append(f"  → 资金费率={fund_rate*100:.2f}% 暗示空头付多头")
            if direction == "HOLD":
                direction = "LONG"
                confidence = min(confidence + 0.05, 0.70)

    # ── Step 4: 潜意识建议 ───────────────────────────────────────────
    reasoning.append("")
    reasoning.append("【做梦部潜意识建议】")
    if suggestions:
        for s in suggestions[:3]:
            reasoning.append(f"  • {s}")
    else:
        reasoning.append("  • 无明显异常，继续观察")

    pattern = {
        "hold_streak": hold_streak,
        "compulsive": compulsive,
        "suggestions": suggestions,
        "decisions": decision_types,
    }

    return {
        "node": "做梦部",
        "oneirology": True,
        "hold_streak": hold_streak,
        "direction": direction,
        "confidence": round(confidence, 3),
        "rationale": reasoning,
        "pattern": pattern,
    }


def oneirology_execute(mkt: Dict, memory: Dict, data: Dict) -> Dict[str, Any]:
    return execute(mkt, memory, data)
