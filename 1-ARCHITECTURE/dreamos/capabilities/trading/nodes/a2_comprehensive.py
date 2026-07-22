"""
A2 第一性原理分析节点 — 辩证看待矛盾

核心职责: 基于第一性原理，调用 A0 矛盾论辩证分析矛盾的主次关系，
找出"阻力最小路径"和"趋势延续性"。

A0 矛盾论内嵌关系:
    A1 = 发现主要矛盾（调用 A0 识别市场主要矛盾是什么）
    A2 = 辩证看待矛盾（调用 A0 分析矛盾的主次关系，哪个决定方向，哪个决定节奏）
    A3 = 推演解决矛盾（调用 A0 围绕主要矛盾推演解决方案）

分析内容:
    - 综合技术面（C链）、基本面（F链）、研究面（A链）
    - 多维度信号加权融合
    - 调用 A0 辩证分析矛盾主次关系
    - 生成阻力最小路径判断

依赖：前面节点的执行结果（从 state.results 读取）
"""

from __future__ import annotations

from typing import Dict, Any, List

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult


class A2ComprehensiveNode(BaseNode):
    """A2 第一性原理分析节点 — 辩证看待矛盾

    跨链多维度信号融合，调用 A0 辩证分析矛盾主次关系，输出阻力最小路径判断。
    """

    node_id = "A2"
    name = "综合分析"
    description = "跨链多维度信号融合（技术/基本面/研究/子系统）"
    chain = "A"
    tags = ["analysis", "fusion", "multi-dimension"]
    estimated_tokens = 0
    estimated_latency_ms = 80

    # 维度权重（含子系统维度）
    DIMENSION_WEIGHTS = {
        "technical": 0.30,   # 技术面（C1/C2/C3 主链聚合）
        "subsystem": 0.25,   # 子系统信号（三屏趋势/马丁/易经）
        "fundamental": 0.20, # 基本面
        "research": 0.15,    # 研究面（A0/A1）
        "sentiment": 0.10,   # 情绪面
    }

    # 子系统节点 ID 集合
    SUBSYSTEM_NODE_IDS = {"C_S3_TREND", "C_MARTIN_V15", "A_YJ_INFER"}

    def execute_core(self, state: State) -> NodeResult:
        rationale: List[str] = []
        dimension_scores: Dict[str, Dict[str, Any]] = {}

        results = state.results if hasattr(state, "results") else {}

        # ── 收集各维度信号（聚合模式） ──────────
        tech_signal = self._extract_technical_signal(results)
        fund_signal = self._extract_fundamental_signal(results)
        research_signal = self._extract_research_signal(results)
        sent_signal = self._extract_sentiment_signal(results)
        subsystem_signal = self._extract_subsystem_signal(results)

        dimension_scores["technical"] = tech_signal
        dimension_scores["subsystem"] = subsystem_signal
        dimension_scores["fundamental"] = fund_signal
        dimension_scores["research"] = research_signal
        dimension_scores["sentiment"] = sent_signal

        # ── 加权融合 ──────────────────────
        long_score = 0.0
        short_score = 0.0
        total_weight = 0.0

        for dim, weight in self.DIMENSION_WEIGHTS.items():
            sig = dimension_scores.get(dim, {"direction": "HOLD", "confidence": 0})
            if sig["direction"] == "LONG":
                long_score += weight * sig["confidence"]
            elif sig["direction"] == "SHORT":
                short_score += weight * sig["confidence"]
            total_weight += weight

        if total_weight == 0:
            return NodeResult(node_id="A2", confidence=0.3, direction="HOLD",
                              outputs={"rationale": ["[A2综合分析] 无可用信号"]})

        # 归一化
        long_norm = long_score / total_weight
        short_norm = short_score / total_weight
        diff = abs(long_norm - short_norm)

        # 方向判断
        if diff < 0.1:
            direction = "HOLD"
            confidence = 0.4 + diff
        elif long_norm > short_norm:
            direction = "LONG"
            confidence = long_norm
        else:
            direction = "SHORT"
            confidence = short_norm

        # 一致性指标
        active_dims = sum(
            1 for d in dimension_scores.values()
            if d["direction"] in ("LONG", "SHORT")
        )
        if active_dims >= 2:
            dirs = [
                d["direction"] for d in dimension_scores.values()
                if d["direction"] in ("LONG", "SHORT")
            ]
            same_ratio = sum(1 for d in dirs if d == direction) / len(dirs)
            confidence *= (0.6 + same_ratio * 0.4)  # 一致性加成

        confidence = min(max(confidence, 0.2), 0.9)

        rationale.append("[A2综合分析] 跨维度融合（含子系统信号）")
        for dim, sig in dimension_scores.items():
            w = self.DIMENSION_WEIGHTS.get(dim, 0)
            sources = sig.get("sources", [sig.get("source", "none")])
            rationale.append(f"  {dim}: {sig['direction']} (conf={sig['confidence']:.0%}, 权重{w:.0%}, 来源={sources})")
        rationale.append(f"  综合: {direction} | 置信度 {confidence:.1%} | 多空差 {diff:.1%}")
        rationale.append(f"  有效维度: {active_dims}/5")

        return NodeResult(
            node_id="A2",
            confidence=round(confidence, 3),
            direction=direction,
            outputs={
                "dimension_scores": dimension_scores,
                "long_score": round(long_norm, 3),
                "short_score": round(short_norm, 3),
                "diff": round(diff, 3),
                "active_dimensions": active_dims,
                "rationale": rationale,
            },
        )

    def _aggregate_signals(self, results: Dict, node_ids: List[str]) -> Dict[str, Any]:
        """聚合多个节点信号为统一维度信号

        采用加权投票：long_score = sum(confidence for LONG),
                     short_score = sum(confidence for SHORT)
        """
        long_score = 0.0
        short_score = 0.0
        sources = []

        for node_id in node_ids:
            result = results.get(node_id)
            if result is None or not hasattr(result, "direction"):
                continue
            direction = result.direction or "HOLD"
            confidence = getattr(result, "confidence", 0.5)
            sources.append({"node": node_id, "direction": direction, "confidence": confidence})

            if direction == "LONG":
                long_score += confidence
            elif direction == "SHORT":
                short_score += confidence

        total = long_score + short_score
        if total == 0:
            return {"direction": "HOLD", "confidence": 0.3, "sources": sources or ["none"]}

        if abs(long_score - short_score) / total < 0.15:
            return {"direction": "HOLD", "confidence": 0.4, "sources": sources}
        elif long_score > short_score:
            return {"direction": "LONG", "confidence": round(long_score / total, 3), "sources": sources}
        else:
            return {"direction": "SHORT", "confidence": round(short_score / total, 3), "sources": sources}

    def _extract_technical_signal(self, results: Dict) -> Dict[str, Any]:
        """提取技术面信号（聚合 C1/C2/C3 主链，排除子系统节点）"""
        main_chain_ids = []
        for node_id in results:
            if node_id.startswith("C") and node_id not in self.SUBSYSTEM_NODE_IDS:
                main_chain_ids.append(node_id)

        return self._aggregate_signals(results, main_chain_ids)

    def _extract_subsystem_signal(self, results: Dict) -> Dict[str, Any]:
        """提取子系统信号（三屏趋势/马丁/易经）"""
        subsystem_ids = [nid for nid in self.SUBSYSTEM_NODE_IDS if nid in results]
        return self._aggregate_signals(results, subsystem_ids)

    def _extract_fundamental_signal(self, results: Dict) -> Dict[str, Any]:
        """提取基本面信号"""
        for node_id, result in results.items():
            if node_id.startswith("F") and hasattr(result, "direction"):
                return {
                    "direction": result.direction or "HOLD",
                    "confidence": getattr(result, "confidence", 0.5),
                    "source": node_id,
                }
        return {"direction": "HOLD", "confidence": 0.3, "source": "none"}

    def _extract_research_signal(self, results: Dict) -> Dict[str, Any]:
        """提取研究面信号（A0/A1，排除 A2/A3/A4 和子系统节点）"""
        best_conf = 0
        best_dir = "HOLD"
        best_src = "none"
        for node_id, result in results.items():
            if node_id.startswith("A") and node_id not in ("A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9"):
                if node_id in self.SUBSYSTEM_NODE_IDS:
                    continue
                conf = getattr(result, "confidence", 0)
                if conf > best_conf and hasattr(result, "direction"):
                    best_conf = conf
                    best_dir = result.direction or "HOLD"
                    best_src = node_id
        if best_src == "none":
            return {"direction": "HOLD", "confidence": 0.3, "source": "none"}
        return {"direction": best_dir, "confidence": best_conf, "source": best_src}

    def _extract_sentiment_signal(self, results: Dict) -> Dict[str, Any]:
        """提取情绪面信号"""
        for node_id, result in results.items():
            if "F3" in node_id or "sent" in node_id.lower():
                return {
                    "direction": result.direction or "HOLD",
                    "confidence": getattr(result, "confidence", 0.5),
                    "source": node_id,
                }
        return {"direction": "HOLD", "confidence": 0.3, "source": "none"}
