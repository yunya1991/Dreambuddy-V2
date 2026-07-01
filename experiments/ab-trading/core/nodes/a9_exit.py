"""
A9 离场评估节点
评估现有持仓是否需要离场，调整止损止盈

SKILL.md 调用路径: experiments/ab-trading/core/nodes/a9_exit
"""

from typing import Dict, Any, List


def execute(mkt: Dict, memory: Dict, data: Dict) -> Dict[str, Any]:
    """
    执行 A9 离场评估

    Args:
        mkt: 市场数据
        memory: 记忆数据（包含 active_positions）
        data: 节点间共享数据

    Returns:
        {
            "direction": "HOLD",  # A9 不改变方向
            "confidence": 0.5,
            "rationale": [...],
            "exits": [...]  # 离场建议列表
        }
    """
    coin = mkt.get("coin", "BTC")
    price = mkt.get("price", 0)
    rsi = mkt.get("rsi14", 50)

    reasoning = []
    exits: List[Dict] = []

    active_positions = memory.get("active_positions", {})

    if not active_positions:
        reasoning.append("无活跃持仓，跳过离场评估")
        return {
            "node": "A9_离场评估",
            "direction": "HOLD",
            "confidence": 0.50,
            "rationale": reasoning,
            "exits": [],
        }

    reasoning.append(f"评估 {len(active_positions)} 个持仓...")

    def _is_long(act: str) -> bool:
        return (act or "").upper() in ("LONG", "BUY", "LONG_BUY")

    def _is_short(act: str) -> bool:
        return (act or "").upper() in ("SHORT", "SELL", "SHORT_SELL")

    for pos_coin, pos in active_positions.items():
        action = pos.get("action", "LONG")
        entry_price = pos.get("entry_price", 0)
        stop_loss = pos.get("stop_loss", 0)
        take_profit = pos.get("take_profit", 0)
        size = pos.get("size", 0)
        pnl_pct = pos.get("pnl_pct", 0)

        pos_reasoning = [f"[{pos_coin}] 持仓: {action} @ {entry_price:.4f}"]

        # ── L1 基础检查 ───────────────────────────────────────────────
        l1_triggered = False
        l1_reason = ""

        if price > 0 and entry_price > 0:
            if _is_long(action):
                if stop_loss > 0 and price <= stop_loss:
                    l1_triggered = True
                    l1_reason = f"L1止损触发: ${price:.4f} <= ${stop_loss:.4f}"
                elif take_profit > 0 and price >= take_profit:
                    l1_triggered = True
                    l1_reason = f"L1止盈触发: ${price:.4f} >= ${take_profit:.4f}"
                elif pnl_pct < -0.03:
                    l1_triggered = True
                    l1_reason = f"浮亏超3%: {pnl_pct*100:+.1f}%"
                elif pnl_pct > 0.06:
                    # 移动止损检查
                    new_sl = round(entry_price * 1.02, 4)  # 保本 + 2%
                    if stop_loss < new_sl:
                        exits.append({
                            "coin": pos_coin,
                            "action": "UPDATE_SL",
                            "old_sl": stop_loss,
                            "new_sl": new_sl,
                            "reason": f"浮盈{pnl_pct*100:+.1f}%，上移止损至 ${new_sl:.4f}",
                        })
                        pos_reasoning.append(f"✅ 上移止损至 ${new_sl:.4f}")
            elif _is_short(action):
                if stop_loss > 0 and price >= stop_loss:
                    l1_triggered = True
                    l1_reason = f"L1止损触发: ${price:.4f} >= ${stop_loss:.4f}"
                elif take_profit > 0 and price <= take_profit:
                    l1_triggered = True
                    l1_reason = f"L1止盈触发: ${price:.4f} <= ${take_profit:.4f}"

        if l1_triggered:
            exits.append({
                "coin": pos_coin,
                "action": "CLOSE",
                "reason": l1_reason,
                "pnl_pct": pnl_pct,
            })
            pos_reasoning.append(f"🚨 {l1_reason}")
        else:
            pos_reasoning.append(f"  当前盈亏: {pnl_pct*100:+.2f}% | 止损: ${stop_loss:.4f} | 止盈: ${take_profit:.4f}")

        # ── A9 智能评估 ────────────────────────────────────────────────
        if not l1_triggered:
            # RSI 超买/超卖评估
            if _is_long(action) and rsi > 75:
                exits.append({
                    "coin": pos_coin,
                    "action": "CLOSE",
                    "reason": f"A9 RSI超买警告: {rsi:.1f}",
                    "pnl_pct": pnl_pct,
                })
                pos_reasoning.append(f"⚠️ A9: RSI={rsi:.1f} 超买，建议止盈")
            elif _is_short(action) and rsi < 25:
                exits.append({
                    "coin": pos_coin,
                    "action": "CLOSE",
                    "reason": f"A9 RSI超卖警告: {rsi:.1f}",
                    "pnl_pct": pnl_pct,
                })
                pos_reasoning.append(f"⚠️ A9: RSI={rsi:.1f} 超卖，建议止盈")

        reasoning.extend(pos_reasoning)

    if not exits:
        reasoning.append("✅ 无触发离场条件，继续持有")

    return {
        "node": "A9_离场评估",
        "direction": "HOLD",
        "confidence": 0.50,
        "rationale": reasoning,
        "exits": exits,
    }


def a9_execute(mkt: Dict, memory: Dict, data: Dict) -> Dict[str, Any]:
    return execute(mkt, memory, data)
