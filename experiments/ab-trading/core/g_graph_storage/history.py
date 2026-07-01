#!/usr/bin/env python3
"""
历史检索器 - 基于G层的历史执行检索和经验复用

位置: experiments/ab-trading/core/g_graph_storage/history.py

职责：
1. 历史执行记录检索
2. 相似任务匹配
3. 经验复用（从历史执行中提取可复用的知识）
4. 模式识别（发现重复的执行模式）

这是操作系统的"记忆"功能，为动态链融合的"执行反思进化"提供数据支撑。
"""

import time
import re
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field

from .types import (
    BlueprintGraph,
    ArchitectureGraph,
    ChronicleGraph,
    CompressionResult,
    NodeId,
    _gen_id,
)
from .manager import GraphStorageManager


# ============================================================
# 历史记录类型
# ============================================================

@dataclass
class HistoryRecord:
    """历史执行记录"""
    execution_id: str = ""
    blueprint_id: str = ""
    architecture_id: str = ""
    chronicle_id: str = ""

    blueprint_name: str = ""
    description: str = ""

    created_at: float = 0.0
    completed_at: float = 0.0

    total_duration_ms: float = 0.0
    total_tokens: int = 0
    node_count: int = 0

    # 压缩相关
    compressed: bool = False
    compression_ratio: float = 1.0

    # 标签
    tags: List[str] = field(default_factory=list)

    # 结果摘要
    result_summary: str = ""
    success: bool = True

    def to_dict(self) -> Dict:
        return {
            "execution_id": self.execution_id,
            "blueprint_id": self.blueprint_id,
            "architecture_id": self.architecture_id,
            "chronicle_id": self.chronicle_id,
            "blueprint_name": self.blueprint_name,
            "description": self.description,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "total_duration_ms": self.total_duration_ms,
            "total_tokens": self.total_tokens,
            "node_count": self.node_count,
            "compressed": self.compressed,
            "compression_ratio": self.compression_ratio,
            "tags": self.tags,
            "result_summary": self.result_summary,
            "success": self.success,
        }


@dataclass
class SimilarTaskMatch:
    """相似任务匹配结果"""
    record: HistoryRecord
    similarity: float = 0.0
    match_reason: str = ""

    # 可复用的部分
    reusable_nodes: List[str] = field(default_factory=list)
    reusable_outputs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionPattern:
    """执行模式（从历史中发现的重复模式）"""
    pattern_id: str = field(default_factory=lambda: _gen_id("pat"))
    name: str = ""
    description: str = ""

    # 模式特征
    node_sequence: List[str] = field(default_factory=list)
    frequency: int = 0
    avg_duration_ms: float = 0.0
    avg_token_cost: int = 0

    # 适用场景
    tags: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "pattern_id": self.pattern_id,
            "name": self.name,
            "description": self.description,
            "node_sequence": self.node_sequence,
            "frequency": self.frequency,
            "avg_duration_ms": self.avg_duration_ms,
            "avg_token_cost": self.avg_token_cost,
            "tags": self.tags,
            "keywords": self.keywords,
        }


# ============================================================
# 历史检索器
# ============================================================

