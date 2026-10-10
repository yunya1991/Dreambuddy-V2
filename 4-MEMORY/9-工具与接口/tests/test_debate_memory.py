"""test_debate_memory.py — 辩论记忆 7 标准接口测试 (TDD RED→GREEN)

SPEC v2.0-rc3 第五节：辩论认知模块。
4-MEMORY L2 应用记忆新增 "debate" 类型。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TOOL_DIR not in sys.path:
    sys.path.insert(0, TOOL_DIR)


class TestImport(unittest.TestCase):
    def test_importable(self):
        from debate_memory import DebateMemory  # noqa: F401


class TestAdd(unittest.TestCase):
    """add: 添加辩论记忆。"""

    def test_add_returns_memory_id(self):
        from debate_memory import DebateMemory
        mem = DebateMemory(":memory:")
        mid = mem.add(
            content=json.dumps({"thesis": "BTC稀缺性", "side": "bull"}),
            quality_level="B",
            tags="debate,argument-pattern,BTC,多空",
        )
        self.assertIsNotNone(mid)
        self.assertIsInstance(mid, str)

    def test_add_with_default_tags(self):
        """无 tags 时使用默认值。"""
        from debate_memory import DebateMemory
        mem = DebateMemory(":memory:")
        mid = mem.add(
            content="test content",
            quality_level="C",
        )
        self.assertIsNotNone(mid)


class TestGet(unittest.TestCase):
    """get: 获取单条记忆。"""

    def test_get_returns_memory(self):
        from debate_memory import DebateMemory
        mem = DebateMemory(":memory:")
        mid = mem.add(
            content=json.dumps({"thesis": "BTC稀缺性"}),
            quality_level="B",
            tags="debate,BTC",
        )
        result = mem.get(mid)
        self.assertIsNotNone(result)
        self.assertIn("content", result)

    def test_get_nonexistent_returns_none(self):
        from debate_memory import DebateMemory
        mem = DebateMemory(":memory:")
        result = mem.get("VM-nonexistent")
        self.assertIsNone(result)


class TestSearch(unittest.TestCase):
    """search: 搜索辩论记忆。"""

    def test_search_returns_list(self):
        from debate_memory import DebateMemory
        mem = DebateMemory(":memory:")
        mem.add(content=json.dumps({"thesis": "BTC稀缺"}),
                quality_level="B", tags="debate,BTC")
        mem.add(content=json.dumps({"thesis": "ETH DeFi"}),
                quality_level="C", tags="debate,ETH")
        results = mem.search("BTC", top_k=5)
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)

    def test_search_top_k_limit(self):
        """top_k 限制返回数量。"""
        from debate_memory import DebateMemory
        mem = DebateMemory(":memory:")
        for i in range(5):
            mem.add(content=f"BTC test {i}", quality_level="B",
                    tags="debate,BTC")
        results = mem.search("BTC", top_k=2)
        self.assertLessEqual(len(results), 2)


class TestUpdate(unittest.TestCase):
    """update: 更新辩论记忆。"""

    def test_update_quality(self):
        from debate_memory import DebateMemory
        mem = DebateMemory(":memory:")
        mid = mem.add(content="test", quality_level="C", tags="debate")
        updated = mem.update(mid, quality_level="A")
        self.assertTrue(updated)
        result = mem.get(mid)
        self.assertEqual(result["quality_level"], "A")


class TestStats(unittest.TestCase):
    """stats: 统计信息。"""

    def test_stats_returns_dict(self):
        from debate_memory import DebateMemory
        mem = DebateMemory(":memory:")
        mem.add(content="t1", quality_level="B", tags="debate,BTC")
        mem.add(content="t2", quality_level="C", tags="debate,ETH")
        stats = mem.stats()
        self.assertIsInstance(stats, dict)
        self.assertIn("total", stats)
        self.assertGreaterEqual(stats["total"], 2)


class TestDistillCandidates(unittest.TestCase):
    """distill_candidates: 蒸馏候选。"""

    def test_returns_b_quality_and_above(self):
        from debate_memory import DebateMemory
        mem = DebateMemory(":memory:")
        mem.add(content="high", quality_level="A", tags="debate")
        mem.add(content="mid", quality_level="B", tags="debate")
        mem.add(content="low", quality_level="C", tags="debate")
        candidates = mem.distill_candidates(min_quality="B")
        self.assertIsInstance(candidates, list)
        for c in candidates:
            self.assertNotEqual(c.get("quality_level"), "C")


class TestHealthcheck(unittest.TestCase):
    """healthcheck: 健康检查。"""

    def test_returns_ok(self):
        from debate_memory import DebateMemory
        mem = DebateMemory(":memory:")
        result = mem.healthcheck()
        self.assertIsInstance(result, dict)
        self.assertIn("ok", result)
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
