#!/usr/bin/env python3
"""
G层 - 图压缩器

位置: experiments/ab-trading/core/g_graph_storage/compressor.py

职责：
1. 价值评估 - 计算每个节点的价值评分
2. 回溯压缩 - C→A→B 三层压缩
3. 多策略支持 - 价值优先/路径保留/关键节点/语义感知

压缩算法：
- 价值评分 = Token消耗(0.4) + 执行耗时(0.3) + 输出重要性(0.2) + 位置重要性(0.1)
- 保留 top-K 高价值节点
- 低价值节点：标记为 compressed，保留引用关系
- 边：只保留与保留节点相关的边
"""

import time
import copy
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

from .types import (
    ChronicleGraph,
    ArchitectureGraph,
    BlueprintGraph,
    CNode,
    ANode,
    BNode,
    NodeStatus,
    CompressionResult,
    CompressionStrategy,
    NodeId,
)


# ============================================================
# 价值评估器
# ============================================================

class ValueScorer:
    """节点价值评估器"""

    # 权重配置
    WEIGHT_TOKEN_COST = 0.4
    WEIGHT_LATENCY = 0.3
    WEIGHT_OUTPUT_IMPORTANCE = 0.2
    WEIGHT_POSITION = 0.1

    def __init__(self):
        pass

    def score_chronicle_node(self, node: CNode, chronicle: ChronicleGraph) -> float:
        """评估 Chronicle 节点的价值"""
        # 归一化各项指标
        max_tokens = max(1, max(
            n.metadata.token_cost for n in chronicle.nodes.values()
        ))
        max_latency = max(1, max(
            n.duration_ms for n in chronicle.nodes.values()
        ))

        # Token消耗得分
        token_score = node.metadata.token_cost / max_tokens

        # 耗时得分
        latency_score = node.duration_ms / max_latency

        # 输出重要性得分（基于输出字段数量和大小）
        output_importance = self._calc_output_importance(node)

        # 位置重要性（入口/出口节点更重要）
        position_score = self._calc_position_score(node, chronicle)

        # 加权总和
        total_score = (
            token_score * self.WEIGHT_TOKEN_COST
            + latency_score * self.WEIGHT_LATENCY
            + output_importance * self.WEIGHT_OUTPUT_IMPORTANCE
            + position_score * self.WEIGHT_POSITION
        )

        return min(1.0, max(0.0, total_score))

    def score_architecture_node(self, node: ANode, arch: ArchitectureGraph) -> float:
        """评估 Architecture 节点的价值"""
        # 简化：基于元数据中的value_score
        return node.metadata.value_score

    def _calc_output_importance(self, node: CNode) -> float:
        """计算输出重要性"""
        if not node.outputs:
            return 0.0

        # 基于输出字段数量
        field_count = len(node.outputs)
        field_score = min(1.0, field_count / 10.0)

        # 基于输出大小（粗略估计）
        try:
            import json
            output_str = json.dumps(node.outputs, ensure_ascii=False)
            size_score = min(1.0, len(output_str) / 5000.0)
        except Exception:
            size_score = 0.5

        return (field_score + size_score) / 2

    def _calc_position_score(self, node: CNode, chronicle: ChronicleGraph) -> float:
        """计算位置重要性"""
        if not chronicle.sequence:
            return 0.5

        # 第一个和最后一个节点更重要
        idx = (
            chronicle.sequence.index(node.id)
            if node.id in chronicle.sequence
            else len(chronicle.sequence) // 2
        )
        total = len(chronicle.sequence)

        if total <= 1:
            return 1.0

        # 入口和出口节点得1分，中间节点线性递减
        distance_from_edge = min(idx, total - 1 - idx)
        max_distance = (total - 1) / 2
        if max_distance == 0:
            return 1.0

        position_score = 1.0 - (distance_from_edge / max_distance) * 0.5
        return position_score


# ============================================================
# 图压缩器
# ============================================================

