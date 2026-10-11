"""P3-4 预测误差门控 record TDD RED 测试

借鉴预测编码/自由能原理（Friston）+ 记忆再巩固边界（Royal Society B 2026），
record 前生成"预期"（基于 recall 结果），与实际结果差异大时提高 quality_level
初值（类比情绪记忆增强）。

核心机制:
  1. compute_prediction_error(expected, actual) — 预测误差 = |expected - actual|
  2. decide_quality_level(prediction_error) — 误差 > 阈值 → B，否则 C
  3. should_accept_intrusion(base_level) — 记忆再巩固边界:
     只有弱记忆（低 base_level）才在 recall 后接受新信息侵入
  4. prepare_record_params(content, expected, actual) — 输出 record() 参数
     (content, quality_level, tags 带 prediction_error)

RED 契约:
  1. prediction_error_gate 模块不存在 → ImportError
  2. PredictionErrorGate 类不存在
  3. CognitiveLoopEntry 无 prediction_error_gate 属性

参考: SPEC-CognitiveSystem-Evolution.md §2.5.4 + §4.3 P3-4
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


class TestPredictionErrorComputation:
    """预测误差计算。"""

    def test_import_prediction_error_gate(self):
        """RED: prediction_error_gate 模块可导入。"""
        from prediction_error_gate import PredictionErrorGate  # noqa: F401

    def test_compute_error_zero_when_equal(self):
        """RED: expected == actual → 误差 0.0。"""
        from prediction_error_gate import PredictionErrorGate

        gate = PredictionErrorGate()
        assert gate.compute_prediction_error(0.7, 0.7) == 0.0

    def test_compute_error_positive(self):
        """RED: expected=0.3, actual=0.9 → 误差 0.6。"""
        from prediction_error_gate import PredictionErrorGate

        gate = PredictionErrorGate()
        assert gate.compute_prediction_error(0.3, 0.9) == pytest.approx(0.6)

    def test_compute_error_symmetric(self):
        """RED: 误差对称 |expected - actual| == |actual - expected|。"""
        from prediction_error_gate import PredictionErrorGate

        gate = PredictionErrorGate()
        assert gate.compute_prediction_error(0.2, 0.8) == gate.compute_prediction_error(0.8, 0.2)

    def test_compute_error_failopen_none(self):
        """RED: None 输入 → FAIL-OPEN 返回 0.0（不阻塞 record）。"""
        from prediction_error_gate import PredictionErrorGate

        gate = PredictionErrorGate()
        assert gate.compute_prediction_error(None, 0.5) == 0.0
        assert gate.compute_prediction_error(0.5, None) == 0.0

    def test_compute_error_failopen_invalid_string(self):
        """RED: 字符串输入 → FAIL-OPEN 返回 0.0。"""
        from prediction_error_gate import PredictionErrorGate

        gate = PredictionErrorGate()
        assert gate.compute_prediction_error("high", 0.5) == 0.0


class TestQualityLevelDecision:
    """quality_level 决策门控。"""

    def test_high_error_upgrades_to_b(self):
        """RED: 误差 > 阈值(0.3) → quality_level=B（高预测误差 → 提升初始质量）。"""
        from prediction_error_gate import PredictionErrorGate

        gate = PredictionErrorGate()
        assert gate.decide_quality_level(0.5) == "B"

    def test_error_at_threshold_is_c(self):
        """RED: 误差 == 阈值（不严格大于）→ C。"""
        from prediction_error_gate import PredictionErrorGate

        gate = PredictionErrorGate()
        assert gate.decide_quality_level(0.3) == "C"

    def test_low_error_is_c(self):
        """RED: 符合预期（误差=0.0）→ 正常质量 C。"""
        from prediction_error_gate import PredictionErrorGate

        gate = PredictionErrorGate()
        assert gate.decide_quality_level(0.0) == "C"


class TestReconsolidationBoundary:
    """记忆再巩固边界：只有弱记忆（低 base_level）才接受 recall 后新信息侵入。"""

    def test_weak_memory_accepts_intrusion(self):
        """RED: base_level 低（弱记忆）→ 接受新信息侵入 → True。"""
        from prediction_error_gate import PredictionErrorGate

        gate = PredictionErrorGate()
        assert gate.should_accept_intrusion(base_level=0.2) is True

    def test_strong_memory_resists_intrusion(self):
        """RED: base_level 高（强记忆）→ 抵抗新信息侵入 → False。"""
        from prediction_error_gate import PredictionErrorGate

        gate = PredictionErrorGate()
        assert gate.should_accept_intrusion(base_level=0.9) is False

    def test_boundary_at_threshold(self):
        """RED: base_level == 阈值（0.5）→ 边界处视为强记忆 → False。"""
        from prediction_error_gate import PredictionErrorGate

        gate = PredictionErrorGate()
        assert gate.should_accept_intrusion(base_level=0.5) is False

    def test_failopen_none_base_level(self):
        """RED: base_level=None → FAIL-OPEN 接受（不阻塞）。"""
        from prediction_error_gate import PredictionErrorGate

        gate = PredictionErrorGate()
        assert gate.should_accept_intrusion(base_level=None) is True


class TestPrepareRecordParams:
    """record() 参数准备（复用 33-REA prepare_record_params 模式）。"""

    def test_prepare_params_high_error(self):
        """RED: 高预测误差 → quality_level=B + tags 带 prediction_error。"""
        from prediction_error_gate import PredictionErrorGate

        gate = PredictionErrorGate()
        params = gate.prepare_record_params(
            content="测试内容",
            expected_outcome=0.2,
            actual_outcome=0.9,
        )
        assert params["content"] == "测试内容"
        assert params["quality_level"] == "B"
        assert "prediction_error=0.7" in params["tags"]

    def test_prepare_params_low_error(self):
        """RED: 符合预期 → quality_level=C。"""
        from prediction_error_gate import PredictionErrorGate

        gate = PredictionErrorGate()
        params = gate.prepare_record_params(
            content="测试内容",
            expected_outcome=0.5,
            actual_outcome=0.5,
        )
        assert params["quality_level"] == "C"
        assert "prediction_error=0.0" in params["tags"]

    def test_prepare_params_includes_extra_tags(self):
        """RED: 额外 tags 被合并到输出 tags。"""
        from prediction_error_gate import PredictionErrorGate

        gate = PredictionErrorGate()
        params = gate.prepare_record_params(
            content="测试",
            expected_outcome=0.1,
            actual_outcome=0.9,
            extra_tags="33-REA,逆向分析",
        )
        assert "prediction_error=0.8" in params["tags"]
        assert "33-REA,逆向分析" in params["tags"]

    def test_prepare_params_failopen(self):
        """RED: 异常输入 → FAIL-OPEN 正常质量 C 不阻塞 record。"""
        from prediction_error_gate import PredictionErrorGate

        gate = PredictionErrorGate()
        params = gate.prepare_record_params(
            content="测试",
            expected_outcome=None,
            actual_outcome=None,
        )
        assert params["quality_level"] == "C"


class TestCognitiveLoopEntryIntegration:
    """CognitiveLoopEntry P3-4 集成点。"""

    def test_prediction_error_gate_attribute_exists(self):
        """RED: CognitiveLoopEntry 应有 prediction_error_gate 属性。"""
        from cognitive_loop_entry import CognitiveLoopEntry

        src = inspect.getsource(CognitiveLoopEntry.__init__)
        assert "prediction_error_gate" in src
        assert "PredictionErrorGate" in src
