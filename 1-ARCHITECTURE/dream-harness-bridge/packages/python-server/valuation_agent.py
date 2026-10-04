#!/usr/bin/env python3
"""valuation-agent — 估值面 subagent (Spec §3.2, F3 节点)

数据源: F3 节点已验证输出 (HC-1: LLM 不生成原始数据)
输出: SubagentOutput (summary + signals + charts)
图表: scatter(散点) + line(回归线)
"""
from __future__ import annotations

import traceback
from typing import Any, Callable, Dict, List, Optional

from subagent_types import ChartSpec, Signal, SubagentOutput


class ValuationAgent:
    """估值面 subagent: F3 节点输出 → SubagentOutput"""

    def __init__(self, llm_fn: Optional[Callable[[str], str]] = None):
        self._llm_fn = llm_fn

    def execute(self, node_output: dict) -> SubagentOutput:
        indicators = node_output.get("indicators", {})
        rationale = node_output.get("rationale", [])
        direction = node_output.get("direction", "NEUTRAL")
        confidence = float(node_output.get("confidence", 0.5))

        signals = self._extract_signals(indicators)
        summary = self._generate_summary(signals, rationale, direction, confidence)
        charts = self._generate_charts(indicators)

        # D3: 填充 reasoning_chain + evidence_refs + artifact_uri
        reasoning_chain = " | ".join(rationale) if rationale else ""
        evidence_refs = [f"indicator:{k}" for k in indicators.keys()]
        artifact_uri = f"artifact://valuation/{hash(str(indicators)) % 100000:05d}" if indicators else None

        return SubagentOutput(
            module="valuation",
            summary=summary,
            signals=signals,
            charts=charts,
            raw_data=node_output,
            confidence=confidence,
            reasoning_chain=reasoning_chain,
            evidence_refs=evidence_refs,
            artifact_uri=artifact_uri,
        )

    def _extract_signals(self, indicators: Dict[str, Any]) -> List[Signal]:
        """从估值指标提取标准化信号 (HC-1)"""
        signals: List[Signal] = []
        nvt = indicators.get("nvt", 0)
        stf = indicators.get("stock_to_flow", 0)
        dominance = indicators.get("market_cap_dominance", 0)
        price = indicators.get("price", 0)
        pi_top = indicators.get("pi_cycle_top", 0)
        pi_bottom = indicators.get("pi_cycle_bottom", 0)

        # NVT 信号
        if nvt > 30:
            signals.append(Signal("NVT", nvt, "short", 0.65))
        elif nvt < 15:
            signals.append(Signal("NVT", nvt, "long", 0.6))
        else:
            signals.append(Signal("NVT", nvt, "neutral", 0.4))

        # Stock to Flow 信号
        if stf > 50:
            signals.append(Signal("StockFlow", stf, "long", 0.55))
        elif stf < 20:
            signals.append(Signal("StockFlow", stf, "short", 0.5))
        else:
            signals.append(Signal("StockFlow", stf, "neutral", 0.4))

        # 市占率信号
        if dominance > 50:
            signals.append(Signal("市占率", dominance, "long", 0.45))
        elif dominance < 30:
            signals.append(Signal("市占率", dominance, "neutral", 0.4))

        # Pi Cycle 信号
        if pi_top > 0 and price > pi_top:
            signals.append(Signal("PiCycle顶", price, "short", 0.7))
        elif pi_bottom > 0 and price < pi_bottom:
            signals.append(Signal("PiCycle底", price, "long", 0.7))

        return signals

    def _generate_summary(self, signals: List[Signal], rationale: List[str],
                          direction: str, confidence: float) -> str:
        if self._llm_fn is not None:
            try:
                prompt = (
                    f"估值分析摘要: 方向={direction}, 置信度={confidence:.2f}, "
                    f"信号={[s.to_dict() for s in signals]}, "
                    f"理由={rationale[:3]}"
                )
                return self._llm_fn(prompt)[:300]
            except Exception:  # noqa: BLE001 FAIL-OPEN
                pass
        long_count = sum(1 for s in signals if s.direction == "long")
        short_count = sum(1 for s in signals if s.direction == "short")
        return (f"估值面{direction}({confidence:.0%}), "
                f"多信号{long_count}/空信号{short_count}")

    def _generate_charts(self, indicators: Dict[str, Any]) -> List[ChartSpec]:
        charts: List[ChartSpec] = []

        # 散点图: NVT vs 价格
        nvt = indicators.get("nvt")
        price = indicators.get("price")
        if nvt is not None and price is not None:
            scatter_data = [[nvt, price]]
            charts.append(ChartSpec(
                type="scatter",
                title="NVT vs 价格散点",
                data=scatter_data,
                config={
                    "xAxis": {"type": "value", "name": "NVT"},
                    "yAxis": {"type": "value", "name": "价格"},
                },
            ))

        # 回归线图: StockFlow 估值趋势
        stf = indicators.get("stock_to_flow")
        if stf is not None and price is not None:
            charts.append(ChartSpec(
                type="line",
                title="StockFlow 估值回归线",
                data={"stock_to_flow": stf, "price": price,
                      "fair_value": price * 0.9},
                config={
                    "xAxis": {"type": "value", "name": "StockFlow"},
                    "yAxis": {"type": "value", "name": "价格"},
                    "showRegression": True,
                },
            ))

        return charts


def handle_valuation_agent(params: dict) -> dict:
    """IPC handler: valuation-agent"""
    try:
        from subagent_registry import get_handler_llm_fn
        agent = ValuationAgent(llm_fn=get_handler_llm_fn())
        output = agent.execute(params.get("node_output", {}))
        return {"ok": True, "output": output.to_dict()}
    except Exception as e:
        return {"ok": False, "error": str(e), "stack": traceback.format_exc()}
