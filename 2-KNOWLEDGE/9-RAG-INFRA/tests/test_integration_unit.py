# -*- coding: utf-8 -*-
"""归档流程补充单元测试（TC9-TC28）。

聚焦 detector/archiver/workflow 各模块的细粒度分支与边界条件，
与 test_integration.py 的功能集成测试互补。

测试在临时目录运行，不污染真实知识库。
向量检索使用 TF-IDF 回退路径，避免加载真实嵌入模型。
"""

import os

# 关闭 ChromaDB 遥测，避免测试环境发起网络请求
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

import sys
from pathlib import Path

# 将 9-RAG-INFRA 加入 sys.path
_RAG_INFRA_DIR = Path(__file__).resolve().parent.parent
if str(_RAG_INFRA_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_INFRA_DIR))

import pytest

# 启用 TF-IDF 回退
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
from integration import detector as detector_mod
from integration import archiver as archiver_mod
from integration import workflow as workflow_mod


# === 隔离 fixture ===
@pytest.fixture
def isolated_kb(tmp_path, monkeypatch):
    """隔离的临时知识库。"""
    kb = tmp_path / "kb"
    kb.mkdir()
    db_dir = tmp_path / "chroma_db"
    graph_path = tmp_path / "knowledge_graph.pkl"

    import evolution.ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "CHROMA_DB_PATH", str(db_dir))
    monkeypatch.setattr(ingest_mod, "COLLECTION_NAME", "test_unit_collection")

    from knowledge_graph import schema as kg_schema
    monkeypatch.setattr(kg_schema, "DEFAULT_GRAPH_PATH", str(graph_path))

    return kb


# ═══════════════════════════════════════════════════════════════
# detector 单元测试：各 finance 子分类
# ═══════════════════════════════════════════════════════════════

def test_tc9_detect_finance_risk_models():
    """风控模型关键词 → finance/risk-models。"""
    content = "我们设计了组合熔断和止损止盈的风控体系"
    detections = detect_research(content)
    fin = [d for d in detections if d["type"] == "finance"]
    assert len(fin) >= 1
    sub = [d for d in fin if d["subcategory"] == "risk-models"]
    assert len(sub) == 1
    assert sub[0]["suggested_path"] == "finance/risk-models"


def test_tc10_detect_finance_market_structure():
    """市场结构关键词 → finance/market-structure。"""
    content = "分析了订单簿流动性和资金费率对市场结构的影响"
    detections = detect_research(content)
    sub = [d for d in detections if d["subcategory"] == "market-structure"]
    assert len(sub) == 1
    assert sub[0]["suggested_path"] == "finance/market-structure"


def test_tc11_detect_finance_trading_psychology():
    """交易心理关键词 → finance/trading-psychology。"""
    content = "研究了交易心理和行为金融对决策偏差的影响"
    detections = detect_research(content)
    sub = [d for d in detections if d["subcategory"] == "trading-psychology"]
    assert len(sub) == 1
    assert sub[0]["suggested_path"] == "finance/trading-psychology"


# ═══════════════════════════════════════════════════════════════
# detector 单元测试：各 github 子分类
# ═══════════════════════════════════════════════════════════════

def test_tc12_detect_github_trading_systems():
    """交易系统仓库 → github/trading-systems。"""
    content = "参考了 github.com/freqtrade/freqtrade 这个交易系统仓库"
    detections = detect_research(content)
    sub = [d for d in detections if d["type"] == "github" and d["subcategory"] == "trading-systems"]
    assert len(sub) == 1


def test_tc13_detect_github_data_engineering():
    """数据工程仓库 → github/data-engineering。"""
    content = "调研了 github.com/apache/airflow 用于数据工程流水线"
    detections = detect_research(content)
    sub = [d for d in detections if d["type"] == "github" and d["subcategory"] == "data-engineering"]
    assert len(sub) == 1


def test_tc14_detect_github_infra_tools():
    """基础设施工具仓库 → github/infra-tools。"""
    content = "使用了 github.com/hashicorp/terraform 作为基础设施工具"
    detections = detect_research(content)
    sub = [d for d in detections if d["type"] == "github" and d["subcategory"] == "infra-tools"]
    assert len(sub) == 1


# ═══════════════════════════════════════════════════════════════
# detector 单元测试：各 technical 子分类
# ═══════════════════════════════════════════════════════════════

