"""P1-1 三层记忆模型 TDD RED 测试

验证 Letta/MemGPT 式三层记忆架构：
  Working Memory   ← 当前任务上下文（WorkingMemoryManager + recall_block）
       ↓ promote
  Recall Memory    ← 近期高频访问缓存（RecallMemoryCache）
       ↓ consolidate
  Archival Memory  ← 长期归档（cognitive_memory.db，已存在）

RED 契约（当前实现缺失，断言应失败）：
  1. recall_memory_cache 模块不存在 → ImportError
  2. RecallMemoryCache 类不存在 → AttributeError
  3. WorkingMemoryManager.recall_block 不存在 → AttributeError
  4. WorkingMemoryManager.load_recall_results() 不存在 → AttributeError
  5. CognitiveLoopEntry.recall_cache 不存在 → AttributeError
  6. CognitiveLoopEntry.recall() 不提升结果到 working_memory.recall_block
  7. 无 layer-aware dispatch（cache 命中不走 hot path）

参考：SPEC-CognitiveSystem-Evolution.md §2.3.1 P1-1
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 添加同目录到 path
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


# ─────────────────────────────── RecallMemoryCache ───────────────────────────────


class TestRecallMemoryCache:
    """RecallMemoryCache — Recall Memory 层（中间缓存）。"""

    def test_import_recall_memory_cache(self):
        """RED: recall_memory_cache 模块可导入。"""
        from recall_memory_cache import RecallMemoryCache  # noqa: F401

    def test_promote_adds_memory_to_cache(self, tmp_path):
        """RED: promote() 将记忆提升到 recall 层缓存。"""
        from recall_memory_cache import RecallMemoryCache

        cache = RecallMemoryCache(cache_path=tmp_path / "cache.json")
        cache.promote(
            memory_id="VM-test-001",
            content="马丁策略X在BTC上参数P盈利",
            score=0.85,
            metadata={"quality_level": "B", "tags": ["strategy"]},
        )

        # 缓存中应有此记忆
        assert cache.get("VM-test-001") is not None
        assert cache.get("VM-test-001")["content"] == "马丁策略X在BTC上参数P盈利"

    def test_get_increments_access_count(self, tmp_path):
        """RED: get() 提升访问计数（频率追踪）。"""
        from recall_memory_cache import RecallMemoryCache

        cache = RecallMemoryCache(cache_path=tmp_path / "cache.json")
        cache.promote("VM-001", "content-A", 0.7, {"quality_level": "C"})

        # 首次访问 access_count=1
        cache.get("VM-001")
        assert cache.get_stats("VM-001")["access_count"] == 1

        # 再次访问 access_count=2
        cache.get("VM-001")
        assert cache.get_stats("VM-001")["access_count"] == 2

    def test_query_searches_cache_by_keyword(self, tmp_path):
        """RED: query() 按关键词从缓存检索（不依赖 SQLite）。"""
        from recall_memory_cache import RecallMemoryCache

        cache = RecallMemoryCache(cache_path=tmp_path / "cache.json")
        cache.promote("VM-001", "马丁策略BTC盈利", 0.8, {})
        cache.promote("VM-002", "趋势跟踪ETH亏损", 0.6, {})

        # 按关键词检索
        results = cache.query("马丁 策略", top_k=5)
        assert len(results) >= 1
        assert any(r["id"] == "VM-001" for r in results)

    def test_lru_eviction_when_capacity_exceeded(self, tmp_path):
        """RED: 缓存超容量时 LRU 淘汰最久未访问的记忆。"""
        from recall_memory_cache import RecallMemoryCache

        cache = RecallMemoryCache(cache_path=tmp_path / "cache.json", max_size=3)
        cache.promote("VM-001", "content-A", 0.7, {})
        cache.promote("VM-002", "content-B", 0.7, {})
        cache.promote("VM-003", "content-C", 0.7, {})

        # 访问 VM-001 使其成为最近使用
        cache.get("VM-001")

        # 加入第4条，应淘汰 VM-002（最久未访问）
        cache.promote("VM-004", "content-D", 0.7, {})
        assert cache.get("VM-002") is None  # 被淘汰
        assert cache.get("VM-001") is not None  # 保留

    def test_consolidate_evicts_low_frequency(self, tmp_path):
        """RED: consolidate() 淘汰低频访问项，保留高频项。"""
        from recall_memory_cache import RecallMemoryCache

        cache = RecallMemoryCache(cache_path=tmp_path / "cache.json", max_size=10)
        cache.promote("VM-001", "高频项", 0.8, {})
        cache.promote("VM-002", "低频项", 0.6, {})

        # 高频项访问 5 次
        for _ in range(5):
            cache.get("VM-001")

        # 低频项只访问 1 次
        cache.get("VM-002")

        # consolidate 应淘汰低频项（access_count <= 1）
        report = cache.consolidate(min_access_threshold=2)
        assert report["evicted_count"] >= 1
        assert cache.get("VM-002") is None
        assert cache.get("VM-001") is not None

    def test_persist_and_restore(self, tmp_path):
        """RED: 缓存持久化到 JSON 文件，重启后可恢复。"""
        from recall_memory_cache import RecallMemoryCache

        cache_path = tmp_path / "cache.json"
        cache = RecallMemoryCache(cache_path=cache_path)
        cache.promote("VM-001", "持久化测试", 0.7, {"quality_level": "B"})
        cache.persist()

        # 新实例恢复
        cache2 = RecallMemoryCache(cache_path=cache_path)
        assert cache2.get("VM-001") is not None
        assert cache2.get("VM-001")["content"] == "持久化测试"


# ─────────────────────────────── WorkingMemoryManager 扩展 ───────────────────────────────


class TestWorkingMemoryRecallBlock:
    """WorkingMemoryManager 新增 recall_block 分区。"""

    def test_recall_block_exists(self):
        """RED: WorkingMemoryManager 应有 recall_block 属性。"""
        from working_memory_manager import WorkingMemoryManager

        wm = WorkingMemoryManager()
        assert hasattr(wm, "recall_block")
        assert wm.recall_block.name == "recall"

    def test_load_recall_results(self):
        """RED: load_recall_results() 将 recall 结果加载到 recall_block。"""
        from working_memory_manager import WorkingMemoryManager

        wm = WorkingMemoryManager()
        results = [
            {"id": "VM-001", "content": "经验A", "score": 0.85},
            {"id": "VM-002", "content": "经验B", "score": 0.70},
        ]
        wm.load_recall_results(results)

        # recall_block 应包含结果摘要
        recall_md = wm.recall_block.get("markdown", "")
        assert "VM-001" in recall_md
        assert "经验A" in recall_md

    def test_prompt_context_includes_recall_block(self):
        """RED: get_prompt_context() 应包含 recall_block 内容。"""
        from working_memory_manager import WorkingMemoryManager

        wm = WorkingMemoryManager()
        wm.load_recall_results([{"id": "VM-X", "content": "测试经验", "score": 0.9}])

        context = wm.get_prompt_context()
        assert "VM-X" in context or "测试经验" in context


# ─────────────────────────────── CognitiveLoopEntry 三层调度 ───────────────────────────────


@pytest.fixture
def isolated_cle(tmp_path):
    """构造隔离的 CognitiveLoopEntry 实例（独立 SQLite + 独立缓存）。"""
    # 重置单例
    try:
        import cognitive_loop_entry as cle_mod
        cle_mod.reset_cle()
    except Exception:
        pass

    storage_path = str(tmp_path / "test_cognitive.db")
    cache_path = tmp_path / "test_recall_cache.json"

    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry(
        storage_path=storage_path,
        enable_distill=False,
    )

    # 注入测试用 RecallMemoryCache
    try:
        from recall_memory_cache import RecallMemoryCache
        cle.recall_cache = RecallMemoryCache(cache_path=cache_path)
    except ImportError:
        # RED 阶段 RecallMemoryCache 尚不存在
        pass

    return cle


class TestCognitiveLoopEntryThreeLayer:
    """CognitiveLoopEntry 三层调度集成测试。"""

    def test_recall_cache_attribute_exists(self, isolated_cle):
        """RED: CognitiveLoopEntry 应有 recall_cache 属性。"""
        assert hasattr(isolated_cle, "recall_cache")
        assert isolated_cle.recall_cache is not None

    def test_recall_promotes_results_to_working_memory(self, isolated_cle):
        """RED: recall() 应将结果提升到 working_memory.recall_block。"""
        # 先 record 一条记忆
        isolated_cle.record(
            content="P1-1 三层记忆模型测试经验",
            tags="三层记忆,p1-1,test",
            quality_level="B",
        )

        # recall
        results = isolated_cle.recall("三层记忆模型", top_k=5, min_quality="C")

        # working_memory.recall_block 应包含 recall 结果
        wm = isolated_cle.working_memory
        assert hasattr(wm, "recall_block")
        recall_md = wm.recall_block.get("markdown", "")
        assert len(recall_md) > 0
        if results:
            assert any(r["id"] in recall_md for r in results)

    def test_recall_cache_hit_returns_cached(self, isolated_cle):
        """RED: 第二次 recall 相同 context 应命中缓存（hot path），且缓存有 access 痕迹。"""
        isolated_cle.record(
            content="缓存命中测试经验",
            tags="缓存,测试",
            quality_level="B",
        )

        # 第一次 recall，miss → 查 SQLite → promote 到 cache
        results1 = isolated_cle.recall("缓存命中", top_k=5, min_quality="C")
        assert results1, "第一次 recall 应有结果"

        # 第二次 recall 相同 context，应命中 cache
        results2 = isolated_cle.recall("缓存命中", top_k=5, min_quality="C")

        # 两次结果应一致
        ids1 = {r["id"] for r in results1}
        ids2 = {r["id"] for r in results2}
        assert ids1 == ids2, "相同 context 两次 recall 结果应一致"

        # RED 契约：recall_cache 应有 access 痕迹（access_count > 0）
        # 当前 recall_cache 不存在 → AttributeError / False
        rc = getattr(isolated_cle, "recall_cache", None)
        assert rc is not None, "recall_cache 应存在"
        # 至少有一条缓存项 access_count > 0
        cached_ids = [mid for mid in ids1 if rc.get(mid) is not None]
        assert len(cached_ids) > 0, "至少一条记忆应被 promote 到 recall_cache"

    def test_consolidate_recall_cache_method(self, isolated_cle):
        """RED: CognitiveLoopEntry 应有 consolidate_recall_cache() 方法。"""
        assert hasattr(isolated_cle, "consolidate_recall_cache")
        report = isolated_cle.consolidate_recall_cache()
        assert isinstance(report, dict)
        assert "evicted_count" in report
