#!/usr/bin/env python3
"""flow-agent — 资金流面 subagent (Spec §3.2, F2 节点)

数据源: F2 节点已验证输出 (HC-1: LLM 不生成原始数据)
输出: SubagentOutput (summary + signals + charts)
图表: sankey(资金流向) + bar(柱状)
"""
from __future__ import annotations

import traceback
from typing import Any, Callable, Dict, List, Optional

from subagent_types import ChartSpec, Signal, SubagentOutput


class FlowAgent:
    """资金流面 subagent: F2 节点输出 → SubagentOutput"""

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
        artifact_uri = f"artifact://flow/{hash(str(indicators)) % 100000:05d}" if indicators else None

        return SubagentOutput(
            module="flow",
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
        """从资金流指标提取标准化信号 (HC-1)"""
        signals: List[Signal] = []
        etf_inflow = indicators.get("etf_inflow", 0)
        leverage = indicators.get("leverage_ratio", 0)
        stablecoin = indicators.get("stablecoin_mcap", 0)
        fund_flow = indicators.get("fund_flow", 0)

        # ETF 流入信号
        if etf_inflow > 0:
            signals.append(Signal("ETF流入", etf_inflow, "long", 0.7))
        elif etf_inflow < 0:
            signals.append(Signal("ETF流入", etf_inflow, "short", 0.7))

        # 杠杆信号
        if leverage > 3.5:
            signals.append(Signal("杠杆倍数", leverage, "short", 0.6))
        elif leverage < 1.5:
            signals.append(Signal("杠杆倍数", leverage, "long", 0.5))
        else:
            signals.append(Signal("杠杆倍数", leverage, "neutral", 0.4))

        # 稳定币市值信号
        if stablecoin > 0:
            signals.append(Signal("稳定币市值", stablecoin, "long", 0.5))

        # 资金净流信号
        if fund_flow > 0:
            signals.append(Signal("资金净流", fund_flow, "long", 0.65))
        elif fund_flow < 0:
            signals.append(Signal("资金净流", fund_flow, "short", 0.65))

        return signals

    def _generate_summary(self, signals: List[Signal], rationale: List[str],
                          direction: str, confidence: float) -> str:
        if self._llm_fn is not None:
            try:
                prompt = (
                    f"资金流分析摘要: 方向={direction}, 置信度={confidence:.2f}, "
                    f"信号={[s.to_dict() for s in signals]}, "
                    f"理由={rationale[:3]}"
                )
                return self._llm_fn(prompt)[:300]
            except Exception:  # noqa: BLE001 FAIL-OPEN
                pass
        long_count = sum(1 for s in signals if s.direction == "long")
        short_count = sum(1 for s in signals if s.direction == "short")
        return (f"资金流{direction}({confidence:.0%}), "
                f"多信号{long_count}/空信号{short_count}")

    def _generate_charts(self, indicators: Dict[str, Any]) -> List[ChartSpec]:
        charts: List[ChartSpec] = []

        # Sankey 图: 资金流向
        etf = indicators.get("etf_inflow", 0)
        fund = indicators.get("fund_flow", 0)
        stable = indicators.get("stablecoin_mcap", 0)
        sankey_data = {
            "nodes": [
                {"name": "ETF"},
                {"name": "基金"},
                {"name": "稳定币"},
                {"name": "流入市场"},
                {"name": "流出市场"},
            ],
            "links": [
                {"source": "ETF", "target": "流入市场" if etf >= 0 else "流出市场",
                 "value": abs(etf)},
                {"source": "基金", "target": "流入市场" if fund >= 0 else "流出市场",
                 "value": abs(fund)},
                {"source": "稳定币", "target": "流入市场",
                 "value": stable / 1e9 if stable > 0 else 0},
            ],
        }
        charts.append(ChartSpec(
            type="sankey",
            title="资金流向图",
            data=sankey_data,
        ))

        # 柱状图: 资金指标对比
        bar_data = [
            {"name": "ETF流入", "value": etf},
            {"name": "资金净流", "value": fund},
        ]
        charts.append(ChartSpec(
            type="bar",
            title="资金指标对比",
            data=bar_data,
            config={
                "xAxis": {"type": "category",
                          "data": ["ETF流入", "资金净流"]},
                "yAxis": {"type": "value", "name": "M USD"},
            },
        ))

        return charts


def handle_flow_agent(params: dict) -> dict:
    """IPC handler: flow-agent"""
    try:
        from subagent_registry import get_handler_llm_fn
        agent = FlowAgent(llm_fn=get_handler_llm_fn())
        output = agent.execute(params.get("node_output", {}))
        return {"ok": True, "output": output.to_dict()}
    except Exception as e:
        return {"ok": False, "error": str(e), "stack": traceback.format_exc()}
