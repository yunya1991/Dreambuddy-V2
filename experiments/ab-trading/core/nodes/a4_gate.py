"""
A4 门禁节点
A7 实践论闸门：置信度 ≥ 65% 才允许开仓

SKILL.md 调用路径: experiments/ab-trading/core/nodes/a4_gate
"""

from typing import Dict, Any


GATE_THRESHOLD = 0.65  # 默认门禁门槛


def execute(mkt: Dict, memory: Dict, data: Dict,
            threshold: float = GATE_THRESHOLD) -> Dict[str, Any]:
    """
    执行 A4/A7 门禁检查

    Args:
        mkt: 市场数据
        memory: 记忆数据
        data: 节点间共享数据（从前序节点累积的置信度和方向）
        threshold: 门禁门槛（默认 65%）

    Returns:
        {
            "gate_passed": True | False,
            "direction": "LONG" | "SHORT" | "HOLD",
            "confidence": 0.0-1.0,
            "reason": "通过/拦截原因",
            "rationale": [...]
        }
    """
    # ── 收集前序节点数据 ─────────────────────────────────────────────────
    # 方向和置信度应该从前序节点累积
    direction = data.get("direction", "HOLD")
    confidence = data.get("confidence", 0.0)

    # 如果 data 中有 node_results，从最后执行的节点获取
    if "node_results" in data and data["node_results"]:
        last_result = data["node_results"][-1]
        direction = last_result.get("direction", direction)
        confidence = last_result.get("confidence", confidence)

    reasoning = [
        f"[A4/A7 门禁] 置信度: {confidence:.0%} | 门槛: {threshold:.0%}",
        f"方向: {direction}",
    ]

    # ── 门禁检查 ───────────────────────────────────────────────────────
    gate_passed = confidence >= threshold and direction != "HOLD"

    if gate_passed:
        reasoning.append(f"✅ A7 闸门通过: {confidence:.0%} ≥ {threshold:.0%}")
        gate_reason = f"置信度{confidence:.0%} ≥ 门槛{threshold:.0%}，允许开仓"
    else:
        if confidence < threshold:
            reasoning.append(f"❌ A7 拦截: 置信度{confidence:.0%} < 门槛{threshold:.0%}")
            gate_reason = f"置信度{confidence:.0%} < 门槛{threshold:.0%}，未过A7"
        else:
            reasoning.append(f"❌ A7 拦截: 方向={direction}（非交易方向）")
            gate_reason = f"方向={direction}，无有效信号"

    # ── A8 知行合一检查 ────────────────────────────────────────────────
    intent_confidence = data.get("intent_confidence", 0.0)
    if intent_confidence > 0:
        gap = abs(confidence - intent_confidence)
        reasoning.append(f"[A8 知行合一] 意图={intent_confidence:.0%} vs 执行={confidence:.0%} | Gap={gap:+.0%}")
        if gap > 0.25:
            reasoning.append(f"⚠️ 知行偏差大({gap:.0%})，建议反思")
        elif gap <= 0.10:
            reasoning.append(f"✅ 知行基本一致")

    return {
        "node": "A4_门禁",
        "gate_passed": gate_passed,
        "direction": direction,
        "confidence": round(confidence, 3),
        "reason": gate_reason,
        "rationale": reasoning,
    }


def a4_execute(mkt: Dict, memory: Dict, data: Dict) -> Dict[str, Any]:
    return execute(mkt, memory, data)
