#!/usr/bin/env python3
"""
G层 - 图存储/压缩层

位置: experiments/ab-trading/core/g_graph_storage/

命名说明:
- G层 = Graph Storage Layer（图存储/压缩层）
- 对应原 6-图结构上下文压缩 项目的三层模型

三层模型:
  G.B - Blueprint（蓝图级）    顶层架构图，组件/模块/服务
  G.A - Architecture（架构级） DAG执行步骤图
  G.C - Chronicle（记录级）    时间线执行记录

压缩方向:
  正向展开: G.B → G.A → G.C
  回溯压缩: G.C → G.A → G.B

与运行时三层的关系:
  运行时: S(意图) → A(编排) → C(执行)
           ↓        ↓        ↓
  存储:   G.B      G.A      G.C

核心组件:
- types: 三层图模型定义
- compressor: 压缩器（价值评估 + 回溯压缩）
- expander: 展开器（正向展开）
- manager: 图存储管理器（统一入口 + 持久化）
- bridge: G层桥接器（连接运行时三层与存储三层）
- history: 历史检索器（经验复用 + 模式识别）

特色:
- 操作系统级原生压缩能力
- 价值优先的智能压缩
- 可追溯、可恢复
- 支持无限上下文（对数级存储增长）
- 历史经验复用
- 执行模式识别
"""

from .types import (
    # 基础类型
    NodeId,
    EdgeId,
    NodeStatus,
    NodeType,
    ComponentType,
    CompressionStrategy,
    NodeMetadata,
    # G.B - Blueprint
    BNode,
    BEdge,
    BlueprintGraph,
    # G.A - Architecture
    ANode,
    AEdge,
    ArchitectureGraph,
    # G.C - Chronicle
    CNode,
    CEdge,
    ChronicleGraph,
    # 结果
    CompressionResult,
)

from .compressor import (
    ValueScorer,
    GraphCompressor,
)

from .expander import (
    GraphExpander,
)

from .manager import (
    GraphStorageManager,
)

from .bridge import (
    GraphStorageBridge,
)

from .history import (
    HistoryRecord,
    SimilarTaskMatch,
    ExecutionPattern,
    HistoryRetriever,
)

__all__ = [
    # 基础类型
    "NodeId",
    "EdgeId",
    "NodeStatus",
    "NodeType",
    "ComponentType",
    "CompressionStrategy",
    "NodeMetadata",
    # G.B - Blueprint
    "BNode",
    "BEdge",
    "BlueprintGraph",
    # G.A - Architecture
    "ANode",
    "AEdge",
    "ArchitectureGraph",
    # G.C - Chronicle
    "CNode",
    "CEdge",
    "ChronicleGraph",
    # 结果
    "CompressionResult",
    # 压缩器
    "ValueScorer",
    "GraphCompressor",
    # 展开器
    "GraphExpander",
    # 管理器
    "GraphStorageManager",
    # 桥接器
    "GraphStorageBridge",
    # 历史检索
    "HistoryRecord",
    "SimilarTaskMatch",
    "ExecutionPattern",
    "HistoryRetriever",
]
