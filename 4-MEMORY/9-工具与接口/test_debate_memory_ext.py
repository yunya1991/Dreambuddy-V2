#!/usr/bin/env python3
"""test_debate_memory_ext.py — debate_memory CBR+Elo 扩展测试 (TDD RED→GREEN)

SPEC v1.2-rc1 §6 P1: debate_memory.py 新增 CBR 案例表 + 策略权重表 + Elo 表
- add_cbr_case: CBR 案例入库
- search_cbr_cases: cosine similarity 检索 (简化版用 LIKE)
- add_strategy_weight: 策略权重记录
- get_strategy_weights: 获取策略权重
- add_elo / get_elo / update_elo: Persona Elo 持久化
- 向后兼容: 原 7 接口不变
"""
from __future__ import annotations
import os, sys, unittest

# 添加 python-server 到 path (导入 debate_trainer 的 hash encoder)
SERVER_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "1-ARCHITECTURE", "dream-harness-bridge", "packages", "python-server",
)
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

MEM_DIR = os.path.dirname(os.path.abspath(__file__))
if MEM_DIR not in sys.path:
    sys.path.insert(0, MEM_DIR)


class TestCBRCaseStorage(unittest.TestCase):
    """CBR 案例持久化。"""

    def test_add_cbr_case(self):
        from debate_memory import DebateMemory
        mem = DebateMemory(db_path=":memory:")
        case_id = mem.add_cbr_case(
            topic="BTC是数字黄金",
            topic_type="crypto",
            strategies_used='["evidence-heavy"]',
            winner="bull",
            bull_score=23.0,
            bear_score=19.0,
            effective_strategies='["evidence-heavy"]',
            adaptation_hints='["需要历史数据"]',
        )
        self.assertIsNotNone(case_id)

    def test_search_cbr_cases(self):
        from debate_memory import DebateMemory
        mem = DebateMemory(db_path=":memory:")
        mem.add_cbr_case("BTC是数字黄金", "crypto", '["evidence-heavy"]',
                         "bull", 23, 19, '["evidence-heavy"]', '[]')
        mem.add_cbr_case("AI取代人类", "ai", '["kritik"]',
                         "bear", 20, 22, '["kritik"]', '[]')
        results = mem.search_cbr_cases("BTC", top_k=2)
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]["topic"], "BTC是数字黄金")

    def test_cbr_case_count(self):
        from debate_memory import DebateMemory
        mem = DebateMemory(db_path=":memory:")
        self.assertEqual(mem.cbr_case_count(), 0)
        mem.add_cbr_case("BTC", "crypto", '[]', "bull", 20, 18, '[]', '[]')
        self.assertEqual(mem.cbr_case_count(), 1)


class TestStrategyWeightStorage(unittest.TestCase):
    """策略权重持久化。"""

    def test_add_strategy_weight(self):
        from debate_memory import DebateMemory
        mem = DebateMemory(db_path=":memory:")
        mem.add_strategy_weight(
            strategy="evidence-heavy",
            topic_type="crypto",
            alpha=2.0, beta=1.0,
        )

    def test_get_strategy_weights(self):
        from debate_memory import DebateMemory
        mem = DebateMemory(db_path=":memory:")
        mem.add_strategy_weight("evidence-heavy", "crypto", 2.0, 1.0)
        mem.add_strategy_weight("counterplan", "crypto", 1.0, 2.0)
        weights = mem.get_strategy_weights("crypto")
        self.assertIsInstance(weights, list)
        self.assertGreater(len(weights), 0)
        # 找到 evidence-heavy
        eh = [w for w in weights if w["strategy"] == "evidence-heavy"]
        self.assertEqual(len(eh), 1)
        self.assertEqual(eh[0]["alpha"], 2.0)

    def test_update_strategy_weight(self):
        from debate_memory import DebateMemory
        mem = DebateMemory(db_path=":memory:")
        mem.add_strategy_weight("evidence-heavy", "crypto", 1.0, 1.0)
        mem.update_strategy_weight("evidence-heavy", "crypto", alpha=3.0, beta=2.0)
        weights = mem.get_strategy_weights("crypto")
        eh = [w for w in weights if w["strategy"] == "evidence-heavy"][0]
        self.assertEqual(eh["alpha"], 3.0)
        self.assertEqual(eh["beta"], 2.0)


class TestEloStorage(unittest.TestCase):
    """Persona Elo 持久化。"""

    def test_add_elo(self):
        from debate_memory import DebateMemory
        mem = DebateMemory(db_path=":memory:")
        mem.add_elo("乐观分析师", elo=1200.0, debates=0)

    def test_get_elo(self):
        from debate_memory import DebateMemory
        mem = DebateMemory(db_path=":memory:")
        mem.add_elo("乐观分析师", elo=1200.0, debates=0)
        elo = mem.get_elo("乐观分析师")
        self.assertIsNotNone(elo)
        self.assertEqual(elo["elo"], 1200.0)

    def test_update_elo(self):
        from debate_memory import DebateMemory
        mem = DebateMemory(db_path=":memory:")
        mem.add_elo("乐观分析师", elo=1200.0, debates=0)
        mem.update_elo("乐观分析师", elo=1232.0, debates=1)
        elo = mem.get_elo("乐观分析师")
        self.assertEqual(elo["elo"], 1232.0)
        self.assertEqual(elo["debates"], 1)

    def test_get_elo_nonexistent(self):
        from debate_memory import DebateMemory
        mem = DebateMemory(db_path=":memory:")
        elo = mem.get_elo("不存在")
        self.assertIsNone(elo)


class TestBackwardCompatibility(unittest.TestCase):
    """向后兼容: 原 7 接口不变。"""

    def test_original_add_still_works(self):
        from debate_memory import DebateMemory
        mem = DebateMemory(db_path=":memory:")
        mid = mem.add("测试内容", quality_level="B", tags="debate")
        self.assertIsNotNone(mid)

    def test_original_search_still_works(self):
        from debate_memory import DebateMemory
        mem = DebateMemory(db_path=":memory:")
        mem.add("BTC辩论", quality_level="B", tags="debate,crypto")
        results = mem.search("BTC", top_k=5)
        self.assertGreater(len(results), 0)

    def test_original_stats_still_works(self):
        from debate_memory import DebateMemory
        mem = DebateMemory(db_path=":memory:")
        stats = mem.stats()
        self.assertIsInstance(stats, dict)
        self.assertIn("total", stats)


if __name__ == "__main__":
    unittest.main(verbosity=2)
