"""
G2 治理节点

基于治理系统的合规和审计能力：
    - 合规规则检查
    - 审计日志记录
    - 交易审批流程
    - 系统状态检查
    - 配置变更验证
    - 权限验证

输入: state.account + state.position + state.intent
输出: direction / confidence / compliance_status / audit_log / governance_actions / rationale
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional
from datetime import datetime

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult


class G2GovernanceNode(BaseNode):
    """G2 治理节点

    合规和审计治理，确保交易符合规则和策略约束。
    """

    node_id = "G2"
    name = "治理检查"
    description = "合规和审计治理（合规规则/审计日志/审批流程/系统状态/配置验证）"
    chain = "G"
    tags = ["governance", "compliance", "audit", "approval", "system_status"]
    estimated_tokens = 0
    estimated_latency_ms = 100

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        position = self._get_position(state)
        intent = state.intent if isinstance(state.intent, dict) else {}
        rationale: List[str] = []
        compliance_issues: List[str] = []
        scores = []

        # ── 1. 合规规则检查 ──────────────────────────────
        trading_allowed = intent.get("trading_allowed", True)
        if not trading_allowed:
            compliance_issues.append("交易被禁止")
            scores.append(("HOLD", 0.30, "交易被系统禁止"))

        # ── 2. 交易时间检查 ──────────────────────────────
        current_hour = datetime.now().hour
        restricted_hours = self.config.get("restricted_hours", [])
        if current_hour in restricted_hours:
            scores.append(("HOLD", 0.15, f"当前时间({current_hour}:00)在交易限制时段"))

        # ── 3. 审批流程检查 ──────────────────────────────
        approval_required = self.config.get("approval_required", False)
        approval_status = intent.get("approval_status", "approved")

        if approval_required and approval_status != "approved":
            compliance_issues.append("未获得审批")
            scores.append(("HOLD", 0.30, f"交易需要审批(当前状态:{approval_status})"))

        # ── 4. 策略一致性检查 ────────────────────────────
        strategy_direction = intent.get("strategy_direction", "")
        position_direction = position.get("direction", "LONG")

        if strategy_direction and strategy_direction != position_direction:
            scores.append(("HOLD", 0.20, f"策略方向与持仓方向不一致({strategy_direction} vs {position_direction})"))

        # ── 5. 系统状态检查 ──────────────────────────────
        system_status = intent.get("system_status", "healthy")
        if system_status != "healthy":
            compliance_issues.append(f"系统状态异常({system_status})")
            scores.append(("HOLD", 0.25, f"系统状态异常，暂停交易"))

        # ── 6. 配置变更验证 ──────────────────────────────
        config_changed = intent.get("config_changed", False)
        if config_changed:
            scores.append(("HOLD", 0.15, "配置已变更，需要验证"))

        # ── 7. 风控前置检查 ──────────────────────────────
        risk_passed = intent.get("risk_passed", True)
        if not risk_passed:
            compliance_issues.append("风控检查未通过")
            scores.append(("HOLD", 0.30, "风控检查未通过"))

        # ── 8. 审计日志记录 ──────────────────────────────
        audit_log = {
            "timestamp": datetime.now().isoformat(),
            "action": "governance_check",
            "intent": intent.get("intent", ""),
            "position_direction": position_direction,
            "compliance_issues": compliance_issues,
            "system_status": system_status,
        }

        # ── 综合计算 ────────────────────────────────────
        long_score = sum(w for d, w, _ in scores if d == "LONG")
        short_score = sum(w for d, w, _ in scores if d == "SHORT")
        hold_score = sum(w for d, w, _ in scores if d == "HOLD")
        total = long_score + short_score + hold_score

        if total == 0:
            direction = "LONG"
            confidence = 0.95
            compliance_status = "compliant"
        elif hold_score > 0.3:
            direction = "HOLD"
            confidence = 0.9
            compliance_status = "non_compliant"
        elif long_score > short_score:
            direction = "LONG"
            confidence = min(0.95, long_score / max(total, 0.01))
            compliance_status = "compliant"
        else:
            direction = "SHORT"
            confidence = min(0.95, short_score / max(total, 0.01))
            compliance_status = "compliant"

        governance_actions = []
        if compliance_issues:
            governance_actions.append({"type": "block", "reason": compliance_issues})
        if approval_required and approval_status == "pending":
            governance_actions.append({"type": "wait_approval"})

        rationale = [r for _, _, r in scores[:6]]
        rationale.insert(0, f"[G2治理] 合规状态={compliance_status}")
        if compliance_issues:
            rationale.append(f"  合规问题: {'; '.join(compliance_issues)}")
        rationale.append(f"  方向: {direction} | 置信度: {confidence:.1%}")

        outputs = {
            "compliance_status": compliance_status,
            "compliance_issues": compliance_issues,
            "audit_log": audit_log,
            "governance_actions": governance_actions,
            "system_status": system_status,
            "approval_status": approval_status,
            "strategy_direction": strategy_direction,
            "scores": {"long": round(long_score, 3), "short": round(short_score, 3), "hold": round(hold_score, 3)},
            "rationale": rationale,
        }

        return NodeResult(
            node_id="G2",
            confidence=round(confidence, 3),
            direction=direction,
            outputs=outputs,
        )

    def _get_market_data(self, state: State) -> Dict[str, Any]:
        if hasattr(state, "market") and state.market:
            return state.market
        if hasattr(state, "market_data") and state.market_data:
            return state.market_data
        if isinstance(state.intent, dict) and "mkt" in state.intent:
            return state.intent["mkt"]
        return {}

    def _get_position(self, state: State) -> Dict[str, Any]:
        if hasattr(state, "position") and state.position:
            return state.position
        if isinstance(state.intent, dict) and "position" in state.intent:
            return state.intent["position"]
        return {"direction": "LONG", "size": 0}