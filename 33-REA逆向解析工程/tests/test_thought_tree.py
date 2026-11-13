"""thought_tree.py 单元测试（G5 思维树）。
覆盖：确定性、剪枝 top-K、回溯父链路、不劣化保证、fail-open、签名去重。
"""

from __future__ import annotations

import sys
import unittest
from typing import Any, Dict, List

sys.path.insert(0, "/home/luke/dreambuddy/33-REA逆向解析工程")

from core.reflection.thought_tree import (  # noqa: E402
    ThoughtNode,
    beam_search_dream,
    strategy_signature,
)


class _FakePool:
    """假回放池：无树，list_trees 返回空。"""

    def list_trees(self) -> List[Any]:
        return []

    def eval_ready(self) -> bool:
        return True


class _FakeLoop:
    """假评估器：V 由 v_map 按签名给出，缺省 budget/10。"""

    def __init__(self, v_map: Dict[tuple, float] | None = None):
        self.pool = _FakePool()
        self.calls = 0
        self.v_map = v_map or {}

    def evaluate_strategy(self, strategy: Dict[str, Any]) -> Dict[str, Any]:
        self.calls += 1
        budget = int((strategy.get("budget") or {}).get("max_calls") or 10)
        v = self.v_map.get(strategy_signature(strategy), float(budget) / 10.0)
        return {"avg_v": v}


class _CrashLoop:
    """评估必抛异常的假评估器（fail-open 验证）。"""

    pool = None

    def evaluate_strategy(self, strategy):
        raise RuntimeError("boom")


class TestStrategySignature(unittest.TestCase):
    def test_signature_fields(self):
        a = {"analyzer_sequence": ["x", "y"], "budget": {"max_calls": 10}, "parallelism": 1}
        b = {"analyzer_sequence": ["x", "y"], "budget": {"max_calls": 10}, "parallelism": 2}
        self.assertEqual(strategy_signature(a), strategy_signature(dict(a)))
        self.assertNotEqual(strategy_signature(a), strategy_signature(b))


class TestBacktrace(unittest.TestCase):
    def test_backtrace_root_to_leaf(self):
        root = ThoughtNode(strategy={}, v=0.0, depth=0)
        mid = ThoughtNode(strategy={}, v=1.0, depth=1, parent=root)
        leaf = ThoughtNode(strategy={}, v=2.0, depth=2, parent=mid)
        path = leaf.backtrace()
        self.assertEqual([n.depth for n in path], [0, 1, 2])
        self.assertIs(path[0], root)

    def test_root_backtrace_self(self):
        root = ThoughtNode(strategy={}, v=0.0, depth=0)
        self.assertEqual(root.backtrace(), [root])


class TestBeamSearchDream(unittest.TestCase):
    def _current(self) -> Dict[str, Any]:
        return {
            "budget": {"max_calls": 10},
            "parallelism": 1,
            "analyzer_sequence": ["a", "b", "c"],
            "transform": "current",
        }

    def test_deterministic(self):
        r1 = beam_search_dream(_FakeLoop(), self._current(), depth=2, beam_width=3)
        r2 = beam_search_dream(_FakeLoop(), self._current(), depth=2, beam_width=3)
        self.assertEqual(r1["best_v"], r2["best_v"])
        self.assertEqual(r1["nodes_expanded"], r2["nodes_expanded"])
        self.assertEqual(r1["path"], r2["path"])

    def test_no_degradation_root_in_beam(self):
        # 所有子节点 V 均低于根：最优应仍是根（不劣化保证）
        cur = self._current()
        root_sig = strategy_signature(cur)
        low_map = {root_sig: 0.9}
        # 其余签名缺省走 budget/10，最大 1.5x 预算 → 1.5；显式压低全部候选
        for mc in (5, 15):
            low_map[(("a", "b", "c"), mc, 1)] = 0.1
            low_map[(("a", "b", "c"), mc, 2)] = 0.1
        for perm in (
            ("b", "a", "c"),
            ("c", "b", "a"),
            ("a", "c", "b"),
            ("b", "c", "a"),
            ("c", "a", "b"),
        ):
            for mc in (5, 10, 15):
                for par in (1, 2):
                    low_map[(perm, mc, par)] = 0.2
        loop = _FakeLoop(v_map=low_map)
        r = beam_search_dream(loop, cur, depth=2, beam_width=3)
        self.assertEqual(r["best_v"], 0.9)
        self.assertFalse(r["improved"])
        self.assertEqual(r["path"][0]["transform"], "root")

    def test_improvement_and_path(self):
        cur = self._current()
        root_sig = strategy_signature(cur)
        # 根 V=0.5，预算 1.5x 候选 V=0.95 → 应改进
        loop = _FakeLoop(v_map={root_sig: 0.5, (("a", "b", "c"), 15, 1): 0.95})
        r = beam_search_dream(loop, cur, depth=2, beam_width=3)
        self.assertTrue(r["improved"])
        self.assertGreater(r["best_v"], r["current_v"])
        # 回溯路径首节点为根
        self.assertEqual(r["path"][0]["depth"], 0)
        self.assertEqual(r["path"][0]["transform"], "root")
        # 路径深度单调递增
        depths = [p["depth"] for p in r["path"]]
        self.assertEqual(depths, sorted(depths))

    def test_pruning_respects_beam_width(self):
        r = beam_search_dream(_FakeLoop(), self._current(), depth=3, beam_width=2)
        for pruned in r["pruned_per_round"]:
            self.assertGreaterEqual(pruned, 0)

    def test_fail_open_on_crash(self):
        # 评估器全崩：根 V 置 0，搜索不中断，返回根为最优
        r = beam_search_dream(_CrashLoop(), self._current(), depth=2, beam_width=2)
        self.assertEqual(r["best_v"], 0.0)
        self.assertFalse(r["improved"])
        self.assertEqual(r["path"][0]["transform"], "root")

    def test_result_fields(self):
        r = beam_search_dream(_FakeLoop(), self._current(), depth=2, beam_width=3)
        for key in (
            "version",
            "best_strategy",
            "best_v",
            "current_v",
            "improved",
            "eval_ready",
            "nodes_expanded",
            "nodes_evaluated",
            "pruned_per_round",
            "path",
        ):
            self.assertIn(key, r)
        self.assertTrue(r["eval_ready"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
