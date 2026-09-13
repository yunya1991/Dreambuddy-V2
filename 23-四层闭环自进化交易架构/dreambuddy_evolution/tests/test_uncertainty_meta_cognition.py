"""
test_uncertainty_meta_cognition — Phase 5.1 + 5.2 集成测试

覆盖：
  Phase 5.1 UncertaintyQuantifier:
    - Conformal Prediction 校准 + 区间
    - Deep Ensemble 训练 + 预测
    - 不确定性评分 [0,1]
    - 端到端 predict_with_uncertainty
    - FAIL-OPEN（样本不足/异常）

  Phase 5.2 MetaCognitionGate:
    - 四档决策（low/medium/high/critical）
    - HC-AGI-06: uncertainty>0.4 → 降仓 0.5×
    - uncertainty>0.7 → 拒开仓
    - Sharpe 豁免（medium→low）
    - Confidence 校准（过度自信检测）
    - FAIL-OPEN

  集成：
    - UncertaintyQuantifier → MetaCognitionGate 端到端
"""
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from dreambuddy_evolution.core.uncertainty_quantifier import UncertaintyQuantifier
from dreambuddy_evolution.engines.meta_cognition_gate import MetaCognitionGate


# ==================================================================
# Phase 5.1: UncertaintyQuantifier
# ==================================================================
class TestConformalPrediction:
    def test_fit_conformal_success(self):
        uq = UncertaintyQuantifier(confidence=0.9)
        np.random.seed(42)
        n = 100
        X = np.random.randn(n, 3)
        y = X[:, 0] * 2.0 + np.random.randn(n) * 0.5
        result = uq.fit_conformal(X, y)
        assert result["calibrated"] is True
        assert result["conformal_quantile"] is not None
        assert result["conformal_quantile"] > 0

    def test_conformal_interval(self):
        uq = UncertaintyQuantifier(confidence=0.9)
        np.random.seed(42)
        n = 100
        X = np.random.randn(n, 3)
        y = X[:, 0] * 2.0 + np.random.randn(n) * 0.5
        uq.fit_conformal(X, y)
        lower, upper = uq.conformal_interval(0.0)
        assert lower is not None and upper is not None
        assert lower < 0 < upper

    def test_conformal_not_calibrated(self):
        uq = UncertaintyQuantifier()
        lower, upper = uq.conformal_interval(0.0)
        assert lower is None and upper is None

    def test_conformal_insufficient_samples(self):
        uq = UncertaintyQuantifier(min_calibration_samples=50)
        X = np.random.randn(10, 2)
        y = np.random.randn(10)
        result = uq.fit_conformal(X, y)
        assert result["calibrated"] is False


class TestDeepEnsemble:
    def test_fit_ensemble(self):
        uq = UncertaintyQuantifier(n_ensemble=3)
        np.random.seed(42)
        n = 100
        X = np.random.randn(n, 3)
        y = X[:, 0] * 2.0 + np.random.randn(n) * 0.5
        result = uq.fit_ensemble(X, y)
        assert result["trained"] is True
        assert result["n_models"] == 3

    def test_ensemble_predict(self):
        uq = UncertaintyQuantifier(n_ensemble=3)
        np.random.seed(42)
        n = 100
        X = np.random.randn(n, 3)
        y = X[:, 0] * 2.0 + np.random.randn(n) * 0.5
        uq.fit_ensemble(X, y)
        result = uq.ensemble_predict(X[:1])
        assert "mean" in result
        assert "std" in result
        assert result["n_models"] == 3

    def test_ensemble_untrained(self):
        uq = UncertaintyQuantifier()
        result = uq.ensemble_predict(np.array([[1.0, 2.0]]))
        assert result["std"] == 1.0  # 默认最大不确定性


class TestUncertaintyScore:
    def test_score_in_range(self):
        uq = UncertaintyQuantifier()
        result = uq.quantify_uncertainty(
            prediction=1.0, ensemble_std=0.1, conformal_width=0.2, feature_noise=0.3
        )
        assert 0.0 <= result["uncertainty_score"] <= 1.0

    def test_high_uncertainty_level(self):
        uq = UncertaintyQuantifier()
        result = uq.quantify_uncertainty(prediction=1.0, ensemble_std=5.0)
        assert result["level"] in ("high", "critical")

    def test_low_uncertainty_level(self):
        uq = UncertaintyQuantifier()
        result = uq.quantify_uncertainty(prediction=100.0, ensemble_std=0.01, conformal_width=0.01)
        assert result["level"] == "low"

    def test_failopen_returns_critical(self):
        uq = UncertaintyQuantifier()
        result = uq.quantify_uncertainty(prediction=float("nan"))
        assert result["level"] == "critical"
        assert result["uncertainty_score"] == 1.0


class TestEndToEnd:
    def test_predict_with_uncertainty(self):
        uq = UncertaintyQuantifier(n_ensemble=3)
        np.random.seed(42)
        n = 200
        X = np.random.randn(n, 3)
        y = X[:, 0] * 2.0 + np.random.randn(n) * 0.5
        result = uq.predict_with_uncertainty(X, y)
        assert "prediction" in result
        assert "uncertainty_score" in result
        assert 0.0 <= result["uncertainty_score"] <= 1.0

    def test_insufficient_samples_failopen(self):
        uq = UncertaintyQuantifier()
        X = np.random.randn(10, 2)
        y = np.random.randn(10)
        result = uq.predict_with_uncertainty(X, y)
        assert result["uncertainty_score"] == 1.0
        assert result["level"] == "critical"


