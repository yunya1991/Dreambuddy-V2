#!/usr/bin/env python3
"""sentiment-agent — 市场情绪 subagent (Spec §3.2)

数据源: F1 节点已验证输出 (HC-1: LLM 不生成原始数据)
输出: SubagentOutput (summary + signals + charts)
图表: 仪表盘(gauge) + FGI折线(line)
"""
from __future__ import annotations

import traceback
from typing import Any, Callable, Dict, List, Optional

from subagent_types import ChartSpec, Signal, SubagentOutput


class SentimentAgent:
    """市场情绪 subagent: F1 节点输出 → SubagentOutput"""

    def __init__(self, llm_fn: Optional[Callable[[str], str]] = None):
        self._llm_fn = llm_fn

    def execute(self, node_output: dict) -> SubagentOutput:
        """执行情绪面提炼

        Args:
            node_output: F1 节点输出, 含:
                - sentiment: dict (impact/score/fgi/rsi)
                - rationale: List[str]
        """
        sentiment = node_output.get("sentiment", {})
        rationale = node_output.get("rationale", [])
        confidence = float(node_output.get("confidence", 0.5))

        signals = self._extract_signals(sentiment)
        summary = self._generate_summary(sentiment, rationale, signals)
        charts = self._generate_charts(sentiment)

        # D3: 填充 reasoning_chain + evidence_refs + artifact_uri
        reasoning_chain = " | ".join(rationale) if rationale else ""
        evidence_refs = [f"sentiment:{k}" for k in sentiment.keys()]
        artifact_uri = f"artifact://sentiment/{hash(str(sentiment)) % 100000:05d}" if sentiment else None

        return SubagentOutput(
            module="sentiment",
            summary=summary,
            signals=signals,
            charts=charts,
            raw_data=node_output,
            confidence=confidence,
            reasoning_chain=reasoning_chain,
            evidence_refs=evidence_refs,
            artifact_uri=artifact_uri,
        )

    def _extract_signals(self, sentiment: Dict[str, Any]) -> List[Signal]:
        """从情绪指标提取标准化信号 (HC-1)"""
        signals: List[Signal] = []
        impact = sentiment.get("impact", "NEUTRAL")
        score = sentiment.get("score", 0.5)
        fgi = sentiment.get("fgi")

        # 新闻影响信号
        dir_map = {"BULLISH": "long", "BEARISH": "short", "NEUTRAL": "neutral"}
        signals.append(Signal("新闻情绪", impact,
                              dir_map.get(impact, "neutral"), score))

        # 恐惧贪婪指数信号
        if fgi is not None:
            if fgi < 25:
                signals.append(Signal("恐惧贪婪指数", fgi, "long", 0.6))
            elif fgi > 75:
                signals.append(Signal("恐惧贪婪指数", fgi, "short", 0.6))
            else:
                signals.append(Signal("恐惧贪婪指数", fgi, "neutral", 0.4))

        return signals

    def _generate_summary(self, sentiment: Dict[str, Any],
                          rationale: List[str], signals: List[Signal]) -> str:
        """生成人读摘要"""
        if self._llm_fn is not None:
            try:
                prompt = (f"情绪分析摘要: sentiment={sentiment}, "
                          f"signals={[s.to_dict() for s in signals]}")
                return self._llm_fn(prompt)[:300]
            except Exception:  # noqa: BLE001 FAIL-OPEN
                pass
        impact = sentiment.get("impact", "NEUTRAL")
        score = sentiment.get("score", 0.5)
        return f"市场情绪{impact}(score={score:.2f})"

    def _generate_charts(self, sentiment: Dict[str, Any]) -> List[ChartSpec]:
        """生成图表配置 (HC-6)"""
        charts: List[ChartSpec] = []

        # 情绪仪表盘
        score = sentiment.get("score", 0.5)
        charts.append(ChartSpec(
            type="gauge",
            title="市场情绪仪表盘",
            data={"score": score, "impact": sentiment.get("impact", "NEUTRAL")},
            config={
                "min": 0, "max": 1,
                "axisLine": {"lineStyle": {"width": 20}},
            },
        ))

        # FGI 趋势折线
        fgi = sentiment.get("fgi")
        if fgi is not None:
            charts.append(ChartSpec(
                type="line",
                title="恐惧贪婪指数趋势",
                data={"fgi": fgi},
            ))

        return charts


def handle_sentiment_agent(params: dict) -> dict:
    """IPC handler: sentiment-agent"""
    try:
        from subagent_registry import get_handler_llm_fn
        agent = SentimentAgent(llm_fn=get_handler_llm_fn())
        output = agent.execute(params.get("node_output", {}))
        return {"ok": True, "output": output.to_dict()}
    except Exception as e:
        return {"ok": False, "error": str(e), "stack": traceback.format_exc()}
