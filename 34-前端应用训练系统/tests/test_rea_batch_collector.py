"""REABatchCollector 单元测试。

测试:
  1. 扫描目录下 .py 文件被采集
  2. TrainingCase 字段正确映射（algorithm_pattern→DSH, dependency_graph→G）
  3. FAIL-OPEN：目录不存在/reduce_algorithm不可用时返回空列表
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ADAPTERS_DIR = os.path.join(os.path.dirname(_THIS_DIR), "adapters")
_34_DIR = os.path.dirname(_THIS_DIR)

for _p in [_THIS_DIR, _ADAPTERS_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


class REABatchCollectorTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """创建临时目录和测试 .py 文件。"""
        cls._tmpdir = tempfile.mkdtemp(prefix="rea_batch_test_")

        # 创建 2 个测试 .py 文件
        cls._file1 = os.path.join(cls._tmpdir, "module_a.py")
        with open(cls._file1, "w") as f:
            f.write("def foo():\n    if x > 0:\n        return 1\n")

        cls._file2 = os.path.join(cls._tmpdir, "module_b.py")
        with open(cls._file2, "w") as f:
            f.write("import os\ndef bar():\n    for i in range(10):\n        print(i)\n")

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def test_collect_python_files(self):
        """扫描目录下 .py 文件应被采集。"""
        from rea_batch_collector import REABatchCollector

        # Mock reduce_algorithm 返回测试模式
        def mock_reduce(path, **kwargs):
            return {
                "patterns": [{"type": "条件分支 conditional_branch"}],
                "evidence": [],
            }

        collector = REABatchCollector(scan_dir=self._tmpdir)
        with patch("rea_batch_collector.REABatchCollector._get_reduce_algorithm",
                    return_value=mock_reduce):
            cases = collector.fetch_cases(limit=100)

        self.assertEqual(len(cases), 2)
        intents = [c.intent for c in cases]
        self.assertIn("module_a.py", intents)
        self.assertIn("module_b.py", intents)

    def test_training_case_fields_mapped(self):
        """TrainingCase 字段正确映射：patterns→DSH, dependency→G。"""
        from rea_batch_collector import REABatchCollector

        def mock_reduce(path, **kwargs):
            return {
                "patterns": [{"type": "循环迭代 iteration"}],
                "evidence": [],
            }

        collector = REABatchCollector(scan_dir=self._tmpdir)
        with patch("rea_batch_collector.REABatchCollector._get_reduce_algorithm",
                    return_value=mock_reduce):
            cases = collector.fetch_cases(limit=10)

        self.assertTrue(len(cases) > 0)
        case = cases[0]
        self.assertEqual(case.source, "rea")
        self.assertIn("DSH", case.layer_tags)
        self.assertIn("G", case.layer_tags)
        self.assertEqual(case.quality, "B")

    def test_source_name(self):
        from rea_batch_collector import REABatchCollector
        collector = REABatchCollector(scan_dir=self._tmpdir)
        self.assertEqual(collector.get_source_name(), "rea")

    def test_quality_threshold(self):
        from rea_batch_collector import REABatchCollector
        collector = REABatchCollector(scan_dir=self._tmpdir)
        self.assertEqual(collector.get_quality_threshold(), "B")

    def test_fail_open_dir_missing(self):
        """目录不存在时返回空列表。"""
        from rea_batch_collector import REABatchCollector
        collector = REABatchCollector(scan_dir="/nonexistent/dir")
        cases = collector.fetch_cases(limit=10)
        self.assertEqual(cases, [])

    def test_fail_open_reduce_unavailable(self):
        """reduce_algorithm 不可用时返回空列表（不抛异常）。"""
        from rea_batch_collector import REABatchCollector

        collector = REABatchCollector(scan_dir=self._tmpdir)
        with patch("rea_batch_collector.REABatchCollector._get_reduce_algorithm",
                    return_value=None):
            cases = collector.fetch_cases(limit=10)
        self.assertEqual(cases, [])


if __name__ == "__main__":
    unittest.main()