class GraphCompressor:
    """图压缩器

    实现回溯压缩：G.C → G.A → G.B
    """

    def __init__(
        self,
        strategy: CompressionStrategy = CompressionStrategy.VALUE_PRIORITY,
        target_ratio: float = 0.5,
    ):
        """
        Args:
            strategy: 压缩策略
            target_ratio: 目标压缩率（保留的节点比例）
        """
        self.strategy = strategy
        self.target_ratio = target_ratio
        self.scorer = ValueScorer()

    def compress_chronicle(
        self,
        chronicle: ChronicleGraph,
        target_ratio: Optional[float] = None,
        strategy: Optional[CompressionStrategy] = None,
    ) -> CompressionResult:
        """
        压缩 Chronicle（G.C 层压缩）

        Args:
            chronicle: 原始时间线
            target_ratio: 目标压缩率（覆盖默认值）
            strategy: 压缩策略（覆盖默认值）

        Returns:
            CompressionResult - 压缩结果
        """
        start_time = time.time()
        ratio = target_ratio or self.target_ratio
        strat = strategy or self.strategy

        result = CompressionResult()
        result.strategy = strat
        result.original_chronicle = chronicle
        result.original_size = self._calc_chronicle_size(chronicle)

        try:
            # 1. 计算所有节点的价值评分
            node_scores = self._score_all_nodes(chronicle)

            # 2. 根据策略选择要保留的节点
            preserved_ids = self._select_preserved_nodes(
                node_scores, chronicle, ratio, strat
            )

            # 3. 创建压缩后的 Chronicle
            compressed_chronicle = self._create_compressed_chronicle(
                chronicle, preserved_ids, node_scores
            )

            result.compressed_chronicle = compressed_chronicle
            result.preserved_nodes = preserved_ids
            result.compressed_nodes = [
                nid for nid in chronicle.nodes
                if nid not in preserved_ids
            ]
            result.compressed_size = self._calc_chronicle_size(compressed_chronicle)
            result.compression_ratio = (
                result.compressed_size / result.original_size
                if result.original_size > 0 else 1.0
            )
            result.success = True

        except Exception as e:
            result.success = False
            result.discarded_details.append({"error": str(e)})

        result.compression_time_ms = (time.time() - start_time) * 1000
        return result

    def compress_to_architecture(
        self,
        chronicle: ChronicleGraph,
        architecture: ArchitectureGraph,
    ) -> Tuple[CompressionResult, ArchitectureGraph]:
        """
        从 Chronicle 压缩到 Architecture（C→A）

        Args:
            chronicle: 时间线
            architecture: 原始架构图

        Returns:
            (压缩结果, 压缩后的架构图)
        """
        # 先压缩 Chronicle
        result = self.compress_chronicle(chronicle)

        if not result.success:
            return result, architecture

        # 然后基于压缩后的 Chronicle 更新 Architecture
        compressed_arch = self._sync_architecture_with_chronicle(
            architecture, result.compressed_chronicle
        )
        compressed_arch.compression_level = architecture.compression_level + 1

        result.compressed_architecture = compressed_arch

        return result, compressed_arch

    def compress_to_blueprint(
        self,
        chronicle: ChronicleGraph,
        architecture: ArchitectureGraph,
        blueprint: BlueprintGraph,
    ) -> Tuple[CompressionResult, BlueprintGraph]:
        """
        从 Chronicle 压缩到 Blueprint（C→A→B）

        Args:
            chronicle: 时间线
            architecture: 架构图
            blueprint: 蓝图

        Returns:
            (压缩结果, 压缩后的蓝图)
        """
        # 先压缩到 Architecture
        result, compressed_arch = self.compress_to_architecture(
            chronicle, architecture
        )

        if not result.success:
            return result, blueprint

        # 再压缩到 Blueprint
        compressed_bp = self._sync_blueprint_with_architecture(
            blueprint, compressed_arch
        )

        result.compressed_blueprint = compressed_bp

        return result, compressed_bp

    def _score_all_nodes(self, chronicle: ChronicleGraph) -> Dict[NodeId, float]:
        """计算所有节点的价值评分"""
        scores = {}
        for node_id, node in chronicle.nodes.items():
            score = self.scorer.score_chronicle_node(node, chronicle)
            scores[node_id] = score
            node.metadata.value_score = score
        return scores

    def _select_preserved_nodes(
        self,
        node_scores: Dict[NodeId, float],
        chronicle: ChronicleGraph,
        target_ratio: float,
        strategy: CompressionStrategy,
    ) -> List[NodeId]:
        """根据策略选择要保留的节点"""
        if strategy == CompressionStrategy.VALUE_PRIORITY:
            return self._select_by_value(node_scores, chronicle, target_ratio)
        elif strategy == CompressionStrategy.PATH_PRESERVE:
            return self._select_path_preserve(node_scores, chronicle, target_ratio)
        elif strategy == CompressionStrategy.CRITICAL_ONLY:
            return self._select_critical_only(chronicle)
        else:
            return self._select_by_value(node_scores, chronicle, target_ratio)

    def _select_by_value(
        self,
        node_scores: Dict[NodeId, float],
        chronicle: ChronicleGraph,
        target_ratio: float,
    ) -> List[NodeId]:
        """价值优先策略：按价值排序，保留 top-K"""
        total_nodes = len(chronicle.nodes)
        if total_nodes == 0:
            return []

        # 计算要保留的节点数
        preserve_count = max(1, int(total_nodes * target_ratio))

        # 按价值排序
        sorted_nodes = sorted(
            node_scores.items(),
            key=lambda x: x[1],
            reverse=True,
        )

        # 保留前 N 个
        preserved = [nid for nid, _ in sorted_nodes[:preserve_count]]

        # 确保首尾节点都保留
        if chronicle.sequence:
            first = chronicle.sequence[0]
            last = chronicle.sequence[-1]
            if first not in preserved:
                preserved.append(first)
            if last not in preserved:
                preserved.append(last)

        return preserved

    def _select_path_preserve(
        self,
        node_scores: Dict[NodeId, float],
        chronicle: ChronicleGraph,
        target_ratio: float,
    ) -> List[NodeId]:
        """路径保留策略：保留主要执行路径"""
        # 简化实现：保留所有节点（路径保留意味着不怎么压缩）
        # 在实际场景中会根据路径重要性选择
        return list(chronicle.nodes.keys())

    def _select_critical_only(
        self,
        chronicle: ChronicleGraph,
    ) -> List[NodeId]:
        """关键节点策略：只保留入口和出口"""
        if not chronicle.sequence:
            return list(chronicle.nodes.keys())

        critical = [chronicle.sequence[0]]
        if len(chronicle.sequence) > 1:
            critical.append(chronicle.sequence[-1])

        return critical

    def _create_compressed_chronicle(
        self,
        original: ChronicleGraph,
        preserved_ids: List[NodeId],
        node_scores: Dict[NodeId, float],
    ) -> ChronicleGraph:
        """创建压缩后的 Chronicle"""
        compressed = ChronicleGraph(
            id=f"{original.id}_compressed",
            architecture_id=original.architecture_id,
            execution_id=original.execution_id,
            compression_level=original.compression_level + 1,
        )

        preserved_set = set(preserved_ids)

        # 复制保留的节点，压缩其他节点
        for node_id in original.sequence:
            node = original.nodes[node_id]

            if node_id in preserved_set:
                # 保留节点：复制完整信息
                new_node = copy.deepcopy(node)
                compressed.add_node(new_node)
            else:
                # 压缩节点：只保留摘要信息
                compressed_node = CNode(
                    id=node.id,
                    architecture_node_id=node.architecture_node_id,
                    execution_id=node.execution_id,
                    start_time=node.start_time,
                    end_time=node.end_time,
                    is_compressed=True,
                    compressed_from=[node.id],
                )
                compressed_node.metadata = copy.deepcopy(node.metadata)
                compressed_node.metadata.status = NodeStatus.COMPRESSED

                # 保留输出摘要
                if node.outputs:
                    compressed_node.outputs = {
                        "_compressed": True,
                        "_summary": self._generate_output_summary(node.outputs),
                    }

                compressed.add_node(compressed_node)

        # 复制边（只保留与保留节点相关的边）
        for edge in original.edges:
            if edge.source in preserved_set or edge.target in preserved_set:
                compressed.add_edge(copy.deepcopy(edge))

        return compressed

    def _generate_output_summary(self, outputs: Dict) -> str:
        """生成输出摘要"""
        keys = list(outputs.keys())[:5]
        return f"包含 {len(outputs)} 个字段: {', '.join(keys)}"

    def _sync_architecture_with_chronicle(
        self,
        architecture: ArchitectureGraph,
        chronicle: ChronicleGraph,
    ) -> ArchitectureGraph:
        """根据压缩后的 Chronicle 更新 Architecture"""
        compressed_arch = copy.deepcopy(architecture)

        # 更新 Architecture 节点状态
        for cnode in chronicle.nodes.values():
            anode_id = cnode.architecture_node_id
            anode = compressed_arch.get_node(anode_id)
            if anode:
                anode.metadata.value_score = cnode.metadata.value_score
                if cnode.is_compressed:
                    anode.metadata.status = NodeStatus.COMPRESSED

        return compressed_arch

    def _sync_blueprint_with_architecture(
        self,
        blueprint: BlueprintGraph,
        architecture: ArchitectureGraph,
    ) -> BlueprintGraph:
        """根据压缩后的 Architecture 更新 Blueprint"""
        compressed_bp = copy.deepcopy(blueprint)

        # 统计每个 BNode 对应的压缩比例
        for bnode in compressed_bp.nodes.values():
            related_anodes = [
                anode for anode in architecture.nodes.values()
                if anode.parent_bnode_id == bnode.id
            ]
            if related_anodes:
                compressed_count = sum(
                    1 for anode in related_anodes
                    if anode.metadata.status == NodeStatus.COMPRESSED
                )
                ratio = compressed_count / len(related_anodes)
                bnode.metadata.value_score = 1.0 - ratio

        return compressed_bp

    def _calc_chronicle_size(self, chronicle: ChronicleGraph) -> int:
        """计算 Chronicle 的大小（粗略估算，用于压缩率计算）"""
        # 使用有效数据大小（非元数据）来评估压缩效果
        # 计算所有节点的输出+输入数据总大小
        import json
        total_data_size = 0
        for node in chronicle.nodes.values():
            if not node.is_compressed:
                # 未压缩节点：计算完整输出大小
                try:
                    total_data_size += len(json.dumps(node.outputs, ensure_ascii=False))
                    total_data_size += len(json.dumps(node.inputs, ensure_ascii=False))
                except Exception:
                    total_data_size += 200
            else:
                # 压缩节点：只算摘要大小
                total_data_size += 50  # 压缩后的估算大小

        # 加上节点数量的固定开销
        total_data_size += len(chronicle.nodes) * 20
        return total_data_size