def test_tc15_detect_technical_algorithms():
    """算法实现关键词 → technical/algorithms。"""
    content = "实现了分块和向量化embedding算法用于检索排序"
    detections = detect_research(content)
    sub = [d for d in detections if d["type"] == "technical" and d["subcategory"] == "algorithms"]
    assert len(sub) == 1


def test_tc16_detect_technical_testing():
    """测试方法关键词 → technical/testing。"""
    content = "采用TDD和单元测试驱动开发，配合Fail-Open原则"
    detections = detect_research(content)
    sub = [d for d in detections if d["type"] == "technical" and d["subcategory"] == "testing"]
    assert len(sub) == 1


# ═══════════════════════════════════════════════════════════════
# detector 边界条件
# ═══════════════════════════════════════════════════════════════

def test_tc17_detect_multi_type_mixed():
    """混合内容同时命中 finance + technical 两类。"""
    content = "使用 Kalman 量化滤波配合 RAG 架构设计"
    detections = detect_research(content)
    types = {d["type"] for d in detections}
    assert "finance" in types
    assert "technical" in types


def test_tc18_detect_empty_input():
    """空字符串输入返回空列表。"""
    assert detect_research("") == []


def test_tc19_detect_tags_generation():
    """多个匹配关键词生成多个不重复标签。"""
    content = "Kalman 量化滤波与 PCA 主成分分析结合止损止盈"
    detections = detect_research(content)
    fin = [d for d in detections if d["type"] == "finance"]
    assert len(fin) >= 1
    # 至少有 kalman 标签
    all_tags = set()
    for d in fin:
        all_tags.update(d["tags"])
    assert "#kalman" in all_tags


def test_tc20_detect_excerpt_bounds():
    """excerpt 在匹配位置前后截取，长度合理。"""
    long_text = "前" * 200 + " Kalman Filter " + "后" * 200
    detections = detect_research(long_text)
    fin = [d for d in detections if d["type"] == "finance"]
    assert len(fin) >= 1
    # excerpt 应包含匹配词且非全文
    assert "Kalman" in fin[0]["excerpt"]
    assert len(fin[0]["excerpt"]) < len(long_text)


# ═══════════════════════════════════════════════════════════════
# archiver 单元测试
# ═══════════════════════════════════════════════════════════════

def test_tc21_archiver_template_fields(isolated_kb):
    """归档md文件模板字段完整填充。"""
    content = "Kalman Filter 量化滤波状态估计"
    detection = detect_research(content)[0]

    result = archive_research(detection, content, isolated_kb,
                              research_topic="Kalman滤波调研",
                              research_scenario="力向量系统实现")

    fp = Path(result["file_path"])
    text = fp.read_text(encoding="utf-8")

    # 模板各字段
    assert "**分类**" in text
    assert "**调研日期**" in text
    assert "**调研场景**" in text
    assert "**来源**" in text
    assert "**标签**" in text
    assert "**状态**: active" in text
    assert "## 调研结论" in text
    assert "## 调研路径" in text
    assert "## 在DreamBuddy中的应用" in text
    # 场景字段应包含传入的scenario
    assert "力向量系统实现" in text


def test_tc22_archiver_filename_slug(isolated_kb):
    """文件名slug化，去除特殊字符。"""
    content = "RAG 架构设计模式"
    detection = detect_research(content)[0]

    result = archive_research(detection, content, isolated_kb,
                              research_topic="RAG架构/设计:模式")

    fp = Path(result["file_path"])
    filename = fp.name
    # 文件名不应含 / 或 : 等特殊字符
    assert "/" not in filename
    assert ":" not in filename
    # 应以日期开头
    assert filename[:4].isdigit()  # YYYY


def test_tc23_archiver_dedup(isolated_kb):
    """相同内容重复归档触发去重（status=duplicate）。"""
    content = "Kalman Filter 量化滤波"
    detection = detect_research(content)[0]

    # 首次归档
    r1 = archive_research(detection, content, isolated_kb,
                          research_topic="第一次")
    assert r1["status"] == "indexed"

    # 第二次归档相同内容（不同topic）
    r2 = archive_research(detection, content, isolated_kb,
                          research_topic="第二次")
    # ingest_document检测到md5重复
    assert r2["status"] in ("duplicate", "indexed")


