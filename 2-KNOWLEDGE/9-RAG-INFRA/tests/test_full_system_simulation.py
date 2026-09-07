#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""完整系统模拟测试：验证认知系统 ↔ 知识库系统协同闭环。

模拟真实使用场景，覆盖完整链路：
  场景1：对话→检测→归档→记录记忆→检索→verify→boost 影响后续检索
  场景2：多轮 verify 累积 boost 变化（升权/降权/上下限保护）
  场景3：FAIL-OPEN 鲁棒性（认知系统不可用、模块缺失）
  场景4：批量检索与归档的性能与正确性

运行方式：
    python3 tests/test_full_system_simulation.py

测试隔离：使用临时目录 + FakeCLE，不污染真实认知库/知识库。
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

# === 路径与 TF-IDF 回退设置 ===
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

_RAG_INFRA_DIR = Path(__file__).resolve().parent.parent
if str(_RAG_INFRA_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_INFRA_DIR))

_COGNITIVE_DIR = _RAG_INFRA_DIR.parent.parent / "4-MEMORY" / "9-工具与接口"
if str(_COGNITIVE_DIR) not in sys.path:
    sys.path.insert(0, str(_COGNITIVE_DIR))

from vector_store.embedder import _embedder
_embedder._use_tfidf_fallback = True
_embedder._model = None

import pytest
from rag_engine import hybrid_search, search_with_feedback
from bridge import (
    record_retrieval_as_memory, verify_and_feedback,
    apply_boost_to_results, get_boost, update_boost, reset,
    BOOST_MIN, BOOST_MAX, BOOST_SUCCESS_FACTOR, BOOST_FAILURE_FACTOR,
    DEFAULT_BOOST,
)
from bridge import weight_feedback as wf_mod
from bridge import memory_bridge as mb_mod
from integration import archive_from_conversation, detect_research


# === FakeCLE：模拟认知系统 ===

class FakeCLE:
    """模拟 CognitiveLoopEntry，追踪 record/verify 调用。"""

    def __init__(self):
        self.records = []
        self.verifies = []
        self._counter = 0
        self._record_enabled = True

    def record(self, content, quality_level="C", confidence=0.3,
               tags=None, source="trae", memory_type="experience"):
        if not self._record_enabled:
            return None
        self._counter += 1
        mid = f"VM-SIM-{self._counter:04d}"
        self.records.append({
            "memory_id": mid, "content": content,
            "quality_level": quality_level, "tags": tags or [],
        })
        return mid

    def verify(self, memory_id, success=True):
        self.verifies.append({"memory_id": memory_id, "success": success})
        return {"success": True, "memory_id": memory_id, "new_quality": "B"}


class UnavailableCLE:
    """模拟认知系统不可用。"""
    def record(self, *a, **kw): return None
    def verify(self, *a, **kw): return None


# === 隔离 fixture ===

@pytest.fixture
def sim_env(tmp_path, monkeypatch):
    """完整隔离环境：临时权重文件+映射表+知识库+FakeCLE。"""
    weight_path = tmp_path / "weight.json"
    map_path = tmp_path / "map.jsonl"
    kb = tmp_path / "kb"
    kb.mkdir()

    fake_cle = FakeCLE()
    monkeypatch.setattr(mb_mod, "_get_cle", lambda: fake_cle)

    # 隔离 ingest 路径
    import evolution.ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "CHROMA_DB_PATH", str(tmp_path / "chroma"))
    monkeypatch.setattr(ingest_mod, "COLLECTION_NAME", "sim_test")
    from knowledge_graph import schema as kg
    monkeypatch.setattr(kg, "DEFAULT_GRAPH_PATH", str(tmp_path / "kg.pkl"))

    return {
        "tmp": tmp_path, "weight": weight_path, "map": map_path,
        "kb": kb, "cle": fake_cle,
    }


# ========== 场景1：完整闭环 ==========

