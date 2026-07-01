#!/usr/bin/env python3
"""
A层 - 图编排引擎 类型定义

位置: experiments/ab-trading/core/a_graph_orchestrator/types.py

架构说明:
- S层: 意图识别（用户目标 → OKR → 执行蓝图）
- A层: 图编排引擎（基于蓝图编排节点执行顺序/并行/条件）
- C层: 执行层（调用适配器框架执行节点，和AI大模型动态链融合）

A层职责：
1. 基于 ExecutionBlueprint 编排节点执行顺序
2. 管理节点间依赖关系（DAG执行）
3. 支持顺序/并行/混合执行模式
4. 提供节点执行状态回调
"""

import time
import uuid
from typing import Dict, List, Optional, Any, Callable, Set
from dataclasses import dataclass, field

from ..shared.interfaces import NodeExecutionStatus


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ============================================================
# A层：图编排引擎 - 图执行结果
# ============================================================

@dataclass
class GraphExecutionResult:
    """图执行结果

    A层输出的完整执行结果，包含所有节点的状态和聚合结果
    """
    result_id: str = field(default_factory=lambda: _gen_id("graph"))
    blueprint_id: str = ""
    objective_id: str = ""

    # 执行状态
    status: str = "pending"  # pending / running / completed / partial / failed
    execution_mode: str = ""  # sequential / parallel / hybrid

    # 节点执行详情
    node_statuses: Dict[str, NodeExecutionStatus] = field(default_factory=dict)

    # 执行统计
    total_nodes: int = 0
    completed_nodes: int = 0
    failed_nodes: int = 0
    skipped_nodes: int = 0
    total_duration_ms: float = 0.0

    # 开始/结束时间
    start_time: Optional[float] = None
    end_time: Optional[float] = None

    # 聚合结果（C层产出）
    aggregated_result: Optional[Dict] = None
    confidence: float = 0.0
    rationale: str = ""

    # 错误信息
    error: Optional[str] = None
    failed_node_ids: List[str] = field(default_factory=list)

    # 元信息
    metadata: Dict = field(default_factory=dict)

    def add_node_status(self, status: NodeExecutionStatus):
        """添加节点执行状态"""
        self.node_statuses[status.node_id] = status

    def get_node_status(self, node_id: str) -> Optional[NodeExecutionStatus]:
        """获取节点执行状态"""
        return self.node_statuses.get(node_id)

    def get_completed_results(self) -> Dict[str, Any]:
        """获取所有成功节点的输出结果"""
        return {
            node_id: status.result
            for node_id, status in self.node_statuses.items()
            if status.status == "completed" and status.result is not None
        }

    def update_statistics(self):
        """更新统计信息"""
        self.total_nodes = len(self.node_statuses)
        self.completed_nodes = sum(
            1 for s in self.node_statuses.values() if s.status == "completed"
        )
        self.failed_nodes = sum(
            1 for s in self.node_statuses.values() if s.status == "failed"
        )
        self.skipped_nodes = sum(
            1 for s in self.node_statuses.values() if s.status == "skipped"
        )

        if self.start_time and self.end_time:
            self.total_duration_ms = (self.end_time - self.start_time) * 1000

        self.failed_node_ids = [
            node_id for node_id, s in self.node_statuses.items()
            if s.status == "failed"
        ]

    def to_dict(self) -> Dict:
        return {
            "result_id": self.result_id,
            "blueprint_id": self.blueprint_id,
            "objective_id": self.objective_id,
            "status": self.status,
            "execution_mode": self.execution_mode,
            "total_nodes": self.total_nodes,
            "completed_nodes": self.completed_nodes,
            "failed_nodes": self.failed_nodes,
            "skipped_nodes": self.skipped_nodes,
            "total_duration_ms": self.total_duration_ms,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "aggregated_result": self.aggregated_result,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "error": self.error,
            "failed_node_ids": self.failed_node_ids,
            "node_statuses": {
                node_id: status.to_dict()
                for node_id, status in self.node_statuses.items()
            },
            "metadata": self.metadata,
        }


# 从shared模块导入共享类型
from ..shared.interfaces import ExecutionStrategy
