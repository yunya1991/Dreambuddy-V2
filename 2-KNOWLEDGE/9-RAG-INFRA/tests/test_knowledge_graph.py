# -*- coding: utf-8 -*-
"""知识图谱层测试（TC9-TC13）。

测试在临时目录运行，不污染真实知识库。
实体抽取为确定性规则匹配，断言可复现。
"""

import os

# 关闭 ChromaDB 遥测（与向量层测试环境一致，避免网络请求）
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

import sys
from pathlib import Path

# 将 9-RAG-INFRA 加入 sys.path，使 knowledge_graph 可作为包导入
_RAG_INFRA_DIR = Path(__file__).resolve().parent.parent
if str(_RAG_INFRA_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_INFRA_DIR))

import pytest

from knowledge_graph import build_graph, graph_search, extract_entities
from knowledge_graph.schema import NodeType


# === 测试用 Markdown 固件（3 文件，2 域，仿真实知识库结构） ===
FIXTURES = {
    "1-TRADING/BCRM2推理引擎.md": """# BCRM2.0 推理引擎

> **来源：** 11-易经推理系统/polling_trader.py + bcrm2/ 目录
> **定位：** 二元矛盾推理模型，11-易经推理系统的策略层核心

## 核心架构

BCRM2.0 是**二元矛盾推理模型**，通过逐层推理识别市场矛盾，最终输出交易信号。

## 关键参数

| 参数 | 值 | 说明 |
|------|-----|------|
| L1模型数 | 344 | 二元矛盾推理单元 |
| L2模型数 | 278 | 融合模型 |
| CBR θ_match | 0.71 | 相似度阈值 |
| CBR top-k | 3 | 检索案例数 |

## 与其他模块的关系

| 模块 | 关系 |
|------|------|
| 五计庙算 | 战略层约束输入 |
| CBR案例检索 | 案例权重融合 |
| 通用风控 | 信号门禁过滤 |
""",
    "1-TRADING/V9-马丁基线.md": """# V9 马丁基线策略

> **来源：** 13-通用风控模块/martin.py

## 策略概述

V9马丁基线策略核心参数。

## 关键参数

| 参数 | 值 | 说明 |
|------|-----|------|
| max_layers | 5 | 最大加仓层数 |

## 数据源

行情数据来自 https://api.okx.com 实时推送。
""",
    "2-TECHNICAL/数据管道.md": """# 数据管道

> **来源：** 9-数据采集/data_pipeline.py

## 数据源

行情数据来自交易所 WebSocket 接口 https://stream.okx.com 。

## 清洗规则

异常K线剔除脏数据，按时间对齐多周期序列。
""",
}


@pytest.fixture(scope="session")
def kb_dir(tmp_path_factory):
    """会话级临时知识库目录，写入固件 Markdown。"""
    d = tmp_path_factory.mktemp("kb")
    for rel, content in FIXTURES.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return d


@pytest.fixture(scope="session")
def graph_path(tmp_path_factory):
    """会话级临时图谱持久化路径。"""
    return tmp_path_factory.mktemp("graph_db") / "knowledge_graph.pkl"


@pytest.fixture(scope="session")
def built_graph(kb_dir, graph_path):
    """会话级：构建一次图谱，供后续用例复用。"""
    return build_graph(kb_dir, graph_path=graph_path)


# ---------- TC9：抽取实体 ----------
def test_tc9_extract_entities():
    text = FIXTURES["1-TRADING/BCRM2推理引擎.md"]
    result = extract_entities(text, "1-TRADING/BCRM2推理引擎.md", "1-TRADING")
    types = {n["type"] for n in result["nodes"]}

    # 应抽出 Module / Concept / Parameter 三类节点
    assert NodeType.MODULE.value in types, types
    assert NodeType.CONCEPT.value in types, types
    assert NodeType.PARAMETER.value in types, types

    names = {n["name"] for n in result["nodes"]}
    # 主模块 11-易经推理系统
    assert "11-易经推理系统" in names, names
    # 概念节点（H1 标题与加粗文本）
    assert "BCRM2.0 推理引擎" in names, names
    assert "二元矛盾推理模型" in names, names
    # 参数节点（来自 Markdown 表格）
    params = {n["name"] for n in result["nodes"] if n["type"] == NodeType.PARAMETER.value}
    assert "L1模型数" in params, params
    assert "CBR θ_match" in params, params
    # 参数值应保留
    theta = [n for n in result["nodes"] if n["name"] == "CBR θ_match"][0]
    assert theta["value"] == "0.71", theta
    # 依赖模块（来自"与其他模块的关系"表）应作为 Module 节点
    assert "五计庙算" in names, names
    assert "CBR案例检索" in names, names


