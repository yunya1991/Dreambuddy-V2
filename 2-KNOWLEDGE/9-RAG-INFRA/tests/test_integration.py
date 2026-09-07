# -*- coding: utf-8 -*-
"""开发流程集成测试（TC1-TC8）。

测试在临时目录运行，不污染真实知识库。
向量检索使用 TF-IDF 回退路径（与 vector_store / rag_engine 测试一致），
避免加载真实嵌入模型。
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

from integration import (
    detect_research,
    archive_research,
    check_and_prompt,
    archive_from_conversation,
    batch_detect,
)


# === 隔离 fixture：临时知识库 + 临时索引/图谱路径 ===

@pytest.fixture
def isolated_kb(tmp_path, monkeypatch):
    """隔离的临时知识库，索引与图谱持久化指向 tmp 目录，避免污染真实库。"""
    kb = tmp_path / "kb"
    kb.mkdir()
    db_dir = tmp_path / "chroma_db"
    graph_path = tmp_path / "knowledge_graph.pkl"

    # ingest_document 顶层导入的 CHROMA_DB_PATH / COLLECTION_NAME 为模块全局，
    # 这里 patch 模块属性，使 build_index 走临时路径
    import evolution.ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "CHROMA_DB_PATH", str(db_dir))
    monkeypatch.setattr(ingest_mod, "COLLECTION_NAME", "test_integration_collection")

    # build_graph 的 DEFAULT_GRAPH_PATH 在函数内通过 from ... import 动态读取，
    # patch 源模块属性即可生效
    from knowledge_graph import schema as kg_schema
    monkeypatch.setattr(kg_schema, "DEFAULT_GRAPH_PATH", str(graph_path))

    return kb


# ---------- TC1：检测金融调研内容 ----------
def test_tc1_detect_finance():
    """包含 Kalman Filter 量化滤波 的文本 → finance/quant-methods。"""
    content = "我们在研究中使用了 Kalman Filter 进行量化滤波，回测效果不错"
    detections = detect_research(content)

    assert len(detections) >= 1
    fin = [d for d in detections if d["type"] == "finance"]
    assert len(fin) == 1

    d = fin[0]
    assert d["category"] == "finance"
    assert d["subcategory"] == "quant-methods"
    assert d["suggested_path"] == "finance/quant-methods"
    assert "Kalman" in d["keywords_matched"]
    assert any(t == "#kalman" for t in d["tags"])
    assert d["excerpt"]  # 摘要非空


# ---------- TC2：检测 GitHub 仓库 ----------
def test_tc2_detect_github():
    """包含 github.com/langchain/langchain 的文本 → github/ml-frameworks。"""
    content = "参考了 github.com/langchain/langchain 这个仓库的实现"
    detections = detect_research(content)

    git = [d for d in detections if d["type"] == "github"]
    assert len(git) == 1

    d = git[0]
    assert d["category"] == "github"
    assert d["subcategory"] == "ml-frameworks"
    assert d["suggested_path"] == "github/ml-frameworks"
    assert "langchain" in d["keywords_matched"]


# ---------- TC3：检测技术方案 ----------
def test_tc3_detect_technical():
    """包含 RAG 架构设计模式 的文本 → technical/architecture。"""
    content = "对比 RAG 架构与设计模式 在微服务中的方案"
    detections = detect_research(content)

    tech = [d for d in detections if d["type"] == "technical"]
    assert len(tech) == 1

    d = tech[0]
    assert d["category"] == "technical"
    assert d["subcategory"] == "architecture"
    assert d["suggested_path"] == "technical/architecture"
    assert "RAG" in d["keywords_matched"]


# ---------- TC4：无调研内容 ----------
def test_tc4_no_research():
    """普通文本 → 空检测结果。"""
    content = "今天天气真好，我们去公园散步吧"
    detections = detect_research(content)
    assert detections == []


# ---------- TC5：归档调研内容 ----------
def test_tc5_archive_research(isolated_kb):
    """调用 archive_research 生成 md 文件并触发 ingest。"""
    content = "Kalman Filter 量化滤波实现，用于状态估计"
    detection = detect_research(content)[0]

    result = archive_research(detection, content, isolated_kb,
                             research_topic="Kalman Filter")

    assert result["status"] in ("indexed", "duplicate")
    fp = Path(result["file_path"])
    assert fp.exists(), "归档 md 文件应存在"
    assert "7-EXTERNAL-RESEARCH" in str(fp)
    assert "finance/quant-methods" in str(fp)
    assert result["chunks_indexed"] > 0, "应触发 ingest 并产生分块"

    # md 文件应含模板字段
    text = fp.read_text(encoding="utf-8")
    assert "**分类**" in text
    assert "**状态**: active" in text


# ---------- TC6：完整工作流 ----------
def test_tc6_workflow(isolated_kb):
    """check_and_prompt 返回 need_archive=True，archive_from_conversation 执行归档。"""
    content = "研究了 Kalman Filter 量化方法，用于趋势估计"

    prompt = check_and_prompt(content)
    assert prompt["need_archive"] is True
    assert len(prompt["detections"]) >= 1
    assert "是否归档" in prompt["prompt_message"]

    result = archive_from_conversation(content, research_topic="Kalman量化研究",
                                      knowledge_dir=isolated_kb)
    assert result["status"] == "done"
    assert len(result["archived"]) >= 1
    assert Path(result["archived"][0]["file_path"]).exists()


# ---------- TC7：批量检测 ----------
def test_tc7_batch_detect():
    """多条内容批量检测，分别命中 finance/github/technical/无。"""
    contents = [
        "使用 Kalman 量化滤波",
        "参考 github.com/langchain/langchain",
        "RAG 架构设计模式",
        "今天天气不错",
    ]
    results = batch_detect(contents)

    assert len(results) == 4
    assert len(results[0]) >= 1
    assert results[0][0]["type"] == "finance"
    assert len(results[1]) >= 1
    assert results[1][0]["type"] == "github"
    assert len(results[2]) >= 1
    assert results[2][0]["type"] == "technical"
    assert results[3] == []


# ---------- TC8：INDEX.md 更新 ----------
def test_tc8_index_update(isolated_kb):
    """归档后 7-EXTERNAL-RESEARCH/INDEX.md 包含新条目。"""
    content = "Kalman Filter 量化滤波方法"
    detection = detect_research(content)[0]

    archive_research(detection, content, isolated_kb,
                    research_topic="Kalman调研")

    index_path = isolated_kb / "7-EXTERNAL-RESEARCH" / "INDEX.md"
    assert index_path.exists(), "INDEX.md 应被创建/更新"

    idx_text = index_path.read_text(encoding="utf-8")
    assert "Kalman调研" in idx_text
    assert "finance/quant-methods" in idx_text
    assert "## 维护规则" in idx_text
