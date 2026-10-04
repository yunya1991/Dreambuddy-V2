#!/usr/bin/env python3
"""macro-agent — 宏观面 subagent (Spec §3.2, F5 节点)

数据源: F5 节点已验证输出 (HC-1: LLM 不生成原始数据)
输出: SubagentOutput (summary + signals + charts)
图表: bar(柱状) + line(趋势线)
"""
from __future__ import annotations

import traceback
from typing import Any, Callable, Dict, List, Optional

from subagent_types import ChartSpec, Signal, SubagentOutput


class MacroAgent:
    """宏观面 subagent: F5 节点输出 → SubagentOutput"""

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
        artifact_uri = f"artifact://macro/{hash(str(indicators)) % 100000:05d}" if indicators else None

        return SubagentOutput(
            module="macro",
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
        """从宏观指标提取标准化信号 (HC-1)"""
        signals: List[Signal] = []
        gdp = indicators.get("gdp_yoy", 0)
        cpi = indicators.get("cpi_yoy", 0)
        rate = indicators.get("interest_rate", 0)
        liquidity = indicators.get("liquidity_m2", 0)

        # GDP 信号
        if gdp > 2.0:
            signals.append(Signal("GDP同比", gdp, "long", 0.7))
        elif gdp < 0:
            signals.append(Signal("GDP同比", gdp, "short", 0.7))
        else:
            signals.append(Signal("GDP同比", gdp, "neutral", 0.4))

        # CPI 信号
        if cpi > 5:
            signals.append(Signal("CPI同比", cpi, "short", 0.6))
        elif cpi < 1:
            signals.append(Signal("CPI同比", cpi, "long", 0.5))
        else:
            signals.append(Signal("CPI同比", cpi, "neutral", 0.4))

        # 利率信号
        if rate > 5.0:
            signals.append(Signal("利率", rate, "short", 0.5))
        elif rate < 1.0:
            signals.append(Signal("利率", rate, "long", 0.5))

        # 流动性信号
        if liquidity > 0:
            signals.append(Signal("M2流动性", liquidity, "long", 0.55))

        return signals

    def _generate_summary(self, signals: List[Signal], rationale: List[str],
                          direction: str, confidence: float) -> str:
        if self._llm_fn is not None:
            try:
                prompt = (
                    f"宏观分析摘要: 方向={direction}, 置信度={confidence:.2f}, "
                    f"信号={[s.to_dict() for s in signals]}, "
                    f"理由={rationale[:3]}"
                )
                return self._llm_fn(prompt)[:300]
            except Exception:  # noqa: BLE001 FAIL-OPEN
                pass
        long_count = sum(1 for s in signals if s.direction == "long")
        short_count = sum(1 for s in signals if s.direction == "short")
        return (f"宏观面{direction}({confidence:.0%}), "
                f"多信号{long_count}/空信号{short_count}")

    def _generate_charts(self, indicators: Dict[str, Any]) -> List[ChartSpec]:
        charts: List[ChartSpec] = []

        # 柱状图: 宏观指标概览
        gdp = indicators.get("gdp_yoy")
        cpi = indicators.get("cpi_yoy")
        rate = indicators.get("interest_rate")
        if gdp is not None or cpi is not None or rate is not None:
            bar_data = [
                {"name": "GDP同比", "value": gdp or 0},
                {"name": "CPI同比", "value": cpi or 0},
                {"name": "利率", "value": rate or 0},
            ]
            charts.append(ChartSpec(
                type="bar",
                title="宏观指标概览",
                data=bar_data,
                config={
                    "xAxis": {"type": "category",
                              "data": ["GDP同比", "CPI同比", "利率"]},
                    "yAxis": {"type": "value", "name": "百分比%"},
                },
            ))

        # 趋势线图: 流动性 M2 趋势
        liquidity = indicators.get("liquidity_m2")
        if liquidity is not None:
            charts.append(ChartSpec(
                type="line",
                title="M2流动性趋势",
                data={"liquidity_m2": liquidity},
                config={
                    "yAxis": {"type": "value", "name": "M2"},
                    "smooth": True,
                },
            ))

        return charts


def handle_macro_agent(params: dict) -> dict:
    """IPC handler: macro-agent"""
    try:
        from subagent_registry import get_handler_llm_fn
        agent = MacroAgent(llm_fn=get_handler_llm_fn())
        output = agent.execute(params.get("node_output", {}))
        return {"ok": True, "output": output.to_dict()}
    except Exception as e:
        return {"ok": False, "error": str(e), "stack": traceback.format_exc()}
