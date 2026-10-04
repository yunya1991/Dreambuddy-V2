#!/usr/bin/env python3
"""onchain-agent — 链上面 subagent (Spec §3.2, F4 节点)

数据源: F4 节点已验证输出 (HC-1: LLM 不生成原始数据)
输出: SubagentOutput (summary + signals + charts)
图表: line(折线) + heatmap(热力图)
"""
from __future__ import annotations

import traceback
from typing import Any, Callable, Dict, List, Optional

from subagent_types import ChartSpec, Signal, SubagentOutput


class OnchainAgent:
    """链上面 subagent: F4 节点输出 → SubagentOutput"""

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
        artifact_uri = f"artifact://onchain/{hash(str(indicators)) % 100000:05d}" if indicators else None

        return SubagentOutput(
            module="onchain",
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
        """从链上指标提取标准化信号 (HC-1)"""
        signals: List[Signal] = []
        active = indicators.get("active_addresses", 0)
        hashrate = indicators.get("hashrate", 0)
        mvrv = indicators.get("mvrv", 1.0)
        exchange_inflow = indicators.get("exchange_inflow", 0)
        nupl = indicators.get("nupl", 0)

        # MVRV 信号
        if mvrv > 3.0:
            signals.append(Signal("MVRV", mvrv, "short", 0.7))
        elif mvrv < 1.0:
            signals.append(Signal("MVRV", mvrv, "short", 0.65))
        elif 1.5 <= mvrv <= 3.0:
            signals.append(Signal("MVRV", mvrv, "long", 0.55))
        else:
            signals.append(Signal("MVRV", mvrv, "neutral", 0.4))

        # 活跃地址信号
        if active > 1e6:
            signals.append(Signal("活跃地址", active, "long", 0.5))

        # 算力信号
        if hashrate > 0:
            signals.append(Signal("算力", hashrate, "long", 0.45))

        # 交易所流入信号
        if exchange_inflow > 500:
            signals.append(Signal("交易所流入", exchange_inflow, "short", 0.6))
        elif exchange_inflow < 100:
            signals.append(Signal("交易所流入", exchange_inflow, "long", 0.5))
        else:
            signals.append(Signal("交易所流入", exchange_inflow, "neutral", 0.4))

        # NUPL 信号
        if nupl > 0.5:
            signals.append(Signal("NUPL", nupl, "short", 0.55))
        elif nupl < 0:
            signals.append(Signal("NUPL", nupl, "long", 0.55))

        return signals

    def _generate_summary(self, signals: List[Signal], rationale: List[str],
                          direction: str, confidence: float) -> str:
        if self._llm_fn is not None:
            try:
                prompt = (
                    f"链上分析摘要: 方向={direction}, 置信度={confidence:.2f}, "
                    f"信号={[s.to_dict() for s in signals]}, "
                    f"理由={rationale[:3]}"
                )
                return self._llm_fn(prompt)[:300]
            except Exception:  # noqa: BLE001 FAIL-OPEN
                pass
        long_count = sum(1 for s in signals if s.direction == "long")
        short_count = sum(1 for s in signals if s.direction == "short")
        return (f"链上面{direction}({confidence:.0%}), "
                f"多信号{long_count}/空信号{short_count}")

    def _generate_charts(self, indicators: Dict[str, Any]) -> List[ChartSpec]:
        charts: List[ChartSpec] = []

        # 折线图: 链上活动趋势
        active = indicators.get("active_addresses")
        hashrate = indicators.get("hashrate")
        if active is not None or hashrate is not None:
            charts.append(ChartSpec(
                type="line",
                title="链上活动趋势",
                data={
                    "active_addresses": active or 0,
                    "hashrate": (hashrate or 0) / 1e12,  # TH/s
                },
                config={
                    "yAxis": [{"type": "value", "name": "活跃地址"},
                              {"type": "value", "name": "算力(TH/s)"}],
                    "smooth": True,
                },
            ))

        # 热力图: 链上指标矩阵
        mvrv = indicators.get("mvrv", 0)
        nupl = indicators.get("nupl", 0)
        exchange_inflow = indicators.get("exchange_inflow", 0)
        heatmap_data = [
            ["MVRV", "当前值", mvrv],
            ["NUPL", "当前值", nupl],
            ["交易所流入", "当前值", exchange_inflow],
        ]
        charts.append(ChartSpec(
            type="heatmap",
            title="链上指标热力图",
            data=heatmap_data,
            config={
                "xAxis": {"type": "category", "data": ["MVRV", "NUPL", "交易所流入"]},
                "yAxis": {"type": "category", "data": ["当前值"]},
                "visualMap": {"min": -1, "max": 5, "calculable": True},
            },
        ))

        return charts


def handle_onchain_agent(params: dict) -> dict:
    """IPC handler: onchain-agent"""
    try:
        from subagent_registry import get_handler_llm_fn
        agent = OnchainAgent(llm_fn=get_handler_llm_fn())
        output = agent.execute(params.get("node_output", {}))
        return {"ok": True, "output": output.to_dict()}
    except Exception as e:
        return {"ok": False, "error": str(e), "stack": traceback.format_exc()}
