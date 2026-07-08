"""
F4 链上数据节点 — 链上指标综合分析
"""

from __future__ import annotations

from typing import Dict, Any, List

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult


class F4OnchainNode(BaseNode):
    """F4 链上数据节点

    链上指标综合分析（MVP 占位实现）:
        - 交易所净流入/流出
        - 大额转账（鲸鱼动向）
        - 活跃地址数
        - 链上活跃度
    """

    node_id = "F4"
    name = "链上数据"
    description = "链上指标综合分析（交易所资金/鲸鱼动向/活跃地址）"
    chain = "F"
    tags = ["fundamental", "on-chain", "whale"]
    estimated_tokens = 0
    estimated_latency_ms = 100

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        rationale: List[str] = []
        signals = []

        exchange_netflow = mkt.get("exchange_netflow", 0)
        whale_transfers = mkt.get("whale_transfers", 0)
        active_addresses = mkt.get("active_addresses", 0)
        chain_activity = mkt.get("chain_activity", 0.5)
        price = mkt.get("price", 0)

        if exchange_netflow != 0:
            if exchange_netflow < -500:
                signals.append(("LONG", 0.25, f"交易所净流出 {exchange_netflow:+.0f} BTC，吸筹"))
            elif exchange_netflow > 500:
                signals.append(("SHORT", 0.25, f"交易所净流入 {exchange_netflow:+.0f} BTC，抛压"))
            elif exchange_netflow < 0:
                signals.append(("LONG", 0.10, f"交易所小幅流出"))
            else:
                signals.append(("SHORT", 0.10, f"交易所小幅流入"))

        if whale_transfers != 0:
            if whale_transfers > 15:
                signals.append(("SHORT", 0.20, f"大额转账活跃({whale_transfers}笔)，鲸鱼出货"))
            elif whale_transfers < -5:
                signals.append(("LONG", 0.20, f"大额转账减少，鲸鱼持仓稳定"))

        if active_addresses != 0:
            addr_trend = mkt.get("active_addresses_trend", 0)
            if addr_trend > 0.1:
                signals.append(("LONG", 0.15, f"活跃地址增长({addr_trend:.0%})"))
            elif addr_trend < -0.1:
                signals.append(("SHORT", 0.15, f"活跃地址下降({addr_trend:.0%})"))

        if chain_activity != 0:
            if chain_activity > 0.7:
                signals.append(("LONG", 0.10, f"链上活跃度高({chain_activity:.0%})"))
            elif chain_activity < 0.3:
                signals.append(("SHORT", 0.10, f"链上活跃度低({chain_activity:.0%})"))

        long_score = sum(w for d, w, _ in signals if d == "LONG")
        short_score = sum(w for d, w, _ in signals if d == "SHORT")
        total = long_score + short_score

        if total == 0:
            direction = "HOLD"
            confidence = 0.35
        elif long_score > short_score:
            direction = "LONG"
            confidence = long_score / max(total, 0.01)
        else:
            direction = "SHORT"
            confidence = short_score / max(total, 0.01)

        confidence = min(max(confidence, 0.25), 0.85)

        rationale.append("[F4链上] 链上数据分析")
        for _, _, r in signals:
            rationale.append(f"  • {r}")
        rationale.append(f"  综合: {direction} | 置信度 {confidence:.1%}")

        return NodeResult(
            node_id="F4",
            confidence=round(confidence, 3),
            direction=direction,
            outputs={
                "rationale": rationale,
                "exchange_netflow": exchange_netflow,
                "whale_transfers": whale_transfers,
                "active_addresses": active_addresses,
                "chain_activity": chain_activity,
                "signals": signals,
            },
        )

    def _get_market_data(self, state: State) -> Dict[str, Any]:
        if hasattr(state, "market") and state.market:
            return state.market
        if hasattr(state, "market_data") and state.market_data:
            return state.market_data
        if isinstance(state.intent, dict) and "mkt" in state.intent:
            return state.intent["mkt"]
        return {}