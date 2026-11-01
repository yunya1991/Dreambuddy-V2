"""P3 外部最优路径获取模块测试（harvest.py）。

覆盖：E1 采集 / E2 解析（含降级）/ E3 三重验证 / E4 注入 / 全链路 FAIL-OPEN。
"""

import os
import tempfile
import unittest

from core.reflection.harvest import (
    ExternalHarvester,
    HarvestSource,
    VERIFY_PASS_THRESHOLD,
)
from core.reflection.replay_simulator import ReplayPool


class TestHarvest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rea_harvest_test_")
        self.pool = ReplayPool(os.path.join(self.tmp, "pool"))
        self.harvester = ExternalHarvester(self.pool, work_dir=os.path.join(self.tmp, "work"))
        # 构造一个带源码文件的本地源
        self.src_dir = os.path.join(self.tmp, "sample_project")
        os.makedirs(os.path.join(self.src_dir, "models"), exist_ok=True)
        for name, body in [
            ("models/user.py", "class User:\n    pass\n"),
            ("models/order.py", "class Order:\n    pass\n"),
            ("service.py", "def serve():\n    return 1\n"),
        ]:
            with open(os.path.join(self.src_dir, name), "w", encoding="utf-8") as f:
                f.write(body)

    def test_e1_fetch_local_path(self):
        src = HarvestSource(source_type="local_path", location=self.src_dir, label="sample")
        self.assertEqual(self.harvester.fetch_source(src), self.src_dir)

    def test_e1_fetch_missing_dir_returns_none(self):
        src = HarvestSource(source_type="local_path", location="/nonexistent/xyz")
        self.assertIsNone(self.harvester.fetch_source(src))

    def test_e2_parse_builds_external_tree(self):
        src = HarvestSource(source_type="local_path", location=self.src_dir, label="sample")
        tree = self.harvester.parse_source(src, self.src_dir)
        self.assertIsNotNone(tree)
        self.assertEqual(tree.provenance, "external")
        self.assertGreaterEqual(len(tree.nodes), 2)  # 根 + 至少一个发现节点

    def test_e2_parse_empty_dir_returns_none(self):
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty, exist_ok=True)
        src = HarvestSource(source_type="local_path", location=empty, label="empty")
        self.assertIsNone(self.harvester.parse_source(src, empty))

    def test_e3_verify_local_source(self):
        src = HarvestSource(source_type="local_path", location=self.src_dir, label="sample")
        tree = self.harvester.parse_source(src, self.src_dir)
        rate = self.harvester.verify_tree(tree, src)
        self.assertGreaterEqual(rate, 2 / 3)  # 网络+内容通过，交叉在空池放行

    def test_e4_inject_threshold(self):
        src = HarvestSource(source_type="local_path", location=self.src_dir, label="sample")
        tree = self.harvester.parse_source(src, self.src_dir)
        # 低于阈值不注入
        self.assertIsNone(self.harvester.inject_tree(tree, VERIFY_PASS_THRESHOLD - 0.1))
        # 达到阈值注入
        tree_id = self.harvester.inject_tree(tree, VERIFY_PASS_THRESHOLD)
        self.assertIsNotNone(tree_id)
        self.assertEqual(self.pool.count("external"), 1)

    def test_e2_quality_gate_rejects_shell(self):
        """空壳树（有效节点 < MIN_EFFECTIVE_NODES）不入池（SPEC §8.7 质量门）。"""
        shell = os.path.join(self.tmp, "shell_project")
        os.makedirs(shell, exist_ok=True)
        with open(os.path.join(shell, "only.py"), "w", encoding="utf-8") as f:
            f.write("x = 1\n")
        out = self.harvester.harvest([
            HarvestSource(source_type="local_path", location=shell, label="shell"),
        ])
        self.assertEqual(len(out.injected_trees), 0)
        self.assertEqual(out.rejected[0]["stage"], "E2-quality")
        self.assertEqual(self.pool.count("external"), 0)

    def test_e4_metadata_backfilled(self):
        """注入树回填 repo_url / license / collected_at（SPEC A2）。"""
        out = self.harvester.harvest([
            HarvestSource(source_type="local_path", location=self.src_dir,
                          label="sample", license="MIT"),
        ])
        self.assertEqual(len(out.injected_trees), 1)
        tree = self.pool.list_trees("external")[0]
        self.assertEqual(tree.source_id, "sample")
        self.assertEqual(tree.repo_url, self.src_dir)
        self.assertEqual(tree.license, "MIT")
        self.assertGreater(tree.collected_at, 0)

    def test_full_pipeline_fail_open(self):
        out = self.harvester.harvest([
            HarvestSource(source_type="local_path", location=self.src_dir, label="sample"),
            HarvestSource(source_type="local_path", location="/nonexistent/xyz", label="bad"),
        ])
        self.assertTrue(out.ok)  # FAIL-OPEN：坏源不产生 error
        self.assertEqual(len(out.injected_trees), 1)
        self.assertEqual(len(out.rejected), 1)
        self.assertEqual(out.rejected[0]["stage"], "E1")


if __name__ == "__main__":
    unittest.main()
