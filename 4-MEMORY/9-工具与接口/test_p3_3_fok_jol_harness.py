"""P3-3 FOK/JOL 元认知 Harness TDD RED 测试

借鉴 arXiv:2605.14186 LLM 元认知信号研究。现状：无"我觉得能解决吗"的预评估。
方案（SPEC §2.5.3）: SKILL 执行前注入 FOK 提示，执行后注入 JOL：
  - FOK (Feeling of Knowing) 执行前: "你认为能解决此任务吗？0-1 打分"
    低 FOK → 自动 recall 补充 或 escalate 到 deep-research SKILL
  - JOL (Judgment of Learning) 执行后: "你学到了什么？0-1 打分"
    低 JOL → 标记为需要后续 verify

RED 契约:
  1. fok_jol_harness 模块不存在 → ImportError
  2. MetacogHarness 类不存在
  3. CognitiveLoopEntry 无 metacog_harness 属性

参考: SPEC-CognitiveSystem-Evolution.md §2.5.3 + §4.3 P3-3
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


class TestFOKPreExecution:
    """FOK：SKILL 执行前预评估。"""

    def test_import_fok_jol_harness(self):
        """RED: fok_jol_harness 模块可导入。"""
        from fok_jol_harness import MetacogHarness  # noqa: F401

    def test_fok_high_skill_confidence_proceed(self):
        """RED: 高 skill 匹配 + 强记忆召回 → FOK 高 → action=proceed。"""
        from fok_jol_harness import MetacogHarness

        harness = MetacogHarness()
        result = harness.pre_execute_fok(
            task="分析 BTC 趋势",
            skill_match=[{"id": "trend-analysis", "score": 0.9}],
            memory_recall=[{"id": "VM-1", "score": 0.85}, {"id": "VM-2", "score": 0.8}],
        )
        assert result["fok_score"] >= 0.5
        assert result["action"] == "proceed"

    def test_fok_low_recall_supplement(self):
        """RED: FOK 中低 (0.3-0.5) → action=recall_supplement。"""
        from fok_jol_harness import MetacogHarness

        harness = MetacogHarness()
        result = harness.pre_execute_fok(
            task="冷门任务",
            skill_match=[{"id": "s", "score": 0.4}],
            memory_recall=[],
        )
        assert result["action"] == "recall_supplement"

    def test_fok_very_low_escalate(self):
        """RED: FOK 极低 (<0.3) → action=escalate（升级 deep-research）。"""
        from fok_jol_harness import MetacogHarness

        harness = MetacogHarness()
        result = harness.pre_execute_fok(
            task="完全陌生任务",
            skill_match=[],
            memory_recall=[],
        )
        assert result["fok_score"] < 0.3
        assert result["action"] == "escalate"

    def test_fok_includes_prompt(self):
        """RED: 结果含 FOK 提示模板（注入 LLM 的预评估问句）。"""
        from fok_jol_harness import MetacogHarness

        harness = MetacogHarness()
        result = harness.pre_execute_fok(task="任务", skill_match=[], memory_recall=[])
        assert "prompt" in result
        assert len(result["prompt"]) > 0

    def test_fok_failopen_none(self):
        """RED: None 输入 → FAIL-OPEN 中性分数不阻塞。"""
        from fok_jol_harness import MetacogHarness

        harness = MetacogHarness()
        result = harness.pre_execute_fok(task=None, skill_match=None, memory_recall=None)
        assert 0.0 <= result["fok_score"] <= 1.0
        assert isinstance(result, dict)


class TestJOLPostExecution:
    """JOL：SKILL 执行后学习评估。"""

    def test_jol_success_high(self):
        """RED: 执行成功 → JOL 高 → action=record。"""
        from fok_jol_harness import MetacogHarness

        harness = MetacogHarness()
        result = harness.post_execute_jol({
            "success": True, "error": None, "output": "分析完成",
        })
        assert result["jol_score"] >= 0.5
        assert result["action"] == "record"

    def test_jol_failure_low_mark_verify(self):
        """RED: 执行失败 → JOL 低 → action=mark_verify（标记需要后续 verify）。"""
        from fok_jol_harness import MetacogHarness

        harness = MetacogHarness()
        result = harness.post_execute_jol({
            "success": False, "error": "timeout",
        })
        assert result["jol_score"] < 0.5
        assert result["action"] == "mark_verify"

    def test_jol_includes_prompt(self):
        """RED: 结果含 JOL 提示模板（"你学到了什么？0-1 打分"）。"""
        from fok_jol_harness import MetacogHarness

        harness = MetacogHarness()
        result = harness.post_execute_jol({"success": True})
        assert "prompt" in result
        assert "学到" in result["prompt"]

    def test_jol_failopen_none(self):
        """RED: None 输入 → FAIL-OPEN 不抛异常。"""
        from fok_jol_harness import MetacogHarness

        harness = MetacogHarness()
        result = harness.post_execute_jol(None)
        assert isinstance(result, dict)
        assert 0.0 <= result["jol_score"] <= 1.0


class TestCognitiveLoopEntryIntegration:
    """CognitiveLoopEntry P3-3 集成点。"""

    def test_metacog_harness_attribute_exists(self):
        """RED: CognitiveLoopEntry 应有 metacog_harness 属性。"""
        from cognitive_loop_entry import CognitiveLoopEntry

        src = inspect.getsource(CognitiveLoopEntry.__init__)
        assert "metacog_harness" in src
        assert "MetacogHarness" in src