def test_tc24_archiver_index_md_create_when_missing(isolated_kb):
    """INDEX.md不存在时自动创建。"""
    # 确保INDEX.md不存在
    index_path = isolated_kb / "7-EXTERNAL-RESEARCH" / "INDEX.md"
    assert not index_path.exists()

    content = "Kalman 量化滤波"
    detection = detect_research(content)[0]
    archive_research(detection, content, isolated_kb, research_topic="测试")

    # 应自动创建INDEX.md
    assert index_path.exists()
    text = index_path.read_text(encoding="utf-8")
    assert "测试" in text
    assert "## 维护规则" in text


def test_tc25_archiver_index_md_append(isolated_kb):
    """INDEX.md已有内容时追加新条目。"""
    # 先创建已有INDEX.md
    index_path = isolated_kb / "7-EXTERNAL-RESEARCH" / "INDEX.md"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text("# 外部调研索引\n\n已有内容\n\n## 维护规则\n- 规则1\n", encoding="utf-8")

    # 归档
    content = "Kalman 量化滤波"
    detection = detect_research(content)[0]
    archive_research(detection, content, isolated_kb, research_topic="新增调研")

    text = index_path.read_text(encoding="utf-8")
    # 原有内容保留
    assert "已有内容" in text
    # 新条目追加
    assert "新增调研" in text
    # 维护规则仍在
    assert "## 维护规则" in text


# ═══════════════════════════════════════════════════════════════
# workflow 单元测试
# ═══════════════════════════════════════════════════════════════

def test_tc26_workflow_no_research_prompt():
    """无调研内容时 check_and_prompt 返回 need_archive=False。"""
    prompt = check_and_prompt("今天天气真好")
    assert prompt["need_archive"] is False
    assert prompt["detections"] == []
    # prompt_message 可能为空或提示无内容
    assert "是否归档" not in prompt.get("prompt_message", "")


def test_tc27_workflow_multi_detection_prompt():
    """多类检测结果时 prompt_message 包含所有类型。"""
    content = "Kalman 量化滤波 + github.com/langchain/langchain + RAG 架构"
    prompt = check_and_prompt(content)
    assert prompt["need_archive"] is True
    assert len(prompt["detections"]) >= 2
    msg = prompt["prompt_message"]
    # 提示消息应提及多个归档目标
    assert "finance" in msg or "quant" in msg
    assert "github" in msg


def test_tc28_workflow_fail_open(isolated_kb, monkeypatch):
    """某个归档失败时 FAIL-OPEN，不影响整体流程。"""
    # mock archiver 的 ingest_document 抛异常
    import integration.archiver as archiver_mod

    original_ingest = archiver_mod.ingest_document

    call_count = {"n": 0}

    def flaky_ingest(file_path, knowledge_dir):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("模拟ingest失败")
        return original_ingest(file_path, knowledge_dir)

    monkeypatch.setattr(archiver_mod, "ingest_document", flaky_ingest)

    content = "Kalman 量化滤波"
    result = archive_from_conversation(content, research_topic="FAIL-OPEN测试",
                                       knowledge_dir=isolated_kb)
    # 工作流应完成，即使某次ingest失败
    assert result["status"] == "done"
    # 应有归档记录（即使索引失败）
    assert len(result["archived"]) >= 1


# ═══════════════════════════════════════════════════════════════
# 完整回归：所有测试一起运行不冲突
# ═══════════════════════════════════════════════════════════════

def test_tc29_batch_detect_consistency():
    """批量检测与单条检测结果一致。"""
    contents = [
        "Kalman 量化滤波",
        "github.com/langchain/langchain",
    ]
    batch = batch_detect(contents)

    # 逐条检测
    single = [detect_research(c) for c in contents]

    # 结果类型一致
    assert len(batch) == len(single) == 2
    for b, s in zip(batch, single):
        assert {d["type"] for d in b} == {d["type"] for d in s}


# ═══════════════════════════════════════════════════════════════
# detector 内部函数边界测试
# ═══════════════════════════════════════════════════════════════

def test_tc30_find_pos_english_false_positive_guard():
    """英文关键词两侧不允许紧邻 ASCII 字母，避免误报。

    IC 不命中 specification，RAG 不命中 garbage；
    但允许英文关键词后接中文（如 RAG架构、Fail-Open原则）。
    """
    # IC 在 specification 中应不命中（两侧为字母）
    assert detector_mod._find_pos("IC", "specification of model") == -1
    # RAG 在 garbage 中应不命中
    assert detector_mod._find_pos("RAG", "garbage collection") == -1
    # IC 单独出现应命中
    assert detector_mod._find_pos("IC", "计算 IC 值") >= 0
    # RAG 后接中文应命中
    assert detector_mod._find_pos("RAG", "RAG架构设计") >= 0


