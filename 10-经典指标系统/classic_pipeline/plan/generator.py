"""计划生成层（Plan Generator）。

聚合信号和风控输出生成交易计划。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from classic_pipeline.core.utils import _sf0


def generate(
    signal: Dict[str, Any],
    risk_result: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """生成交易计划。

    Args:
        signal: 信号 {direction, confidence, strategy, entry_price}
        risk_result: 风控结果 {approved, position_size, stop_loss, take_profit}
        config: 配置

    Returns:
        {entry_decision, direction, entry_price, stop_loss, take_profit,
         position_size, confidence, strategy}
    """
    cfg = config or {}
    direction = str(signal.get("direction") or "neutral").strip().lower()
    confidence = _sf0(signal.get("confidence"), 0.0)

    # 默认 entry_decision
    entry_decision = "observe"
    if direction in ("long", "short") and confidence > 0:
        entry_decision = "open"

    # 风控结果
    rr = risk_result or {}
    approved = bool(rr.get("approved", False))
    position_size = _sf0(rr.get("position_size"), 0.0)
    stop_loss = _sf0(rr.get("stop_loss"), 0.0)
    take_profit = _sf0(rr.get("take_profit"), 0.0)

    # 风控未通过则观察
    if not approved:
        entry_decision = "observe"

    entry_price = _sf0(signal.get("entry_price"), 0.0)

    # 计算具体的止损/止盈价格
    sl_price = 0.0
    tp_price = 0.0
    if entry_price > 0:
        if direction == "long":
            sl_price = entry_price * (1 - stop_loss)
            tp_price = entry_price * (1 + take_profit)
        elif direction == "short":
            sl_price = entry_price * (1 + stop_loss)
            tp_price = entry_price * (1 - take_profit)

    return {
        "entry_decision": entry_decision,
        "direction": direction,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "stop_loss_price": sl_price,
        "take_profit": take_profit,
        "take_profit_price": tp_price,
        "position_size": position_size,
        "confidence": confidence,
        "strategy": signal.get("strategy", ""),
    }
