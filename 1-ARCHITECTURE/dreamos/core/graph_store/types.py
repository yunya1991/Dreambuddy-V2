"""
DreamOS G层 — GraphStore 图存储层类型定义

核心数据结构:
    - Checkpoint:        状态检查点
    - CompressedState:   压缩后的状态
    - HistoryEntry:      历史记录条目
    - ReplayResult:      回放结果
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime


# ============================================================
# 检查点
# ============================================================

@dataclass
class Checkpoint:
    """状态检查点

    在关键执行节点保存 State 快照:
        - 每个节点执行后可选保存
        - 支持回滚到任意检查点
        - 支持从检查点恢复执行
    """
    checkpoint_id: str
    cycle_id: str
    node_id: str                          # 触发检查点的节点
    state_snapshot: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "cycle_id": self.cycle_id,
            "node_id": self.node_id,
            "state_snapshot": self.state_snapshot,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


# ============================================================
# 压缩状态
# ============================================================

@dataclass
class CompressedState:
    """压缩后的状态

    当 State 过大时，压缩历史数据:
        - 保留最近的 N 条 trace
        - 合并旧节点结果为摘要
        - 压缩 market/memory 快照
    """
    original_size: int = 0                 # 压缩前大小（估算）
    compressed_size: int = 0              # 压缩后大小
    compression_ratio: float = 0.0        # 压缩率
    summary: Dict[str, Any] = field(default_factory=dict)
    retained_trace_count: int = 0
    removed_trace_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_size": self.original_size,
            "compressed_size": self.compressed_size,
            "compression_ratio": round(self.compression_ratio, 3),
            "summary": self.summary,
            "retained_trace_count": self.retained_trace_count,
            "removed_trace_count": self.removed_trace_count,
        }


# ============================================================
# 历史记录条目
# ============================================================

@dataclass
class HistoryEntry:
    """历史记录条目

    记录每次执行的完整信息:
        - 执行结果
        - 上下文快照
        - 关键指标
    """
    cycle_id: str
    intent_type: str = ""
    planned_chain: str = ""
    final_action: str = ""
    final_confidence: float = 0.0
    total_tokens: int = 0
    total_latency_ms: float = 0.0
    success_rate: float = 0.0
    node_count: int = 0
    early_terminated: bool = False
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    snapshot: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "intent_type": self.intent_type,
            "planned_chain": self.planned_chain,
            "final_action": self.final_action,
            "final_confidence": self.final_confidence,
            "total_tokens": self.total_tokens,
            "total_latency_ms": round(self.total_latency_ms, 1),
            "success_rate": self.success_rate,
            "node_count": self.node_count,
            "early_terminated": self.early_terminated,
            "created_at": self.created_at,
            "snapshot": self.snapshot,
        }


# ============================================================
# 回放结果
# ============================================================

@dataclass
class ReplayResult:
    """历史回放结果"""
    cycle_id: str
    entries: List[HistoryEntry] = field(default_factory=list)
    patterns: Dict[str, Any] = field(default_factory=dict)
    total: int = 0

    @property
    def success_count(self) -> int:
        return sum(1 for e in self.entries if e.final_action and e.final_action != "HOLD")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "entries": [e.to_dict() for e in self.entries],
            "patterns": self.patterns,
            "total": self.total,
            "success_count": self.success_count,
        }
