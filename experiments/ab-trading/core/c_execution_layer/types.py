#!/usr/bin/env python3
"""
C层 - 执行层 类型定义

位置: experiments/ab-trading/core/c_execution_layer/types.py

架构说明:
- S层: 意图识别 → ExecutionBlueprint
- A层: 图编排引擎 → 编排节点执行顺序/并行/条件
- C层: 执行层 → 具体执行节点

C层职责：
1. 节点执行器 - 调用适配器框架执行节点
2. 结果聚合器 - 聚合多链/多模块结果
3. 动态链融合器 - AI大模型驱动的动态链融合（后面做）

C层特点：
- 对接 A链/C链/F链 模块
- 支持降级容错
- AI大模型动态链融合（支持动态重规划、执行反思进化）
"""

import time
import uuid
from typing import Dict, List, Optional, Any, Literal, Union
from dataclasses import dataclass, field
from enum import Enum


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ============================================================
# C层：执行层 - 执行上下文
# ============================================================

@dataclass
class ExecutionContext:
    """执行上下文

    贯穿整个执行流程的上下文信息
    """
    # 基础信息
    execution_id: str = field(default_factory=lambda: _gen_id("exec"))
    session_id: Optional[str] = None
    user_id: Optional[str] = None

    # 蓝图信息
    blueprint_id: str = ""
    objective_id: str = ""
    okr_mode: str = ""
    complexity: str = ""

    # 执行状态
    current_node_id: Optional[str] = None
    completed_nodes: List[str] = field(default_factory=list)
    node_outputs: Dict[str, Any] = field(default_factory=dict)

    # 置信度追踪
    overall_confidence: float = 0.0
    confidence_factors: Dict[str, float] = field(default_factory=dict)

    # 元信息
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def update_node_output(self, node_id: str, output: Any):
        """更新节点输出"""
        self.node_outputs[node_id] = output
        if node_id not in self.completed_nodes:
            self.completed_nodes.append(node_id)
        self.current_node_id = node_id

    def get_node_output(self, node_id: str) -> Optional[Any]:
        """获取节点输出"""
        return self.node_outputs.get(node_id)

    def get_all_outputs(self) -> Dict[str, Any]:
        """获取所有节点输出"""
        return self.node_outputs.copy()


# ============================================================
# C层：执行层 - 节点执行结果
# ============================================================

class NodeStatus(Enum):
    """节点执行状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


@dataclass
class NodeExecutionResult:
    """节点执行结果

    C层节点执行后的完整结果
    """
    node_id: str
    node_name: str = ""
    status: NodeStatus = NodeStatus.PENDING

    # 执行信息
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    duration_ms: float = 0.0
    retry_count: int = 0

    # 输入输出
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Optional[Dict[str, Any]] = None
    raw_result: Optional[Any] = None

    # 置信度
    confidence: float = 0.0
    confidence_dimensions: Dict[str, float] = field(default_factory=dict)

    # 成本
    tokens_used: int = 0
    api_calls: int = 0
    cost: float = 0.0

    # 错误信息
    error: Optional[str] = None
    error_code: Optional[str] = None

    # 源信息
    source_module: Optional[str] = None  # 实际调用的模块
    source_chain: Optional[str] = None   # A链/C链/F链
    fallback_used: bool = False

    # 元信息
    metadata: Dict[str, Any] = field(default_factory=dict)

    def mark_started(self):
        """标记开始"""
        self.status = NodeStatus.RUNNING
        self.start_time = time.time()

    def mark_completed(self, outputs: Any):
        """标记完成"""
        self.status = NodeStatus.COMPLETED
        self.end_time = time.time()
        self.raw_result = outputs
        if isinstance(outputs, dict):
            self.outputs = outputs
        else:
            self.outputs = {"result": outputs}
        if self.start_time:
            self.duration_ms = (self.end_time - self.start_time) * 1000

    def mark_failed(self, error: str, error_code: Optional[str] = None):
        """标记失败"""
        self.status = NodeStatus.FAILED
        self.end_time = time.time()
        self.error = error
        self.error_code = error_code
        if self.start_time:
            self.duration_ms = (self.end_time - self.start_time) * 1000

    def mark_retrying(self):
        """标记重试中"""
        self.status = NodeStatus.RETRYING
        self.retry_count += 1

    @property
    def is_success(self) -> bool:
        return self.status == NodeStatus.COMPLETED

    @property
    def is_failure(self) -> bool:
        return self.status == NodeStatus.FAILED

    def to_dict(self) -> Dict:
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "status": self.status.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "retry_count": self.retry_count,
            "outputs": self.outputs,
            "confidence": self.confidence,
            "confidence_dimensions": self.confidence_dimensions,
            "tokens_used": self.tokens_used,
            "cost": self.cost,
            "error": self.error,
            "error_code": self.error_code,
            "source_module": self.source_module,
            "source_chain": self.source_chain,
            "fallback_used": self.fallback_used,
            "metadata": self.metadata,
        }


# ============================================================
# C层：执行层 - 动态链融合
# ============================================================

@dataclass
class ChainFusionDecision:
    """动态链融合决策

    AI大模型分析执行结果后做出的决策
    """
    decision_id: str = field(default_factory=lambda: _gen_id("fusion"))
    node_id: str = ""
    analysis_result: str = ""  # 大模型的分析结果

    # 决策类型
    action: str = "continue"  # continue / skip / retry / redirect / replan

    # 决策参数
    next_node_id: Optional[str] = None  # 下一个执行的节点
    retry_params: Optional[Dict] = None  # 重试参数
    redirect_target: Optional[str] = None  # 重定向目标
    replan_required: bool = False  # 是否需要重新规划
    replan_reason: Optional[str] = None  # 重新规划原因

    # 置信度
    confidence: float = 0.0
    reasoning: str = ""  # 决策理由

    def to_dict(self) -> Dict:
        return {
            "decision_id": self.decision_id,
            "node_id": self.node_id,
            "analysis_result": self.analysis_result,
            "action": self.action,
            "next_node_id": self.next_node_id,
            "retry_params": self.retry_params,
            "redirect_target": self.redirect_target,
            "replan_required": self.replan_required,
            "replan_reason": self.replan_reason,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }


# ============================================================
# C层：执行层 - 结果聚合
# ============================================================

@dataclass
class AggregatedResult:
    """聚合结果

    多链/多模块结果的聚合
    """
    result_id: str = field(default_factory=lambda: _gen_id("agg"))

    # 聚合信息
    mode: str = "weighted"  # weighted / max / min / voting
    node_results: List[NodeExecutionResult] = field(default_factory=list)

    # 聚合输出
    aggregated_output: Optional[Dict] = None
    final_decision: Optional[str] = None

    # 聚合置信度
    overall_confidence: float = 0.0
    confidence_breakdown: Dict[str, float] = field(default_factory=dict)

    # 聚合理由
    rationale: str = ""

    def add_result(self, result: NodeExecutionResult):
        """添加节点结果"""
        self.node_results.append(result)

    def to_dict(self) -> Dict:
        return {
            "result_id": self.result_id,
            "mode": self.mode,
            "aggregated_output": self.aggregated_output,
            "final_decision": self.final_decision,
            "overall_confidence": self.overall_confidence,
            "confidence_breakdown": self.confidence_breakdown,
            "rationale": self.rationale,
            "node_results": [r.to_dict() for r in self.node_results],
        }