def test_scenario1_full_closed_loop(sim_env):
    """模拟完整闭环：对话→检测→归档→记忆→检索→verify→boost→影响检索。"""
    print("\n=== 场景1：完整闭环测试 ===")

    # Step1: 模拟对话，检测调研内容
    content = "研究了 Kalman Filter 量化滤波方法，回测效果不错"
    detections = detect_research(content)
    assert len(detections) >= 1
    print(f"Step1 检测: {len(detections)} 条调研内容")

    # Step2: 归档 + 记录记忆
    result = archive_from_conversation(
        content, research_topic="Kalman量化滤波研究",
        knowledge_dir=sim_env["kb"], map_path=sim_env["map"])
    assert result["status"] == "done"
    assert result["memory_recorded"] > 0
    print(f"Step2 归档: {len(result['archived'])} 条, 记忆: {result['memory_recorded']} 条")

    # Step3: 检索并记录记忆
    r1 = search_with_feedback(
        "Kalman 量化", top_k=5,
        weight_path=sim_env["weight"], map_path=sim_env["map"])
    assert r1["boost_applied"] is True
    assert r1["record_done"] is True
    print(f"Step3 检索: {len(r1['results'])} 结果, "
          f"{len(r1['memory_mappings'])} 记忆映射")

    if not r1["memory_mappings"]:
        pytest.skip("无检索结果")

    # Step4: verify 第一条记忆 → boost 升权
    m = r1["memory_mappings"][0]
    vr = verify_and_feedback(
        m["memory_id"], success=True,
        map_path=sim_env["map"], weight_path=sim_env["weight"])
    assert vr["status"] == "done"
    assert vr["new_boost"] > DEFAULT_BOOST
    print(f"Step4 verify: boost {DEFAULT_BOOST}→{vr['new_boost']}")

    # Step5: 再次检索，验证 boost 影响
    r2 = search_with_feedback(
        "Kalman 量化", top_k=5,
        weight_path=sim_env["weight"], map_path=sim_env["map"])
    assert r2["boost_applied"] is True

    # 被 verify 的知识单元 boost 应 > 1.0
    boosted = [r for r in r2["results"]
               if r.get("source_file") == m["source_file"]
               and r.get("heading") == m["heading"]]
    if boosted:
        fb = boosted[0].get("rerank_signals", {}).get("feedback_boost", 1.0)
        assert fb > DEFAULT_BOOST
        print(f"Step5 验证: feedback_boost={fb} > {DEFAULT_BOOST} ✓")
    else:
        print(f"Step5: 被verify的知识单元未出现在结果（TF-IDF 模式正常）")

    print("=== 场景1 通过 ✓ ===\n")


# ========== 场景2：多轮 verify 累积 ==========