# ---------- TC10：构建图谱 ----------
def test_tc10_build_graph(built_graph):
    stats = built_graph
    assert stats["total_nodes"] >= 10, stats
    assert stats["total_edges"] >= 5, stats
    assert stats["failed_files"] == 0, stats
    assert stats["duration_sec"] >= 0
    # 节点/边按类型分布应有内容
    assert stats["node_by_type"], stats["node_by_type"]
    assert stats["edge_by_type"], stats["edge_by_type"]
    # 图谱文件已持久化
    assert Path(stats["graph_path"]).exists()


# ---------- TC11：图谱检索（依赖模块 + 实现概念） ----------
def test_tc11_graph_search(built_graph, graph_path):
    r = graph_search("11-易经推理系统", hops=2, graph_path=graph_path)
    assert r["center_node"] is not None, "中心实体应存在"
    assert r["center_node"]["name"] == "11-易经推理系统"

    neighbor_names = {nb["name"] for nb in r["neighbors"]}
    # 依赖模块：通过 DEPENDS_ON 关系可达
    dep_modules = {
        nb["name"] for nb in r["neighbors"] if nb["relation"] == "DEPENDS_ON"
    }
    assert dep_modules, f"应返回依赖模块: {neighbor_names}"
    assert {"五计庙算", "CBR案例检索", "通用风控"} <= dep_modules, dep_modules

    # 实现概念：通过 IMPLEMENTS 关系可达的概念节点
    impl_concepts = {
        nb["name"] for nb in r["neighbors"]
        if nb["relation"] == "IMPLEMENTS" and nb["type"] == NodeType.CONCEPT.value
    }
    assert impl_concepts, f"应返回实现概念: {neighbor_names}"
    assert "BCRM2.0 推理引擎" in impl_concepts, impl_concepts


# ---------- TC12：多跳检索 ----------
def test_tc12_multihop_search(built_graph, graph_path):
    r1 = graph_search("11-易经推理系统", hops=1, graph_path=graph_path)
    r2 = graph_search("11-易经推理系统", hops=2, graph_path=graph_path)

    names_1 = {nb["name"] for nb in r1["neighbors"]}
    names_2 = {nb["name"] for nb in r2["neighbors"]}

    # hops=2 应包含 hops=1 之外间接关联实体
    extra = names_2 - names_1
    assert extra, f"hops=2 应返回更多间接关联: {names_2}"

    # 参数节点不直接连到模块，需经概念中转（2 跳）才可达
    params_hop1 = {
        nb["name"] for nb in r1["neighbors"]
        if nb["type"] == NodeType.PARAMETER.value
    }
    params_hop2 = {
        nb["name"] for nb in r2["neighbors"]
        if nb["type"] == NodeType.PARAMETER.value
    }
    assert not params_hop1, f"hops=1 不应直达参数: {params_hop1}"
    assert params_hop2, f"hops=2 应经概念中转到达参数: {params_hop2}"

    # paths 应包含长度为 3 的路径（中心->概念->参数）
    assert any(len(p["path"]) == 3 for p in r2["paths"]), [
        len(p["path"]) for p in r2["paths"]
    ]


# ---------- TC13：关系过滤 ----------
def test_tc13_relation_filter(built_graph, graph_path):
    r = graph_search(
        "11-易经推理系统", hops=2,
        relation_filter=["DEPENDS_ON"],
        graph_path=graph_path,
    )
    assert r["center_node"] is not None
    rels = {nb["relation"] for nb in r["neighbors"]}
    # 过滤后仅返回 DEPENDS_ON 关系
    assert rels == {"DEPENDS_ON"}, rels
    # 依赖模块应全部命中
    names = {nb["name"] for nb in r["neighbors"]}
    assert {"五计庙算", "CBR案例检索", "通用风控"} <= names, names
    # 不应包含概念节点（IMPLEMENTS 被过滤掉）
    assert not any(
        nb["type"] == NodeType.CONCEPT.value for nb in r["neighbors"]
    ), [nb["name"] for nb in r["neighbors"]]


# ---------- 附加：FAIL-OPEN ----------
def test_failopen_missing_entity_and_graph(graph_path):
    # 不存在的实体 -> 空结果
    r = graph_search("不存在的实体XYZ", hops=2, graph_path=graph_path)
    assert r["center_node"] is None
    assert r["neighbors"] == []
    # 不存在的图谱路径 -> 空结果
    r2 = graph_search("11-易经推理系统", hops=2,
                      graph_path="/tmp/__nonexistent_graph__.pkl")
    assert r2["center_node"] is None
    assert r2["neighbors"] == []
