"""PollingTraderLogCollector 单元测试 — P2 DSH 层交易日志采集器.

测试覆盖:
  TR-3.1  类存在且实现 TrainingDataProvider 接口
  TR-3.2  get_source_name() 返回 "polling_trader_log"
  TR-3.3  get_quality_threshold() 返回 "B"
  TR-3.4  fetch_cases() 采集 TrainingCase
  TR-3.5  node_sequence 含交易决策节点
  TR-3.6  layer_tags 包含 "DSH"
  TR-3.7  FAIL-OPEN: 文件不存在返回空列表
  TR-3.8  FAIL-OPEN: 空日志文件返回空列表
"""
import os
import sys
import tempfile
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ADAPTERS_DIR = os.path.join(os.path.dirname(_THIS_DIR), "adapters")
_34_DIR = os.path.dirname(_THIS_DIR)

for _p in [_THIS_DIR, _ADAPTERS_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


class PollingTraderLogCollectorTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix="trader_log_test_")
        cls._logfile = os.path.join(cls._tmpdir, "trading_stdout.log")
        with open(cls._logfile, "w") as f:
            f.write("[BDSM 微仓实盘] 单币预算硬上限=250.00 U\n")
            f.write("[2026-10-12 16:52:17] [INFO] [BCRM2.0] 健康检查项: BCRM2Adapter 导入\n")
            f.write("[2026-10-12 16:52:17] [INFO] [BCRM2.0] 模式已启用\n")
            f.write("[2026-10-12 16:52:20] [INFO] [CBR] 案例检索增强已初始化\n")
            f.write("[2026-10-12 16:52:20] [INFO] [A7] 实践论门禁已初始化\n")
            f.write("[2026-10-12 16:52:23] [INFO] [持仓同步] 已同步 AMZN long @ 256.0\n")
            f.write("[2026-10-12 16:52:24] [WARN] [持仓同步] ARB 止损修复\n")
            f.write("[2026-10-12 16:53:00] [INFO] [Score_B] cont=0.75 conf=0.70 score=0.73\n")
            f.write("[2026-10-12 16:53:01] [INFO] [BDSM] 出场巡检: BTC 持仓正常\n")
            f.write("[2026-10-12 16:53:02] [INFO] [战略层] 影子模式检查通过\n")

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def test_class_exists_and_implements_interface(self):
        from polling_trader_log_collector import PollingTraderLogCollector
        from interfaces.training_data_provider import TrainingDataProvider
        self.assertIsInstance(PollingTraderLogCollector(), TrainingDataProvider)

    def test_get_source_name(self):
        from polling_trader_log_collector import PollingTraderLogCollector
        self.assertEqual(PollingTraderLogCollector().get_source_name(), "polling_trader_log")

    def test_get_quality_threshold(self):
        from polling_trader_log_collector import PollingTraderLogCollector
        self.assertEqual(PollingTraderLogCollector().get_quality_threshold(), "B")

    def test_fetch_cases_returns_training_cases(self):
        from polling_trader_log_collector import PollingTraderLogCollector
        c = PollingTraderLogCollector(log_path=self._logfile)
        cases = c.fetch_cases(limit=100)
        self.assertGreater(len(cases), 0, "应至少采集1条")

    def test_node_sequence_has_decision_nodes(self):
        from polling_trader_log_collector import PollingTraderLogCollector
        c = PollingTraderLogCollector(log_path=self._logfile)
        cases = c.fetch_cases(limit=100)
        # node_sequence 应含 BCRM2 或 持仓同步 或 Score_B 等决策节点
        all_actions = ",".join(a for case in cases for a in case.actions)
        self.assertTrue(
            any(kw in all_actions for kw in ["BCRM2", "持仓同步", "Score_B", "CBR", "BDSM"]),
            f"node_sequence 应含决策节点, got: {all_actions[:200]}"
        )

    def test_layer_tags_contains_dsh(self):
        from polling_trader_log_collector import PollingTraderLogCollector
        c = PollingTraderLogCollector(log_path=self._logfile)
        for case in c.fetch_cases(limit=10):
            self.assertIn("DSH", case.layer_tags)

    def test_fail_open_file_missing(self):
        from polling_trader_log_collector import PollingTraderLogCollector
        c = PollingTraderLogCollector(log_path="/nonexistent/log.log")
        self.assertEqual(c.fetch_cases(limit=10), [])

    def test_fail_open_empty_file(self):
        from polling_trader_log_collector import PollingTraderLogCollector
        empty = os.path.join(self._tmpdir, "empty.log")
        with open(empty, "w") as f:
            f.write("")
        c = PollingTraderLogCollector(log_path=empty)
        self.assertEqual(c.fetch_cases(limit=10), [])


if __name__ == "__main__":
    unittest.main()
