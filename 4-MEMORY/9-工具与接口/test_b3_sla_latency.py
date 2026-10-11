"""B3 SLA 延迟预算 / 缓存命中率埋点 TDD RED 测试

SPEC-CognitiveSystem-Evolution.md §3.5 B3 评审修复项：
  1. 交易场景 recall SLA ≤ 200ms
  2. recall 中埋点记录"规则缓存命中率"（cache hit rate）
  3. SLA 超限时记录警告日志（不阻塞，FAIL-OPEN）

RED 契约（当前实现缺失，断言应失败）：
  - CognitiveLoopEntry 无 _recall_stats 计数器
  - recall 不测量 latency / 不记录 cache hit / 不告警 SLA 超限
  - 无 get_recall_stats() 方法
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import pytest

# 添加同目录到 path
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


@pytest.fixture
def isolated_cle(tmp_path):
    """构造隔离的 CognitiveLoopEntry 实例（独立 SQLite + 独立缓存）。"""
    try:
        import cognitive_loop_entry as cle_mod
        cle_mod.reset_cle()
    except Exception:
        pass

    storage_path = str(tmp_path / "test_b3_cognitive.db")
    cache_path = tmp_path / "test_b3_recall_cache.json"

    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry(
        storage_path=storage_path,
        enable_distill=False,
    )

    # 注入测试用 RecallMemoryCache（隔离缓存）
    try:
        from recall_memory_cache import RecallMemoryCache
        cle.recall_cache = RecallMemoryCache(cache_path=cache_path)
    except ImportError:
        pass

    return cle


# ─────────────────────────────── 缓存命中率埋点 ───────────────────────────────


class TestRecallCacheHitRate:
    """B3: recall 缓存命中率统计埋点。"""

    def test_recall_records_cache_hit_rate(self, isolated_cle):
        """RED: recall 后可通过 get_recall_stats() 获取 cache_hit_rate（命中数/总查询数）。"""
        # 预先向 recall_cache 注入一条记忆，确保 hot path 命中
        isolated_cle.recall_cache.promote(
            "VM-HIT-001", "马丁策略命中测试经验", 0.85, {"quality_level": "B"}
        )
        # mock archival 查询返回空，确保只走 cache 路径（确定性）
        isolated_cle._vm.search = lambda *a, **k: []

        isolated_cle.recall("马丁策略", top_k=5, min_quality="C")

        stats = isolated_cle.get_recall_stats()
        assert isinstance(stats, dict)
        assert stats["total"] == 1
        assert stats["cache_hits"] == 1
        assert stats["cache_hit_rate"] == 1.0

    def test_cache_hit_rate_accumulates(self, isolated_cle):
        """RED: 多次 recall 后命中率累积统计正确。"""
        isolated_cle._vm.search = lambda *a, **k: []
        isolated_cle.recall_cache.promote("VM-A", "alpha 经验内容", 0.8, {})

        # 1) recall "alpha" → cache 命中
        isolated_cle.recall("alpha", top_k=5)
        # 2) recall "beta" → cache 未命中（archival 也空）
        isolated_cle.recall("beta", top_k=5)
        # 3) recall "alpha" → cache 再次命中
        isolated_cle.recall("alpha", top_k=5)

        stats = isolated_cle.get_recall_stats()
        assert stats["total"] == 3
        assert stats["cache_hits"] == 2
        assert abs(stats["cache_hit_rate"] - (2 / 3)) < 0.01


# ─────────────────────────────── SLA 200ms 告警 ───────────────────────────────


class TestRecallSLAWarning:
    """B3: recall SLA ≤ 200ms，超限告警（FAIL-OPEN，不阻塞）。"""

    def test_recall_sla_warning_on_slow(self, isolated_cle, caplog):
        """RED: recall 延迟 >200ms 时记录 SLA 告警（检查日志 + 计数）。"""
        def slow_search(*args, **kwargs):
            time.sleep(0.25)  # 250ms，超过 200ms SLA
            return []

        isolated_cle._vm.search = slow_search

        with caplog.at_level(logging.WARNING, logger="cognitive_loop_entry"):
            isolated_cle.recall("slow context sla", top_k=5, min_quality="C")

        stats = isolated_cle.get_recall_stats()
        assert stats["sla_breaches"] >= 1
        # 日志应含 SLA 告警
        assert any(
            "SLA" in r.getMessage() or "200ms" in r.getMessage()
            for r in caplog.records
        )

    def test_recall_sla_no_warning_on_fast(self, isolated_cle, caplog):
        """RED: 延迟 <200ms 时不触发 SLA 告警。"""
        isolated_cle._vm.search = lambda *a, **k: []  # 立即返回，远低于 200ms

        with caplog.at_level(logging.WARNING, logger="cognitive_loop_entry"):
            isolated_cle.recall("fast context", top_k=5, min_quality="C")

        stats = isolated_cle.get_recall_stats()
        assert stats["sla_breaches"] == 0
        assert not any("SLA" in r.getMessage() for r in caplog.records)
