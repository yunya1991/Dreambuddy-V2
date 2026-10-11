"""P1-7 pgmpy 集成 verify — 因果推理引擎 TDD RED 测试

SPEC: SPEC-CognitiveSystem-Evolution.md §1.4 pgmpy + §4.2 P1-7

将 verify 从贝叶斯置信度更新升级为因果推理引擎：
  1. 因果图构建 — 从记忆 tags 重叠 + verify 时序构建因果关系图
  2. do-calculus — 反事实推理 "如果 do(memory_id=false)，哪些依赖记忆受影响？"
  3. 因果发现 — 从 verify 历史时序发现 A→B 因果链
  4. verify 影响评估 — verify 时评估记忆的因果影响范围

工程约束：
  - pgmpy 是可选依赖（无 pgmpy 时 fallback 到纯 Python 实现）
  - FAIL-OPEN：因果引擎异常不阻断 verify 主流程
  - 零外部依赖（pgmpy 不可用时用轻量级实现）

RED 契约：
  - CausalInferenceEngine 类不存在 → ImportError
  - verify 返回无 causal 子键 → KeyError
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


# ─────────────────────────────── 辅助 fixture ───────────────────────────────

@pytest.fixture
def sample_memories():
    """构造一组有 tags 重叠的样例记忆。"""
    return [
        {
            "id": "VM-001",
            "content": "马丁策略在 BTC 参数 P1 盈利",
            "tags": ["马丁策略", "BTC", "趋势"],
            "quality_level": "B",
            "confidence": 0.5,
            "verify_count": 2,
        },
        {
            "id": "VM-002",
            "content": "BTC 趋势策略突破后跟涨效果好",
            "tags": ["BTC", "趋势", "突破"],
            "quality_level": "A",
            "confidence": 0.8,
            "verify_count": 5,
        },
        {
            "id": "VM-003",
            "content": "ETH 马丁策略参数优化记录",
            "tags": ["马丁策略", "ETH", "参数优化"],
            "quality_level": "C",
            "confidence": 0.3,
            "verify_count": 0,
        },
    ]


@pytest.fixture
def sample_verify_history():
    """构造 verify 历史时序数据：VM-001 verify 成功后 VM-002 也 verify 成功。"""
    base_ts = int(time.time())
    return [
        {"memory_id": "VM-001", "success": True, "timestamp": base_ts - 100},
        {"memory_id": "VM-002", "success": True, "timestamp": base_ts - 80},
        {"memory_id": "VM-001", "success": True, "timestamp": base_ts - 60},
        {"memory_id": "VM-002", "success": True, "timestamp": base_ts - 40},
        {"memory_id": "VM-003", "success": False, "timestamp": base_ts - 20},
    ]


@pytest.fixture
def engine(tmp_path):
    """构造 CausalInferenceEngine 实例。"""
    from causal_inference_engine import CausalInferenceEngine
    return CausalInferenceEngine(graph_path=tmp_path / "causal_graph.json")


# ─────────────────────────────── RED: 引擎初始化 ───────────────────────────────

def test_causal_engine_init_no_pgmpy(tmp_path):
    """RED: 无 pgmpy 时引擎仍可初始化（可选依赖）。"""
    from causal_inference_engine import CausalInferenceEngine
    eng = CausalInferenceEngine(graph_path=tmp_path / "cg.json")
    assert eng is not None
    # pgmpy_available 属性存在（无论 True/False）
    assert hasattr(eng, "pgmpy_available")


def test_causal_engine_persists_graph_path(tmp_path):
    """RED: 引擎接受 graph_path 参数用于持久化因果图。"""
    from causal_inference_engine import CausalInferenceEngine
    graph_path = tmp_path / "causal_graph.json"
    eng = CausalInferenceEngine(graph_path=graph_path)
    assert eng.graph_path == graph_path


# ─────────────────────────────── RED: 因果图构建 ───────────────────────────────

def test_build_causal_graph_empty(engine):
    """RED: 空记忆列表返回空因果图。"""
    graph = engine.build_causal_graph([])
    assert graph is not None
    assert len(graph.get("nodes", [])) == 0
    assert len(graph.get("edges", [])) == 0


def test_build_causal_graph_with_tag_overlap(engine, sample_memories):
    """RED: tags 重叠的记忆之间构建因果边。"""
    graph = engine.build_causal_graph(sample_memories)
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    # 3 个记忆 → 3 个节点
    assert len(nodes) == 3
    # VM-001 和 VM-002 共享 ["BTC", "趋势"] → 有边
    # VM-001 和 VM-003 共享 ["马丁策略"] → 有边
    # VM-002 和 VM-003 无共享 tags → 无边
    assert len(edges) >= 2, f"tags 重叠的记忆应有因果边，实际 {len(edges)} 条"
    # 检查边结构含 source/target/weight
    for edge in edges:
        assert "source" in edge
        assert "target" in edge
        assert "weight" in edge


# ─────────────────────────────── RED: do-calculus ───────────────────────────────

def test_do_calculus_intervene_success(engine, sample_memories):
    """RED: do(memory_id=success) 推理 — 干预后依赖记忆的预期置信度变化。"""
    engine.build_causal_graph(sample_memories)
    result = engine.do_calculus(
        intervention_node="VM-001",
        intervention_value=True,  # do(VM-001 = success)
    )
    assert result is not None
    assert "intervention" in result
    assert "affected_nodes" in result
    # VM-002 依赖 VM-001（tags 重叠），应出现在受影响节点中
    affected_ids = [n["id"] for n in result["affected_nodes"]]
    assert "VM-002" in affected_ids or "VM-003" in affected_ids


def test_do_calculus_intervene_failure(engine, sample_memories):
    """RED: do(memory_id=failure) 推理 — 失败干预应降低依赖记忆的预期置信度。"""
    engine.build_causal_graph(sample_memories)
    result = engine.do_calculus(
        intervention_node="VM-001",
        intervention_value=False,  # do(VM-001 = failure)
    )
    assert result is not None
    # 失败干预 → 受影响记忆的 delta_confidence 应为负
    for node in result.get("affected_nodes", []):
        assert node.get("delta_confidence", 0) <= 0, (
            "失败干预应降低依赖记忆的置信度"
        )


# ─────────────────────────────── RED: 因果发现 ───────────────────────────────

def test_discover_causes_temporal(engine, sample_verify_history):
    """RED: 从 verify 历史时序发现因果关系（A 先成功 → B 后成功 → A→B 因果链）。"""
    causal_chains = engine.discover_causes(sample_verify_history)
    assert causal_chains is not None
    assert isinstance(causal_chains, list)
    # VM-001 先 verify 成功，VM-002 后 verify 成功 → 可能存在 VM-001→VM-002 因果链
    # 至少发现 1 条因果链
    assert len(causal_chains) >= 1, (
        "应从 verify 时序中发现至少 1 条因果链"
    )
    for chain in causal_chains:
        assert "cause" in chain
        assert "effect" in chain
        assert "confidence" in chain


# ─────────────────────────────── RED: verify 影响评估 ───────────────────────────────

def test_assess_verify_impact(engine, sample_memories, sample_verify_history):
    """RED: verify 影响评估返回结构化结果。"""
    engine.build_causal_graph(sample_memories)
    impact = engine.assess_verify_impact(
        memory_id="VM-001",
        success=True,
        related_memories=sample_memories,
        verify_history=sample_verify_history,
    )
    assert impact is not None
    assert "memory_id" in impact
    assert "impact_radius" in impact  # 影响半径（受影响记忆数）
    assert "affected_memories" in impact
    assert "counterfactual" in impact  # 反事实分析


# ─────────────────────────────── RED: verify 集成 ───────────────────────────────

def test_verify_returns_causal_field(tmp_path):
    """RED: verify() 返回结果应包含 causal 子键。"""
    from cognitive_loop_entry import CognitiveLoopEntry

    cle = CognitiveLoopEntry(
        storage_path=str(tmp_path / "test_cog.db"),
    )
    # 先 record 一条记忆
    mid = cle.record(
        content="P1-7 因果推理测试记忆",
        quality_level="B",
        tags="causal,inference,test",
        source="test",
    )
    # verify 应返回 causal 子键
    result = cle.verify(memory_id=mid, success=True)
    assert "causal" in result, (
        "P1-7 RED: verify() 返回应包含 causal 子键"
    )
    causal = result["causal"]
    assert "impact_radius" in causal
    assert "affected_memories" in causal


def test_verify_causal_fail_open(tmp_path):
    """RED: 因果引擎异常时 verify 仍成功（FAIL-OPEN）。"""
    from cognitive_loop_entry import CognitiveLoopEntry

    cle = CognitiveLoopEntry(
        storage_path=str(tmp_path / "test_cog2.db"),
    )
    mid = cle.record(
        content="P1-7 FAIL-OPEN 测试",
        quality_level="C",
        tags="causal,fail-open",
        source="test",
    )
    # mock causal_engine 为 None（模拟不可用）
    with patch.object(cle, "causal_engine", None):
        result = cle.verify(memory_id=mid, success=True)
    # verify 仍成功
    assert result["success"] is True
    # causal 子键应为 FAIL-OPEN 兜底
    assert "causal" in result
    assert result["causal"].get("fail_open") is True or \
           result["causal"].get("error") is not None
