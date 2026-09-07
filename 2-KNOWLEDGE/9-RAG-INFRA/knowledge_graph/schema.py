# -*- coding: utf-8 -*-
"""知识图谱 Schema：节点类型、关系类型与各类节点的属性定义。

图引擎使用 NetworkX（纯 Python，无外部服务依赖）。
接口设计兼容后续替换为 Neo4j：节点/关系类型以枚举字符串标识，
节点属性以扁平 dict 存储，便于映射到图数据库的 label 与 property。
"""

from enum import Enum

from pathlib import Path

# === 默认持久化路径（基于本文件位置解析，任意工作目录可用） ===
# schema.py 位于 9-RAG-INFRA/knowledge_graph/schema.py
_THIS_DIR = Path(__file__).resolve().parent          # .../9-RAG-INFRA/knowledge_graph
_RAG_INFRA_DIR = _THIS_DIR.parent                     # .../9-RAG-INFRA

# 图谱持久化目录与文件（graph_db/ 已在 .gitignore 中忽略）
GRAPH_DB_DIR = _RAG_INFRA_DIR / "graph_db"
DEFAULT_GRAPH_PATH = GRAPH_DB_DIR / "knowledge_graph.pkl"


class NodeType(str, Enum):
    """节点类型枚举。继承 str 使其可 JSON 序列化、可直接作 NetworkX 属性。"""

    MODULE = "Module"            # 模块（如 11-易经推理系统）
    CONCEPT = "Concept"          # 概念（如 二元矛盾推理模型）
    ALGORITHM = "Algorithm"      # 算法（如 kalman、pca，来自 #tag）
    FILE = "File"                # 文件（*.py / *.md）
    STRATEGY = "Strategy"        # 策略（如 V9-马丁基线）
    PARAMETER = "Parameter"      # 参数（如 θ_match=0.71）
    DATA_SOURCE = "DataSource"   # 数据源（如 https://api.okx.com）


class RelationType(str, Enum):
    """关系类型枚举。方向语义：source -> target。"""

    DEPENDS_ON = "DEPENDS_ON"            # A 依赖 B（A -> B）
    IMPLEMENTS = "IMPLEMENTS"            # A 实现 B（文件/概念 -> 模块）
    USES_ALGORITHM = "USES_ALGORITHM"    # A 使用算法 B（模块/概念 -> 算法）
    INJECTS_INTO = "INJECTS_INTO"        # A 注入到 B（数据源/引擎 -> 模块）
    CONFIGURED_BY = "CONFIGURED_BY"      # A 由 B 配置（参数 -> 模块/概念）
    FEEDS_DATA = "FEEDS_DATA"            # A 向 B 供给数据（数据源 -> 模块）
    RELATES_TO = "RELATES_TO"            # 泛化关联（兜底关系）


# === 每种节点类型的属性定义（用于校验/文档/后续映射图数据库） ===
# 必备属性：name（显示名）、source_files（来源文件列表）
NODE_PROPS: dict[str, list[str]] = {
    NodeType.MODULE.value: [
        "name",            # 模块名（如 11-易经推理系统）
        "source_files",    # 出现该模块的文件列表
        "domain",          # 所属域（如 1-TRADING）
    ],
    NodeType.CONCEPT.value: [
        "name",            # 概念名（如 二元矛盾推理模型）
        "source_files",
        "domain",
    ],
    NodeType.ALGORITHM.value: [
        "name",            # 算法标签（如 kalman）
        "source_files",
    ],
    NodeType.FILE.value: [
        "name",            # 文件路径（如 polling_trader.py）
        "source_files",    # 引用该文件的来源文件
        "extension",       # 扩展名（py / md）
    ],
    NodeType.STRATEGY.value: [
        "name",            # 策略名（如 V9-马丁基线）
        "source_files",
        "domain",
    ],
    NodeType.PARAMETER.value: [
        "name",            # 参数名（如 θ_match*）
        "value",           # 参数值（字符串保留原样，如 0.71 / 3）
        "source_files",
        "domain",
    ],
    NodeType.DATA_SOURCE.value: [
        "name",            # 数据源 URL
        "source_files",
        "domain",
    ],
}


def node_id(node_type: NodeType, name: str) -> str:
    """构造节点唯一标识：'{类型}:{名称}'，用于跨文件去重。"""
    return f"{node_type.value}:{name}"


__all__ = [
    "NodeType",
    "RelationType",
    "NODE_PROPS",
    "node_id",
    "DEFAULT_GRAPH_PATH",
    "GRAPH_DB_DIR",
]
