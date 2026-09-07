# -*- coding: utf-8 -*-
"""知识图谱层（阶段2）：实体关系抽取、NetworkX 图谱构建与检索。

图引擎使用 NetworkX（纯 Python，无外部服务依赖）。
接口设计兼容后续替换为 Neo4j：节点/关系类型以枚举字符串标识，
节点属性扁平存储，便于映射到图数据库的 label 与 property。
"""

from . import schema
from .schema import NodeType, RelationType, NODE_PROPS, node_id, DEFAULT_GRAPH_PATH
from .entity_extractor import extract_entities
from .build_graph import build_graph
from .graph_search import graph_search

__all__ = [
    "schema",
    "NodeType",
    "RelationType",
    "NODE_PROPS",
    "node_id",
    "DEFAULT_GRAPH_PATH",
    "extract_entities",
    "build_graph",
    "graph_search",
]
