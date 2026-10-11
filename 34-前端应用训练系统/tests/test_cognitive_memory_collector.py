"""CognitiveMemoryCollector 单元测试。

测试:
  1. B级以上记忆被采集（S/A/B）
  2. C级和D级记忆被跳过
  3. TrainingCase 字段正确映射
  4. 增量采集：since 时间戳过滤
  5. FAIL-OPEN：DB 不可用时返回空列表
"""
import os
import sys
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ADAPTERS_DIR = os.path.join(os.path.dirname(_THIS_DIR), "adapters")
_34_DIR = os.path.dirname(_THIS_DIR)

for _p in [_THIS_DIR, _ADAPTERS_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


class CognitiveMemoryCollectorTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """创建临时 cognitive_memory DB 用于测试。"""
        cls._tmpdir = tempfile.mkdtemp(prefix="cognitive_test_")
        cls._db_path = os.path.join(cls._tmpdir, "cognitive_memory.db")
        cls._create_test_db()

    @classmethod
    def _create_test_db(cls):
        """创建测试 DB 并插入测试数据。"""
        conn = sqlite3.connect(cls._db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                vector BLOB,
                quality_level TEXT DEFAULT 'C',
                confidence REAL DEFAULT 0.0,
                tags TEXT DEFAULT '[]',
                memory_type TEXT DEFAULT 'experience',
                source TEXT DEFAULT '',
                created_at TEXT DEFAULT '',
                updated_at TEXT DEFAULT '',
                verify_count INTEGER DEFAULT 0,
                level TEXT DEFAULT 'observation',
                known_gaps TEXT DEFAULT '[]',
                observations TEXT DEFAULT '[]'
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_quality ON memories(quality_level)")

        # 插入各级别测试数据
        # (id, content, quality_level, confidence, tags, memory_type, source, created_at, verify_count, level)
        test_memories = [
            ("VM-S001", "S级记忆内容", "S", 0.95, '["硬约束","架构"]', "experience",
             "mcp", "2026-10-01T10:00:00Z", 10, "axiom"),
            ("VM-A001", "A级记忆内容: bug修复经验", "A", 0.80, '["bugfix","dreamos"]',
             "experience", "git-post-commit", "2026-10-02T10:00:00Z", 5, "observation"),
            ("VM-B001", "B级记忆内容: TDD最佳实践", "B", 0.50, '["tdd","测试"]',
             "experience", "mcp", "2026-10-03T10:00:00Z", 2, "observation"),
            ("VM-C001", "C级记忆内容: 未验证假设", "C", 0.30, '["假设"]',
             "experience", "mcp", "2026-10-04T10:00:00Z", 0, "hypothesis"),
            ("VM-D001", "D级已证伪内容", "D", 0.10, '["已证伪"]',
             "experience", "mcp", "2026-10-05T10:00:00Z", 0, "falsified"),
        ]

        for m in test_memories:
            conn.execute(
                "INSERT INTO memories (id, content, quality_level, confidence, tags, "
                "memory_type, source, created_at, verify_count, level, known_gaps, observations) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', '[]')",
                m
            )
        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def test_collect_b_level_and_above(self):
        """B级以上(S/A/B)记忆应被采集，C/D级应被跳过。"""
        from cognitive_memory_collector import CognitiveMemoryCollector

        collector = CognitiveMemoryCollector(db_path=self._db_path)
        cases = collector.fetch_cases(limit=100)

        # 应该只有 S/A/B = 3 条
        self.assertEqual(len(cases), 3)

        # 确认不包含 C/D 级
        qualities = [c.quality for c in cases]
        self.assertIn("S", qualities)
        self.assertIn("A", qualities)
        self.assertIn("B", qualities)
        self.assertNotIn("C", qualities)
        self.assertNotIn("D", qualities)

    def test_training_case_fields_mapped(self):
        """TrainingCase 字段应正确映射。"""
        from cognitive_memory_collector import CognitiveMemoryCollector

        collector = CognitiveMemoryCollector(db_path=self._db_path)
        cases = collector.fetch_cases(limit=100)

        # 找 B 级案例
        b_cases = [c for c in cases if c.quality == "B"]
        self.assertTrue(len(b_cases) > 0)
        case = b_cases[0]

        self.assertEqual(case.source, "cognitive")
        self.assertEqual(case.confidence, 0.50)
        self.assertTrue(len(case.outcome_text) > 0)
        self.assertTrue(len(case.learned) > 0)
        self.assertIn("id", case.metadata)
        self.assertIn("tags", case.metadata)

    def test_incremental_collect(self):
        """增量采集：since 参数应过滤旧数据。"""
        from cognitive_memory_collector import CognitiveMemoryCollector

        collector = CognitiveMemoryCollector(db_path=self._db_path)

        # 全量采集
        all_cases = collector.fetch_cases(limit=100)
        self.assertEqual(len(all_cases), 3)

        # 增量采集：只取 2026-10-03 之后的（应该只有 B001，因为 S/A 都在 10-03 之前）
        # created_at 是 TEXT 类型 ISO 格式，转 ms 时间戳
        import datetime
        dt = datetime.datetime(2026, 10, 3, 0, 0, 0, tzinfo=datetime.timezone.utc)
        since_ts = str(int(dt.timestamp() * 1000))

        new_cases = collector.fetch_cases(limit=100, since=since_ts)
        # B001 created_at = 2026-10-03T10:00:00Z > 2026-10-03T00:00:00Z → 包含
        self.assertTrue(len(new_cases) >= 1)
        ids = [c.metadata.get("id", "") for c in new_cases]
        self.assertIn("VM-B001", ids)

    def test_source_name(self):
        """get_source_name 应返回 'cognitive'。"""
        from cognitive_memory_collector import CognitiveMemoryCollector
        collector = CognitiveMemoryCollector(db_path=self._db_path)
        self.assertEqual(collector.get_source_name(), "cognitive")

    def test_quality_threshold(self):
        """get_quality_threshold 应返回 'B'。"""
        from cognitive_memory_collector import CognitiveMemoryCollector
        collector = CognitiveMemoryCollector(db_path=self._db_path)
        self.assertEqual(collector.get_quality_threshold(), "B")

    def test_fail_open_db_unavailable(self):
        """DB 不可用时，fetch_cases 应返回空列表而非抛异常。"""
        from cognitive_memory_collector import CognitiveMemoryCollector
        collector = CognitiveMemoryCollector(db_path="/nonexistent/path.db")
        cases = collector.fetch_cases(limit=10)
        self.assertEqual(cases, [])


if __name__ == "__main__":
    unittest.main()
