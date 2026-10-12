"""REATestCollector 单元测试 — P3 DSH 层 REA 测试采集器.

测试覆盖:
  TR-4.1  类存在且实现 TrainingDataProvider 接口
  TR-4.2  get_source_name() 返回 "rea_test"
  TR-4.3  get_quality_threshold() 返回 "B"
  TR-4.4  fetch_cases() 采集 TrainingCase
  TR-4.5  node_sequence 含 AST 调用链
  TR-4.6  layer_tags 包含 "DSH"
  TR-4.7  FAIL-OPEN: 目录不存在返回空列表
"""
import os
import sys
import tempfile
import textwrap
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ADAPTERS_DIR = os.path.join(os.path.dirname(_THIS_DIR), "adapters")
_34_DIR = os.path.dirname(_THIS_DIR)

for _p in [_THIS_DIR, _ADAPTERS_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


class REATestCollectorTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix="rea_test_collector_")
        # 样本 REA 测试文件
        with open(os.path.join(cls._tmpdir, "test_investigate_dsh.py"), "w") as f:
            f.write(textwrap.dedent('''
                def investigate_dsh(node):
                    result = analyze_node(node)
                    return classify_pattern(result)

                def test_investigate_basic():
                    result = investigate_dsh({"type": "call"})
                    assert result is not None

                def test_investigate_complex():
                    node = {"type": "branch", "depth": 3}
                    result = investigate_dsh(node)
                    pattern = classify_pattern(result)
                    assert pattern == "conditional"
            '''))

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def test_class_exists_and_implements_interface(self):
        from rea_test_collector import REATestCollector
        from interfaces.training_data_provider import TrainingDataProvider
        self.assertIsInstance(REATestCollector(), TrainingDataProvider)

    def test_get_source_name(self):
        from rea_test_collector import REATestCollector
        self.assertEqual(REATestCollector().get_source_name(), "rea_test")

    def test_get_quality_threshold(self):
        from rea_test_collector import REATestCollector
        self.assertEqual(REATestCollector().get_quality_threshold(), "B")

    def test_fetch_cases_returns_training_cases(self):
        from rea_test_collector import REATestCollector
        c = REATestCollector(scan_dirs=[(self._tmpdir, "rea")])
        cases = c.fetch_cases(limit=100)
        self.assertGreater(len(cases), 0)

    def test_node_sequence_has_call_chain(self):
        from rea_test_collector import REATestCollector
        c = REATestCollector(scan_dirs=[(self._tmpdir, "rea")])
        cases = c.fetch_cases(limit=100)
        all_actions = ",".join(a for case in cases for a in case.actions)
        self.assertIn("investigate_dsh", all_actions)

    def test_layer_tags_contains_dsh(self):
        from rea_test_collector import REATestCollector
        c = REATestCollector(scan_dirs=[(self._tmpdir, "rea")])
        for case in c.fetch_cases(limit=10):
            self.assertIn("DSH", case.layer_tags)

    def test_fail_open_dir_missing(self):
        from rea_test_collector import REATestCollector
        c = REATestCollector(scan_dirs=[("/nonexistent/dir", "rea")])
        self.assertEqual(c.fetch_cases(limit=10), [])


if __name__ == "__main__":
    unittest.main()
