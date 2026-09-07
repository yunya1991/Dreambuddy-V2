# -*- coding: utf-8 -*-
"""RAG 融合引擎与持续进化层测试（TC14-TC20）。

测试在临时目录运行，不依赖真实知识库。
向量检索使用 TF-IDF 回退路径（与 vector_store 测试一致），避免加载真实模型。
"""

import os

# 关闭 ChromaDB 遥测，避免测试环境发起网络请求
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

import sys
from pathlib import Path

# 将 9-RAG-INFRA 加入 sys.path，使各子包可作为顶层包导入
_RAG_INFRA_DIR = Path(__file__).resolve().parent.parent
if str(_RAG_INFRA_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_INFRA_DIR))

import pytest

# 启用 TF-IDF 回退（与向量层测试一致，避免加载 bge 模型）
from vector_store.embedder import _embedder
_embedder._use_tfidf_fallback = True
_embedder._model = None

from vector_store import build_index
from knowledge_graph import build_graph
from rag_engine import (
    hybrid_search,
    generate,
    keyword_search,
    build_keyword_index,
    rerank,
)
from evolution import ingest_document, annotate_chunk, record_feedback


# === 测试用 Markdown 固件（3 文件，2 域） ===
FIXTURES = {
    "1-TRADING/BCRM2推理引擎.md": """# BCRM2.0 推理引擎

> **来源：** 11-易经推理系统

## 核心架构

BCRM2.0 是**二元矛盾推理模型**，通过逐层推理识别市场矛盾，最终输出交易信号。

## 力向量计算

**力向量**通过多空力量对比计算，多头力量减去空头力量得到合力方向。
力向量用于判断市场的主导趋势方向，是 BCRM 推理的核心指标。

## 关键参数

| 参数 | 值 | 说明 |
|------|-----|------|
| L1模型数 | 344 | 二元矛盾推理单元 |
| CBR θ_match | 0.71 | 相似度阈值 |
""",
    "1-TRADING/V9马丁基线.md": """# V9 马丁基线策略

> **来源：** 13-通用风控模块

## 策略概述

V9马丁基线策略核心参数。

## 数据源

行情数据来自 https://api.okx.com 实时推送。
""",
    "2-TECHNICAL/数据管道.md": """# 数据管道

## 数据源

行情数据来自交易所 WebSocket 接口 https://stream.okx.com 。

## 清洗规则

异常K线剔除脏数据，按时间对齐多周期序列。
""",
}


# === 会话级 fixture ===

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
def db_dir(tmp_path_factory):
    """会话级临时 ChromaDB 目录。"""
    return tmp_path_factory.mktemp("chromadb")


@pytest.fixture(scope="session")
def graph_path(tmp_path_factory):
    """会话级临时图谱持久化路径。"""
    return tmp_path_factory.mktemp("graph_db") / "knowledge_graph.pkl"


@pytest.fixture(scope="session")
def index_path(tmp_path_factory):
    """会话级临时 Whoosh 关键词索引目录。"""
    return tmp_path_factory.mktemp("keyword_index")


@pytest.fixture(scope="session")
def built_indexes(kb_dir, db_dir, graph_path, index_path):
    """会话级：构建向量、图谱、关键词三路索引。"""
    build_index(kb_dir, db_path=str(db_dir))
    build_graph(kb_dir, graph_path=graph_path)
    build_keyword_index(kb_dir, index_path=index_path)
    return {
        "kb_dir": kb_dir,
        "db_dir": str(db_dir),
        "graph_path": graph_path,
        "index_path": index_path,
    }


# ---------- TC14：混合检索（三路召回） ----------
def test_tc14_hybrid_search(built_indexes):
    """混合检索'力向量如何计算'：三路召回，top-5 非空。"""
    results = hybrid_search(
        "力向量如何计算",
        top_k=10,
        db_path=built_indexes["db_dir"],
        index_path=built_indexes["index_path"],
        graph_path=built_indexes["graph_path"],
    )

    # top-5 非空
    assert len(results) > 0, "混合检索应返回非空结果"
    assert len(results[:5]) > 0, "top-5 结果应非空"

    # 每项应有 final_score
    for r in results:
        assert "final_score" in r, "每项应含 final_score"
        assert "content" in r
        assert "source_file" in r

    # 至少有一路召回命中（三路召回验证）
    all_methods = set()
    for r in results:
        all_methods.update(r.get("retrieval_methods", []))
    assert len(all_methods) >= 1, f"至少一路召回应命中: {all_methods}"

    # 结果应按 final_score 降序排列
    scores = [r["final_score"] for r in results]
    assert scores == sorted(scores, reverse=True), "结果应按 final_score 降序"


# ---------- TC15：RAG 生成（有检索结果） ----------
def test_tc15_generate_with_chunks():
    """RAG 生成'BCRM2.0是什么'：answer_prompt 非空，citations 非空。"""
    chunks = [
        {
            "content": "BCRM2.0 是二元矛盾推理模型，通过逐层推理识别市场矛盾，最终输出交易信号。",
            "source_file": "1-TRADING/BCRM2推理引擎.md",
            "heading": "核心架构",
            "domain": "1-TRADING",
            "score": 0.92,
            "final_score": 0.88,
        },
        {
            "content": "力向量通过多空力量对比计算，是 BCRM 推理的核心指标。",
            "source_file": "1-TRADING/BCRM2推理引擎.md",
            "heading": "力向量计算",
            "domain": "1-TRADING",
            "score": 0.85,
            "final_score": 0.80,
        },
    ]

    result = generate("BCRM2.0是什么", chunks)

    assert result["answer_prompt"], "answer_prompt 应非空"
    assert "BCRM2.0是什么" in result["answer_prompt"], "prompt 应包含查询"
    assert len(result["citations"]) == 2, "citations 应有 2 条"
    assert result["citations"][0]["source_file"] == "1-TRADING/BCRM2推理引擎.md"
    assert result["confidence"] > 0, "confidence 应大于 0"
    assert result["raw_chunks"] == chunks, "raw_chunks 应为原始检索结果"


