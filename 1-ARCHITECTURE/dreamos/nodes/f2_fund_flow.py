"""
F2 资金流分析节点

资金面分析：
    - 资金费率（多空拥挤度）
    - ETF 资金流
    - 交易所净流入/流出
    - 大额转账（鲸鱼动向）
"""

from __future__ import annotations

from typing import Dict, Any, List

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult


class F2FundFlowNode(BaseNode):
    """F2 资金流分析节点

    多维度资金面分析。
    """

    node_id = "F2"
    name = "资金流分析"
    description = "资金面分析（资金费率/净流入/大额转账）"
    chain = "F"
    tags = ["fundamental", "fund-flow", "on-chain"]
    estimated_tokens = 0
    estimated_latency_ms = 100

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        rationale: List[str] = []
        signals = []

        # ── 1. 资金费率 ──────────────────────
        funding = mkt.get("funding_rate", 0)
        funding_bps = funding * 10000

        if funding < -0.0005:  # -5bps
            signals.append(("LONG", 0.25, f"资金费率 {funding_bps:+.1f}bps，空头拥挤，反向做多"))
        elif funding > 0.0005:
            signals.append(("SHORT", 0.25, f"资金费率 {funding_bps:+.1f}bps，多头拥挤，反向做空"))
        elif funding < 0:
            signals.append(("LONG", 0.10, f"资金费率 {funding_bps:+.1f}bps，小幅偏空"))
        else:
            signals.append(("SHORT", 0.10, f"资金费率 {funding_bps:+.1f}bps，小幅偏多"))

        # ── 2. 交易所净流入 ──────────────────
        net_flow = mkt.get("exchange_netflow", 0)  # 正=净流入（抛压），负=净流出（吸筹）
        if net_flow > 1000:  # 大额流入
            signals.append(("SHORT", 0.20, f"交易所净流入 {net_flow:+.0f} BTC，抛压增大"))
        elif net_flow < -1000:
            signals.append(("LONG", 0.20, f"交易所净流出 {net_flow:+.0f} BTC，吸筹"))
        elif net_flow > 0:
            signals.append(("SHORT", 0.08, f"交易所小幅流入 {net_flow:+.0f} BTC"))
        else:
            signals.append(("LONG", 0.08, f"交易所小幅流出 {net_flow:+.0f} BTC"))

        # ── 3. 鲸鱼动向 ─────────────────────
        whale_transfers = mkt.get("whale_transfers", 0)
        if whale_transfers > 10:
            signals.append(("SHORT", 0.15, f"大额转账 {whale_transfers} 笔，鲸鱼活跃偏空"))
        elif whale_transfers < -5:
            signals.append(("LONG", 0.15, f"大额转账减少，鲸鱼持仓稳定"))

        # ── 4. ETF 资金流 ───────────────────
        etf_flow = mkt.get("etf_flow", 0)  # 正=流入
        if etf_flow > 100:  # 百万美元
            signals.append(("LONG", 0.20, f"ETF 净流入 ${etf_flow:+.0f}M，机构入场"))
        elif etf_flow < -100:
            signals.append(("SHORT", 0.20, f"ETF 净流出 ${etf_flow:+.0f}M，机构离场"))

        # ── 综合 ──────────────────────────
        long_score = sum(w for d, w, _ in signals if d == "LONG")
        short_score = sum(w for d, w, _ in signals if d == "SHORT")
        total = long_score + short_score

        if total == 0:
            direction = "HOLD"
            confidence = 0.3
        elif long_score > short_score:
            direction = "LONG"
            confidence = long_score / max(total, 0.01)
        else:
            direction = "SHORT"
            confidence = short_score / max(total, 0.01)

        confidence = min(max(confidence, 0.25), 0.85)

        rationale.append("[F2资金流] 资金面分析")
        for _, _, r in signals:
            rationale.append(f"  • {r}")
        rationale.append(f"  综合: {direction} | 置信度 {confidence:.1%}")

        return NodeResult(
            node_id="F2",
            confidence=round(confidence, 3),
            direction=direction,
            outputs={
                "funding_rate": funding,
                "funding_bps": funding_bps,
                "exchange_netflow": net_flow,
                "whale_transfers": whale_transfers,
                "etf_flow": etf_flow,
                "signals": [
                    {"direction": d, "weight": w, "rationale": r}
                    for d, w, r in signals
                ],
                "rationale": rationale,
            },
        )

    def _get_market_data(self, state: State) -> Dict[str, Any]:
        if hasattr(state, "market_data") and state.market_data:
            return state.market_data
        if isinstance(state.inputs, dict) and "mkt" in state.inputs:
            return state.inputs["mkt"]
        if isinstance(state.inputs, dict):
            return state.inputs
        return {}
