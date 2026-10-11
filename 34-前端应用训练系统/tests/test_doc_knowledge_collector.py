"""DocKnowledgeCollector 单元测试。

测试:
  1. INDEX.md 中的文档条目被采集
  2. TrainingCase 字段正确映射（文档名→intent, 职责→outcome_text）
  3. layer_tags 包含 G（背景知识层）和 LLM
  4. 增量采集：INDEX.md 修改时间 > since 时才采集
  5. FAIL-OPEN：INDEX.md 不存在时返回空列表
"""
import os
import sys
import tempfile
import time
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ADAPTERS_DIR = os.path.join(os.path.dirname(_THIS_DIR), "adapters")
_34_DIR = os.path.dirname(_THIS_DIR)

for _p in [_THIS_DIR, _ADAPTERS_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


class DocKnowledgeCollectorTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """创建临时 INDEX.md 用于测试。"""
        cls._tmpdir = tempfile.mkdtemp(prefix="doc_test_")
        cls._index_path = os.path.join(cls._tmpdir, "INDEX.md")

        test_index = """# 全项目文档索引

## L0 — 顶层元文档

| 文档 | 路径 | 职责 |
|------|------|------|
| 项目入口 | [README.md](../README.md) | 极简入口 |
| 文档管理中枢 | [0-系统文档管理/README.md](./README.md) | 文档体系的元层管理 |

## L1 — 顶层架构

| 文档 | 路径 | 职责 | 状态 |
|------|------|------|------|
| 架构总览 | [SYSTEM_ARCHITECTURE_OVERVIEW.md](../1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md) | 架构唯一事实源 | ✅ |
| 治理章程 | [GOVERNANCE_CHARTER.md](../2-GOVERNANCE/GOVERNANCE_CHARTER.md) | 系统根本大法 | ✅ |
"""
        with open(cls._index_path, "w", encoding="utf-8") as f:
            f.write(test_index)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def test_collect_doc_entries(self):
        """INDEX.md 中的文档条目应被采集。"""
        from doc_knowledge_collector import DocKnowledgeCollector

        collector = DocKnowledgeCollector(index_path=self._index_path)
        cases = collector.fetch_cases(limit=100)

        # 4 个文档条目
        self.assertEqual(len(cases), 4)

        intents = [c.intent for c in cases]
        self.assertIn("项目入口", intents)
        self.assertIn("架构总览", intents)

    def test_training_case_fields_mapped(self):
        """TrainingCase 字段正确映射。"""
        from doc_knowledge_collector import DocKnowledgeCollector

        collector = DocKnowledgeCollector(index_path=self._index_path)
        cases = collector.fetch_cases(limit=100)

        arch_case = [c for c in cases if c.intent == "架构总览"][0]

        self.assertEqual(arch_case.source, "doc")
        self.assertIn("架构唯一事实源", arch_case.outcome_text)
        # layer_tags 包含 G 和 LLM
        self.assertIn("G", arch_case.layer_tags)
        self.assertIn("LLM", arch_case.layer_tags)
        self.assertEqual(arch_case.quality, "B")
        self.assertIn("path", arch_case.metadata)

    def test_source_name(self):
        from doc_knowledge_collector import DocKnowledgeCollector
        collector = DocKnowledgeCollector(index_path=self._index_path)
        self.assertEqual(collector.get_source_name(), "doc")

    def test_quality_threshold(self):
        from doc_knowledge_collector import DocKnowledgeCollector
        collector = DocKnowledgeCollector(index_path=self._index_path)
        self.assertEqual(collector.get_quality_threshold(), "B")

    def test_fail_open_index_missing(self):
        """INDEX.md 不存在时返回空列表。"""
        from doc_knowledge_collector import DocKnowledgeCollector
        collector = DocKnowledgeCollector(index_path="/nonexistent/INDEX.md")
        cases = collector.fetch_cases(limit=10)
        self.assertEqual(cases, [])

    def test_incremental_by_mtime(self):
        """增量采集：since > mtime 时返回空，since < mtime 时返回数据。"""
        from doc_knowledge_collector import DocKnowledgeCollector

        collector = DocKnowledgeCollector(index_path=self._index_path)

        # since 远小于 mtime → 应返回全部
        mtime = os.path.getmtime(self._index_path)
        since_old = str(int(mtime * 1000) - 1000)
        cases_old = collector.fetch_cases(limit=100, since=since_old)
        self.assertTrue(len(cases_old) > 0)

        # since 远大于 mtime → 应返回空（无新数据）
        since_new = str(int(mtime * 1000) + 100000)
        cases_new = collector.fetch_cases(limit=100, since=since_new)
        self.assertEqual(cases_new, [])


if __name__ == "__main__":
    unittest.main()
