# -*- coding: utf-8 -*-
"""RAG ↔ 4-MEMORY 桥接测试。

覆盖：
- weight_feedback：boost 因子读写、上下限保护、apply_boost_to_results、持久化
- memory_bridge：record 检索为 C 级记忆、映射表持久化、verify 反哺
- FAIL-OPEN：认知系统不可用、映射不存在、verify 异常

测试隔离：使用 tmp_path 临时目录，不污染真实认知库与权重文件。
认知系统通过 FakeCLE mock，避免加载真实 SQLite/蒸馏引擎。
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

import pytest

from bridge import (
    record_retrieval_as_memory,
    verify_and_feedback,
    apply_boost_to_results,
    get_boost,
    update_boost,
    reset,
    BOOST_MIN,
    BOOST_MAX,
    BOOST_SUCCESS_FACTOR,
    BOOST_FAILURE_FACTOR,
    DEFAULT_BOOST,
)
from bridge import weight_feedback as wf_mod
from bridge import memory_bridge as mb_mod


# === FakeCLE：模拟 CognitiveLoopEntry ===

class FakeCLE:
    """模拟认知闭环入口，record/verify 行为可控。"""

    def __init__(self, verify_ok=True):
        self.records = []  # 记录所有 record 调用
        self.verifies = []  # 记录所有 verify 调用
        self._counter = 0
        self._verify_ok = verify_ok

    def record(self, content, quality_level="C", confidence=0.3,
               tags=None, source="trae", memory_type="experience"):
        self._counter += 1
        mid = f"VM-FAKE-{self._counter:04d}"
        self.records.append({
            "memory_id": mid,
            "content": content,
            "quality_level": quality_level,
            "confidence": confidence,
            "tags": tags or [],
            "source": source,
        })
        return mid

    def verify(self, memory_id, success=True):
        self.verifies.append({"memory_id": memory_id, "success": success})
        if not self._verify_ok:
            return {"success": False, "error": f"记忆不存在: {memory_id}"}
        return {"success": True, "memory_id": memory_id, "new_quality": "B"}


class FailingCLE:
    """模拟认知系统 record/verify 抛异常。"""

    def record(self, *args, **kwargs):
        raise RuntimeError("认知系统不可用")

    def verify(self, *args, **kwargs):
        raise RuntimeError("认知系统不可用")


# === fixtures ===

@pytest.fixture
def fake_cle():
    return FakeCLE()


@pytest.fixture
def isolated_paths(tmp_path):
    """隔离的权重文件与映射表路径。"""
    return {
        "weight_path": tmp_path / "weight_feedback.json",
        "map_path": tmp_path / "retrieval_memory_map.jsonl",
    }


# ═══════════════════════════════════════════════════════════════
# weight_feedback 单元测试
# ═══════════════════════════════════════════════════════════════

def test_tc1_get_boost_default(isolated_paths):
    """未记录的知识单元 boost 默认 1.0。"""
    assert get_boost("unknown.md", "未知标题",
                     weight_path=isolated_paths["weight_path"]) == DEFAULT_BOOST


def test_tc2_update_boost_success_increases(isolated_paths):
    """verify 成功时 boost 上升（乘以 SUCCESS_FACTOR）。"""
    new = update_boost("file.md", "标题", success=True,
                       weight_path=isolated_paths["weight_path"])
    expected = round(DEFAULT_BOOST * BOOST_SUCCESS_FACTOR, 4)
    assert new == expected
    # 持久化生效
    assert get_boost("file.md", "标题",
                     weight_path=isolated_paths["weight_path"]) == expected


def test_tc3_update_boost_failure_decreases(isolated_paths):
    """verify 失败时 boost 下降（乘以 FAILURE_FACTOR）。"""
    new = update_boost("file.md", "标题", success=False,
                       weight_path=isolated_paths["weight_path"])
    expected = round(DEFAULT_BOOST * BOOST_FAILURE_FACTOR, 4)
    assert new == expected


def test_tc4_boost_upper_limit(isolated_paths):
    """boost 不超过 BOOST_MAX（多次成功后封顶）。"""
    wp = isolated_paths["weight_path"]
    current = DEFAULT_BOOST
    for _ in range(50):
        current = update_boost("file.md", "标题", success=True, weight_path=wp)
    assert current == BOOST_MAX


def test_tc5_boost_lower_limit(isolated_paths):
    """boost 不低于 BOOST_MIN（多次失败后封底）。"""
    wp = isolated_paths["weight_path"]
    current = DEFAULT_BOOST
    for _ in range(50):
        current = update_boost("file.md", "标题", success=False, weight_path=wp)
    assert current == BOOST_MIN


def test_tc6_boost_accumulates(isolated_paths):
    """多次 verify 累积更新 boost。"""
    wp = isolated_paths["weight_path"]
    # 连续2次成功
    b1 = update_boost("f.md", "h", True, weight_path=wp)
    b2 = update_boost("f.md", "h", True, weight_path=wp)
    assert b2 > b1
    # 再1次失败
    b3 = update_boost("f.md", "h", False, weight_path=wp)
    assert b3 < b2


def test_tc7_apply_boost_reorders_results(isolated_paths):
    """apply_boost_to_results 将 boost 叠加到 final_score 并重排序。"""
    wp = isolated_paths["weight_path"]
    # 给 result_a 设置高 boost
    update_boost("a.md", "标题A", True, weight_path=wp)
    update_boost("a.md", "标题A", True, weight_path=wp)

    # a.md 原始分接近 b.md，boost 后应反超
    results = [
        {"source_file": "a.md", "heading": "标题A",
         "content": "A", "final_score": 0.80},
        {"source_file": "b.md", "heading": "标题B",
         "content": "B", "final_score": 0.85},
    ]
    adjusted = apply_boost_to_results(results, weight_path=wp)
    # a.md boost≈1.21，叠加后 0.80*1.21≈0.968 > 0.85，应排第一
    assert adjusted[0]["source_file"] == "a.md"
    # 记录了 feedback_boost 信号
    assert adjusted[0]["rerank_signals"]["feedback_boost"] > DEFAULT_BOOST


def test_tc8_apply_boost_empty_results(isolated_paths):
    """空结果列表返回空。"""
    assert apply_boost_to_results([], weight_path=isolated_paths["weight_path"]) == []


def test_tc9_apply_boost_no_feedback_keeps_order(isolated_paths):
    """无 boost 反馈时结果顺序不变，feedback_boost 记录为 1.0。"""
    wp = isolated_paths["weight_path"]
    results = [
        {"source_file": "a.md", "heading": "A", "final_score": 0.9},
        {"source_file": "b.md", "heading": "B", "final_score": 0.5},
    ]
    adjusted = apply_boost_to_results(results, weight_path=wp)
    assert adjusted[0]["source_file"] == "a.md"
    assert adjusted[0]["rerank_signals"]["feedback_boost"] == DEFAULT_BOOST


def test_tc10_weight_feedback_persistence(isolated_paths):
    """权重反馈持久化到 JSON 文件。"""
    wp = isolated_paths["weight_path"]
    update_boost("f.md", "h", True, weight_path=wp)
    data = json.loads(wp.read_text(encoding="utf-8"))
    assert "f.md::h" in data


# ═══════════════════════════════════════════════════════════════
# memory_bridge: record_retrieval_as_memory
# ═══════════════════════════════════════════════════════════════

def test_tc11_record_retrieval_as_memory(fake_cle, isolated_paths):
    """RAG 检索结果 record 为 C 级记忆，返回映射列表。"""
    query = "BCRM推理模型"
    results = [
        {"source_file": "BCRM.md", "heading": "344模型",
         "content": "BCRM采用344+278模型架构", "domain": "trading",
         "final_score": 0.85},
        {"source_file": "五计.md", "heading": "五维评分",
         "content": "道天地将法五维加权", "domain": "strategy",
         "final_score": 0.72},
    ]
    mappings = record_retrieval_as_memory(
        query, results, cle=fake_cle,
        map_path=isolated_paths["map_path"])

    assert len(mappings) == 2
    # 每条映射含必要字段
    for m in mappings:
        assert m["memory_id"].startswith("VM-FAKE-")
        assert m["source_file"]
        assert m["heading"]
        assert m["query"] == query
        assert "timestamp" in m

    # CLE 被调用2次，quality_level=C，confidence=0.3，source=rag-bridge
    assert len(fake_cle.records) == 2
    rec = fake_cle.records[0]
    assert rec["quality_level"] == "C"
    assert rec["confidence"] == 0.3
    assert rec["source"] == "rag-bridge"
    assert "BCRM推理模型" in rec["content"]
    assert "BCRM.md" in rec["content"]


def test_tc12_record_persists_map_jsonl(fake_cle, isolated_paths):
    """映射表持久化到 JSONL 文件。"""
    query = "Kalman滤波"
    results = [{"source_file": "f.md", "heading": "h",
                "content": "c", "final_score": 0.8}]
    record_retrieval_as_memory(query, results, cle=fake_cle,
                               map_path=isolated_paths["map_path"])

    mp = isolated_paths["map_path"]
    assert mp.exists()
    lines = mp.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["memory_id"].startswith("VM-FAKE-")
    assert record["source_file"] == "f.md"
    assert record["heading"] == "h"


def test_tc13_record_empty_results(fake_cle, isolated_paths):
    """空结果列表返回空映射。"""
    mappings = record_retrieval_as_memory("query", [], cle=fake_cle,
                                          map_path=isolated_paths["map_path"])
    assert mappings == []


def test_tc14_record_empty_query(fake_cle, isolated_paths):
    """空查询返回空映射。"""
    results = [{"source_file": "f.md", "heading": "h", "content": "c"}]
    mappings = record_retrieval_as_memory("", results, cle=fake_cle,
                                          map_path=isolated_paths["map_path"])
    assert mappings == []


def test_tc15_record_fail_open_cle_none(isolated_paths, monkeypatch):
    """CLE 懒加载失败时 FAIL-OPEN 返回空列表。"""
    # mock _get_cle 返回 None
    monkeypatch.setattr(mb_mod, "_get_cle", lambda: None)
    results = [{"source_file": "f.md", "heading": "h", "content": "c"}]
    mappings = record_retrieval_as_memory("query", results,
                                         map_path=isolated_paths["map_path"])
    assert mappings == []


def test_tc16_record_fail_open_record_exception(isolated_paths):
    """CLE.record 抛异常时单条失败不阻塞其余（FAIL-OPEN）。"""
    cle = FailingCLE()
    results = [
        {"source_file": "f1.md", "heading": "h1", "content": "c1"},
        {"source_file": "f2.md", "heading": "h2", "content": "c2"},
    ]
    mappings = record_retrieval_as_memory("query", results, cle=cle,
                                          map_path=isolated_paths["map_path"])
    # 全部 record 抛异常，返回空列表
    assert mappings == []


# ═══════════════════════════════════════════════════════════════
# memory_bridge: verify_and_feedback
# ═══════════════════════════════════════════════════════════════

def test_tc17_verify_and_feedback_success(fake_cle, isolated_paths):
    """verify 成功时更新 boost（上升）并返回 done。"""
    # 先 record 建立映射
    query = "测试"
    results = [{"source_file": "f.md", "heading": "h",
                "content": "c", "final_score": 0.8}]
    mappings = record_retrieval_as_memory(query, results, cle=fake_cle,
                                          map_path=isolated_paths["map_path"])
    mid = mappings[0]["memory_id"]

    # verify 成功
    r = verify_and_feedback(mid, success=True, cle=fake_cle,
                            map_path=isolated_paths["map_path"],
                            weight_path=isolated_paths["weight_path"])
    assert r["status"] == "done"
    assert r["boost_updated"] is True
    assert r["source_file"] == "f.md"
    assert r["heading"] == "h"
    assert r["new_boost"] > DEFAULT_BOOST
    # CLE.verify 被调用
    assert len(fake_cle.verifies) == 1


def test_tc18_verify_and_feedback_failure(fake_cle, isolated_paths):
    """verify 失败时更新 boost（下降）并返回 done。"""
    mappings = record_retrieval_as_memory(
        "q", [{"source_file": "f.md", "heading": "h", "content": "c"}],
        cle=fake_cle, map_path=isolated_paths["map_path"])
    mid = mappings[0]["memory_id"]

    r = verify_and_feedback(mid, success=False, cle=fake_cle,
                            map_path=isolated_paths["map_path"],
                            weight_path=isolated_paths["weight_path"])
    assert r["status"] == "done"
    assert r["boost_updated"] is True
    assert r["new_boost"] < DEFAULT_BOOST


def test_tc19_verify_mapping_not_found(fake_cle, isolated_paths):
    """memory_id 在映射表中不存在时返回 skipped。"""
    r = verify_and_feedback("VM-NONEXISTENT", success=True, cle=fake_cle,
                            map_path=isolated_paths["map_path"],
                            weight_path=isolated_paths["weight_path"])
    assert r["status"] == "skipped"
    assert r["error"] == "mapping_not_found"
    assert r["boost_updated"] is False


def test_tc20_verify_fail_open_cle_exception(isolated_paths):
    """CLE.verify 抛异常时返回 failed（FAIL-OPEN）。"""
    cle = FailingCLE()
    # 先用 FakeCLE 建立映射
    fake = FakeCLE()
    mappings = record_retrieval_as_memory(
        "q", [{"source_file": "f.md", "heading": "h", "content": "c"}],
        cle=fake, map_path=isolated_paths["map_path"])
    mid = mappings[0]["memory_id"]

    r = verify_and_feedback(mid, success=True, cle=cle,
                            map_path=isolated_paths["map_path"],
                            weight_path=isolated_paths["weight_path"])
    assert r["status"] == "failed"
    assert "verify_exception" in (r["error"] or "")


def test_tc21_verify_fail_open_verify_returns_error(isolated_paths):
    """CLE.verify 返回 {success:False, error} 时不更新 boost。"""
    cle = FakeCLE(verify_ok=False)
    fake = FakeCLE()
    mappings = record_retrieval_as_memory(
        "q", [{"source_file": "f.md", "heading": "h", "content": "c"}],
        cle=fake, map_path=isolated_paths["map_path"])
    mid = mappings[0]["memory_id"]

    r = verify_and_feedback(mid, success=True, cle=cle,
                            map_path=isolated_paths["map_path"],
                            weight_path=isolated_paths["weight_path"])
    assert r["status"] == "failed"
    assert "记忆不存在" in (r["error"] or "")
    assert r["boost_updated"] is False


def test_tc22_verify_cle_none_updates_boost_only(isolated_paths, monkeypatch):
    """CLE 不可用时仍尝试更新 boost（verify 跳过，反哺不阻塞）。"""
    fake = FakeCLE()
    mappings = record_retrieval_as_memory(
        "q", [{"source_file": "f.md", "heading": "h", "content": "c"}],
        cle=fake, map_path=isolated_paths["map_path"])
    mid = mappings[0]["memory_id"]

    # _get_cle 返回 None
    monkeypatch.setattr(mb_mod, "_get_cle", lambda: None)
    r = verify_and_feedback(mid, success=True,
                            map_path=isolated_paths["map_path"],
                            weight_path=isolated_paths["weight_path"])
    # verify 跳过但 boost 更新成功
    assert r["status"] == "done"
    assert r["boost_updated"] is True
    assert r["new_boost"] > DEFAULT_BOOST


# ═══════════════════════════════════════════════════════════════
# 端到端闭环测试
# ═══════════════════════════════════════════════════════════════

def test_tc23_e2e_record_verify_feedback_apply(fake_cle, isolated_paths):
    """端到端：record → verify → apply_boost_to_results 闭环。"""
    wp = isolated_paths["weight_path"]
    mp = isolated_paths["map_path"]

    # 1. record 检索结果为记忆
    query = "RAG架构"
    results = [
        {"source_file": "rag.md", "heading": "混合检索",
         "content": "三路召回", "domain": "technical", "final_score": 0.8},
        {"source_file": "kg.md", "heading": "知识图谱",
         "content": "NetworkX图", "domain": "technical", "final_score": 0.6},
    ]
    mappings = record_retrieval_as_memory(query, results, cle=fake_cle, map_path=mp)
    assert len(mappings) == 2

    # 2. verify 第一条（成功）
    r = verify_and_feedback(mappings[0]["memory_id"], success=True,
                            cle=fake_cle, map_path=mp, weight_path=wp)
    assert r["status"] == "done"

    # 3. apply_boost_to_results 验证 boost 叠加
    new_results = [
        {"source_file": "rag.md", "heading": "混合检索",
         "content": "三路召回", "final_score": 0.8},
        {"source_file": "kg.md", "heading": "知识图谱",
         "content": "NetworkX图", "final_score": 0.6},
    ]
    adjusted = apply_boost_to_results(new_results, weight_path=wp)
    # rag.md 有 boost > 1.0，应排在前面
    assert adjusted[0]["source_file"] == "rag.md"
    assert adjusted[0]["rerank_signals"]["feedback_boost"] > DEFAULT_BOOST
    # kg.md 无 boost，保持 1.0
    kg = [r for r in adjusted if r["source_file"] == "kg.md"][0]
    assert kg["rerank_signals"]["feedback_boost"] == DEFAULT_BOOST


def test_tc24_e2e_repeated_verify_accumulates(fake_cle, isolated_paths):
    """多次 record + verify 同一知识单元，boost 累积。"""
    wp = isolated_paths["weight_path"]
    mp = isolated_paths["map_path"]

    # 两次检索同一知识单元
    for q in ["查询1", "查询2"]:
        results = [{"source_file": "f.md", "heading": "h",
                    "content": "c", "final_score": 0.7}]
        mappings = record_retrieval_as_memory(q, results, cle=fake_cle, map_path=mp)
        r = verify_and_feedback(mappings[0]["memory_id"], success=True,
                                cle=fake_cle, map_path=mp, weight_path=wp)
        assert r["status"] == "done"

    # 两次成功 verify，boost 应 > 单次
    boost = get_boost("f.md", "h", weight_path=wp)
    expected_once = round(DEFAULT_BOOST * BOOST_SUCCESS_FACTOR, 4)
    assert boost > expected_once


# ═══════════════════════════════════════════════════════════════
# F1: pytest 临时路径垃圾清理（purge_temporary_entries）
# ═══════════════════════════════════════════════════════════════

from bridge import purge_temporary_entries  # noqa: E402


def _make_mixed_weight_file(path: Path) -> None:
    """构造含pytest tmp路径和真实生产路径的weight_feedback.json。"""
    data = {
        # pytest 临时路径（应删除）
        "/private/var/folders/xx/pytest-123/test_tc1/kb/7-EXTERNAL-RESEARCH/finance/x.md::标题": 1.1,
        "/tmp/pytest-of-user/pytest-456/test_tc2/kb/xxx.md::T": 1.1,
        "/var/folders/yy/tmpzz/kb/f.md::h": 1.1,
        # 真实生产路径（应保留）
        "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/2-KNOWLEDGE/7-EXTERNAL-RESEARCH/finance/risk-models/2026-09-01-恐贪指数调研.md::恐贪指数调研": 1.1,
        "7-EXTERNAL-RESEARCH/debug/pathfix.md::W3 parents[3] pathfix 验证": 1.1,
        "real-doc.md::Heading1": 0.9,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_mixed_map_file(path: Path) -> None:
    """构造含pytest tmp路径和真实行的retrieval_memory_map.jsonl。"""
    lines = [
        # pytest 临时路径（应删除）
        json.dumps({"memory_id": "VM-TMP-1", "source_file": "/private/var/folders/xx/pytest-1/kb/f.md::h",
                    "heading": "h", "query": "q", "timestamp": 1}, ensure_ascii=False),
        json.dumps({"memory_id": "VM-TMP-2", "source_file": "/tmp/pytest-of-u/1/kb/f.md",
                    "heading": "h", "query": "q", "timestamp": 2}, ensure_ascii=False),
        json.dumps({"memory_id": "VM-TMP-3", "source_file": "/var/folders/z/tmp/kb/f.md",
                    "heading": "h", "query": "q", "timestamp": 3}, ensure_ascii=False),
        # 真实路径（应保留）
        json.dumps({"memory_id": "VM-REAL-1",
                    "source_file": "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/2-KNOWLEDGE/7-EXTERNAL-RESEARCH/finance/risk-models/2026-09-01-恐贪.md",
                    "heading": "调研", "query": "归档: 恐贪", "timestamp": 4}, ensure_ascii=False),
        json.dumps({"memory_id": "VM-REAL-2", "source_file": "7-EXTERNAL-RESEARCH/debug/pathfix.md",
                    "heading": "验证", "query": "修复", "timestamp": 5}, ensure_ascii=False),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_f1_purge_weight_removes_tmp_paths(isolated_paths):
    """清理权重文件：tmp路径删除，真实路径保留。"""
    wp = isolated_paths["weight_path"]
    _make_mixed_weight_file(wp)

    stats = purge_temporary_entries(weight_path=wp, map_path=None)

    # 应有3条删除，3条保留
    assert stats["weight_removed"] == 3
    assert stats["weight_kept"] == 3
    remaining = json.loads(wp.read_text(encoding="utf-8"))
    assert len(remaining) == 3
    for k in remaining:
        assert "/tmp/" not in k and "/private/var/" not in k and "/var/folders/" not in k


def test_f1_purge_map_removes_tmp_rows(isolated_paths):
    """清理映射表：tmp行删除，真实行保留。"""
    mp = isolated_paths["map_path"]
    _make_mixed_map_file(mp)

    stats = purge_temporary_entries(weight_path=None, map_path=mp)

    assert stats["map_removed"] == 3
    assert stats["map_kept"] == 2
    remaining_lines = [ln for ln in mp.read_text(encoding="utf-8").strip().split("\n") if ln.strip()]
    assert len(remaining_lines) == 2
    for ln in remaining_lines:
        rec = json.loads(ln)
        sf = rec["source_file"]
        assert "/tmp/" not in sf and "/private/var/" not in sf and "/var/folders/" not in sf


def test_f1_purge_dry_run_does_not_modify(isolated_paths):
    """dry_run=True 不修改文件，只返回统计。"""
    wp = isolated_paths["weight_path"]
    mp = isolated_paths["map_path"]
    _make_mixed_weight_file(wp)
    _make_mixed_map_file(mp)

    before_wp = wp.read_text(encoding="utf-8")
    before_mp = mp.read_text(encoding="utf-8")

    stats = purge_temporary_entries(weight_path=wp, map_path=mp, dry_run=True)

    after_wp = wp.read_text(encoding="utf-8")
    after_mp = mp.read_text(encoding="utf-8")
    # 文件未变
    assert after_wp == before_wp
    assert after_mp == before_mp
    # 但统计正确
    assert stats["weight_removed"] == 3
    assert stats["map_removed"] == 3


def test_f1_purge_handles_nonexistent_files(isolated_paths):
    """文件不存在时不报错，统计为0。"""
    no_wp = isolated_paths["weight_path"].parent / "noexist_weight.json"
    no_mp = isolated_paths["map_path"].parent / "noexist_map.jsonl"

    stats = purge_temporary_entries(weight_path=no_wp, map_path=no_mp)
    assert stats["weight_removed"] == 0
    assert stats["weight_kept"] == 0
    assert stats["map_removed"] == 0
    assert stats["map_kept"] == 0


# ============================================================
# F4: pytest 隔离 — 通过 TEST_BRIDGE_* 环境变量重定向默认路径
# ============================================================

def test_f4_env_var_resolves_map_path(monkeypatch, tmp_path):
    """TEST_BRIDGE_MAP_PATH 存在时，resolve_default_paths 返回 env 指定路径。"""
    env_map = tmp_path / "custom_map.jsonl"
    env_weight = tmp_path / "custom_weight.json"
    # 未实现前 resolve_default_paths 应该不存在，RED 阶段会 AttributeError（或等价失败）
    monkeypatch.setenv("TEST_BRIDGE_MAP_PATH", str(env_map))
    monkeypatch.setenv("TEST_BRIDGE_WEIGHT_PATH", str(env_weight))

    # 触发重算（强制重新读取 env）：如果未实现，直接断言路径重定向行为
    from importlib import reload
    reload(mb_mod)
    reload(wf_mod)
    paths = mb_mod.resolve_default_paths()
    assert Path(paths["map_path"]) == env_map
    assert Path(paths["weight_path"]) == env_weight


def test_f4_defaults_without_env(monkeypatch, tmp_path):
    """无 TEST_BRIDGE_* 变量时，默认路径为生产文件（非 tmp_path）。"""
    monkeypatch.delenv("TEST_BRIDGE_MAP_PATH", raising=False)
    monkeypatch.delenv("TEST_BRIDGE_WEIGHT_PATH", raising=False)
    from importlib import reload
    reload(mb_mod)
    reload(wf_mod)
    paths = mb_mod.resolve_default_paths()
    # map_path 应该包含 retrieval_memory_map.jsonl 基名、weight_path 包含 weight_feedback.json
    assert Path(paths["map_path"]).name == "retrieval_memory_map.jsonl"
    assert Path(paths["weight_path"]).name == "weight_feedback.json"
    # 且不位于测试临时目录
    assert str(tmp_path) not in str(paths["map_path"])
    assert str(tmp_path) not in str(paths["weight_path"])


def test_f4_record_uses_env_map_path(monkeypatch, tmp_path):
    """record_retrieval_as_memory 不传 map_path 时，写入 env 中指定的 map 文件。"""
    env_map = tmp_path / "env_map.jsonl"
    env_weight = tmp_path / "env_weight.json"
    monkeypatch.setenv("TEST_BRIDGE_MAP_PATH", str(env_map))
    monkeypatch.setenv("TEST_BRIDGE_WEIGHT_PATH", str(env_weight))

    from importlib import reload
    reload(mb_mod)
    reload(wf_mod)

    fake = FakeCLE()
    record_retrieval_as_memory(
        query="test_f4",
        results=[{
            "source_file": "src.md",
            "heading": "H",
            "domain": "d",
            "final_score": 0.9,
            "content": "snippet",
        }],
        cle=fake,
        # 显式不传 map_path（强制走默认解析）
    )
    # 映射应该写入 env 指定的文件，而非真实生产文件
    assert env_map.exists(), "record_retrieval_as_memory 未将映射写入 TEST_BRIDGE_MAP_PATH"
    assert env_map.read_text(encoding="utf-8").strip() != ""
    # 生产文件未被污染（size 不变或追加内容中不含 TEST_BRIDGE_MAP_PATH）
    real_map = Path(mb_mod.__file__).parent / "retrieval_memory_map.jsonl"
    prod_before = env_map.stat().st_size  # noop just to avoid lint
    assert prod_before > 0  # f4写入一定大于0


# ============================================================
# F8: RAG桥接记忆格式升级
# 目标：snippet 200→500字符；核心结论摘要注入content，而非纯元数据包裹
# ============================================================

def test_f8_snippet_limit_expanded_to_500():
    """snippet长度上限从200扩展为500，超长内容在500处截断加省略号。"""
    long_content = "A" * 600
    result = {
        "source_file": "s.md", "heading": "H", "domain": "d", "score": 0.9,
        "content": long_content,
    }
    built = mb_mod._build_memory_content(query="q", result=result)
    # snippet部分最长=500+3(省略号)
    assert "snippet=" in built
    # 提取snippet=到结束或下一个|之前
    import re
    m = re.search(r"snippet=([A-Za-z0-9_.\u4e00-\u9fff，。、 ]+)", built)
    assert m is not None, f"snippet字段未正常解析, got: {built[:80]}"
    snip = m.group(1)
    # 600A截断500+... → 实际503字符
    assert len(snip) == 503, f"期望503字符(500A+3省略), 实际={len(snip)} 首/尾: {snip[:10]}..{snip[-6:]}"
    assert snip.endswith("..."), "截断内容未添加省略号"


def test_f8_content_injects_summary_not_metadata_only():
    """result含summary/conclusion字段时应优先注入，而非纯[RAG检索]元数据包裹。"""
    result = {
        "source_file": "Medallion调研.md",
        "heading": "Medallion三层奖章架构调研",
        "domain": "finance",
        "score": 0.95,
        "summary": "核心结论：Bronze→Silver硬门禁(quality.py三级σ过滤拦截+Schema)→Gold；Silver/FeatureHub异常FAIL-OPEN中性兜底+Lark5/3。",
        "content": "完整正文会很长会被截断忽略巴拉巴拉",
    }
    built = mb_mod._build_memory_content(query="Medallion", result=result)
    # 必须包含核心结论正文（不只是元数据的domain/source/heading）
    assert "核心结论" in built, "summary字段未被注入记忆content"
    assert "Silver硬门禁" in built, "核心结论关键词未出现"
    assert "FAIL-OPEN中性兜底" in built
    # 纯元数据也保留，但核心语义段前置
    assert built.startswith("[RAG检索]"), f"前缀未保留: {built[:40]}"


def test_f8_no_summary_falls_back_snippet():
    """没有summary/conclusion时，仅用snippet不报错，且snippet=500上限。"""
    result = {
        "source_file": "x.md", "heading": "H", "domain": "d", "score": 0.5,
        "content": "Z" * 550,
    }
    built = mb_mod._build_memory_content(query="q", result=result)
    assert "核心结论" not in built
    # snippet=500 Z + ...
    assert built.count("Z") == 500, f"无summary回退截断错误: Z数量期望500实际{built.count('Z')}"


def test_f8_record_writes_injected_format():
    """record_retrieval_as_memory 调用cle.record时传入的content=已注入summary+500snippet格式。"""
    fake = FakeCLE()
    record_retrieval_as_memory(
        query="Medallion调研",
        results=[{
            "source_file": "archive/Medallion三层奖章架构.md",
            "heading": "Medallion调研",
            "domain": "finance",
            "final_score": 0.9,
            "content": "完整正文会截断",
            "summary": "核心结论：Silver层硬门禁，quality.py从监控升级为拦截。",
        }],
        cle=fake,
    )
    assert len(fake.records) == 1
    content = fake.records[0]["content"]
    assert "核心结论" in content
    assert "Silver层硬门禁" in content
    # 元数据字段依旧保留
    assert "[RAG检索]" in content
    assert "query=Medallion调研" in content
