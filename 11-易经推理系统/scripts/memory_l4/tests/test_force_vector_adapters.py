"""TC: 力向量适配层测试。

验证 LeastResistanceAdapter / SignalEngineAdapter 正确复用 9-基本面 引擎输出。
对应 Spec §二 ForceVector 核心字段映射。
"""
import pytest
import sys
from pathlib import Path

# 将 memory_l4 加入 sys.path（force_vector 包所在目录）
_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))

# 将 9-基本面分析 加入 sys.path（导入 engines）
_ROOT = _L4_DIR.parent.parent.parent  # dreambuddy-v2
_9_FUND = _ROOT / "9-基本面分析"
if _9_FUND.is_dir() and str(_9_FUND) not in sys.path:
    sys.path.insert(0, str(_9_FUND))

from force_vector.adapters import LeastResistanceAdapter, SignalEngineAdapter
from engines.least_resistance import compute_resistance_3d
from engines.signal_engine import SignalEngine


class TestLeastResistanceAdapter:
    """验证 r3d dict → ForceVector 核心字段映射。"""

    def test_direction_uses_direction_score_not_string(self):
        """direction 必须取 direction_score(float)，而非字符串 'up'。"""
        adapter = LeastResistanceAdapter()
        r3d = compute_resistance_3d(0.6, [0.1, 0.2, 0.3, 0.4, 0.5])
        fields = adapter.to_force_vector_fields("dao", r3d)
        # direction 应为 float，取自 direction_score
        assert isinstance(fields["direction"], float)
        assert fields["direction"] == pytest.approx(r3d["direction_score"])
        # 确保不是字符串 "up"
        assert fields["direction"] != "up"

    def test_magnitude_is_abs_of_direction_score(self):
        """magnitude = |direction_score|。"""
        adapter = LeastResistanceAdapter()
        r3d = compute_resistance_3d(-0.7, [-0.1, -0.2, -0.3])
        fields = adapter.to_force_vector_fields("di", r3d)
        assert fields["magnitude"] == pytest.approx(abs(r3d["direction_score"]))

    def test_velocity_acceleration_confidence_mapped(self):
        """velocity/acceleration/confidence 透传。"""
        adapter = LeastResistanceAdapter()
        r3d = compute_resistance_3d(0.5, [0.1, 0.2, 0.3, 0.4])
        fields = adapter.to_force_vector_fields("jiang", r3d)
        assert fields["velocity"] == pytest.approx(r3d["velocity"])
        assert fields["acceleration"] == pytest.approx(r3d["acceleration"])
        assert fields["confidence"] == pytest.approx(r3d["confidence"])

    def test_dimension_passthrough(self):
        """dimension 原样透传。"""
        adapter = LeastResistanceAdapter()
        r3d = compute_resistance_3d(0.3, [])
        fields = adapter.to_force_vector_fields("fa", r3d, raw_confidence=0.5)
        assert fields["dimension"] == "fa"

    def test_confidence_fallback_to_raw(self):
        """r3d 无 confidence 字段时回退 raw_confidence。"""
        adapter = LeastResistanceAdapter()
        r3d = {"direction_score": 0.4, "velocity": 0.1, "acceleration": 0.0}
        fields = adapter.to_force_vector_fields("tian", r3d, raw_confidence=0.55)
        assert fields["confidence"] == pytest.approx(0.55)


class TestSignalEngineAdapter:
    """验证 SignalEngineAdapter 在正常/异常情况下返回合理值。"""

    def test_bayesian_confidence_raw_when_predictions_insufficient(self):
        """predictions<10 → 返回 raw_confidence（SignalEngine 原始行为）。"""
        adapter = SignalEngineAdapter()
        se = SignalEngine()
        out = adapter.bayesian_confidence(se, "flow", 0.6)
        assert out == pytest.approx(0.6)

    def test_bayesian_confidence_modified_when_enough_predictions(self):
        """predictions>=10 → 贝叶斯修正生效，返回值在 [0.1, 0.95]。"""
        adapter = SignalEngineAdapter()
        se = SignalEngine()
        for _ in range(15):
            se.update_module_performance("flow", True)
        out = adapter.bayesian_confidence(se, "flow", 0.6)
        assert 0.1 <= out <= 0.95

    def test_bayesian_confidence_fallback_on_exception(self):
        """signal_engine=None → 返回 raw_confidence。"""
        adapter = SignalEngineAdapter()
        out = adapter.bayesian_confidence(None, "flow", 0.6)
        assert out == pytest.approx(0.6)

    def test_bayesian_confidence_fallback_on_missing_method(self):
        """signal_engine 无 _bayesian_confidence 方法 → 返回 raw_confidence。"""
        adapter = SignalEngineAdapter()
        out = adapter.bayesian_confidence(object(), "flow", 0.42)
        assert out == pytest.approx(0.42)

    def test_adaptive_weight_returns_base_when_insufficient(self):
        """predictions<5 → 返回 base 权重（>0）。"""
        adapter = SignalEngineAdapter()
        se = SignalEngine()
        out = adapter.adaptive_weight(se, "flow")
        assert out > 0.0

    def test_adaptive_weight_modified_when_enough_predictions(self):
        """predictions>=5 → 自适应权重生效，返回值在合理范围。"""
        adapter = SignalEngineAdapter()
        se = SignalEngine()
        for _ in range(10):
            se.update_module_performance("flow", True)
        out = adapter.adaptive_weight(se, "flow")
        assert out > 0.0

    def test_adaptive_weight_fallback_on_exception(self):
        """signal_engine=None → 返回 1.0。"""
        adapter = SignalEngineAdapter()
        out = adapter.adaptive_weight(None, "flow")
        assert out == pytest.approx(1.0)
