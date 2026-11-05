"""executor_agent.py — 执行策略 agent Phase 1（运行骨架）

定位（SPEC-L0-TRADE-EXEC-MCP §10）：只做**执行层建议**，不改变方向、不下单。
  输入：signal（方向/置信度）+ context（风控等级/波动/是否过期）
  输出：{execute, size_multiplier, order_type, urgency, reasons, policy_version}

硬约束：
  - 只能建议，最终下单仍经 place_order 的 ExecutionRights 闸门 + RiskBridge（fail-closed）
  - policy 可注入（Phase 1b 训练后替换），但安全钳位始终在本模块生效
  - critical 风险等级强制 execute=False；size_multiplier 上限 1.0
"""

from __future__ import annotations

from typing import Any, Dict, Optional

POLICY_VERSION = "phase1-rule-v1"
MIN_CONFIDENCE = 0.60
HIGH_VOL_BPS = 60.0
MAX_SIZE_MULTIPLIER = 1.0


class ExecutorAgent:
    """规则底座 + 可替换 policy 的执行建议器。"""

    def __init__(self, policy: Optional[Any] = None, policy_version: str = POLICY_VERSION):
        self.policy = policy
        self.policy_version = policy_version

    def decide(
        self, signal: Dict[str, Any], context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        ctx = context or {}
        reasons = []
        execute = True

        confidence = _f(signal.get("confidence"), 0.0)
        volatility_bps = _f(ctx.get("volatility_bps"), 0.0)
        risk_level = str(ctx.get("risk_level") or "normal").lower()

        if ctx.get("expired") or signal.get("expired"):
            execute = False
            reasons.append("expired")
        if confidence < MIN_CONFIDENCE:
            execute = False
            reasons.append("low_confidence")
        if risk_level == "critical":
            execute = False
            reasons.append("risk_critical")

        multiplier = MAX_SIZE_MULTIPLIER
        if confidence < 0.80:
            multiplier = min(multiplier, 0.6)
        if volatility_bps > HIGH_VOL_BPS:
            multiplier = min(multiplier, 0.5)
        if risk_level == "high":
            multiplier = min(multiplier, 0.5)
        if risk_level == "critical":
            multiplier = 0.0

        # Phase 1b：训练后的 policy 只影响乘数与单型，仍受上方钳位
        if self.policy is not None and execute:
            try:
                suggestion = (
                    self.policy.predict(
                        {
                            "confidence": confidence,
                            "volatility_bps": volatility_bps,
                            "risk_level": risk_level,
                        }
                    )
                    or {}
                )
                multiplier = min(
                    multiplier,
                    _f(suggestion.get("size_multiplier"), multiplier),
                    MAX_SIZE_MULTIPLIER,
                )
            except Exception:  # noqa: BLE001 — policy 失败降级到规则底座
                reasons.append("policy_fallback")

        order_type = "limit" if (volatility_bps > HIGH_VOL_BPS or confidence < 0.70) else "market"
        if confidence >= 0.85 and volatility_bps <= HIGH_VOL_BPS:
            urgency = "high"
        elif confidence < 0.70:
            urgency = "low"
        else:
            urgency = "normal"

        return {
            "execute": execute,
            "size_multiplier": round(max(0.0, multiplier), 4),
            "order_type": order_type,
            "urgency": urgency,
            "direction": signal.get("direction") or "",
            "reasons": reasons,
            "policy_version": self.policy_version,
        }


def _f(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
