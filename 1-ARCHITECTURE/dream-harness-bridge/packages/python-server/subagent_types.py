#!/usr/bin/env python3
"""Subagent 共享类型 — Spec §3.3 SubagentOutput 契约

所有 subagent (technical/sentiment/macro/flow/...) 输出统一格式,
供 C-Drive-Agent 聚合 + 前端图表渲染。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class Signal:
    """标准化信号"""
    name: str
    value: Any
    direction: str  # "long" | "short" | "neutral"
    confidence: float

    def to_dict(self) -> dict:
        return {"name": self.name, "value": self.value,
                "direction": self.direction, "confidence": self.confidence}


@dataclass
class ChartSpec:
    """图表配置 (ECharts option 格式, HC-6)"""
    type: str  # candlestick|line|bar|gauge|scatter|heatmap|pie|sankey
    title: str
    data: Any
    config: Optional[dict] = None

    def to_dict(self) -> dict:
        return {"type": self.type, "title": self.title,
                "data": self.data, "config": self.config}


@dataclass
class SubagentOutput:
    """subagent 输出契约 v0.3 (Spec §3.3, HC-5, D1)

    v0.3 新增 4 字段:
        confidence: 0-1 浮点, 驱动 Bull/Bear 分级触发
        reasoning_chain: LLM 推理过程, audit 用
        evidence_refs: 引用节点 indicators 原始数据 hash
        artifact_uri: 结构化产物（图表/报告）的引用, C-Drive 按引用拉取
    """
    module: str
    summary: str
    signals: List[Signal] = field(default_factory=list)
    charts: List[ChartSpec] = field(default_factory=list)
    raw_data: Optional[Any] = None
    # ── D1 新增字段 (均可选, 向后兼容) ──
    confidence: float = 0.5
    reasoning_chain: str = ""
    evidence_refs: List[str] = field(default_factory=list)
    artifact_uri: Optional[str] = None

    def to_dict(self) -> dict:
        return {"module": self.module, "summary": self.summary,
                "signals": [s.to_dict() for s in self.signals],
                "charts": [c.to_dict() for c in self.charts],
                "raw_data": self.raw_data,
                "confidence": self.confidence,
                "reasoning_chain": self.reasoning_chain,
                "evidence_refs": self.evidence_refs,
                "artifact_uri": self.artifact_uri}
