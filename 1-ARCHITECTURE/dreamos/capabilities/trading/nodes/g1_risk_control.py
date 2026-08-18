"""
G1 风控节点

基于治理系统的风控能力：
    - 最大回撤检查
    - 日亏损限制
    - 持仓集中度限制
    - 杠杆限制
    - 流动性检查
    - 风险预算管理

输入: state.account + state.position + state.market_data
输出: direction / confidence / risk_level / risk_warnings / risk_score / rationale
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult


class G1RiskControlNode(BaseNode):
    """G1 风控节点

    账户级风险控制，确保交易在风险预算内执行。
    """

    node_id = "G1"
    name = "风控检查"
    description = "账户级风控检查（最大回撤/日亏损/持仓集中度/杠杆/流动性/风险预算）"
    chain = "G"
    tags = ["risk", "governance", "risk_control", "max_drawdown", "position_limit"]
    estimated_tokens = 0
    estimated_latency_ms = 100

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        account = self._get_account(state)
        position = self._get_position(state)
        rationale: List[str] = []
        risk_warnings: List[str] = []
        scores = []

        equity = account.get("equity", 10000)
        max_equity = account.get("max_equity", equity)
        daily_pnl = account.get("daily_pnl", 0)
        daily_pnl_pct = account.get("daily_pnl_pct", 0)
        position_size = position.get("size", 0)
        leverage = position.get("leverage", 1)

        max_drawdown_pct = self.config.get("max_drawdown_pct", 10)
        max_daily_loss_pct = self.config.get("max_daily_loss_pct", 5)
        max_position_pct = self.config.get("max_position_pct", 50)
        max_leverage = self.config.get("max_leverage", 10)

        # ── 1. 最大回撤检查 ──────────────────────────────
        drawdown = 0
        if max_equity > 0:
            drawdown = (max_equity - equity) / max_equity * 100

        if drawdown > max_drawdown_pct:
            risk_warnings.append(f"最大回撤超限({drawdown:.1f}% > {max_drawdown_pct}%)")
            scores.append(("HOLD", 0.30, f"回撤超限，停止开新仓"))
        elif drawdown > max_drawdown_pct * 0.7:
            risk_warnings.append(f"回撤接近阈值({drawdown:.1f}%)")
            scores.append(("HOLD", 0.15, f"回撤偏高，谨慎操作"))

        # ── 2. 日亏损限制 ────────────────────────────────
        if daily_pnl_pct < -max_daily_loss_pct:
            risk_warnings.append(f"日亏损超限({daily_pnl_pct:.1f}% > -{max_daily_loss_pct}%)")
            scores.append(("HOLD", 0.30, f"日亏损超限，停止交易"))
        elif daily_pnl_pct < -max_daily_loss_pct * 0.7:
            scores.append(("HOLD", 0.10, f"日亏损偏高({daily_pnl_pct:.1f}%)"))

        # ── 3. 持仓集中度限制 ────────────────────────────
        position_value = position_size * mkt.get("price", 0)
        position_pct = (position_value / max(equity, 1)) * 100 if equity > 0 else 0

        if position_pct > max_position_pct:
            risk_warnings.append(f"持仓集中度过高({position_pct:.1f}% > {max_position_pct}%)")
            scores.append(("REDUCE", 0.20, f"持仓集中，建议减仓"))

        # ── 4. 杠杆限制 ──────────────────────────────────
        if leverage > max_leverage:
            risk_warnings.append(f"杠杆超限({leverage}x > {max_leverage}x)")
            scores.append(("HOLD", 0.25, f"杠杆过高，降低杠杆"))

        # ── 5. 流动性检查 ────────────────────────────────
        volume_24h = mkt.get("volume_24h", 0)
        if volume_24h < 1000000:
            risk_warnings.append(f"流动性不足(24h量={volume_24h:.0f})")
            scores.append(("HOLD", 0.15, f"流动性不足，谨慎交易"))

        # ── 6. 风险预算管理 ──────────────────────────────
        risk_budget_remaining = max(0, max_drawdown_pct - drawdown)
        if risk_budget_remaining < 2:
            scores.append(("HOLD", 0.20, f"风险预算不足({risk_budget_remaining:.1f}%)"))

        # ── 综合计算 ────────────────────────────────────
        long_score = sum(w for d, w, _ in scores if d == "LONG")
        short_score = sum(w for d, w, _ in scores if d == "SHORT")
        hold_score = sum(w for d, w, _ in scores if d == "HOLD")
        reduce_score = sum(w for d, w, _ in scores if d == "REDUCE")

        total = long_score + short_score + hold_score + reduce_score

        if total == 0:
            direction = "LONG"
            confidence = 0.9
            risk_level = "safe"
        elif hold_score > 0.5:
            direction = "HOLD"
            confidence = 0.8
            risk_level = "high"
        elif reduce_score > 0.2:
            direction = "REDUCE"
            confidence = 0.7
            risk_level = "medium"
        elif long_score > short_score:
            direction = "LONG"
            confidence = min(0.9, long_score / max(total, 0.01))
            risk_level = "safe"
        else:
            direction = "SHORT"
            confidence = min(0.9, short_score / max(total, 0.01))
            risk_level = "safe"

        risk_score = 1 - (hold_score + reduce_score)
        if risk_score < 0.3:
            risk_level = "high"
        elif risk_score < 0.7:
            risk_level = "medium"

        rationale = [r for _, _, r in scores[:6]]
        rationale.insert(0, f"[G1风控] 风险等级={risk_level} | 风险得分={risk_score:.2f}")
        if risk_warnings:
            rationale.append(f"  风险警告: {'; '.join(risk_warnings)}")
        rationale.append(f"  方向: {direction} | 置信度: {confidence:.1%}")

        outputs = {
            "risk_level": risk_level,
            "risk_score": round(risk_score, 3),
            "risk_warnings": risk_warnings,
            "drawdown": round(drawdown, 2),
            "max_drawdown_limit": max_drawdown_pct,
            "daily_pnl": round(daily_pnl, 2),
            "daily_pnl_pct": round(daily_pnl_pct, 2),
            "max_daily_loss_limit": max_daily_loss_pct,
            "position_pct": round(position_pct, 2),
            "max_position_limit": max_position_pct,
            "leverage": leverage,
            "max_leverage_limit": max_leverage,
            "liquidity": {
                "volume_24h": volume_24h,
            },
            "risk_budget_remaining": round(risk_budget_remaining, 2),
            "scores": {
                "long": round(long_score, 3),
                "short": round(short_score, 3),
                "hold": round(hold_score, 3),
                "reduce": round(reduce_score, 3),
            },
            "rationale": rationale,
        }

        return NodeResult(
            node_id="G1",
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

    def _get_account(self, state: State) -> Dict[str, Any]:
        if hasattr(state, "account") and state.account:
            return state.account
        if isinstance(state.intent, dict) and "account" in state.intent:
            return state.intent["account"]
        return {"equity": 10000, "max_equity": 10000, "daily_pnl": 0, "daily_pnl_pct": 0}

    def _get_position(self, state: State) -> Dict[str, Any]:
        if hasattr(state, "position") and state.position:
            return state.position
        if isinstance(state.intent, dict) and "position" in state.intent:
            return state.intent["position"]
        return {"size": 0, "direction": "LONG", "leverage": 1}