# ==================================================================
# Phase 5.2: MetaCognitionGate
# ==================================================================
class TestMetaCognitionDecisions:
    def test_low_uncertainty_normal_position(self):
        gate = MetaCognitionGate()
        result = gate.evaluate(uncertainty_score=0.1)
        assert result["allow_trade"] is True
        assert result["position_multiplier"] == 1.0
        assert result["uncertainty_level"] == "low"

    def test_medium_uncertainty_reduce(self):
        gate = MetaCognitionGate()
        result = gate.evaluate(uncertainty_score=0.3)
        assert result["allow_trade"] is True
        assert result["position_multiplier"] == 0.7

    def test_high_uncertainty_halve(self):
        """HC-AGI-06: uncertainty > 0.4 → 降仓 0.5×"""
        gate = MetaCognitionGate()
        result = gate.evaluate(uncertainty_score=0.5)
        assert result["allow_trade"] is True
        assert result["position_multiplier"] == 0.5  # HC-AGI-06

    def test_critical_uncertainty_reject(self):
        """uncertainty > 0.7 → 拒开仓"""
        gate = MetaCognitionGate()
        result = gate.evaluate(uncertainty_score=0.8)
        assert result["allow_trade"] is False
        assert result["position_multiplier"] == 0.0
        assert result["uncertainty_level"] == "critical"

    def test_invalid_uncertainty_reject(self):
        gate = MetaCognitionGate()
        result = gate.evaluate(uncertainty_score=float("nan"))
        assert result["allow_trade"] is False

    def test_adjusted_position(self):
        gate = MetaCognitionGate()
        result = gate.evaluate(uncertainty_score=0.5, position_size=100.0)
        assert result["adjusted_position"] == 50.0  # 100 * 0.5

    def test_confidence_downgraded(self):
        gate = MetaCognitionGate()
        result = gate.evaluate(uncertainty_score=0.8, base_confidence=0.9)
        assert result["adjusted_confidence"] < 0.9


class TestSharpeExemption:
    def test_high_sharpe_medium_exempt(self):
        """Sharpe>1.5 可豁免 medium→low（恢复正常仓位）"""
        gate = MetaCognitionGate()
        result = gate.evaluate(uncertainty_score=0.3, strategy_sharpe=2.0)
        assert result["position_multiplier"] == 1.0

    def test_high_sharpe_high_not_exempt(self):
        """HC-AGI-06: high 不豁免（硬约束）"""
        gate = MetaCognitionGate()
        result = gate.evaluate(uncertainty_score=0.5, strategy_sharpe=3.0)
        assert result["position_multiplier"] == 0.5


class TestConfidenceCalibration:
    def test_calibration_detects_overconfidence(self):
        gate = MetaCognitionGate()
        # 构造过度自信：高 confidence 但低准确率
        preds = np.array([1, 1, 1, 1, 1, -1, -1, -1, -1, -1])
        outcomes = np.array([-1, -1, -1, -1, -1, 1, 1, 1, 1, 1])
        confs = np.array([0.9] * 10)
        result = gate.calibrate_confidence(preds, outcomes, confs)
        assert result["overconfidence_score"] > 0
        assert result["reliable"] is False

    def test_calibration_reliable(self):
        gate = MetaCognitionGate()
        preds = np.array([1, -1, 1, -1, 1, -1, 1, -1, 1, -1])
        outcomes = np.array([1, -1, 1, -1, 1, -1, 1, -1, 1, -1])
        confs = np.array([0.6] * 10)
        result = gate.calibrate_confidence(preds, outcomes, confs)
        assert result["reliable"] is True

    def test_apply_calibration(self):
        gate = MetaCognitionGate()
        preds = np.array([1] * 10)
        outcomes = np.array([-1] * 10)
        confs = np.array([0.9] * 10)
        gate.calibrate_confidence(preds, outcomes, confs)
        adjusted = gate.apply_calibration(0.9)
        assert adjusted < 0.9  # 过度自信 → 下调


class TestQuickMethods:
    def test_should_trade(self):
        gate = MetaCognitionGate()
        assert gate.should_trade(0.1) is True
        assert gate.should_trade(0.8) is False

    def test_position_multiplier(self):
        gate = MetaCognitionGate()
        assert gate.position_multiplier(0.1) == 1.0
        assert gate.position_multiplier(0.5) == 0.5


# ==================================================================
# 集成测试
# ==================================================================
class TestIntegration:
    def test_uncertainty_to_gate(self):
        """UncertaintyQuantifier → MetaCognitionGate 端到端"""
        uq = UncertaintyQuantifier(n_ensemble=3, confidence=0.9)
        gate = MetaCognitionGate()

        np.random.seed(42)
        n = 200
        X = np.random.randn(n, 3)
        y = X[:, 0] * 2.0 + np.random.randn(n) * 0.5

        # 1. 不确定性量化
        uq_result = uq.predict_with_uncertainty(X, y)

        # 2. 元认知门禁决策
        decision = gate.gate_decision(
            uncertainty_score=uq_result["uncertainty_score"],
            base_confidence=0.7,
            position_size=100.0,
        )

        # 3. 验证决策一致性
        assert decision["allow_trade"] in (True, False)
        assert 0.0 <= decision["position_multiplier"] <= 1.0
        assert decision["adjusted_position"] == 100.0 * decision["position_multiplier"]

    def test_critical_uncertainty_rejects_trade(self):
        """高不确定性 → 拒开仓"""
        uq = UncertaintyQuantifier()
        gate = MetaCognitionGate()
        # 模拟高不确定性
        decision = gate.gate_decision(
            uncertainty_score=0.8,
            base_confidence=0.7,
            position_size=100.0,
        )
        assert decision["allow_trade"] is False
        assert decision["adjusted_position"] == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