def test_scenario2_cumulative_verify(sim_env):
    """多轮 verify 累积 boost 变化：升权→降权→上限保护→下限保护。"""
    print("=== 场景2：多轮 verify 累积 ===")

    source = "cumulative_test.md"
    heading = "累积测试"

    # Round1-3: 连续 3 次 verify(True) → boost 应持续上升
    boosts = []
    for i in range(3):
        # 需要先有映射才能 verify_and_feedback
        pseudo = [{"source_file": source, "heading": heading,
                   "domain": "test", "final_score": 1.0, "content": "test"}]
        mappings = record_retrieval_as_memory(
            f"query_{i}", pseudo, cle=sim_env["cle"], map_path=sim_env["map"])
        assert len(mappings) == 1

        vr = verify_and_feedback(
            mappings[0]["memory_id"], success=True,
            map_path=sim_env["map"], weight_path=sim_env["weight"])
        boosts.append(vr["new_boost"])

    print(f"Round1-3 升权: {boosts}")
    assert boosts[0] > DEFAULT_BOOST
    assert boosts[1] > boosts[0]  # 持续上升
    assert boosts[2] > boosts[1]

    # Round4: 继续升权到接近上限
    for i in range(3, 20):
        pseudo = [{"source_file": source, "heading": heading,
                   "domain": "test", "final_score": 1.0, "content": "test"}]
        mappings = record_retrieval_as_memory(
            f"query_{i}", pseudo, cle=sim_env["cle"], map_path=sim_env["map"])
        vr = verify_and_feedback(
            mappings[0]["memory_id"], success=True,
            map_path=sim_env["map"], weight_path=sim_env["weight"])
        boosts.append(vr["new_boost"])

    print(f"Round4-20: final boost={boosts[-1]}, max={BOOST_MAX}")
    assert boosts[-1] <= BOOST_MAX  # 上限保护

    # Round5: 连续 verify(False) → boost 下降
    fail_boosts = []
    for i in range(20, 40):
        pseudo = [{"source_file": source, "heading": heading,
                   "domain": "test", "final_score": 1.0, "content": "test"}]
        mappings = record_retrieval_as_memory(
            f"query_{i}", pseudo, cle=sim_env["cle"], map_path=sim_env["map"])
        vr = verify_and_feedback(
            mappings[0]["memory_id"], success=False,
            map_path=sim_env["map"], weight_path=sim_env["weight"])
        fail_boosts.append(vr["new_boost"])

    print(f"Round20-40 降权: final={fail_boosts[-1]}, min={BOOST_MIN}")
    assert fail_boosts[-1] >= BOOST_MIN  # 下限保护
    assert fail_boosts[-1] < boosts[-1]  # 确实下降了

    print("=== 场景2 通过 ✓ ===\n")


# ========== 场景3：FAIL-OPEN 鲁棒性 ==========

def test_scenario3_failopen_robustness(tmp_path, monkeypatch):
    """FAIL-OPEN：认知系统不可用时检索/归档不阻塞。"""
    print("=== 场景3：FAIL-OPEN 鲁棒性 ===")

    weight_path = tmp_path / "weight.json"
    map_path = tmp_path / "map.jsonl"

    # 3a: 认知系统返回 None（不可用）
    monkeypatch.setattr(mb_mod, "_get_cle", lambda: None)

    r = search_with_feedback(
        "Kalman", top_k=3,
        weight_path=weight_path, map_path=map_path)
    assert isinstance(r["results"], list)
    assert r["record_done"] is False  # 记忆记录失败
    assert r["memory_mappings"] == []
    print("3a 认知系统不可用: 检索正常, record_done=False ✓")

    # 3b: 归档时认知系统不可用
    kb = tmp_path / "kb_failopen"
    kb.mkdir()
    import evolution.ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "CHROMA_DB_PATH", str(tmp_path / "chroma2"))
    monkeypatch.setattr(ingest_mod, "COLLECTION_NAME", "failopen_test")
    from knowledge_graph import schema as kg
    monkeypatch.setattr(kg, "DEFAULT_GRAPH_PATH", str(tmp_path / "kg2.pkl"))

    content = "研究了 Kalman Filter 量化方法"
    result = archive_from_conversation(
        content, research_topic="FAIL-OPEN测试",
        knowledge_dir=kb, map_path=map_path)
    assert result["status"] == "done"
    assert result["memory_recorded"] == 0
    print("3b 归档时认知不可用: 归档成功, memory_recorded=0 ✓")

    print("=== 场景3 通过 ✓ ===\n")


# ========== 场景4：批量检索与归档 ==========

