#!/usr/bin/env python3
"""生产版聚合器 — 合并多 subagent 输出为统一摘要

从 test_e2e_subagent_aggregation.py 迁出, 扩展 avg_confidence + top_signals。

用于 C-Drive-Agent SUPPLEMENT 后的多 subagent 结果合并,
供 synthesizer_agent 进一步 LLM 综合重写。
"""
from __future__ import annotations

from typing import Any, Dict, List

from subagent_types import SubagentOutput, Signal, ChartSpec


def aggregate_subagent_outputs(outputs: List[SubagentOutput]) -> Dict[str, Any]:
    """聚合多个 subagent 输出为统一摘要

    Returns:
        包含以下字段的字典:
        - summaries: List[str] — 各 subagent 摘要
        - all_signals: List[dict] — 合并后的所有信号 (to_dict)
        - all_charts: List[dict] — 合并后的所有图表 (to_dict)
        - modules: List[str] — 各 subagent 模块名
        - total_signals: int — 信号总数
        - total_charts: int — 图表总数
        - consensus_direction: str — "long" | "short" | "neutral" (多数投票)
        - long_count: int — long 方向信号数
        - short_count: int — short 方向信号数
        - avg_confidence: float — 平均置信度 (生产扩展)
        - top_signals: List[dict] — 按置信度降序 top 5 (生产扩展)
    """
    if not outputs:
        return {
            "summaries": [], "all_signals": [], "all_charts": [],
            "modules": [], "total_signals": 0,
            "consensus_direction": "neutral",
            "long_count": 0, "short_count": 0,
            "total_charts": 0,
            "avg_confidence": 0.0,
            "top_signals": [],
        }

    summaries = [o.summary for o in outputs]
    all_signals: List[Signal] = []
    all_charts: List[ChartSpec] = []
    modules = [o.module for o in outputs]
    # 各 subagent 原始指标数据 (供 synthesizer LLM 深度分析使用)
    raw_data_by_module: Dict[str, Any] = {}

    for o in outputs:
        all_signals.extend(o.signals)
        all_charts.extend(o.charts)
        raw_data_by_module[o.module] = o.raw_data or {}

    # 多数投票方向
    long_n = sum(1 for s in all_signals if s.direction == "long")
    short_n = sum(1 for s in all_signals if s.direction == "short")
    if long_n > short_n:
        consensus = "long"
    elif short_n > long_n:
        consensus = "short"
    else:
        consensus = "neutral"

    # 平均置信度 (生产扩展)
    if all_signals:
        avg_conf = sum(s.confidence for s in all_signals) / len(all_signals)
    else:
        avg_conf = 0.0

    # top 5 signals 按置信度降序 (生产扩展, 供 synthesizer 使用)
    sorted_signals = sorted(
        all_signals, key=lambda s: s.confidence, reverse=True)
    top_signals = [s.to_dict() for s in sorted_signals[:5]]

    return {
        "summaries": summaries,
        "all_signals": [s.to_dict() for s in all_signals],
        "all_charts": [c.to_dict() for c in all_charts],
        "modules": modules,
        "total_signals": len(all_signals),
        "total_charts": len(all_charts),
        "consensus_direction": consensus,
        "long_count": long_n,
        "short_count": short_n,
        "avg_confidence": round(avg_conf, 4),
        "top_signals": top_signals,
        "raw_data_by_module": raw_data_by_module,
    }
