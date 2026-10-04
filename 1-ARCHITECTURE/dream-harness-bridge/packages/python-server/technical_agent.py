#!/usr/bin/env python3
"""technical-agent — 技术面 subagent (Spec §3.2)

数据源: C1/C2/C3 节点已验证输出 (HC-1: LLM 不生成原始数据)
输出: SubagentOutput (summary + signals + charts)
图表: K线+指标叠加 (candlestick)
"""
from __future__ import annotations

import traceback
from typing import Any, Callable, Dict, List, Optional

from subagent_types import ChartSpec, Signal, SubagentOutput


class TechnicalAgent:
    """技术面 subagent: C1/C2/C3 节点输出 → SubagentOutput"""

    def __init__(self, llm_fn: Optional[Callable[[str], str]] = None):
        """Args:
            llm_fn: LLM 提炼函数 (prompt) -> str. None 时规则生成 (FAIL-OPEN).
        """
        self._llm_fn = llm_fn

    def execute(self, node_output: dict) -> SubagentOutput:
        """执行技术面提炼

        Args:
            node_output: C1/C2/C3 节点输出, 含:
                - indicators: dict (ema20/ema50/rsi14/macd/volume...)
                - rationale: List[str]
                - direction: str
                - confidence: float
        """
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
        artifact_uri = f"artifact://technical/{hash(str(indicators)) % 100000:05d}" if indicators else None

        return SubagentOutput(
            module="technical",
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
        """从技术指标提取标准化信号 (HC-1: 不生成原始数据)"""
        signals: List[Signal] = []
        price = indicators.get("price", 0)
        ema20 = indicators.get("ema20", price)
        ema50 = indicators.get("ema50", price)
        rsi14 = indicators.get("rsi14", 50)
        macd = indicators.get("macd", 0)

        # EMA 趋势信号
        if price > ema20 > ema50:
            signals.append(Signal("EMA排列", f"{price:.2f}>EMA20>EMA50",
                                  "long", 0.7))
        elif price < ema20 < ema50:
            signals.append(Signal("EMA排列", f"{price:.2f}<EMA20<EMA50",
                                  "short", 0.7))

        # RSI 信号
        if rsi14 < 30:
            signals.append(Signal("RSI14", rsi14, "long", 0.65))
        elif rsi14 > 70:
            signals.append(Signal("RSI14", rsi14, "short", 0.65))
        else:
            signals.append(Signal("RSI14", rsi14, "neutral", 0.4))

        # MACD 信号
        if macd > 0:
            signals.append(Signal("MACD", macd, "long", 0.6))
        elif macd < 0:
            signals.append(Signal("MACD", macd, "short", 0.6))

        return signals

    def _generate_summary(self, signals: List[Signal], rationale: List[str],
                          direction: str, confidence: float) -> str:
        """生成人读摘要 (LLM 或规则, HC-1: 只提炼不生成)"""
        if self._llm_fn is not None:
            try:
                prompt = (
                    f"技术分析摘要: 方向={direction}, 置信度={confidence:.2f}, "
                    f"信号={[s.to_dict() for s in signals]}, "
                    f"理由={rationale[:3]}")
                return self._llm_fn(prompt)[:300]
            except Exception:  # noqa: BLE001 FAIL-OPEN
                pass
        # 规则生成
        long_count = sum(1 for s in signals if s.direction == "long")
        short_count = sum(1 for s in signals if s.direction == "short")
        return (f"技术面{direction}({confidence:.0%}), "
                f"多信号{long_count}/空信号{short_count}")

    def _generate_charts(self, indicators: Dict[str, Any]) -> List[ChartSpec]:
        """生成图表配置 (HC-6: ECharts option 格式)"""
        charts: List[ChartSpec] = []

        # 指标叠加折线图
        price = indicators.get("price", 0)
        ema20 = indicators.get("ema20")
        ema50 = indicators.get("ema50")
        rsi14 = indicators.get("rsi14")

        if ema20 is not None or ema50 is not None:
            chart_data = {
                "price": price,
                "ema20": ema20,
                "ema50": ema50,
                "rsi14": rsi14,
            }
            charts.append(ChartSpec(
                type="line",
                title="技术指标概览",
                data=chart_data,
                config={
                    "yAxis": [{"type": "value", "name": "价格"},
                              {"type": "value", "name": "RSI"}],
                },
            ))

        return charts


def handle_technical_agent(params: dict) -> dict:
    """IPC handler: technical-agent"""
    try:
        from subagent_registry import get_handler_llm_fn
        agent = TechnicalAgent(llm_fn=get_handler_llm_fn())
        output = agent.execute(params.get("node_output", {}))
        return {"ok": True, "output": output.to_dict()}
    except Exception as e:
        return {"ok": False, "error": str(e), "stack": traceback.format_exc()}
