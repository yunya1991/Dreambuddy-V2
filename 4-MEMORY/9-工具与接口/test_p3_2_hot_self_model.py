"""P3-2 HOT Self-Model TDD RED 测试

HOT (Higher-Order Thought) 高阶自我监控，监控 workspace 内容的可靠性：
  1. check_calibration(confidence, actual_accuracy) — 置信度校准
  2. find_contradictions(workspace_content) — 矛盾检测
  3. detect_errors(workspace_content) — 错误监测（类比 ACC 前扣带回）
  4. monitor(workspace_content) — 综合监控 → action: verify/proceed

RED 契约:
  1. self_model 模块不存在 → ImportError
  2. SelfModel 类不存在
  3. check_calibration / find_contradictions / detect_errors / monitor 不存在
  4. CognitiveLoopEntry 无 self_model 属性

参考: SPEC-CognitiveSystem-Evolution.md §2.5.2 + §4.3 P3-2
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


class TestSelfModelCalibration:
    """置信度校准能力。"""

    def test_import_self_model(self):
        """RED: self_model 模块可导入。"""
        from self_model import SelfModel  # noqa: F401

    def test_check_calibration_perfect(self):
        """RED: confidence == actual_accuracy → 校准分 1.0。"""
        from self_model import SelfModel

        sm = SelfModel()
        score = sm.check_calibration(confidence=0.8, actual_accuracy=0.8)
        assert score == 1.0

    def test_check_calibration_mismatch(self):
        """RED: 置信度与准确率差距大 → 校准分低。"""
        from self_model import SelfModel

        sm = SelfModel()
        score = sm.check_calibration(confidence=0.9, actual_accuracy=0.3)
        assert score < 0.5

    def test_check_calibration_range(self):
        """RED: 校准分在 [0, 1] 范围内。"""
        from self_model import SelfModel

        sm = SelfModel()
        for c, a in [(0.0, 1.0), (1.0, 0.0), (0.5, 0.5)]:
            score = sm.check_calibration(confidence=c, actual_accuracy=a)
            assert 0.0 <= score <= 1.0

    def test_check_calibration_failopen_none(self):
        """RED: actual_accuracy=None → FAIL-OPEN 返回 1.0（不阻塞）。"""
        from self_model import SelfModel

        sm = SelfModel()
        score = sm.check_calibration(confidence=0.8, actual_accuracy=None)
        assert score == 1.0


class TestSelfModelContradictions:
    """矛盾检测能力。"""

    def test_find_contradictions_none(self):
        """RED: 无矛盾时返回空列表。"""
        from self_model import SelfModel
        from workspace_bus import WorkspaceContent

        sm = SelfModel()
        content = WorkspaceContent(
            intent={"type": "query"},
            memory_recall=[{"id": "VM-1", "content": "价格上涨", "score": 0.9}],
            skill_match=[{"id": "skill-1", "score": 0.8}],
            knowledge_retrieval=[],
            confidence=0.85,
        )
        contradictions = sm.find_contradictions(content)
        assert contradictions == []

    def test_find_contradictions_detected(self):
        """RED: 检测到矛盾（同一 subject 相反结论）。"""
        from self_model import SelfModel
        from workspace_bus import WorkspaceContent

        sm = SelfModel()
        content = WorkspaceContent(
            intent={"type": "query"},
            memory_recall=[
                {"id": "VM-1", "subject": "price", "conclusion": "上涨", "score": 0.9},
                {"id": "VM-2", "subject": "price", "conclusion": "下跌", "score": 0.85},
            ],
            skill_match=[],
            knowledge_retrieval=[],
            confidence=0.7,
        )
        contradictions = sm.find_contradictions(content)
        assert len(contradictions) > 0
        assert "price" in str(contradictions)

    def test_find_contradictions_failopen(self):
        """RED: content 异常时返回空列表（FAIL-OPEN）。"""
        from self_model import SelfModel

        sm = SelfModel()
        assert sm.find_contradictions(None) == []


class TestSelfModelErrors:
    """错误监测能力（类比 ACC 前扣带回）。"""

    def test_detect_errors_none(self):
        """RED: 无错误时返回空列表。"""
        from self_model import SelfModel
        from workspace_bus import WorkspaceContent

        sm = SelfModel()
        content = WorkspaceContent(
            intent={"type": "query"},
            memory_recall=[{"id": "VM-1", "score": 0.9}],
            skill_match=[{"id": "skill-1", "score": 0.8}],
            knowledge_retrieval=[{"id": "chunk-1", "score": 0.7}],
            confidence=0.85,
        )
        errors = sm.detect_errors(content)
        assert errors == []

    def test_detect_errors_high_confidence_empty_recall(self):
        """RED: 高置信但 recall 为空 → 检测为错误。"""
        from self_model import SelfModel
        from workspace_bus import WorkspaceContent

        sm = SelfModel()
        content = WorkspaceContent(
            intent={"type": "query"},
            memory_recall=[],
            skill_match=[],
            knowledge_retrieval=[],
            confidence=0.95,  # 高置信但无任何召回
        )
        errors = sm.detect_errors(content)
        assert len(errors) > 0

    def test_detect_errors_confidence_out_of_range(self):
        """RED: 置信度超出 [0,1] → 检测为错误。"""
        from self_model import SelfModel
        from workspace_bus import WorkspaceContent

        sm = SelfModel()
        content = WorkspaceContent(
            intent={},
            memory_recall=[{"id": "VM-1"}],
            skill_match=[],
            knowledge_retrieval=[],
            confidence=1.5,  # 超范围
        )
        errors = sm.detect_errors(content)
        assert any("range" in str(e).lower() or "confidence" in str(e).lower() for e in errors)

    def test_detect_errors_failopen(self):
        """RED: content 异常时返回空列表（FAIL-OPEN）。"""
        from self_model import SelfModel

        sm = SelfModel()
        assert sm.detect_errors(None) == []


class TestSelfModelMonitor:
    """综合监控 monitor() 能力。"""

    def test_monitor_proceed_when_clean(self):
        """RED: 无矛盾无错误 → action=proceed。"""
        from self_model import SelfModel
        from workspace_bus import WorkspaceContent

        sm = SelfModel()
        content = WorkspaceContent(
            intent={"type": "query"},
            memory_recall=[{"id": "VM-1", "score": 0.9}],
            skill_match=[{"id": "skill-1", "score": 0.8}],
            knowledge_retrieval=[{"id": "chunk-1", "score": 0.7}],
            confidence=0.85,
        )
        result = sm.monitor(content)
        assert result["action"] == "proceed"

    def test_monitor_verify_on_contradiction(self):
        """RED: 检测到矛盾 → action=verify。"""
        from self_model import SelfModel
        from workspace_bus import WorkspaceContent

        sm = SelfModel()
        content = WorkspaceContent(
            intent={"type": "query"},
            memory_recall=[
                {"id": "VM-1", "subject": "price", "conclusion": "上涨"},
                {"id": "VM-2", "subject": "price", "conclusion": "下跌"},
            ],
            skill_match=[],
            knowledge_retrieval=[],
            confidence=0.7,
        )
        result = sm.monitor(content)
        assert result["action"] == "verify"
        assert len(result["targets"]) > 0

    def test_monitor_verify_on_error(self):
        """RED: 检测到错误 → action=verify。"""
        from self_model import SelfModel
        from workspace_bus import WorkspaceContent

        sm = SelfModel()
        content = WorkspaceContent(
            intent={"type": "query"},
            memory_recall=[],
            skill_match=[],
            knowledge_retrieval=[],
            confidence=0.95,  # 高置信空召回
        )
        result = sm.monitor(content)
        assert result["action"] == "verify"

    def test_monitor_verify_on_low_calibration(self):
        """RED: 校准分 < 0.5 → action=verify。"""
        from self_model import SelfModel
        from workspace_bus import WorkspaceContent

        sm = SelfModel()
        content = WorkspaceContent(
            intent={"type": "query"},
            memory_recall=[{"id": "VM-1", "score": 0.9}],
            skill_match=[],
            knowledge_retrieval=[],
            confidence=0.9,
        )
        # 提供 actual_accuracy 与 confidence 差距大
        result = sm.monitor(content, actual_accuracy=0.3)
        assert result["action"] == "verify"

    def test_monitor_returns_dict_with_keys(self):
        """RED: monitor 返回包含 action/targets/calibration 的字典。"""
        from self_model import SelfModel
        from workspace_bus import WorkspaceContent

        sm = SelfModel()
        content = WorkspaceContent(
            intent={}, memory_recall=[], skill_match=[],
            knowledge_retrieval=[], confidence=0.5,
        )
        result = sm.monitor(content)
        assert "action" in result
        assert "targets" in result
        assert "calibration" in result


class TestCognitiveLoopEntrySelfModel:
    """CognitiveLoopEntry P3-2 集成点。"""

    def test_self_model_attribute_exists(self):
        """RED: CognitiveLoopEntry 应有 self_model 属性。"""
        import inspect

        from cognitive_loop_entry import CognitiveLoopEntry

        src = inspect.getsource(CognitiveLoopEntry.__init__)
        assert "self_model" in src
        assert "SelfModel" in src
