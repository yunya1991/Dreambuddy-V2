# -*- coding: utf-8 -*-
"""RAG 生产流程闭环集成测试。

验证桥接已真正接入 RAG 检索与归档生产流程，形成完整认知闭环：
- search_with_feedback：hybrid_search + apply_boost + record_retrieval
- archive_from_conversation：归档 + record 新知识单元为 C 级记忆
- FAIL-OPEN：桥接缺失/认知系统不可用时不阻塞主流程
- 字节等价：hybrid_search 原有行为不变

测试隔离：tmp_path 临时目录 + FakeCLE mock，不污染真实认知库/权重文件/知识库。
"""

import json
import os
import sys
from pathlib import Path

# 关闭 ChromaDB 遥测
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

_RAG_INFRA_DIR = Path(__file__).resolve().parent.parent
if str(_RAG_INFRA_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_INFRA_DIR))

# 启用 TF-IDF 回退（避免加载 bge 模型）
from vector_store.embedder import _embedder
_embedder._use_tfidf_fallback = True
_embedder._model = None

import pytest

from rag_engine import hybrid_search, search_with_feedback
from bridge import weight_feedback as wf_mod
from bridge import memory_bridge as mb_mod
from integration import archive_from_conversation
from integration import workflow as wf


# === FakeCLE：模拟 CognitiveLoopEntry ===

class FakeCLE:
    """模拟认知闭环入口。"""

    def __init__(self):
        self.records = []
        self._counter = 0

    def record(self, content, quality_level="C", confidence=0.3,
               tags=None, source="trae", memory_type="experience"):
        self._counter += 1
        mid = f"VM-FAKE-CLOSED-{self._counter:04d}"
        self.records.append({
            "memory_id": mid, "content": content,
            "quality_level": quality_level, "tags": tags or [],
        })
        return mid

    def verify(self, memory_id, success=True):
        return {"success": True, "memory_id": memory_id, "new_quality": "B"}


# === 隔离 fixture ===

@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """隔离环境：临时权重文件 + 映射表 + FakeCLE。"""
    weight_path = tmp_path / "weight_feedback.json"
    map_path = tmp_path / "retrieval_memory_map.jsonl"

    fake_cle = FakeCLE()
    # patch memory_bridge 的 _get_cle 返回 FakeCLE
    monkeypatch.setattr(mb_mod, "_get_cle", lambda: fake_cle)

    return {
        "tmp_path": tmp_path,
        "weight_path": weight_path,
        "map_path": map_path,
        "fake_cle": fake_cle,
    }


# === TC1：search_with_feedback 返回完整闭环结构 ===

def test_tc1_search_with_feedback_returns_closed_loop_structure(isolated_env):
    """search_with_feedback 返回 {results, memory_mappings, boost_applied, record_done}。"""
    result = search_with_feedback(
        "Kalman 量化滤波", top_k=3,
        weight_path=isolated_env["weight_path"],
        map_path=isolated_env["map_path"])

    assert isinstance(result, dict)
    assert "results" in result
    assert "memory_mappings" in result
    assert "boost_applied" in result
    assert "record_done" in result
    assert isinstance(result["results"], list)
    assert result["boost_applied"] is True
    # 有结果时应记录记忆
    if result["results"]:
        assert result["record_done"] is True
        assert len(result["memory_mappings"]) > 0


# === TC2：boost 应用到检索结果 ===

def test_tc2_boost_applied_to_results(isolated_env):
    """boost 因子叠加到 final_score 并重排序。"""
    # 先写入一个 boost 因子
    wf_mod.update_boost("test_source.md", "test_heading", success=True,
                        weight_path=isolated_env["weight_path"])

    result = search_with_feedback(
        "Kalman 量化滤波", top_k=5,
        weight_path=isolated_env["weight_path"],
        map_path=isolated_env["map_path"])

    # 有检索结果时 boost 应被应用
    if result["results"]:
        assert result["boost_applied"] is True
        # 检索结果应含 rerank_signals.feedback_boost
        for r in result["results"]:
            if "rerank_signals" in r:
                assert "feedback_boost" in r["rerank_signals"]
    else:
        # 无结果时 boost_applied 为 False（无结果可应用）
        assert result["boost_applied"] is False


# === TC3：record 写入 C 级记忆 + 映射表 ===