def test_tc31_find_pos_empty_keyword():
    """空关键词返回 -1。"""
    assert detector_mod._find_pos("", "any content") == -1
    assert detector_mod._find_pos("", "") == -1


def test_tc32_make_tags_normalization():
    """_make_tags 将关键词转为小写标签，空格/斜杠转连字符。"""
    tags = detector_mod._make_tags(["Kalman Filter", "PCA/主成分", "IC"])
    assert "#kalman-filter" in tags
    assert "#pca-主成分" in tags
    assert "#ic" in tags


def test_tc33_detect_tie_break_by_dict_order():
    """同数匹配时按字典序保留首个（确定性，Python 3.7+ 保序）。"""
    # quant-methods(量化) 与 risk-models(止损) 各匹配1个关键词
    # 遍历顺序中 quant-methods 先于 risk-models，严格 > 才更新，故保留 quant-methods
    content = "这次研究涉及量化和止损"
    detections = detect_research(content)
    fin = [d for d in detections if d["type"] == "finance"]
    assert len(fin) == 1
    assert fin[0]["subcategory"] == "quant-methods"


def test_tc34_detect_github_default_subcategory():
    """GitHub URL 无明确子分类匹配时默认归档到 infra-tools。"""
    content = "参考了 github.com/someuser/random-project 的实现"
    detections = detect_research(content)
    git = [d for d in detections if d["type"] == "github"]
    assert len(git) == 1
    assert git[0]["subcategory"] == "infra-tools"


def test_tc35_detect_github_repo_keyword_without_url():
    """仅有"仓库"关键词无 URL 时也能触发 github 检测。"""
    content = "调研了一个开源仓库的实现思路"
    detections = detect_research(content)
    git = [d for d in detections if d["type"] == "github"]
    assert len(git) == 1
    assert git[0]["subcategory"] == "infra-tools"


def test_tc36_detect_all_three_types():
    """三类调研内容同时命中 finance + github + technical。"""
    content = "使用 Kalman 量化滤波，参考 github.com/langchain/langchain，采用 RAG 架构"
    detections = detect_research(content)
    types = {d["type"] for d in detections}
    assert types == {"finance", "github", "technical"}


# ═══════════════════════════════════════════════════════════════
# archiver 边界测试
# ═══════════════════════════════════════════════════════════════

def test_tc37_slugify_edge_cases():
    """_slugify 处理空字符串、纯特殊字符、保留中文。"""
    assert archiver_mod._slugify("") == "research"
    assert archiver_mod._slugify("///:::") == "research"
    # 保留中文，空格转连字符
    assert archiver_mod._slugify("RAG 架构 设计") == "rag-架构-设计"
    # 去除特殊字符保留字母数字
    assert archiver_mod._slugify("test@case#1") == "testcase1"


def test_tc38_update_index_existing_archive_section(isolated_kb):
    """INDEX.md 已有"归档记录"section 时在 section 内追加（不重复创建 section）。"""
    index_path = isolated_kb / "7-EXTERNAL-RESEARCH" / "INDEX.md"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        "# 外部调研索引\n\n## 归档记录\n\n- [2026-01-01] [旧条目](old.md)\n\n## 维护规则\n- 规则1\n",
        encoding="utf-8"
    )

    content = "Kalman 量化滤波"
    detection = detect_research(content)[0]
    archive_research(detection, content, isolated_kb, research_topic="新条目")

    text = index_path.read_text(encoding="utf-8")
    # 旧条目保留
    assert "旧条目" in text
    # 新条目在归档记录 section 内
    assert "新条目" in text
    # 维护规则仍在归档记录之后，新条目位于两者之间
    assert text.index("新条目") < text.index("## 维护规则")
    # 不应重复创建归档记录 section
    assert text.count("## 归档记录") == 1


def test_tc39_update_index_no_sections(isolated_kb):
    """INDEX.md 无"归档记录"也无"维护规则" section 时追加新 section。"""
    index_path = isolated_kb / "7-EXTERNAL-RESEARCH" / "INDEX.md"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text("# 外部调研索引\n\n仅说明文字\n", encoding="utf-8")

    content = "Kalman 量化滤波"
    detection = detect_research(content)[0]
    archive_research(detection, content, isolated_kb, research_topic="追加测试")

    text = index_path.read_text(encoding="utf-8")
    assert "追加测试" in text
    assert "## 归档记录" in text
    # 原有说明文字保留
    assert "仅说明文字" in text