class HistoryRetriever:
    """历史检索器

    基于G层的历史执行检索和经验复用
    """

    def __init__(
        self,
        storage_manager: GraphStorageManager,
        max_history: int = 1000,
    ):
        """
        Args:
            storage_manager: 存储管理器
            max_history: 最大历史记录数
        """
        self.storage = storage_manager
        self.max_history = max_history

        # 历史索引（内存缓存）
        self._history_index: List[HistoryRecord] = []

        # 模式库
        self._patterns: Dict[str, ExecutionPattern] = {}

    # ============================================================
    # 历史记录管理
    # ============================================================

    def add_history(
        self,
        bp: BlueprintGraph,
        arch: ArchitectureGraph,
        chron: ChronicleGraph,
        success: bool = True,
        summary: str = "",
        tags: Optional[List[str]] = None,
    ) -> HistoryRecord:
        """
        添加历史记录

        Args:
            bp: 蓝图
            arch: 架构图
            chron: 时间线
            success: 是否成功
            summary: 结果摘要
            tags: 标签

        Returns:
            HistoryRecord
        """
        record = HistoryRecord(
            execution_id=chron.execution_id,
            blueprint_id=bp.id,
            architecture_id=arch.id,
            chronicle_id=chron.id,
            blueprint_name=bp.name,
            description=bp.description,
            created_at=chron.created_at,
            completed_at=time.time(),
            total_duration_ms=chron.total_duration_ms,
            total_tokens=chron.total_tokens,
            node_count=len(chron.nodes),
            compressed=chron.compression_level > 0,
            compression_ratio=chron.compression_level / 3.0 if chron.compression_level > 0 else 1.0,
            tags=tags or [],
            result_summary=summary,
            success=success,
        )

        self._history_index.insert(0, record)

        # 限制数量
        if len(self._history_index) > self.max_history:
            self._history_index = self._history_index[:self.max_history]

        return record

    def list_history(
        self,
        limit: int = 20,
        offset: int = 0,
        success_only: bool = False,
        tags: Optional[List[str]] = None,
    ) -> List[HistoryRecord]:
        """
        列出历史记录

        Args:
            limit: 数量限制
            offset: 偏移
            success_only: 只看成功的
            tags: 按标签过滤

        Returns:
            历史记录列表
        """
        records = self._history_index

        if success_only:
            records = [r for r in records if r.success]

        if tags:
            records = [r for r in records if any(t in r.tags for t in tags)]

        return records[offset:offset + limit]

    def get_history(self, execution_id: str) -> Optional[HistoryRecord]:
        """获取单条历史记录"""
        for record in self._history_index:
            if record.execution_id == execution_id:
                return record
        return None

    def get_chronicle(self, execution_id: str) -> Optional[ChronicleGraph]:
        """获取执行的完整时间线"""
        record = self.get_history(execution_id)
        if not record:
            return None
        return self.storage.get_chronicle(record.chronicle_id)

    # ============================================================
    # 相似任务检索
    # ============================================================

    def find_similar_tasks(
        self,
        query: str,
        tags: Optional[List[str]] = None,
        top_k: int = 5,
    ) -> List[SimilarTaskMatch]:
        """
        查找相似任务

        Args:
            query: 查询文本（任务描述）
            tags: 标签过滤
            top_k: 返回数量

        Returns:
            相似任务匹配列表
        """
        query_lower = query.lower()
        query_keywords = set(re.findall(r'\w+', query_lower))

        matches = []

        for record in self._history_index:
            # 标签过滤
            if tags and not any(t in record.tags for t in tags):
                continue

            # 计算相似度（简单关键词匹配）
            title_lower = record.blueprint_name.lower()
            desc_lower = record.description.lower()
            summary_lower = record.result_summary.lower()
            tags_lower = ' '.join(record.tags).lower()

            # 合并所有文本
            all_text = f"{title_lower} {desc_lower} {summary_lower} {tags_lower}"

            # 关键词匹配
            text_keywords = set(re.findall(r'\w+', all_text))
            if not query_keywords or not text_keywords:
                similarity = 0.0
            else:
                intersection = query_keywords & text_keywords
                union = query_keywords | text_keywords
                similarity = len(intersection) / len(union) if union else 0.0

            # 标题匹配加权
            if any(kw in title_lower for kw in query_keywords):
                similarity += 0.2

            similarity = min(similarity, 1.0)

            if similarity > 0.1:  # 最低阈值
                match = SimilarTaskMatch(
                    record=record,
                    similarity=similarity,
                    match_reason=self._generate_match_reason(query_keywords, text_keywords, record),
                )
                matches.append(match)

        # 按相似度排序
        matches.sort(key=lambda m: m.similarity, reverse=True)
        return matches[:top_k]

    def _generate_match_reason(
        self,
        query_keywords: set,
        text_keywords: set,
        record: HistoryRecord,
    ) -> str:
        """生成匹配原因"""
        common = query_keywords & text_keywords
        if common:
            return f"匹配关键词: {', '.join(list(common)[:5])}"
        return "语义相似"

    # ============================================================
    # 经验复用
    # ============================================================

    def extract_reusable_knowledge(
        self,
        execution_id: str,
    ) -> Dict[str, Any]:
        """
        从历史执行中提取可复用知识

        Args:
            execution_id: 执行ID

        Returns:
            可复用知识
        """
        chron = self.get_chronicle(execution_id)
        if not chron:
            return {}

        knowledge = {
            "execution_id": execution_id,
            "node_sequence": chron.sequence,
            "total_duration_ms": chron.total_duration_ms,
            "total_tokens": chron.total_tokens,
            "node_outputs": {},
            "key_insights": [],
        }

        # 提取高价值节点的输出
        for nid in chron.sequence:
            node = chron.get_node(nid)
            if not node or node.is_compressed:
                continue

            # 高价值节点（token消耗高的）
            if node.metadata.token_cost > 50:
                knowledge["node_outputs"][nid] = {
                    "outputs": node.outputs,
                    "token_cost": node.metadata.token_cost,
                    "duration_ms": node.duration_ms,
                }

                # 提取关键洞察
                if "insight" in node.outputs:
                    knowledge["key_insights"].append(node.outputs["insight"])
                elif "result" in node.outputs and isinstance(node.outputs["result"], str):
                    if len(node.outputs["result"]) < 200:
                        knowledge["key_insights"].append(node.outputs["result"])

        return knowledge

    # ============================================================
    # 模式识别
    # ============================================================

    def discover_patterns(
        self,
        min_frequency: int = 2,
    ) -> List[ExecutionPattern]:
        """
        从历史中发现执行模式

        Args:
            min_frequency: 最小出现次数

        Returns:
            发现的模式列表
        """
        # 简单的模式识别：找出重复出现的节点序列
        pattern_counts: Dict[str, Dict] = {}

        for record in self._history_index:
            chron = self.storage.get_chronicle(record.chronicle_id)
            if not chron:
                continue

            seq = tuple(chron.sequence)
            seq_key = '|'.join(seq)

            if seq_key not in pattern_counts:
                pattern_counts[seq_key] = {
                    "sequence": list(seq),
                    "count": 0,
                    "total_duration": 0.0,
                    "total_tokens": 0,
                    "records": [],
                }

            pattern_counts[seq_key]["count"] += 1
            pattern_counts[seq_key]["total_duration"] += record.total_duration_ms
            pattern_counts[seq_key]["total_tokens"] += record.total_tokens
            pattern_counts[seq_key]["records"].append(record.execution_id)

        # 筛选高频模式
        patterns = []
        for seq_key, data in pattern_counts.items():
            if data["count"] >= min_frequency:
                count = data["count"]
                pattern = ExecutionPattern(
                    name=f"模式_{len(patterns) + 1}",
                    description=f"出现 {count} 次的执行模式",
                    node_sequence=data["sequence"],
                    frequency=count,
                    avg_duration_ms=data["total_duration"] / count,
                    avg_token_cost=int(data["total_tokens"] / count),
                    tags=[],
                )
                patterns.append(pattern)
                self._patterns[pattern.pattern_id] = pattern

        # 按频率排序
        patterns.sort(key=lambda p: p.frequency, reverse=True)
        return patterns

    def get_patterns(self) -> List[ExecutionPattern]:
        """获取所有已发现的模式"""
        return list(self._patterns.values())

    # ============================================================
    # 统计
    # ============================================================

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        total_tokens = sum(r.total_tokens for r in self._history_index)
        total_duration = sum(r.total_duration_ms for r in self._history_index)
        compressed_count = sum(1 for r in self._history_index if r.compressed)
        success_count = sum(1 for r in self._history_index if r.success)

        return {
            "total_records": len(self._history_index),
            "success_rate": success_count / len(self._history_index) if self._history_index else 0.0,
            "total_tokens": total_tokens,
            "avg_tokens": total_tokens / len(self._history_index) if self._history_index else 0,
            "total_duration_ms": total_duration,
            "avg_duration_ms": total_duration / len(self._history_index) if self._history_index else 0,
            "compressed_count": compressed_count,
            "patterns_count": len(self._patterns),
            "max_history": self.max_history,
        }
