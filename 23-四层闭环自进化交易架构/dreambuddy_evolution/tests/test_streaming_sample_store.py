"""test_streaming_sample_store.py — 流式样本存储单元测试（D5: ds4 mmap 借鉴）

SPEC: SPEC-ds4架构借鉴与系统增强.md §3.2 Dimension 5
哲学: ds4 mmap 按需访问——只解析 header/metadata，张量数据留在内核页缓存按需访问。
映射: 对持续增长的 shadow_rl_samples.jsonl，引入 sqlite 替代全量 read_text。

StreamingSampleStore API:
  - append(sample)         # 追加写
  - read_range(start, end) # 按索引范围读
  - stats()                # SQL 聚合统计（O(1) 非全量遍历）
  - migrate_from_jsonl()   # 从现有 JSONL 迁移（HC-DS4-06 向后兼容）
  - count()                # 样本总数

硬约束:
  HC-DS4-06: 流式样本存储必须向后兼容现有 JSONL 文件
  HC-DS4-01: 开关关闭时与当前 deque+JSONL 行为 100% 等价

覆盖:
  - append 后可读取
  - read_range 范围查询
  - stats 聚合（mean/std/count/effective_count）
  - JSONL 迁移
  - FAIL-OPEN 降级（sqlite 异常时降级内存）
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dreambuddy_evolution.core.streaming_sample_store import StreamingSampleStore


# ==============================================================================
# 1. append + count + read
# ==============================================================================
class TestAppendAndRead:
    """D5: 追加写与读取"""

    def test_append_increases_count(self, tmp_path):
        store = StreamingSampleStore(tmp_path / "samples.db")
        assert store.count() == 0
        store.append({"symbol": "BTC", "reward": 0.1, "action": "buy"})
        assert store.count() == 1
        store.append({"symbol": "ETH", "reward": -0.05, "action": "sell"})
        assert store.count() == 2

    def test_read_all(self, tmp_path):
        store = StreamingSampleStore(tmp_path / "samples.db")
        s1 = {"symbol": "BTC", "reward": 0.1}
        s2 = {"symbol": "ETH", "reward": -0.05}
        store.append(s1)
        store.append(s2)
        rows = store.read_all()
        assert len(rows) == 2
        assert rows[0]["symbol"] == "BTC"
        assert rows[1]["symbol"] == "ETH"

    def test_read_range(self, tmp_path):
        store = StreamingSampleStore(tmp_path / "samples.db")
        for i in range(10):
            store.append({"symbol": f"S{i}", "reward": float(i)})
        rows = store.read_range(2, 5)
        assert len(rows) == 3
        assert rows[0]["symbol"] == "S2"
        assert rows[2]["symbol"] == "S4"

    def test_read_range_out_of_bounds(self, tmp_path):
        store = StreamingSampleStore(tmp_path / "samples.db")
        for i in range(5):
            store.append({"symbol": f"S{i}", "reward": float(i)})
        # end 超出范围 → 返回实际存在的
        rows = store.read_range(3, 100)
        assert len(rows) == 2


# ==============================================================================
# 2. stats 聚合
# ==============================================================================
class TestStats:
    """D5: SQL 聚合统计"""

    def test_empty_stats(self, tmp_path):
        store = StreamingSampleStore(tmp_path / "samples.db")
        stats = store.stats()
        assert stats["count"] == 0
        assert stats["mean_reward"] == 0.0
        assert stats["std_reward"] == 0.0

    def test_stats_with_samples(self, tmp_path):
        store = StreamingSampleStore(tmp_path / "samples.db")
        store.append({"symbol": "BTC", "reward": 0.1})
        store.append({"symbol": "BTC", "reward": 0.2})
        store.append({"symbol": "BTC", "reward": 0.0})  # reward=0 不计入有效
        store.append({"symbol": "BTC", "reward": -0.1})
        stats = store.stats()
        assert stats["count"] == 4
        assert stats["effective_count"] == 3  # reward!=0
        assert abs(stats["mean_reward"] - 0.05) < 1e-6
        assert stats["std_reward"] > 0

    def test_sharpe_in_stats(self, tmp_path):
        store = StreamingSampleStore(tmp_path / "samples.db")
        for r in [0.1, 0.2, 0.3, -0.1, 0.05]:
            store.append({"symbol": "BTC", "reward": r})
        stats = store.stats()
        assert "sharpe" in stats
        assert isinstance(stats["sharpe"], float)


# ==============================================================================
# 3. JSONL 迁移（HC-DS4-06 向后兼容）
# ==============================================================================
class TestJsonlMigration:
    """D5: 从现有 JSONL 迁移"""

    def _make_jsonl(self, tmp_path, samples):
        p = tmp_path / "shadow_rl_samples.jsonl"
        with open(p, "w", encoding="utf-8") as f:
            for s in samples:
                f.write(json.dumps(s) + "\n")
        return p

    def test_migrate_from_jsonl(self, tmp_path):
        samples = [
            {"symbol": "BTC", "reward": 0.1, "action": "buy"},
            {"symbol": "ETH", "reward": -0.05, "action": "sell"},
            {"symbol": "BTC", "reward": 0.0, "action": "hold"},
        ]
        jsonl_path = self._make_jsonl(tmp_path, samples)
        store = StreamingSampleStore(tmp_path / "samples.db")
        n = store.migrate_from_jsonl(jsonl_path)
        assert n == 3
        assert store.count() == 3

    def test_migrate_skips_invalid_lines(self, tmp_path):
        p = tmp_path / "bad.jsonl"
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps({"symbol": "BTC", "reward": 0.1}) + "\n")
            f.write("not a json line\n")
            f.write(json.dumps({"symbol": "ETH", "reward": 0.2}) + "\n")
        store = StreamingSampleStore(tmp_path / "samples.db")
        n = store.migrate_from_jsonl(p)
        assert n == 2  # 跳过 1 行无效
        assert store.count() == 2

    def test_migrate_nonexistent_file_returns_zero(self, tmp_path):
        store = StreamingSampleStore(tmp_path / "samples.db")
        n = store.migrate_from_jsonl(tmp_path / "not_exist.jsonl")
        assert n == 0


# ==============================================================================
# 4. FAIL-OPEN 降级
# ==============================================================================
class TestFailOpen:
    """D5: sqlite 异常时降级为内存存储"""

    def test_fail_open_on_invalid_path(self):
        """无效路径 → 降级内存模式"""
        store = StreamingSampleStore("/tmp/nonexistent_dir_streaming/db.sqlite")
        # 降级后仍可 append
        store.append({"symbol": "BTC", "reward": 0.1})
        assert store.count() == 1
        rows = store.read_all()
        assert len(rows) == 1

    def test_fail_open_memory_mode(self):
        """显式内存模式"""
        store = StreamingSampleStore(":memory:")
        store.append({"symbol": "BTC", "reward": 0.1})
        assert store.count() == 1


# ==============================================================================
# 5. 数据完整性
# ==============================================================================
class TestDataIntegrity:
    """D5: 数据完整性保证"""

    def test_persist_across_reopen(self, tmp_path):
        """同一 db 文件跨实例数据持久化"""
        db_path = tmp_path / "samples.db"
        store1 = StreamingSampleStore(db_path)
        store1.append({"symbol": "BTC", "reward": 0.1})
        store1.append({"symbol": "ETH", "reward": 0.2})
        del store1

        store2 = StreamingSampleStore(db_path)
        assert store2.count() == 2
        rows = store2.read_all()
        assert rows[0]["symbol"] == "BTC"
        assert rows[1]["reward"] == 0.2

    def test_sample_json_serialization(self, tmp_path):
        """复杂嵌套 dict 可正确序列化/反序列化"""
        store = StreamingSampleStore(tmp_path / "samples.db")
        sample = {
            "symbol": "BTC",
            "state": {"price": 50000, "volatility": 0.02},
            "action": "buy",
            "reward": 0.15,
            "next_state": {"price": 50500},
        }
        store.append(sample)
        rows = store.read_all()
        assert rows[0]["state"]["price"] == 50000
        assert rows[0]["next_state"]["price"] == 50500