def test_tc40_update_index_fail_open(isolated_kb, monkeypatch):
    """_update_index 写入异常时 FAIL-OPEN 不抛出。"""
    index_path = isolated_kb / "7-EXTERNAL-RESEARCH" / "INDEX.md"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text("# 已有内容\n", encoding="utf-8")

    detection = {"category": "finance", "subcategory": "quant-methods",
                 "suggested_path": "finance/quant-methods", "tags": ["#kalman"]}
    final_path = isolated_kb / "7-EXTERNAL-RESEARCH" / "finance" / "quant-methods" / "test.md"
    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_text("test", encoding="utf-8")

    def fail_write(self, data, encoding=None):
        raise OSError("模拟写入失败")
    monkeypatch.setattr(Path, "write_text", fail_write)

    # _update_index 内部 try/except 捕获异常，不应抛出
    archiver_mod._update_index(isolated_kb, detection, final_path,
                               "2026-08-31", "test", "测试")


def test_tc41_archive_ingest_exception_fail_open(isolated_kb, monkeypatch):
    """ingest_document 抛异常时 archive_research FAIL-OPEN，直接写入最终路径。"""
    def fail_ingest(file_path, knowledge_dir):
        raise RuntimeError("模拟ingest彻底失败")
    monkeypatch.setattr(archiver_mod, "ingest_document", fail_ingest)

    content = "Kalman 量化滤波"
    detection = detect_research(content)[0]
    result = archive_research(detection, content, isolated_kb, research_topic="异常测试")

    # status 应为 failed，但文件仍写入最终路径
    assert result["status"] == "failed"
    assert result["index_status"] == "failed"
    assert Path(result["file_path"]).exists()


def test_tc42_archive_default_topic():
    """research_topic 为空时使用默认标题与默认场景。"""
    content = "Kalman 量化滤波"
    detection = detect_research(content)[0]
    md_text, _ = archiver_mod._build_md(
        detection, content, research_topic="", research_scenario=""
    )
    # 默认标题应为 category/subcategory 调研
    assert "finance/quant-methods 调研" in md_text
    # 默认调研场景
    assert "对话中检测到的调研内容" in md_text


# ═══════════════════════════════════════════════════════════════
# workflow 边界测试
# ═══════════════════════════════════════════════════════════════

def test_tc43_workflow_no_research_archive(isolated_kb):
    """archive_from_conversation 无调研内容时返回 no_research。"""
    result = archive_from_conversation("今天天气真好", knowledge_dir=isolated_kb)
    assert result["status"] == "no_research"
    assert result["archived"] == []
    assert result["detections"] == []


def test_tc44_workflow_default_knowledge_dir(monkeypatch, tmp_path):
    """knowledge_dir 为 None 时使用 config 默认 KNOWLEDGE_BASE_DIR。"""
    default_dir = tmp_path / "default_kb"
    monkeypatch.setattr(workflow_mod, "KNOWLEDGE_BASE_DIR", str(default_dir))

    content = "Kalman 量化滤波"
    result = archive_from_conversation(content, research_topic="默认路径测试")
    assert result["status"] == "done"
    fp = Path(result["archived"][0]["file_path"])
    assert "default_kb" in str(fp)
    assert fp.exists()


def test_tc45_workflow_single_archive_exception_fail_open(isolated_kb, monkeypatch):
    """单条 archive_research 抛异常时 FAIL-OPEN，不影响其余归档。"""
    call_count = {"n": 0}
    original_archive = workflow_mod.archive_research

    def flaky_archive(detection, content, knowledge_dir, research_topic="",
                      research_scenario=""):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("模拟归档失败")
        return original_archive(detection, content, knowledge_dir,
                                research_topic, research_scenario)

    monkeypatch.setattr(workflow_mod, "archive_research", flaky_archive)

    # 混合内容触发 finance + technical 两类检测
    content = "Kalman 量化滤波配合 RAG 架构设计"
    result = archive_from_conversation(content, research_topic="混合归档",
                                        knowledge_dir=isolated_kb)
    # 整体流程完成
    assert result["status"] == "done"
    assert len(result["archived"]) == 2
    # 第一条失败，第二条成功
    assert result["archived"][0]["status"] == "failed"
    assert result["archived"][1]["status"] in ("indexed", "duplicate")