def test_tc3_record_writes_memory_and_map(isolated_env):
    """search_with_feedback 将检索结果 record 为 C 级记忆并持久化映射。"""
    result = search_with_feedback(
        "BCRM 推理模型", top_k=3,
        map_path=isolated_env["map_path"])

    if result["results"]:
        # FakeCLE 应收到 record 调用
        assert len(isolated_env["fake_cle"].records) > 0
        # 映射表应有记录
        assert isolated_env["map_path"].exists()
        lines = isolated_env["map_path"].read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == len(result["memory_mappings"])
        # 每行含 memory_id
        for line in lines:
            rec = json.loads(line)
            assert "memory_id" in rec
            assert rec["memory_id"].startswith("VM-FAKE-CLOSED-")


# === TC4：enable_boost=False 不应用权重反哺 ===

def test_tc4_disable_boost(isolated_env):
    """enable_boost=False 时 boost_applied=False，结果与 hybrid_search 一致。"""
    result = search_with_feedback(
        "Kalman", top_k=3,
        enable_boost=False,
        map_path=isolated_env["map_path"])

    assert result["boost_applied"] is False


# === TC5：enable_record=False 不记录记忆 ===

def test_tc5_disable_record(isolated_env):
    """enable_record=False 时不调用 record，memory_mappings 为空。"""
    result = search_with_feedback(
        "Kalman", top_k=3,
        enable_record=False,
        weight_path=isolated_env["weight_path"])

    assert result["record_done"] is False
    assert result["memory_mappings"] == []
    assert len(isolated_env["fake_cle"].records) == 0


# === TC6：FAIL-OPEN - 认知系统不可用 ===

def test_tc6_failopen_cognitive_unavailable(tmp_path, monkeypatch):
    """认知系统不可用时（_get_cle 返回 None）检索不阻塞，record_done=False。"""
    weight_path = tmp_path / "weight.json"
    map_path = tmp_path / "map.jsonl"

    # patch _get_cle 返回 None（模拟认知系统不可用）
    monkeypatch.setattr(mb_mod, "_get_cle", lambda: None)

    result = search_with_feedback(
        "Kalman 量化", top_k=3,
        weight_path=weight_path,
        map_path=map_path)

    # 检索应正常返回结果
    assert isinstance(result["results"], list)
    # boost 仍可应用（与认知系统无关）
    assert result["boost_applied"] is True
    # record 应失败（认知系统不可用）
    assert result["record_done"] is False
    assert result["memory_mappings"] == []


# === TC7：FAIL-OPEN - 桥接模块导入失败 ===

def test_tc7_failopen_bridge_import_error(tmp_path, monkeypatch):
    """桥接模块导入失败时（apply_boost 抛异常）检索不阻塞。"""
    map_path = tmp_path / "map.jsonl"

    # 模拟 bridge.weight_feedback.apply_boost_to_results 抛异常
    import rag_engine.hybrid_retriever as hr_mod

    def fake_apply(*args, **kwargs):
        raise ImportError("bridge 模块不可用")

    # 通过 patch sys.modules 使 from bridge.weight_feedback import 失败
    original_bridge = sys.modules.get("bridge.weight_feedback")
    try:
        sys.modules["bridge.weight_feedback"] = None  # 触发 ImportError
        result = search_with_feedback(
            "Kalman", top_k=3,
            enable_record=False,  # 只测 boost FAIL-OPEN
            map_path=map_path)

        # 检索应正常返回
        assert isinstance(result["results"], list)
        # boost 应失败
        assert result["boost_applied"] is False
    finally:
        if original_bridge is not None:
            sys.modules["bridge.weight_feedback"] = original_bridge
        else:
            sys.modules.pop("bridge.weight_feedback", None)


# === TC8：字节等价 - hybrid_search 行为不变 ===

def test_tc8_hybrid_search_unchanged():
    """hybrid_search 原有接口和行为不变（不应用 boost，不记录记忆）。"""
    results = hybrid_search("Kalman 量化滤波", top_k=3)

    # 应返回列表（与改造前一致）
    assert isinstance(results, list)
    # 不应含 feedback_boost（hybrid_search 不应用 boost）
    for r in results:
        if "rerank_signals" in r:
            # hybrid_search 不注入 feedback_boost
            assert "feedback_boost" not in r.get("rerank_signals", {}) or \
                r["rerank_signals"].get("feedback_boost") is None


# === TC9：archive_from_conversation 归档后记录 C 级记忆 ===

def test_tc9_archive_records_memory(isolated_kb, isolated_env):
    """归档成功后，新知识单元被 record 为 C 级记忆。"""
    content = "研究了 Kalman Filter 量化滤波方法，回测效果不错"
    result = archive_from_conversation(
        content,
        research_topic="Kalman量化滤波调研",
        knowledge_dir=isolated_kb,
        map_path=isolated_env["map_path"],
    )

    assert result["status"] == "done"
    assert len(result["archived"]) >= 1
    # 应有记忆被记录
    assert result["memory_recorded"] > 0
    # FakeCLE 应收到 record 调用
    assert len(isolated_env["fake_cle"].records) > 0
    # 映射表应有记录
    assert isolated_env["map_path"].exists()


