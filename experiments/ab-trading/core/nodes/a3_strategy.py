"""
A3 策略设计节点
设计具体交易策略，计算仓位、止损止盈、R:R

SKILL.md 调用路径: experiments/ab-trading/core/nodes/a3_strategy
"""

from typing import Dict, Any


def execute(mkt: Dict, memory: Dict, data: Dict) -> Dict[str, Any]:
    """
    执行 A3 策略设计（含 A0 矛盾验证）

    Args:
        mkt: 市场数据
        memory: 记忆数据
        data: 节点间共享数据

    Returns:
        {
            "direction": "LONG" | "SHORT" | "HOLD",
            "confidence": 0.0-1.0,
            "rationale": [...],
            "strategy": {...}  # 策略详情
        }
    """
    price = mkt.get("price", 0)
    coin = mkt.get("coin", "BTC")
    rsi = mkt.get("rsi14", 50)
    atr = mkt.get("atr14", price * 0.02)

    reasoning = []
    strategy = {}

    # ── 收集方向和置信度 ────────────────────────────────────────────────
    direction = data.get("direction", "HOLD")
    confidence = data.get("confidence", 0.45)

    # ── A0 矛盾一致性校验 ─────────────────────────────────────────────
    a0_data = data.get("a0", {})
    if not a0_data and "a0" in data:
        a0_data = data["a0"]

    dom = a0_data.get("dominant_force", "NEUTRAL")
    reasoning.append(f"[A3-A0验证] 策略方向={direction} vs 矛盾主导={dom}")

    consistent = (dom == "BULL" and direction in ("LONG", "BUY")) or \
                 (dom == "BEAR" and direction in ("SHORT", "SELL")) or \
                 dom == "NEUTRAL" or direction == "HOLD"

    if consistent:
        adj_conf = confidence
        reasoning.append(f"✅ 策略与矛盾一致 ✓")
    else:
        adj_conf = round(confidence * 0.85, 3)
        reasoning.append(f"⚠️ 策略与矛盾不一致，置信度折扣至 {adj_conf:.0%}")

    # ── 策略设计 ───────────────────────────────────────────────────────
    if direction == "HOLD":
        reasoning.append("[策略] 无有效方向，跳过策略设计")
        return {
            "node": "A3_策略设计(含A0)",
            "direction": "HOLD",
            "confidence": 0.50,
            "rationale": reasoning,
            "strategy": {},
        }

    # 仓位计算
    equity = memory.get("equity", 60.0)
    position_size = min(equity * 0.05, 10.0)  # 5% 仓位，最大 10U

    # 止损止盈计算
    if direction == "LONG":
        stop_loss = round(price * (1 - atr / price * 1.5), 4)  # 1.5 ATR
        take_profit = round(price * (1 + atr / price * 3.0), 4)  # 3 ATR
        rr_ratio = (take_profit - price) / (price - stop_loss)
    else:  # SHORT
        stop_loss = round(price * (1 + atr / price * 1.5), 4)
        take_profit = round(price * (1 - atr / price * 3.0), 4)
        rr_ratio = (price - take_profit) / (stop_loss - price)

    # R:R 评估
    if rr_ratio >= 2.0:
        rr_rating = "✅ 优秀"
    elif rr_ratio >= 1.5:
        rr_rating = "⚠️ 一般"
    else:
        rr_rating = "❌ 较差"

    reasoning.append(f"[策略] {direction} {coin} @ ${price:.4f}")
    reasoning.append(f"  仓位: {position_size:.2f} USDT ({position_size/equity*100:.1f}%)")
    reasoning.append(f"  止损: ${stop_loss:.4f} ({abs(price-stop_loss)/price*100:.1f}%)")
    reasoning.append(f"  止盈: ${take_profit:.4f} ({abs(take_profit-price)/price*100:.1f}%)")
    reasoning.append(f"  R:R: {rr_ratio:.2f}:1 {rr_rating}")

    strategy = {
        "coin": coin,
        "direction": direction,
        "entry_price": price,
        "position_size": round(position_size, 2),
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "rr_ratio": round(rr_ratio, 2),
        "leverage": min(5, max(1, int(adj_conf * 5))),
    }

    return {
        "node": "A3_策略设计(含A0)",
        "direction": direction,
        "confidence": round(adj_conf, 3),
        "rationale": reasoning,
        "strategy": strategy,
    }


def a3_execute(mkt: Dict, memory: Dict, data: Dict) -> Dict[str, Any]:
    return execute(mkt, memory, data)
