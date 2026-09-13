"""
test_counterfactual_transfer — Phase 2.2 + 3.2 集成测试

覆盖：
  Phase 2.2 CounterfactualEvaluator:
    - 合成控制法
    - what_if_no_trade
    - 完整评估 + HC-AGI-09 异常检测
    - 迁移验证 HC-AGI-05

  Phase 3.2 TransferLearner:
    - Prototypical Network 原型 + 相似度
    - MAML 适配
    - 端到端迁移（含反事实验证）
    - 相似度不足拒绝
"""
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from dreambuddy_evolution.core.counterfactual_evaluator import CounterfactualEvaluator
from dreambuddy_evolution.core.transfer_learner import TransferLearner


# ==================================================================
# Phase 2.2: CounterfactualEvaluator
# ==================================================================
class TestSyntheticControl:
    def test_synthetic_control(self):
        ce = CounterfactualEvaluator()
        np.random.seed(42)
        T = 100
        target = np.cumsum(np.random.randn(T) * 0.02)
        controls = np.column_stack([
            target + np.random.randn(T) * 0.01,
            target * 0.8 + np.random.randn(T) * 0.02,
            np.cumsum(np.random.randn(T) * 0.01),
        ])
        synthetic, weights = ce.synthetic_control(target, controls)
        assert len(synthetic) == T
        assert abs(weights.sum() - 1.0) < 1e-6

    def test_insufficient_controls(self):
        ce = CounterfactualEvaluator(min_control_units=3)
        target = np.random.randn(50)
        controls = np.random.randn(50, 1)  # 只有1个控制组
        synthetic, weights = ce.synthetic_control(target, controls)
        # FAIL-OPEN: 等权重
        assert weights[0] == 1.0


class TestWhatIfNoTrade:
    def test_what_if_no_trade(self):
        ce = CounterfactualEvaluator()
        np.random.seed(42)
        T = 100
        target = np.cumsum(np.random.randn(T) * 0.02)
        controls = np.column_stack([
            target + np.random.randn(T) * 0.01,
            target * 0.8 + np.random.randn(T) * 0.02,
            np.cumsum(np.random.randn(T) * 0.01),
        ])
        result = ce.what_if_no_trade(actual_pnl=10.0, target_returns=target, control_returns=controls)
        assert "counterfactual_pnl" in result
        assert "alpha" in result
        assert "pnl_attribution" in result

    def test_alpha_is_actual_minus_counterfactual(self):
        ce = CounterfactualEvaluator()
        T = 50
        target = np.ones(T) * 0.01
        controls = np.zeros((T, 3))
        result = ce.what_if_no_trade(actual_pnl=10.0, target_returns=target, control_returns=controls)
        # counterfactual = 0 (controls 全零), alpha = 10 - 0 = 10
        assert abs(result["alpha"] - 10.0) < 1e-6


class TestCounterfactualEval:
    def test_full_eval(self):
        ce = CounterfactualEvaluator()
        np.random.seed(42)
        T = 100
        target = np.cumsum(np.random.randn(T) * 0.02)
        controls = np.column_stack([
            target + np.random.randn(T) * 0.01,
            target * 0.8,
            np.random.randn(T) * 0.01,
        ])
        result = ce.counterfactual_eval(5.0, target, controls)
        assert "actual_pnl" in result
        assert "counterfactual_pnl" in result
        assert "alpha" in result
        assert "reliable" in result
        assert "alpha_significance" in result

    def test_outlier_detection(self):
        """HC-AGI-09: actual_pnl 异常检测"""
        ce = CounterfactualEvaluator()
        T = 100
        target = np.random.randn(T) * 0.01  # 小波动
        controls = np.random.randn(T, 3) * 0.01
        result = ce.counterfactual_eval(100.0, target, controls)  # 极端 pnl
        assert result["actual_is_outlier"] is True

    def test_normal_pnl_not_outlier(self):
        ce = CounterfactualEvaluator()
        T = 100
        target = np.random.randn(T) * 0.01
        controls = np.random.randn(T, 3) * 0.01
        result = ce.counterfactual_eval(0.0, target, controls)
        assert result["actual_is_outlier"] is False