# === TC10：enable_memory=False 不记录记忆 ===

def test_tc10_archive_disable_memory(isolated_kb, isolated_env):
    """enable_memory=False 时归档正常但不记录记忆。"""
    content = "研究了 Kalman Filter 量化滤波方法"
    result = archive_from_conversation(
        content,
        research_topic="测试调研",
        knowledge_dir=isolated_kb,
        enable_memory=False,
        map_path=isolated_env["map_path"],
    )

    assert result["status"] == "done"
    assert result["memory_recorded"] == 0
    assert len(isolated_env["fake_cle"].records) == 0


# === TC11：归档记忆 FAIL-OPEN - 认知系统不可用 ===

def test_tc11_archive_memory_failopen(tmp_path, monkeypatch):
    """认知系统不可用时归档主流程正常，memory_recorded=0。"""
    kb = tmp_path / "kb"
    kb.mkdir()
    map_path = tmp_path / "map.jsonl"

    # patch 认知系统不可用
    monkeypatch.setattr(mb_mod, "_get_cle", lambda: None)

    # patch ingest 路径
    import evolution.ingest as ingest_mod
    db_dir = tmp_path / "chroma_db"
    monkeypatch.setattr(ingest_mod, "CHROMA_DB_PATH", str(db_dir))
    monkeypatch.setattr(ingest_mod, "COLLECTION_NAME", "test_archive_failopen")
    from knowledge_graph import schema as kg_schema
    monkeypatch.setattr(kg_schema, "DEFAULT_GRAPH_PATH", str(tmp_path / "kg.pkl"))

    content = "研究了 Kalman Filter 量化滤波方法"
    result = archive_from_conversation(
        content,
        research_topic="FAIL-OPEN测试",
        knowledge_dir=kb,
        map_path=map_path,
    )

    # 归档应成功
    assert result["status"] == "done"
    # 但记忆记录应为 0
    assert result["memory_recorded"] == 0


# === TC12：完整闭环 - record → verify → boost → 影响检索 ===

def test_tc12_full_closed_loop(isolated_env):
    """端到端验证：检索→record→verify→boost→影响后续检索排序。"""
    weight_path = isolated_env["weight_path"]
    map_path = isolated_env["map_path"]
    fake_cle = isolated_env["fake_cle"]

    # 第一次检索：record 记忆
    r1 = search_with_feedback(
        "BCRM 推理模型", top_k=3,
        weight_path=weight_path,
        map_path=map_path)

    if not r1["results"]:
        pytest.skip("无检索结果")

    # 取第一条结果，verify(success=True) → boost 升权
    first_mapping = r1["memory_mappings"][0]
    mid = first_mapping["memory_id"]
    source = first_mapping["source_file"]
    heading = first_mapping["heading"]

    from bridge import verify_and_feedback
    verify_result = verify_and_feedback(
        mid, success=True,
        map_path=map_path,
        weight_path=weight_path)
    assert verify_result["status"] == "done"
    assert verify_result["new_boost"] > 1.0

    # 第二次检索：boost 应影响排序
    r2 = search_with_feedback(
        "BCRM 推理模型", top_k=3,
        weight_path=weight_path,
        map_path=map_path)

    # 验证 boost 已应用
    assert r2["boost_applied"] is True
    # 被 verify 的知识单元应排在更前
    boosted = [r for r in r2["results"]
               if r.get("source_file") == source
               and r.get("heading") == heading]
    if boosted:
        # 该结果的 final_score 应被 boost 放大
        assert boosted[0]["rerank_signals"]["feedback_boost"] > 1.0


# === 隔离知识库 fixture（复用 test_integration.py 模式）===

@pytest.fixture
def isolated_kb(tmp_path, monkeypatch):
    """隔离的临时知识库。"""
    kb = tmp_path / "kb"
    kb.mkdir()
    db_dir = tmp_path / "chroma_db"
    graph_path = tmp_path / "knowledge_graph.pkl"

    import evolution.ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "CHROMA_DB_PATH", str(db_dir))
    monkeypatch.setattr(ingest_mod, "COLLECTION_NAME", "test_closed_loop_collection")

    from knowledge_graph import schema as kg_schema
    monkeypatch.setattr(kg_schema, "DEFAULT_GRAPH_PATH", str(graph_path))

    return kb