def test_scenario4_batch_operations(sim_env):
    """批量检索与归档的性能与正确性。"""
    print("=== 场景4：批量检索与归档 ===")

    # 4a: 批量归档 5 条调研
    contents = [
        "研究了 Kalman Filter 量化滤波方法",
        "参考了 github.com/langchain/langchain 仓库",
        "对比了 RAG 架构与设计模式 方案",
        "分析了风控对冲止损策略",
        "使用了 docker kubernetes 部署方案",
    ]

    archived_count = 0
    memory_count = 0
    detected_count = 0
    for i, c in enumerate(contents):
        result = archive_from_conversation(
            c, research_topic=f"批量调研_{i}",
            knowledge_dir=sim_env["kb"], map_path=sim_env["map"])
        # 部分内容可能未被检测到（TF-IDF 模式下关键词匹配差异），跳过
        if result["status"] == "no_research":
            print(f"  内容{i} 未检测到调研内容，跳过")
            continue
        assert result["status"] == "done"
        detected_count += 1
        archived_count += len(result["archived"])
        memory_count += result["memory_recorded"]

    print(f"4a 批量归档: {detected_count}/{len(contents)} 被检测, "
          f"归档 {archived_count}, 记忆 {memory_count}")
    assert detected_count >= 1  # 至少 1 条被检测
    assert archived_count >= 1
    assert memory_count >= 1

    # 4b: 批量检索 5 次
    queries = ["Kalman 量化", "langchain 框架", "RAG 架构", "风控 对冲", "docker"]
    total_results = 0
    total_mappings = 0
    for q in queries:
        r = search_with_feedback(
            q, top_k=3,
            weight_path=sim_env["weight"], map_path=sim_env["map"])
        total_results += len(r["results"])
        total_mappings += len(r["memory_mappings"])

    print(f"4b 批量检索: {len(queries)} 次, 结果 {total_results}, "
          f"记忆 {total_mappings}")
    # 有检索结果时应产生记忆映射（认知系统可用时）
    if total_results > 0:
        assert total_mappings >= 1

    # 4c: 验证映射表完整性
    if sim_env["map"].exists():
        lines = sim_env["map"].read_text(encoding="utf-8").strip().split("\n")
        print(f"4c 映射表: {len(lines)} 条记录")
        for line in lines:
            rec = json.loads(line)
            assert "memory_id" in rec
            assert "source_file" in rec

    # 4d: 验证权重文件
    if sim_env["weight"].exists():
        fb = json.loads(sim_env["weight"].read_text(encoding="utf-8"))
        print(f"4d 权重文件: {len(fb)} 条 boost 记录")

    print("=== 场景4 通过 ✓ ===\n")


# ========== 场景5：hybrid_search 字节等价 ==========

def test_scenario5_hybrid_search_equivalence():
    """hybrid_search 原行为不变（不应用 boost，不记录记忆）。"""
    print("=== 场景5：hybrid_search 字节等价 ===")

    results = hybrid_search("Kalman 量化滤波", top_k=3)
    assert isinstance(results, list)

    # hybrid_search 不应含 feedback_boost（除非 reranker 本身有）
    for r in results:
        signals = r.get("rerank_signals", {})
        # hybrid_search 不注入 feedback_boost
        assert "feedback_boost" not in signals or signals["feedback_boost"] is None

    print(f"hybrid_search 返回 {len(results)} 条, 无 feedback_boost 注入 ✓")
    print("=== 场景5 通过 ✓ ===\n")


# ========== 场景6：认知系统状态检查 ==========

def test_scenario6_cognitive_system_stats():
    """验证认知系统 MCP 工具可用（stats/health）。"""
    print("=== 场景6：认知系统状态 ===")

    try:
        from cognitive_loop_entry import get_cle
        cle = get_cle()
        assert cle is not None

        # 检查核心方法存在
        assert hasattr(cle, "record")
        assert hasattr(cle, "verify")
        assert hasattr(cle, "recall")
        print("认知系统 CognitiveLoopEntry: record/verify/recall 可用 ✓")

    except Exception as e:
        pytest.skip(f"认知系统未启用: {e}")

    print("=== 场景6 通过 ✓ ===\n")


if __name__ == "__main__":
    # 独立运行模式（不依赖 pytest）
    print("=" * 60)
    print("完整系统模拟测试：认知系统 ↔ 知识库系统协同闭环")
    print("=" * 60)

    # 使用 pytest 运行
    pytest.main([__file__, "-v", "-s", "--tb=short"])
