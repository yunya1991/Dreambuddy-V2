#!/usr/bin/env python3
"""
G层 - 图存储/压缩层 类型定义

位置: experiments/ab-trading/core/g_graph_storage/types.py

命名说明:
- G层 = Graph Storage Layer（图存储/压缩层）
- G.B = Blueprint（蓝图级）- 顶层架构图
- G.A = Architecture（架构级）- DAG执行步骤图
- G.C = Chronicle（记录级）- 时间线执行记录

与运行时三层的关系:
  S层(意图识别) → A层(图编排) → C层(执行层)
       ↓              ↓              ↓
      G.B            G.A            G.C
  (蓝图存储)    (架构存储)     (记录存储)

压缩方向:
  正向展开: G.B → G.A → G.C
  回溯压缩: G.C → G.A → G.B
"""

import time
import uuid
from typing import Dict, List, Optional, Any, Literal, Union
from dataclasses import dataclass, field, asdict
from enum import Enum


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ============================================================
# 基础类型
# ============================================================

NodeId = str
EdgeId = str


class NodeStatus(str, Enum):
    """节点状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    COMPRESSED = "compressed"  # 压缩标记


class NodeType(str, Enum):
    """节点类型（G.A 用）"""
    STEP = "step"          # 执行步骤
    DECISION = "decision"  # 决策点
    PARALLEL = "parallel"  # 并行分支


class ComponentType(str, Enum):
    """组件类型（G.B 用）"""
    COMPONENT = "component"
    MODULE = "module"
    SERVICE = "service"


class CompressionStrategy(str, Enum):
    """压缩策略"""
    VALUE_PRIORITY = "value_priority"   # 价值优先
    PATH_PRESERVE = "path_preserve"     # 路径保留
    CRITICAL_ONLY = "critical_only"     # 关键节点
    SEMANTIC_AWARE = "semantic_aware"   # 语义感知


# ============================================================
# 节点元数据
# ============================================================

@dataclass
class NodeMetadata:
    """节点元数据"""
    token_cost: int = 0
    latency_ms: int = 0
    status: NodeStatus = NodeStatus.PENDING
    skip_reason: Optional[str] = None
    output_summary: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    tags: List[str] = field(default_factory=list)

    # 价值评分（用于压缩决策）
    value_score: float = 0.0

    # 扩展字段
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: Dict) -> "NodeMetadata":
        status = data.get("status", "pending")
        data = data.copy()
        data["status"] = NodeStatus(status)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ============================================================
# G.B - Blueprint 蓝图级
# ============================================================

@dataclass
class BNode:
    """G.B 节点 - 组件/模块/服务"""
    id: NodeId
    name: str
    type: ComponentType = ComponentType.MODULE
    description: str = ""
    metadata: NodeMetadata = field(default_factory=NodeMetadata)
    children: List[NodeId] = field(default_factory=list)
    parent_id: Optional[NodeId] = None

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "description": self.description,
            "metadata": self.metadata.to_dict(),
            "children": self.children,
            "parent_id": self.parent_id,
        }


@dataclass
class BEdge:
    """G.B 边 - 数据流/控制流"""
    id: EdgeId = field(default_factory=lambda: _gen_id("be"))
    source: NodeId = ""
    target: NodeId = ""
    data_flow_type: str = "data"  # data / control / knowledge
    label: str = ""
    description: str = ""

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "data_flow_type": self.data_flow_type,
            "label": self.label,
            "description": self.description,
        }


@dataclass
class BlueprintGraph:
    """G.B - 蓝图（顶层架构图）"""
    id: str = field(default_factory=lambda: _gen_id("bp"))
    name: str = ""
    description: str = ""
    version: str = "1.0"

    nodes: Dict[NodeId, BNode] = field(default_factory=dict)
    edges: List[BEdge] = field(default_factory=list)
    root_id: NodeId = ""

    # 元信息
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    tags: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    def get_node(self, node_id: NodeId) -> Optional[BNode]:
        return self.nodes.get(node_id)

    def add_node(self, node: BNode):
        self.nodes[node.id] = node
        self.updated_at = time.time()

    def add_edge(self, edge: BEdge):
        self.edges.append(edge)
        self.updated_at = time.time()

    def get_root(self) -> Optional[BNode]:
        return self.nodes.get(self.root_id) if self.root_id else None

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "edges": [e.to_dict() for e in self.edges],
            "root_id": self.root_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "tags": self.tags,
        }


# ============================================================
# G.A - Architecture 架构级（DAG图）
# ============================================================

@dataclass
class ANode:
    """G.A 节点 - 执行步骤/决策点/并行分支"""
    id: NodeId
    name: str
    type: NodeType = NodeType.STEP
    parent_bnode_id: NodeId = ""  # 所属 G.B 节点

    metadata: NodeMetadata = field(default_factory=NodeMetadata)
    requires: List[NodeId] = field(default_factory=list)  # 依赖
    branches: List[Dict] = field(default_factory=list)  # 条件分支

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "parent_bnode_id": self.parent_bnode_id,
            "metadata": self.metadata.to_dict(),
            "requires": self.requires,
            "branches": self.branches,
        }


@dataclass
class AEdge:
    """G.A 边 - 数据依赖/条件分支"""
    id: EdgeId = field(default_factory=lambda: _gen_id("ae"))
    source: NodeId = ""
    target: NodeId = ""
    is_conditional: bool = False
    condition: Optional[str] = None
    data_flow_type: str = "data"

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "is_conditional": self.is_conditional,
            "condition": self.condition,
            "data_flow_type": self.data_flow_type,
        }


@dataclass
class ArchitectureGraph:
    """G.A - 架构图（DAG执行步骤）"""
    id: str = field(default_factory=lambda: _gen_id("arch"))
    blueprint_id: str = ""
    name: str = ""

    nodes: Dict[NodeId, ANode] = field(default_factory=dict)
    edges: List[AEdge] = field(default_factory=list)

    # 入口节点
    entry_node_id: NodeId = ""

    # 元信息
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    compression_level: int = 0  # 压缩层级（0=未压缩）

    def get_node(self, node_id: NodeId) -> Optional[ANode]:
        return self.nodes.get(node_id)

    def add_node(self, node: ANode):
        self.nodes[node.id] = node
        self.updated_at = time.time()

    def add_edge(self, edge: AEdge):
        self.edges.append(edge)
        self.updated_at = time.time()

    def topological_sort(self) -> List[NodeId]:
        """拓扑排序"""
        in_degree = {nid: 0 for nid in self.nodes}
        for edge in self.edges:
            if edge.target in in_degree:
                in_degree[edge.target] += 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        result = []

        while queue:
            node_id = queue.pop(0)
            result.append(node_id)
            for edge in self.edges:
                if edge.source == node_id and edge.target in in_degree:
                    in_degree[edge.target] -= 1
                    if in_degree[edge.target] == 0:
                        queue.append(edge.target)

        return result

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "blueprint_id": self.blueprint_id,
            "name": self.name,
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "edges": [e.to_dict() for e in self.edges],
            "entry_node_id": self.entry_node_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "compression_level": self.compression_level,
        }


# ============================================================
# G.C - Chronicle 记录级（时间线）
# ============================================================

@dataclass
class CNode:
    """G.C 节点 - 执行记录"""
    id: NodeId
    architecture_node_id: NodeId = ""  # 对应的 G.A 节点
    execution_id: str = ""

    # 时间
    start_time: float = 0.0
    end_time: Optional[float] = None

    # 数据
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    logs: List[str] = field(default_factory=list)

    # 元数据
    metadata: NodeMetadata = field(default_factory=NodeMetadata)

    # 压缩相关
    is_compressed: bool = False
    compressed_from: Optional[List[NodeId]] = None  # 由哪些节点压缩而来

    @property
    def duration_ms(self) -> float:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time) * 1000
        return 0.0

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "architecture_node_id": self.architecture_node_id,
            "execution_id": self.execution_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "logs": self.logs,
            "metadata": self.metadata.to_dict(),
            "is_compressed": self.is_compressed,
            "compressed_from": self.compressed_from,
        }


@dataclass
class CEdge:
    """G.C 边 - 数据传递记录"""
    id: EdgeId = field(default_factory=lambda: _gen_id("ce"))
    source: NodeId = ""
    target: NodeId = ""
    data_keys: List[str] = field(default_factory=list)  # 传递了哪些数据
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "data_keys": self.data_keys,
            "timestamp": self.timestamp,
        }


@dataclass
class ChronicleGraph:
    """G.C - 时间线（执行记录）"""
    id: str = field(default_factory=lambda: _gen_id("chron"))
    architecture_id: str = ""
    execution_id: str = ""

    nodes: Dict[NodeId, CNode] = field(default_factory=dict)
    edges: List[CEdge] = field(default_factory=list)

    # 按执行顺序的节点ID列表
    sequence: List[NodeId] = field(default_factory=list)

    # 元信息
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    compression_level: int = 0  # 压缩层级

    def get_node(self, node_id: NodeId) -> Optional[CNode]:
        return self.nodes.get(node_id)

    def add_node(self, node: CNode):
        self.nodes[node.id] = node
        if node.id not in self.sequence:
            self.sequence.append(node.id)
        self.updated_at = time.time()

    def add_edge(self, edge: CEdge):
        self.edges.append(edge)
        self.updated_at = time.time()

    @property
    def total_tokens(self) -> int:
        return sum(n.metadata.token_cost for n in self.nodes.values())

    @property
    def total_duration_ms(self) -> float:
        return sum(n.duration_ms for n in self.nodes.values())

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "architecture_id": self.architecture_id,
            "execution_id": self.execution_id,
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "edges": [e.to_dict() for e in self.edges],
            "sequence": self.sequence,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "compression_level": self.compression_level,
            "total_tokens": self.total_tokens,
            "total_duration_ms": self.total_duration_ms,
        }


# ============================================================
# 压缩结果
# ============================================================

@dataclass
class CompressionResult:
    """压缩结果"""
    success: bool = False
    strategy: CompressionStrategy = CompressionStrategy.VALUE_PRIORITY

    # 压缩前后的图
    original_chronicle: Optional[ChronicleGraph] = None
    compressed_chronicle: Optional[ChronicleGraph] = None
    compressed_architecture: Optional[ArchitectureGraph] = None
    compressed_blueprint: Optional[BlueprintGraph] = None

    # 统计
    original_size: int = 0
    compressed_size: int = 0
    compression_ratio: float = 1.0  # compressed / original

    # 详情
    preserved_nodes: List[NodeId] = field(default_factory=list)
    compressed_nodes: List[NodeId] = field(default_factory=list)
    discarded_details: List[Dict] = field(default_factory=list)

    # 耗时
    compression_time_ms: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "strategy": self.strategy.value,
            "original_size": self.original_size,
            "compressed_size": self.compressed_size,
            "compression_ratio": self.compression_ratio,
            "preserved_nodes_count": len(self.preserved_nodes),
            "compressed_nodes_count": len(self.compressed_nodes),
            "compression_time_ms": self.compression_time_ms,
        }