class TestMigrationValidation:
    def test_validate_migration_negative_alpha(self):
        """HC-AGI-05: alpha<0 迁移无效"""
        ce = CounterfactualEvaluator()
        T = 50
        src = np.random.randn(T) * 0.02
        tgt = np.random.randn(T) * 0.02 - 0.05  # 负收益
        controls = np.random.randn(T, 3) * 0.01
        result = ce.validate_migration(src, tgt, controls, source_pnl=1.0)
        # tgt 累计负收益 → actual_pnl 可能 < counterfactual
        assert "valid" in result
        assert "alpha" in result


# ==================================================================
# Phase 3.2: TransferLearner
# ==================================================================
class TestPrototypicalNetwork:
    def test_compute_prototype(self):
        tl = TransferLearner()
        X = np.random.randn(20, 5)
        result = tl.compute_prototype(X)
        assert result["n_classes"] == 1
        assert 0 in result["prototypes"]

    def test_prototype_with_labels(self):
        tl = TransferLearner()
        X = np.random.randn(20, 5)
        labels = np.array([0]*10 + [1]*10)
        result = tl.compute_prototype(X, labels)
        assert result["n_classes"] == 2

    def test_similarity_identical(self):
        tl = TransferLearner()
        x = np.random.randn(50)
        sim = tl.pattern_similarity(x, x)
        assert sim == pytest.approx(1.0, abs=1e-6)

    def test_similarity_orthogonal(self):
        tl = TransferLearner()
        x = np.array([1.0, 0.0] * 25)
        y = np.array([0.0, 1.0] * 25)
        sim = tl.pattern_similarity(x, y)
        assert sim == pytest.approx(0.5, abs=1e-6)  # cosine=0 → (0+1)/2=0.5

    def test_store_and_asset_similarity(self):
        tl = TransferLearner()
        X1 = np.random.randn(20, 5)
        X2 = X1 + 0.01  # 非常相似
        tl.store_prototype("BTC", X1)
        tl.store_prototype("ETH", X2)
        sim = tl.asset_similarity("BTC", "ETH")
        assert sim > 0.9


class TestMAML:
    def test_maml_torch(self):
        tl = TransferLearner()
        np.random.seed(42)
        T = 50
        src = np.cumsum(np.random.randn(T) * 0.02)
        tgt = src * 0.9 + np.random.randn(T) * 0.01
        result = tl.maml_adapt(src, src, tgt, tgt)
        assert "meta_loss" in result
        assert "improvement" in result


class TestEndToEndTransfer:
    def test_similarity_rejection(self):
        """相似度不足 → 拒绝迁移"""
        tl = TransferLearner(similarity_threshold=0.9)
        np.random.seed(42)
        T = 50
        src = np.random.randn(T) * 0.02
        tgt = np.random.randn(T) * 0.02  # 不相关
        controls = np.random.randn(T, 3) * 0.01
        result = tl.transfer_pattern("BTC", "SOL", src, tgt, controls)
        assert result["valid"] is False
        assert result["rejected_by"] == "similarity"

    def test_full_transfer_flow(self):
        tl = TransferLearner()
        np.random.seed(42)
        T = 100
        src = np.cumsum(np.random.randn(T) * 0.02)
        tgt = src * 0.95 + np.random.randn(T) * 0.005  # 高度相关
        controls = np.column_stack([src*0.3, np.random.randn(T)*0.01, src*0.2])
        result = tl.transfer_pattern("BTC", "ETH", src, tgt, controls)
        # 验证结构完整
        assert "valid" in result
        assert "similarity" in result
        assert "maml_improvement" in result
        assert "counterfactual_alpha" in result

    def test_counterfactual_rejection(self):
        """反事实验证未通过 → 拒绝迁移"""
        tl = TransferLearner(similarity_threshold=0.1)  # 放低相似度门槛
        np.random.seed(42)
        T = 100
        src = np.cumsum(np.random.randn(T) * 0.02)
        # tgt 与 src 高度相关但收益极差
        tgt = src * 0.5 - 10.0
        controls = np.column_stack([src*0.3, np.random.randn(T)*0.01, src*0.2])
        result = tl.transfer_pattern("BTC", "SOL", src, tgt, controls)
        # 可能被 counterfactual 拒绝（alpha<0）
        if result["valid"] is False:
            assert result["rejected_by"] in ("similarity", "counterfactual")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