# ---------- TC16：RAG 生成（空检索结果） ----------
def test_tc16_generate_empty():
    """RAG 生成空检索结果：返回'知识库中未找到相关信息'。"""
    result = generate("任意问题", [])

    assert result["answer_prompt"] == "知识库中未找到相关信息"
    assert result["citations"] == []
    assert result["confidence"] == 0.0
    assert result["raw_chunks"] == []


# ---------- TC17：正反馈 ----------
def test_tc17_positive_feedback(tmp_path):
    """正反馈：feedback_weight +0.1。"""
    graph_path = tmp_path / "test_graph.pkl"

    result = record_feedback(
        "1-TRADING/BCRM2推理引擎.md",
        "核心架构",
        is_positive=True,
        graph_path=graph_path,
    )

    assert result["source_file"] == "1-TRADING/BCRM2推理引擎.md"
    assert result["heading"] == "核心架构"
    assert abs(result["new_weight"] - 0.1) < 1e-9, \
        f"正反馈后权重应为 0.1，实际: {result['new_weight']}"

    # 验证持久化
    weights_file = tmp_path / "feedback_weights.json"
    assert weights_file.exists(), "权重文件应已持久化"


# ---------- TC18：负反馈 ----------
def test_tc18_negative_feedback(tmp_path):
    """负反馈：feedback_weight -0.1。"""
    graph_path = tmp_path / "test_graph.pkl"

    result = record_feedback(
        "1-TRADING/BCRM2推理引擎.md",
        "力向量计算",
        is_positive=False,
        graph_path=graph_path,
    )

    assert result["source_file"] == "1-TRADING/BCRM2推理引擎.md"
    assert result["heading"] == "力向量计算"
    assert abs(result["new_weight"] - (-0.1)) < 1e-9, \
        f"负反馈后权重应为 -0.1，实际: {result['new_weight']}"


# ---------- TC19：文档采集 ----------
def test_tc19_ingest_document(tmp_path, monkeypatch):
    """ingest 文档：自动索引 + 节点抽取。"""
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()

    # 用临时路径替换默认索引路径，避免污染真实数据
    db_path = str(tmp_path / "chromadb")
    import evolution.ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "CHROMA_DB_PATH", db_path)

    import knowledge_graph.schema as schema_mod
    monkeypatch.setattr(schema_mod, "DEFAULT_GRAPH_PATH", tmp_path / "graph.pkl")

    # 创建测试文档
    doc_path = tmp_path / "test_doc.md"
    doc_path.write_text(
        "# 测试文档\n\n"
        "> **来源：** 11-易经推理系统\n\n"
        "## 核心概念\n\n"
        "**力向量**用于计算市场方向。关键参数 θ_match = 0.71。\n\n"
        "## 数据源\n\n"
        "行情来自 https://api.okx.com 实时推送。\n",
        encoding="utf-8",
    )

    result = ingest_document(doc_path, kb_dir)

    assert result["status"] == "indexed", f"采集状态应为 indexed: {result}"
    assert result["file_hash"], "应有文件哈希"
    assert result["chunks_indexed"] > 0, "应有分块被索引"
    assert result["nodes_extracted"] > 0, "应抽取到图谱节点"

    # 验证文件已写入知识库
    assert (kb_dir / "test_doc.md").exists(), "文档应已写入知识库"


# ---------- TC20：自动标注 ----------
def test_tc20_annotate_chunk():
    """annotate 标注：域分类 + 标签 + 质量评分。"""
    chunk = {
        "content": "BCRM2.0 是二元矛盾推理模型，通过逐层推理识别市场矛盾。"
                    "关键参数 θ_match = 0.71，L1模型共344个推理单元。"
                    " #trading #策略",
        "source_file": "1-TRADING/BCRM2推理引擎.md",
        "heading": "核心架构",
        "domain": "",
    }

    annotated = annotate_chunk(chunk)

    assert "annotation" in annotated, "应包含 annotation 字段"
    ann = annotated["annotation"]

    # 域分类
    assert ann["domain"] == "1-TRADING", f"域应为 1-TRADING: {ann['domain']}"

    # 标签抽取
    tag_lowers = [t.lower() for t in ann["tags"]]
    assert "trading" in tag_lowers, f"应包含 trading 标签: {ann['tags']}"
    assert "策略" in ann["tags"], f"应包含 策略 标签: {ann['tags']}"

    # 质量评分
    q = ann["quality"]
    assert "completeness" in q, "应含完整性评分"
    assert "accuracy" in q, "应含准确性评分"
    assert "timeliness" in q, "应含时效性评分"
    assert "overall" in q, "应含综合评分"

    # 各分项应在 [0, 1] 范围内
    for key in ("completeness", "accuracy", "timeliness", "overall"):
        assert 0.0 <= q[key] <= 1.0, f"{key} 应在 [0,1]: {q[key]}"

    # overall 应为三项均值
    expected_overall = round(
        (q["completeness"] + q["accuracy"] + q["timeliness"]) / 3, 4
    )
    assert abs(q["overall"] - expected_overall) < 1e-9, \
        f"overall 应为三项均值: {q['overall']} vs {expected_overall}"
