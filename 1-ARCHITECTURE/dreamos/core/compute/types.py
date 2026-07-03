"""
DreamOS C层 — Compute 执行层类型定义

核心数据结构:
    - ReflectAction:     反射动作枚举
    - ReflectDecision:   反射决策结果
    - ExecutionReport:   执行报告
    - NodeExecutionRecord: 单节点执行记录
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum
from datetime import datetime


# ============================================================
# 反射动作
# ============================================================

class ReflectAction(str, Enum):
    """反射决策的动作类型"""
    CONTINUE = "continue"              # 继续 → 执行下一个节点
    REDO = "redo"                       # 重做 → 重新执行当前节点
    INSERT_BEFORE = "insert_before"     # 前插 → 插入新节点后继续
    JUMP_TO = "jump_to"                # 跳转 → 跳到指定节点
    EARLY_TERMINATE = "early_terminate" # 提前终止 → 结束执行
    SKIP = "skip"                       # 跳过 → 跳过当前节点


# ============================================================
# 反射决策
# ============================================================

@dataclass
class ReflectDecision:
    """反射决策结果

    C 层在每个节点执行后会进行反射决策:
        - 是否继续执行下一个节点？
        - 是否需要重做当前节点？
        - 是否需要插入补充节点？
        - 是否需要跳转到其他节点？
        - 是否提前终止（已有足够信息）？
    """
    action: ReflectAction = ReflectAction.CONTINUE
    reason: str = ""
    confidence: float = 0.0              # 对决策本身的置信度
    insert_node_id: Optional[str] = None  # INSERT_BEFORE 时要插入的节点
    jump_to: Optional[str] = None        # JUMP_TO 时要跳转到的节点
    suggestions: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def should_continue(self) -> bool:
        return self.action == ReflectAction.CONTINUE

    @property
    def should_terminate(self) -> bool:
        return self.action == ReflectAction.EARLY_TERMINATE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action.value,
            "reason": self.reason,
            "confidence": self.confidence,
            "insert_node_id": self.insert_node_id,
            "jump_to": self.jump_to,
            "suggestions": self.suggestions,
        }


# ============================================================
# 单节点执行记录
# ============================================================

@dataclass
class NodeExecutionRecord:
    """单个节点的执行记录"""
    node_id: str
    status: str = "success"              # success / failed / degraded / skipped
    confidence: float = 0.0
    direction: Optional[str] = None
    latency_ms: float = 0.0
    tokens_used: int = 0
    retries: int = 0
    reflect_action: str = "continue"
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "status": self.status,
            "confidence": self.confidence,
            "direction": self.direction,
            "latency_ms": self.latency_ms,
            "tokens_used": self.tokens_used,
            "retries": self.retries,
            "reflect_action": self.reflect_action,
            "error": self.error,
            "timestamp": self.timestamp,
        }


# ============================================================
# 执行报告 (C层最终输出)
# ============================================================

@dataclass
class ExecutionReport:
    """执行报告 — C 层执行完毕后的完整报告

    包含:
        - 执行结果汇总
        - 各节点执行记录
        - 反射决策历史
        - 最终聚合结果
        - Token 消耗统计
    """
    total_nodes: int = 0
    executed_nodes: int = 0
    success_nodes: int = 0
    failed_nodes: int = 0
    degraded_nodes: int = 0
    skipped_nodes: int = 0

    records: List[NodeExecutionRecord] = field(default_factory=list)
    reflect_history: List[Dict[str, Any]] = field(default_factory=list)

    total_tokens: int = 0
    total_latency_ms: float = 0.0

    final_action: Optional[str] = None       # LONG / SHORT / HOLD
    final_confidence: float = 0.0
    final_direction_scores: Dict[str, float] = field(default_factory=dict)

    early_terminated: bool = False
    termination_reason: Optional[str] = None

    @property
    def success_rate(self) -> float:
        if self.executed_nodes == 0:
            return 0.0
        return self.success_nodes / self.executed_nodes

    def add_record(self, record: NodeExecutionRecord) -> None:
        self.records.append(record)
        self.executed_nodes += 1
        self.total_tokens += record.tokens_used
        self.total_latency_ms += record.latency_ms
        if record.status == "success":
            self.success_nodes += 1
        elif record.status == "failed":
            self.failed_nodes += 1
        elif record.status == "degraded":
            self.degraded_nodes += 1
        elif record.status == "skipped":
            self.skipped_nodes += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_nodes": self.total_nodes,
            "executed_nodes": self.executed_nodes,
            "success_nodes": self.success_nodes,
            "failed_nodes": self.failed_nodes,
            "degraded_nodes": self.degraded_nodes,
            "skipped_nodes": self.skipped_nodes,
            "success_rate": round(self.success_rate, 3),
            "records": [r.to_dict() for r in self.records],
            "reflect_history": self.reflect_history,
            "total_tokens": self.total_tokens,
            "total_latency_ms": round(self.total_latency_ms, 1),
            "final_action": self.final_action,
            "final_confidence": self.final_confidence,
            "final_direction_scores": self.final_direction_scores,
            "early_terminated": self.early_terminated,
            "termination_reason": self.termination_reason,
        }
