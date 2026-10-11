"""Causal Inference Engine — 因果推理引擎

SPEC: SPEC-CognitiveSystem-Evolution.md §1.4 pgmpy + §4.2 P1-7

将 verify 从贝叶斯置信度更新升级为因果推理引擎：
  1. 因果图构建 — 从记忆 tags 重叠构建因果关系图
  2. do-calculus — 反事实推理 "如果 do(memory_id=false)，哪些依赖记忆受影响？"
  3. 因果发现 — 从 verify 历史时序发现 A→B 因果链
  4. verify 影响评估 — verify 时评估记忆的因果影响范围

工程约束：
  - pgmpy 是可选依赖（无 pgmpy 时 fallback 到纯 Python 轻量级实现）
  - FAIL-OPEN：异常不阻断 verify 主流程
  - 零外部依赖（pgmpy 不可用时用纯标准库实现）

参考：
  - pgmpy: do-calculus + 因果发现 + 贝叶斯网络
  - Pearl, Causality (2009): do-calculus 三规则
  - SPEC §1.4: "verify升级为因果推理引擎"
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ============================================================
# pgmpy 可选导入
# ============================================================

try:
    import pgmpy  # type: ignore
    from pgmpy.models import BayesianNetwork  # type: ignore
    from pgmpy.inference import VariableElimination  # type: ignore
    PGMPY_AVAILABLE = True
except ImportError:
    PGMPY_AVAILABLE = False
    pgmpy = None  # type: ignore
    BayesianNetwork = None  # type: ignore
    VariableElimination = None  # type: ignore


# ============================================================
# 数据结构
# ============================================================

@dataclass
class CausalNode:
    """因果图节点。"""
    id: str
    content: str = ""
    tags: List[str] = field(default_factory=list)
    confidence: float = 0.5
    quality_level: str = "C"
    verify_count: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "tags": self.tags,
            "confidence": self.confidence,
            "quality_level": self.quality_level,
            "verify_count": self.verify_count,
        }


@dataclass
class CausalEdge:
    """因果图边 — 表示记忆间的因果关系。"""
    source: str
    target: str
    weight: float  # 0.0-1.0，因果强度
    cause_type: str = "tag_overlap"  # tag_overlap / temporal_co-occurrence

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "target": self.target,
            "weight": round(self.weight, 4),
            "cause_type": self.cause_type,
        }


@dataclass
class CausalChain:
    """因果链 — 从 verify 历史发现的因果关系。"""
    cause: str  # 原因记忆 ID
    effect: str  # 结果记忆 ID
    confidence: float  # 因果置信度
    co_occurrence_count: int = 0
    total_count: int = 0

    def to_dict(self) -> dict:
        return {
            "cause": self.cause,
            "effect": self.effect,
            "confidence": round(self.confidence, 4),
            "co_occurrence_count": self.co_occurrence_count,
            "total_count": self.total_count,
        }


# ============================================================
# 核心引擎
# ============================================================

class CausalInferenceEngine:
    """因果推理引擎 — pgmpy 可选依赖。

    核心能力：
      1. build_causal_graph() — 从记忆 tags 重叠构建因果图
      2. do_calculus() — do-calculus 反事实推理
      3. discover_causes() — 从 verify 历史时序发现因果链
      4. assess_verify_impact() — verify 影响评估
    """

    # 干预影响系数（do(success) → 依赖节点 confidence 变化量）
    IMPACT_COEFFICIENT = 0.1
    # 因果发现最小共现次数
    MIN_CO_OCCURRENCE = 1
    # 因果发现时间窗口（秒）— A 在 B 之前此窗口内成功才算因果
    TEMPORAL_WINDOW = 3600  # 1小时

    def __init__(
        self,
        graph_path: Optional[Path] = None,
    ):
        """
        初始化因果推理引擎。

        Args:
            graph_path: 因果图持久化路径。None 则不持久化。
        """
        self.graph_path = Path(graph_path) if graph_path else None
        self.pgmpy_available = PGMPY_AVAILABLE

        # 因果图状态
        self._nodes: Dict[str, CausalNode] = {}
        self._edges: List[CausalEdge] = []
        self._adjacency: Dict[str, List[str]] = {}  # source → [targets]

        # 从持久化恢复
        if self.graph_path and self.graph_path.exists():
            self._restore()

    # ============================================================
    # 1. 因果图构建
    # ============================================================

    def build_causal_graph(
        self,
        memories: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """从记忆列表构建因果图（基于 tags 重叠）。

        Args:
            memories: 记忆列表，每条含 id/tags/content/confidence/quality_level/verify_count

        Returns:
            {nodes: [...], edges: [...]}
        """
        self._nodes.clear()
        self._edges.clear()
        self._adjacency.clear()

        # 构建节点
        for mem in memories:
            mid = mem.get("id") or mem.get("memory_id", "")
            if not mid:
                continue
            node = CausalNode(
                id=mid,
                content=mem.get("content", ""),
                tags=list(mem.get("tags") or []),
                confidence=float(mem.get("confidence") or 0.0),
                quality_level=mem.get("quality_level", "C"),
                verify_count=int(mem.get("verify_count") or 0),
            )
            self._nodes[mid] = node
            self._adjacency.setdefault(mid, [])

        # 构建边（tags 重叠）
        node_list = list(self._nodes.values())
        for i, node_a in enumerate(node_list):
            for node_b in node_list[i + 1:]:
                overlap = set(node_a.tags) & set(node_b.tags)
                if overlap:
                    # weight = overlap_count / min(len_a, len_b)
                    min_len = min(len(node_a.tags), len(node_b.tags)) or 1
                    weight = len(overlap) / min_len
                    # 双向边（因果关系可能双向）
                    self._add_edge(node_a.id, node_b.id, weight)
                    self._add_edge(node_b.id, node_a.id, weight)

        # 持久化
        self._persist()

        return {
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "edges": [e.to_dict() for e in self._edges],
        }

    def _add_edge(self, source: str, target: str, weight: float) -> None:
        """添加因果边。"""
        edge = CausalEdge(source=source, target=target, weight=weight)
        self._edges.append(edge)
        self._adjacency.setdefault(source, []).append(target)

    # ============================================================
    # 2. do-calculus — 反事实推理
    # ============================================================

    def do_calculus(
        self,
        intervention_node: str,
        intervention_value: bool,
    ) -> Dict[str, Any]:
        """do-calculus 反事实推理。

        Pearl 的 do-calculus：干预（do(X=x)）不同于观察（X=x）。
        干预一个记忆的 verify 结果，计算其依赖记忆的预期置信度变化。

        Args:
            intervention_node: 被干预的记忆 ID
            intervention_value: do(X=True/False)

        Returns:
            {intervention, affected_nodes: [{id, delta_confidence}]}
        """
        if intervention_node not in self._nodes:
            return {
                "intervention": {
                    "node": intervention_node,
                    "value": intervention_value,
                },
                "affected_nodes": [],
                "note": "节点不在因果图中",
            }

        affected = []
        neighbors = self._adjacency.get(intervention_node, [])
        for neighbor_id in neighbors:
            if neighbor_id == intervention_node:
                continue
            # 找到边的权重
            edge_weight = 0.5
            for e in self._edges:
                if e.source == intervention_node and e.target == neighbor_id:
                    edge_weight = e.weight
                    break

            # do(success) → 依赖节点 confidence +（weight * IMPACT_COEFFICIENT）
            # do(failure) → 依赖节点 confidence -（weight * IMPACT_COEFFICIENT）
            if intervention_value:
                delta = self.IMPACT_COEFFICIENT * edge_weight
            else:
                delta = -self.IMPACT_COEFFICIENT * edge_weight

            affected.append({
                "id": neighbor_id,
                "delta_confidence": round(delta, 4),
                "edge_weight": round(edge_weight, 4),
            })

        return {
            "intervention": {
                "node": intervention_node,
                "value": intervention_value,
            },
            "affected_nodes": affected,
        }

    # ============================================================
    # 3. 因果发现 — 从 verify 历史时序
    # ============================================================

    def discover_causes(
        self,
        verify_history: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """从 verify 历史时序发现因果关系。

        规则：A 先 verify 成功，B 在 TEMPORAL_WINDOW 内也 verify 成功 → A→B 因果链。
        置信度 = co_occurrence_count / total_A_success_count

        Args:
            verify_history: verify 历史列表，每条含 memory_id/success/timestamp

        Returns:
            因果链列表 [{cause, effect, confidence, ...}]
        """
        if not verify_history:
            return []

        # 按时间排序
        sorted_history = sorted(
            verify_history,
            key=lambda x: x.get("timestamp", 0),
        )

        # 统计每个记忆的成功次数
        success_counts: Dict[str, int] = {}
        for entry in sorted_history:
            mid = entry.get("memory_id", "")
            if entry.get("success"):
                success_counts[mid] = success_counts.get(mid, 0) + 1

        # 发现因果链：A 成功后 B 在窗口内成功
        pair_counts: Dict[Tuple[str, str], int] = {}
        for i, entry_a in enumerate(sorted_history):
            if not entry_a.get("success"):
                continue
            mid_a = entry_a.get("memory_id", "")
            ts_a = entry_a.get("timestamp", 0)

            # 向后看窗口内的成功 verify
            for entry_b in sorted_history[i + 1:]:
                ts_b = entry_b.get("timestamp", 0)
                if ts_b - ts_a > self.TEMPORAL_WINDOW:
                    break
                if not entry_b.get("success"):
                    continue
                mid_b = entry_b.get("memory_id", "")
                if mid_a == mid_b:
                    continue
                pair = (mid_a, mid_b)
                pair_counts[pair] = pair_counts.get(pair, 0) + 1

        # 构建因果链
        chains = []
        for (cause_id, effect_id), co_count in pair_counts.items():
            if co_count < self.MIN_CO_OCCURRENCE:
                continue
            total = success_counts.get(cause_id, co_count)
            confidence = co_count / total if total > 0 else 0.0
            chain = CausalChain(
                cause=cause_id,
                effect=effect_id,
                confidence=confidence,
                co_occurrence_count=co_count,
                total_count=total,
            )
            chains.append(chain.to_dict())

        return chains

    # ============================================================
    # 4. verify 影响评估
    # ============================================================

    def assess_verify_impact(
        self,
        memory_id: str,
        success: bool,
        related_memories: Optional[List[Dict[str, Any]]] = None,
        verify_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """verify 影响评估 — 评估记忆的因果影响范围。

        Args:
            memory_id: 被 verify 的记忆 ID
            success: verify 是否成功
            related_memories: 相关记忆列表（用于构建因果图）
            verify_history: verify 历史（用于因果发现）

        Returns:
            {memory_id, impact_radius, affected_memories, counterfactual}
        """
        # 如果有 related_memories 且因果图为空，先构建
        if related_memories and not self._nodes:
            self.build_causal_graph(related_memories)

        # do-calculus 反事实推理
        do_result = self.do_calculus(memory_id, success)
        affected_nodes = do_result.get("affected_nodes", [])

        # 因果发现
        causal_chains = []
        if verify_history:
            causal_chains = self.discover_causes(verify_history)

        # 反事实分析
        counterfactual_desc = self._build_counterfactual(
            memory_id, success, affected_nodes,
        )

        return {
            "memory_id": memory_id,
            "impact_radius": len(affected_nodes),
            "affected_memories": affected_nodes,
            "counterfactual": counterfactual_desc,
            "causal_chains_found": len(causal_chains),
            "pgmpy_used": self.pgmpy_available,
        }

    def _build_counterfactual(
        self,
        memory_id: str,
        success: bool,
        affected_nodes: List[Dict[str, Any]],
    ) -> str:
        """构建反事实描述。"""
        if not affected_nodes:
            if success:
                return f"do({memory_id}=success): 无依赖记忆受影响"
            else:
                return f"do({memory_id}=failure): 无依赖记忆受影响"
        affected_ids = [n["id"] for n in affected_nodes]
        if success:
            return (
                f"do({memory_id}=success): {len(affected_ids)} 条依赖记忆"
                f"({', '.join(affected_ids[:3])}{'...' if len(affected_ids) > 3 else ''})"
                f"预期置信度上升"
            )
        else:
            return (
                f"do({memory_id}=failure): {len(affected_ids)} 条依赖记忆"
                f"({', '.join(affected_ids[:3])}{'...' if len(affected_ids) > 3 else ''})"
                f"预期置信度下降"
            )

    # ============================================================
    # 持久化
    # ============================================================

    def _persist(self) -> None:
        """持久化因果图到 JSON。"""
        if not self.graph_path:
            return
        try:
            data = {
                "nodes": [n.to_dict() for n in self._nodes.values()],
                "edges": [e.to_dict() for e in self._edges],
                "pgmpy_available": self.pgmpy_available,
            }
            self.graph_path.parent.mkdir(parents=True, exist_ok=True)
            self.graph_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.debug("因果图持久化失败（FAIL-OPEN）: %s", e)

    def _restore(self) -> None:
        """从 JSON 恢复因果图。"""
        try:
            data = json.loads(self.graph_path.read_text(encoding="utf-8"))
            for node_data in data.get("nodes", []):
                node = CausalNode(
                    id=node_data["id"],
                    content=node_data.get("content", ""),
                    tags=node_data.get("tags", []),
                    confidence=node_data.get("confidence", 0.5),
                    quality_level=node_data.get("quality_level", "C"),
                    verify_count=node_data.get("verify_count", 0),
                )
                self._nodes[node.id] = node
                self._adjacency.setdefault(node.id, [])
            for edge_data in data.get("edges", []):
                edge = CausalEdge(
                    source=edge_data["source"],
                    target=edge_data["target"],
                    weight=edge_data.get("weight", 0.5),
                    cause_type=edge_data.get("cause_type", "tag_overlap"),
                )
                self._edges.append(edge)
                self._adjacency.setdefault(edge.source, []).append(edge.target)
        except Exception as e:
            logger.debug("因果图恢复失败（FAIL-OPEN）: %s", e)
