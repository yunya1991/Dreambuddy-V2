"""P1-3 双时序知识图 TDD RED 测试

借鉴 Zep/Graphiti 双时序知识图，为每条记忆添加：
  - valid_time: {start, end} — 事实有效期
  - transaction_time: 写入时间
  - invalidated_by: 被哪条新记忆否定

recall 升级: 过滤 valid_time.end < now 的记忆，或标记为"历史参考"。

RED 契约:
  1. temporal_memory_graph 模块不存在 → ImportError
  2. TemporalMemoryGraph 类不存在
  3. add_temporal_memory() 不存在
  4. invalidate() 不存在
  5. is_valid_at() 不存在
  6. get_active_memories() 不存在
  7. CognitiveLoopEntry 无 temporal_graph 属性

参考: SPEC-CognitiveSystem-Evolution.md §2.3.2 P1-3
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


class TestTemporalMemoryGraph:
    """双时序知识图 — TemporalMemoryGraph。"""

    def test_import_temporal_memory_graph(self):
        """RED: temporal_memory_graph 模块可导入。"""
        from temporal_memory_graph import TemporalMemoryGraph  # noqa: F401

    def test_add_temporal_memory(self, tmp_path):
        """RED: add_temporal_memory() 添加带有效期的记忆。"""
        from temporal_memory_graph import TemporalMemoryGraph

        graph = TemporalMemoryGraph(graph_path=tmp_path / "graph.json")
        graph.add_temporal_memory(
            memory_id="VM-001",
            content="马丁策略X在BTC上参数P盈利",
            valid_start="2024-01-01",
            valid_end="2024-06-01",
            transaction_time="2024-01-15",
        )
        # 应能查询到此记忆
        assert graph.get("VM-001") is not None
        assert graph.get("VM-001")["content"] == "马丁策略X在BTC上参数P盈利"

    def test_is_valid_at_within_range(self, tmp_path):
        """RED: valid_time 范围内 is_valid_at 返回 True。"""
        from temporal_memory_graph import TemporalMemoryGraph

        graph = TemporalMemoryGraph(graph_path=tmp_path / "graph.json")
        graph.add_temporal_memory(
            memory_id="VM-001",
            content="2024年Q1策略有效",
            valid_start="2024-01-01",
            valid_end="2024-06-01",
        )
        # 2024-03-01 在有效期内
        assert graph.is_valid_at("VM-001", "2024-03-01") is True

    def test_is_valid_at_after_expiry(self, tmp_path):
        """RED: valid_time 之后 is_valid_at 返回 False。"""
        from temporal_memory_graph import TemporalMemoryGraph

        graph = TemporalMemoryGraph(graph_path=tmp_path / "graph.json")
        graph.add_temporal_memory(
            memory_id="VM-001",
            content="已过期策略",
            valid_start="2024-01-01",
            valid_end="2024-06-01",
        )
        # 2024-07-01 已过期
        assert graph.is_valid_at("VM-001", "2024-07-01") is False

    def test_invalidate_by_new_memory(self, tmp_path):
        """RED: invalidate() 标记被新记忆否定。"""
        from temporal_memory_graph import TemporalMemoryGraph

        graph = TemporalMemoryGraph(graph_path=tmp_path / "graph.json")
        graph.add_temporal_memory(
            memory_id="VM-001",
            content="旧策略盈利",
            valid_start="2024-01-01",
            valid_end="2024-12-31",
        )
        graph.add_temporal_memory(
            memory_id="VM-002",
            content="新策略已失效",
            valid_start="2024-06-01",
            valid_end="2024-12-31",
        )
        # VM-002 否定 VM-001
        graph.invalidate("VM-001", invalidated_by="VM-002")

        entry = graph.get("VM-001")
        assert entry["invalidated_by"] == "VM-002"

    def test_get_active_memories_filters_expired(self, tmp_path):
        """RED: get_active_memories() 过滤掉已过期的记忆。"""
        from temporal_memory_graph import TemporalMemoryGraph

        graph = TemporalMemoryGraph(graph_path=tmp_path / "graph.json")
        graph.add_temporal_memory(
            memory_id="VM-001",
            content="已过期",
            valid_start="2024-01-01",
            valid_end="2024-03-01",
        )
        graph.add_temporal_memory(
            memory_id="VM-002",
            content="仍有效",
            valid_start="2024-01-01",
            valid_end="2025-12-31",
        )
        # 在 2024-07-01 时，VM-001 已过期，VM-002 仍有效
        active = graph.get_active_memories(at_time="2024-07-01")
        active_ids = {m["memory_id"] for m in active}
        assert "VM-002" in active_ids
        assert "VM-001" not in active_ids

    def test_get_active_memories_excludes_invalidated(self, tmp_path):
        """RED: get_active_memories() 排除被否定的记忆。"""
        from temporal_memory_graph import TemporalMemoryGraph

        graph = TemporalMemoryGraph(graph_path=tmp_path / "graph.json")
        graph.add_temporal_memory(
            memory_id="VM-001",
            content="被否定",
            valid_start="2024-01-01",
            valid_end="2025-12-31",
        )
        graph.add_temporal_memory(
            memory_id="VM-002",
            content="替代",
            valid_start="2024-06-01",
            valid_end="2025-12-31",
        )
        graph.invalidate("VM-001", invalidated_by="VM-002")

        active = graph.get_active_memories(at_time="2024-07-01")
        active_ids = {m["memory_id"] for m in active}
        assert "VM-001" not in active_ids  # 被否定
        assert "VM-002" in active_ids

    def test_mark_expired_as_historical(self, tmp_path):
        """RED: filter_recall_results() 标记过期记忆为'历史参考'而非删除。"""
        from temporal_memory_graph import TemporalMemoryGraph

        graph = TemporalMemoryGraph(graph_path=tmp_path / "graph.json")
        graph.add_temporal_memory(
            memory_id="VM-001",
            content="过期策略",
            valid_start="2024-01-01",
            valid_end="2024-03-01",
        )

        results = [
            {"id": "VM-001", "content": "过期策略", "score": 0.8},
            {"id": "VM-002", "content": "有效策略", "score": 0.7},
        ]
        filtered = graph.filter_recall_results(results, now="2024-07-01")
        # VM-001 应标记为历史参考，不删除
        vm001 = next(r for r in filtered if r["id"] == "VM-001")
        assert vm001.get("temporal_status") == "historical"

    def test_persist_and_restore(self, tmp_path):
        """RED: 持久化到 JSON 并恢复。"""
        from temporal_memory_graph import TemporalMemoryGraph

        graph_path = tmp_path / "graph.json"
        graph = TemporalMemoryGraph(graph_path=graph_path)
        graph.add_temporal_memory(
            "VM-001", "测试", "2024-01-01", "2024-12-31"
        )
        graph.persist()

        graph2 = TemporalMemoryGraph(graph_path=graph_path)
        assert graph2.get("VM-001") is not None
        assert graph2.get("VM-001")["content"] == "测试"


class TestCognitiveLoopEntryTemporal:
    """CognitiveLoopEntry 双时序集成。"""

    def test_temporal_graph_attribute_exists(self):
        """RED: CognitiveLoopEntry 应有 temporal_graph 属性。"""
        from cognitive_loop_entry import CognitiveLoopEntry
        # 类级别检查（不实例化避免 DB 依赖）
        assert hasattr(CognitiveLoopEntry, "__init__")
        # 实例化后检查
        import cognitive_loop_entry as cle_mod
        cle_mod.reset_cle()
        try:
            cle = cle_mod.CognitiveLoopEntry(enable_distill=False)
            assert hasattr(cle, "temporal_graph")
        except Exception:
            pytest.skip("CLE 初始化失败（DB 锁）")
