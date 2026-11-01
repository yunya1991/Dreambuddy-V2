"""反思链路单测：做梦循环 / 回放池 / 记录器 / 做梦节点回归。

覆盖此前缺陷的回归场景：
- 做梦节点缺省 current（缺陷 1：未传必填参数导致 TypeError）
- 记录器回流与 FAIL-OPEN（缺陷 2：记录器未接入生产链路）
- 做梦抽样限制（缺陷 3：全量重放性能）
"""
import os
import sys
import tempfile
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.reflection.replay_simulator import ReplayPool
from core.reflection.recorder import AnalysisRecorder
from core.reflection.seed_cases import SEED_CASES, build_seed_tree
from core.reflection.dreaming import DreamingLoop


def _fill_pool(pool_dir, n=10):
    pool = ReplayPool(pool_dir)
    i = 0
    while pool.count("internal") < n:
        for case in SEED_CASES:
            tree = build_seed_tree(case)
            tree.tree_id = "%s_dup%d" % (tree.tree_id, i)
            pool.save(tree)
            i += 1
            if pool.count("internal") >= n:
                break
    return pool


class TestReplayPool(unittest.TestCase):
    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            pool = _fill_pool(tmp, n=2)
            trees = pool.list_trees("internal")
            self.assertEqual(len(trees), 2)
            tid = trees[0].tree_id
            loaded = pool.load(tid)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.tree_id, tid)

    def test_count_and_eval_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            pool = ReplayPool(tmp)
            self.assertEqual(pool.count(), 0)
            self.assertFalse(pool.eval_ready())
            _fill_pool(tmp, n=10)
            self.assertTrue(pool.eval_ready())


class TestAnalysisRecorder(unittest.TestCase):
    def test_record_and_commit_reflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = AnalysisRecorder(pool_dir=tmp)
            self.assertTrue(rec.begin({"target": "t", "task_type": "analyze"}))
            self.assertTrue(rec.record("dependency_graph", params={"target": "t"},
                                       poe_score=0.8, evidence_refs=[{"source": "s"}]))
            tree_id = rec.commit()
            self.assertIsNotNone(tree_id)
            pool = ReplayPool(tmp)
            self.assertEqual(pool.count(), 1)
            tree = pool.load(tree_id)
            analyzers = [n.action.get("analyzer") for n in tree.nodes]
            self.assertIn("dependency_graph", analyzers)

    def test_fail_open_invalid_pool(self):
        # 记录器对无效池目录构造时内部捕获异常（不抛出），
        # 表现为 begin() 返回 False；FAIL-OPEN 由调用方节点保证（见 TestAnalyzeNodeRecorder）
        rec = AnalysisRecorder(pool_dir="/nonexistent/readonly/pool")
        self.assertFalse(rec.begin({"target": "t", "task_type": "analyze"}))
        self.assertFalse(rec.active)


class TestDreamingLoop(unittest.TestCase):
    def test_dream_with_explicit_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fill_pool(tmp, n=10)
            pool = ReplayPool(tmp)
            seq = [s["analyzer"] for s in SEED_CASES[0]["steps"]]
            current = {"budget": {"max_calls": 10}, "parallelism": 1,
                       "analyzer_sequence": seq, "transform": "current"}
            result = DreamingLoop(pool).dream(current)
            self.assertIn("best_v", result)
            self.assertIn("current_v", result)
            self.assertGreaterEqual(result["best_v"], result["current_v"] - 1e-9)

    def test_sampling_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            _fill_pool(tmp, n=30)
            pool = ReplayPool(tmp)
            seq = [s["analyzer"] for s in SEED_CASES[0]["steps"]]
            current = {"budget": {"max_calls": 10}, "parallelism": 1,
                       "analyzer_sequence": seq, "transform": "current"}
            loop = DreamingLoop(pool, max_trees=10)
            r = loop.evaluate_strategy(current)
            self.assertEqual(r["tree_count"], 10)


class TestDreamNodeRegression(unittest.TestCase):
    """缺陷 1 回归：做梦节点缺省 current 不再抛 TypeError。"""

    def test_dream_node_default_current(self):
        from dsh_nodes import DSH_NODE_REGISTRY
        with tempfile.TemporaryDirectory() as tmp:
            _fill_pool(tmp, n=10)
            out = DSH_NODE_REGISTRY["s33_rea_dream"]({"pool_dir": tmp})
            self.assertTrue(out.get("ok"), "dream node failed: %s" % out.get("error"))
            r = out.get("result") or {}
            self.assertTrue(r.get("current_derived_from_pool"))
            self.assertIn("best_v", r)

    def test_dream_node_explicit_current(self):
        from dsh_nodes import DSH_NODE_REGISTRY
        with tempfile.TemporaryDirectory() as tmp:
            _fill_pool(tmp, n=10)
            seq = [s["analyzer"] for s in SEED_CASES[0]["steps"]]
            out = DSH_NODE_REGISTRY["s33_rea_dream"]({
                "pool_dir": tmp,
                "current": {"budget": {"max_calls": 10}, "parallelism": 1,
                            "analyzer_sequence": seq, "transform": "current"},
            })
            self.assertTrue(out.get("ok"))
            r = out.get("result") or {}
            self.assertFalse(r.get("current_derived_from_pool"))

    def test_dream_node_pool_not_ready(self):
        from dsh_nodes import DSH_NODE_REGISTRY
        with tempfile.TemporaryDirectory() as tmp:
            _fill_pool(tmp, n=2)
            out = DSH_NODE_REGISTRY["s33_rea_dream"]({"pool_dir": tmp})
            self.assertFalse(out.get("ok"))
            self.assertEqual(out.get("error"), "pool_not_eval_ready")


class TestAnalyzeNodeRecorder(unittest.TestCase):
    """缺陷 2 回归：分析节点自动回流回放池。"""

    def test_analyze_reflow_and_fail_open(self):
        from dsh_nodes import DSH_NODE_REGISTRY
        with tempfile.TemporaryDirectory() as tmp:
            out = DSH_NODE_REGISTRY["s33_rea_analyze"]({
                "target": os.path.join(_PROJECT_ROOT, "core", "reflection"),
                "pool_dir": tmp,
            })
            self.assertTrue(out.get("ok"), "analyze failed: %s" % out.get("error"))
            r = out.get("result") or {}
            self.assertTrue(r.get("replay_tree_id"), "recorder did not reflow")
            self.assertGreaterEqual(ReplayPool(tmp).count(), 1)
            # FAIL-OPEN：池不可写时分析仍成功
            out2 = DSH_NODE_REGISTRY["s33_rea_analyze"]({
                "target": os.path.join(_PROJECT_ROOT, "core", "reflection", "recorder.py"),
                "pool_dir": "/nonexistent/readonly/pool",
            })
            self.assertTrue(out2.get("ok"), "FAIL-OPEN violated")


if __name__ == "__main__":
    unittest.main()
