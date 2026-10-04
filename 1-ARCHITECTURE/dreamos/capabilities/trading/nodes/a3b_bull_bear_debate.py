"""
A3B 多空辩论节点 — 借鉴 TradingAgents 三层 Agent 拓扑

TradingAgents 架构:
    分析层 (Analysts) → 辩论层 (Debate) → 决策层 (Decision)

本节点实现辩论层逻辑:
    1. 收集多头论据 (bull arguments) 和空头论据 (bear arguments)
    2. 对论据进行权重评分
    3. 输出辩论后的方向和置信度
    4. 提供给 A4_gate 做最终决策

输入: state 中前序节点的输出 (C1/C2/C3/A1/A2 等)
输出: direction / confidence / debate_summary / bull_args / bear_args
"""

from __future__ import annotations

import logging
from typing import Dict, Any, List, Tuple

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult

logger = logging.getLogger(__name__)


class A3BBullBearDebateNode(BaseNode):
    """A3B 多空辩论节点

    收集多空双方论据，进行加权辩论，输出最终方向和置信度。
    辩论结果供 A4_gate 决策参考。
    """

    node_id = "A3B"
    name = "多空辩论"
    description = "收集多空论据并加权辩论，输出方向和置信度"
    chain = "A"
    tags = ["debate", "bull-bear", "decision-support"]
    estimated_tokens = 0
    estimated_latency_ms = 30

    def execute_core(self, state: State) -> NodeResult:
        # 收集前序节点结果
        bull_args, bear_args = self._collect_arguments(state)

        # 计算多空得分
        bull_score = sum(a["weight"] for a in bull_args)
        bear_score = sum(a["weight"] for a in bear_args)
        total = bull_score + bear_score

        rationale: List[str] = [f"[A3B 多空辩论] 多头得分: {bull_score:.2f} | 空头得分: {bear_score:.2f}"]

        if total == 0:
            direction = "HOLD"
            confidence = 0.3
            rationale.append("无有效论据，返回中性")
        elif bull_score > bear_score * 1.2:
            direction = "LONG"
            confidence = min(bull_score / max(total, 0.01), 0.9)
            rationale.append(f"多头占优 ({bull_score:.1f} vs {bear_score:.1f})")
        elif bear_score > bull_score * 1.2:
            direction = "SHORT"
            confidence = min(bear_score / max(total, 0.01), 0.9)
            rationale.append(f"空头占优 ({bear_score:.1f} vs {bull_score:.1f})")
        else:
            direction = "HOLD"
            confidence = 0.35
            rationale.append(f"多空僵持 ({bull_score:.1f} vs {bear_score:.1f})，建议观望")

        # 输出辩论摘要
        debate_summary = {
            "bull_score": round(bull_score, 3),
            "bear_score": round(bear_score, 3),
            "bull_arguments": [a["text"] for a in bull_args[:3]],
            "bear_arguments": [a["text"] for a in bear_args[:3]],
            "direction": direction,
        }

        rationale.append(f"方向: {direction} | 置信度: {confidence:.1%}")

        return NodeResult(
            node_id="A3B",
            confidence=round(min(max(confidence, 0.3), 0.95), 3),
            direction=direction,
            outputs={
                "debate_summary": debate_summary,
                "bull_args": bull_args,
                "bear_args": bear_args,
                "rationale": rationale,
            },
        )

    def _collect_arguments(self, state: State) -> Tuple[List[Dict], List[Dict]]:
        """从前序节点收集多空论据

        Returns:
            (bull_args, bear_args): 多头和空头论据列表
        """
        bull_args: List[Dict] = []
        bear_args: List[Dict] = []

        # 从 state.results 或 state 中获取前序节点输出
        results = getattr(state, "results", {}) or {}
        if not isinstance(results, dict):
            results = {}

        # C1 技术扫描
        c1 = results.get("C1") or results.get("C1_tech_scan") or {}
        if isinstance(c1, dict):
            c1_dir = c1.get("direction", "")
            c1_conf = float(c1.get("confidence", 0))
            if c1_dir == "LONG":
                bull_args.append({"text": f"C1技术面看多 (置信度{c1_conf:.0%})", "weight": 0.2 + c1_conf * 0.1})
            elif c1_dir == "SHORT":
                bear_args.append({"text": f"C1技术面看空 (置信度{c1_conf:.0%})", "weight": 0.2 + c1_conf * 0.1})

        # C2 动量
        c2 = results.get("C2") or {}
        if isinstance(c2, dict):
            c2_dir = c2.get("direction", "")
            c2_conf = float(c2.get("confidence", 0))
            if c2_dir == "LONG":
                bull_args.append({"text": f"C2动量向上 (置信度{c2_conf:.0%})", "weight": 0.15 + c2_conf * 0.1})
            elif c2_dir == "SHORT":
                bear_args.append({"text": f"C2动量向下 (置信度{c2_conf:.0%})", "weight": 0.15 + c2_conf * 0.1})

        # C3 波动率
        c3 = results.get("C3") or {}
        if isinstance(c3, dict):
            regime = c3.get("regime", "")
            if regime == "TREND":
                # 趋势行情中，跟随趋势方向
                ch24 = c3.get("change_24h", 0)
                if ch24 > 0:
                    bull_args.append({"text": "C3趋势行情+上涨", "weight": 0.15})
                else:
                    bear_args.append({"text": "C3趋势行情+下跌", "weight": 0.15})
            elif regime == "RANGE":
                bull_args.append({"text": "C3震荡行情，观望为主", "weight": 0.05})
                bear_args.append({"text": "C3震荡行情，观望为主", "weight": 0.05})

        # A2 综合分析
        a2 = results.get("A2") or {}
        if isinstance(a2, dict):
            a2_dir = a2.get("direction", "")
            a2_conf = float(a2.get("confidence", 0))
            if a2_dir == "LONG":
                bull_args.append({"text": f"A2综合分析看多 (置信度{a2_conf:.0%})", "weight": 0.2 + a2_conf * 0.1})
            elif a2_dir == "SHORT":
                bear_args.append({"text": f"A2综合分析看空 (置信度{a2_conf:.0%})", "weight": 0.2 + a2_conf * 0.1})

        # BCRM2 辩证ML
        bcrm2 = results.get("BCRM2") or {}
        if isinstance(bcrm2, dict):
            bcrm2_dir = bcrm2.get("direction", "")
            bcrm2_conf = float(bcrm2.get("confidence", 0))
            if bcrm2_dir == "LONG":
                bull_args.append({"text": f"BCRM2辩证ML看多 (置信度{bcrm2_conf:.0%})", "weight": 0.2 + bcrm2_conf * 0.1})
            elif bcrm2_dir == "SHORT":
                bear_args.append({"text": f"BCRM2辩证ML看空 (置信度{bcrm2_conf:.0%})", "weight": 0.2 + bcrm2_conf * 0.1})

        # BDSM 基本面
        bdsm = results.get("BDSM") or {}
        if isinstance(bdsm, dict):
            bds_score = float(bdsm.get("bds_score", 0))
            if bds_score >= 0.6:
                bull_args.append({"text": f"BDSM基本面评分高 ({bds_score:.2f})", "weight": 0.2 + bds_score * 0.1})
            elif bds_score <= 0.3:
                bear_args.append({"text": f"BDSM基本面评分低 ({bds_score:.2f})", "weight": 0.15})

        return bull_args, bear_args
