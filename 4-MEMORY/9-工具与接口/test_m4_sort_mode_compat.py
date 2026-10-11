"""M4 修复 RED 测试：recall sort_mode 兼容模式。

SPEC §3.5 M4：ACT-R 重排序兼容方案
- recall(sort_mode="score") — 原有行为，向后兼容（默认）
- recall(sort_mode="act_r") — 新激活模型排序，需显式启用

当前问题：cognitive_loop_entry.py:354 无条件调用 ACT-R，破坏向后兼容。
修复目标：sort_mode 参数控制是否启用 ACT-R 排序。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest


def test_recall_accepts_sort_mode_param():
    """RED: recall 方法接受 sort_mode 参数。"""
    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry.__new__(CognitiveLoopEntry)
    # 不需要真正执行 recall，只需检查签名接受 sort_mode
    import inspect
    sig = inspect.signature(cle.recall)
    assert "sort_mode" in sig.parameters, "recall 应接受 sort_mode 参数 (M4)"


def test_recall_sort_mode_default_is_score():
    """RED: sort_mode 默认值为 'score'（向后兼容）。"""
    from cognitive_loop_entry import CognitiveLoopEntry
    import inspect
    sig = inspect.signature(CognitiveLoopEntry.recall)
    param = sig.parameters.get("sort_mode")
    assert param is not None, "recall 应有 sort_mode 参数"
    assert param.default == "score", f"sort_mode 默认应为 'score'（向后兼容），got {param.default}"


def test_recall_score_mode_does_not_call_actr(monkeypatch):
    """RED: sort_mode='score' 时不调用 ACTR rank_by_activation。"""
    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry.__new__(CognitiveLoopEntry)
    cle.actr = None  # 标记，如果被调用会失败

    call_count = {"n": 0}

    class FakeActr:
        def rank_by_activation(self, dicts, context=""):
            call_count["n"] += 1
            return dicts

    cle.actr = FakeActr()

    # mock 其他依赖
    cle.recall_cache = None
    cle.temporal_graph = None
    cle.poe_enforcement = "off"
    cle._poe_penalty = 0.5
    cle.evidence_ledger = None
    cle._startup_integrity_passed = True
    cle._sample_reverify_probability = 0.1
    cle._poe_mode = "light"

    # mock 底层数据库查询（self._vm.search）
    import unittest.mock as mock
    class FakeVM:
        def search(self, context, top_k=5, quality_filter="C"):
            return []
    cle._vm = FakeVM()

    results = cle.recall("test context", top_k=5, sort_mode="score")
    assert call_count["n"] == 0, f"sort_mode='score' 不应调用 ACT-R，但被调用了 {call_count['n']} 次"


def test_recall_actr_mode_calls_actr(monkeypatch):
    """RED: sort_mode='act_r' 时调用 ACTR rank_by_activation。"""
    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry.__new__(CognitiveLoopEntry)

    call_count = {"n": 0}

    class FakeActr:
        def rank_by_activation(self, dicts, context=""):
            call_count["n"] += 1
            return dicts

    cle.actr = FakeActr()
    cle.recall_cache = None
    cle.temporal_graph = None
    cle.poe_enforcement = "off"
    cle._poe_penalty = 0.5
    cle.evidence_ledger = None
    cle._startup_integrity_passed = True
    cle._sample_reverify_probability = 0.1
    cle._poe_mode = "light"

    import unittest.mock as mock
    class FakeVM:
        def search(self, context, top_k=5, quality_filter="C"):
            return []
    cle._vm = FakeVM()

    results = cle.recall("test context", top_k=5, sort_mode="act_r")
    assert call_count["n"] == 1, f"sort_mode='act_r' 应调用 ACT-R 1 次，got {call_count['n']}"


def test_recall_default_sort_mode_is_score(monkeypatch):
    """RED: 不传 sort_mode 时默认 score 模式（不调用 ACT-R）。"""
    from cognitive_loop_entry import CognitiveLoopEntry
    cle = CognitiveLoopEntry.__new__(CognitiveLoopEntry)

    call_count = {"n": 0}

    class FakeActr:
        def rank_by_activation(self, dicts, context=""):
            call_count["n"] += 1
            return dicts

    cle.actr = FakeActr()
    cle.recall_cache = None
    cle.temporal_graph = None
    cle.poe_enforcement = "off"
    cle._poe_penalty = 0.5
    cle.evidence_ledger = None
    cle._startup_integrity_passed = True
    cle._sample_reverify_probability = 0.1
    cle._poe_mode = "light"

    import unittest.mock as mock
    class FakeVM:
        def search(self, context, top_k=5, quality_filter="C"):
            return []
    cle._vm = FakeVM()

    # 不传 sort_mode，应默认 score
    results = cle.recall("test context", top_k=5)
    assert call_count["n"] == 0, f"默认（无 sort_mode）不应调用 ACT-R，got {call_count['n']}"
