"""
F2 资金流分析节点

基于基本面分析系统的资金流分析能力：
    - ETF 资金流入/流出
    - 稳定币供给变化
    - 交易所资金流向
    - 聪明钱方向
    - 资金费率分析
    - 清算压力

输入: state.market_data 或 state.inputs["mkt"]
输出: direction / confidence / flow_score / smart_money / etf_flow / stablecoin / rationale
"""

from __future__ import annotations

from typing import Dict, Any, List

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult


class F2FlowAnalysisNode(BaseNode):
    """F2 资金流分析节点

    多维度资金流分析，判断市场资金动向和潜在趋势。
    """

    node_id = "F2"
    name = "资金流分析"
    description = "多维度资金流分析（ETF/稳定币/交易所/聪明钱/资金费率/清算压力）"
    chain = "F"
    tags = ["flow", "fundamental", "money_flow", "etf", "stablecoin"]
    estimated_tokens = 0
    estimated_latency_ms = 100

    def execute_core(self, state: State) -> NodeResult:
        mkt = self._get_market_data(state)
        rationale: List[str] = []
        scores = []

        # ── 1. ETF 资金流 ────────────────────────────────
        etf_net_flow = mkt.get("etf_net_flow", 0)
        etf_spot_volume = mkt.get("etf_spot_volume", 0)
        if etf_net_flow > 50:
            scores.append(("LONG", 0.25, f"ETF净流入({etf_net_flow:.0f}M)，机构资金持续进场"))
        elif etf_net_flow < -30:
            scores.append(("SHORT", 0.20, f"ETF净流出({etf_net_flow:.0f}M)，机构资金离场"))

        # ── 2. 稳定币供给变化 ────────────────────────────
        stablecoin_change = mkt.get("stablecoin_supply_change", 0)
        if stablecoin_change > 2:
            scores.append(("LONG", 0.20, f"稳定币供给增加({stablecoin_change:.1f}%)，新增购买力"))
        elif stablecoin_change < -2:
            scores.append(("SHORT", 0.15, f"稳定币供给减少({stablecoin_change:.1f}%)，购买力下降"))

        # ── 3. 交易所资金流向 ────────────────────────────
        exchange_net_flow = mkt.get("exchange_net_flow", 0)
        exchange_inflow = mkt.get("exchange_inflow", 0)
        exchange_outflow = mkt.get("exchange_outflow", 0)
        if exchange_net_flow < -50:
            scores.append(("LONG", 0.25, f"交易所净流出({exchange_net_flow:.0f}M)，场外积累"))
        elif exchange_net_flow > 50:
            scores.append(("SHORT", 0.20, f"交易所净流入({exchange_net_flow:.0f}M)，抛压增加"))

        # ── 4. 聪明钱方向 ────────────────────────────────
        smart_money_direction = mkt.get("smart_money_direction", 0)
        if smart_money_direction > 0.3:
            scores.append(("LONG", 0.20, f"聪明钱偏多({smart_money_direction:.2f})"))
        elif smart_money_direction < -0.3:
            scores.append(("SHORT", 0.20, f"聪明钱偏空({smart_money_direction:.2f})"))

        # ── 5. 资金费率分析 ──────────────────────────────
        funding_rate = mkt.get("funding_rate", 0)
        if funding_rate > 0.05:
            scores.append(("SHORT", 0.15, f"资金费率偏高({funding_rate*100:.2f}%)，多头拥挤"))
        elif funding_rate < -0.05:
            scores.append(("LONG", 0.15, f"资金费率偏低({funding_rate*100:.2f}%)，空头拥挤"))

        # ── 6. 清算压力 ──────────────────────────────────
        liquidation_pressure = mkt.get("liquidation_pressure", 0)
        liq_long = mkt.get("liquidation_long", 0)
        liq_short = mkt.get("liquidation_short", 0)
        if liquidation_pressure > 70:
            scores.append(("LONG", 0.20, f"高清算压力({liquidation_pressure:.0f})，反向机会"))

        # ── 综合计算 ────────────────────────────────────
        long_score = sum(w for d, w, _ in scores if d == "LONG")
        short_score = sum(w for d, w, _ in scores if d == "SHORT")
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

        flow_score = long_score - short_score

        rationale = [r for _, _, r in scores[:6]]
        rationale.insert(0, f"[F2资金流] 资金流得分={flow_score:+.2f}")
        rationale.append(f"  方向: {direction} | 置信度: {confidence:.1%}")

        outputs = {
            "flow_score": round(flow_score, 3),
            "smart_money_direction": smart_money_direction,
            "etf": {
                "net_flow": etf_net_flow,
                "spot_volume": etf_spot_volume,
            },
            "stablecoin": {
                "supply_change": stablecoin_change,
            },
            "exchange": {
                "net_flow": exchange_net_flow,
                "inflow": exchange_inflow,
                "outflow": exchange_outflow,
            },
            "funding_rate": funding_rate,
            "liquidation": {
                "pressure": liquidation_pressure,
                "long": liq_long,
                "short": liq_short,
            },
            "scores": {"long": round(long_score, 3), "short": round(short_score, 3)},
            "rationale": rationale,
        }

        return NodeResult(
            node_id="F2",
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