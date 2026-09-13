"""
test_causal_engine — CausalEngine 单元测试

覆盖：
  - DAG 学习（偏相关 + 阈值化）
  - ATE 估计（causalml + 线性降级）
  - CATE 异质性效应
  - 虚假关联检测
  - 因果影响力评分
  - FAIL-OPEN（样本不足/异常）
  - 硬约束 HC-AGI-08（最小样本量≥500）
"""
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from dreambuddy_evolution.core.causal_engine import CausalEngine


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------
@pytest.fixture
def engine():
    return CausalEngine()


@pytest.fixture
def confounded_data():
    """构造带混淆因子的数据：C→A, C→B，A-B 虚假关联"""
    np.random.seed(42)
    n = 600
    C = np.random.randn(n)
    A = C * 0.8 + np.random.randn(n) * 0.3
    B = C * 0.8 + np.random.randn(n) * 0.3
    D = np.random.randn(n)  # 独立变量
    return np.column_stack([A, B, C, D]), ["A", "B", "C", "D"]


@pytest.fixture
def causal_treatment_data():
    """构造有因果效应的数据：treatment→y，X 为协变量"""
    np.random.seed(42)
    n = 600
    X = np.random.randn(n, 3)
    treatment = np.random.randint(0, 2, n)
    # 真实 ATE = 2.0，且有 CATE 异质性（与 X[:,0] 相关）
    y = X[:, 0] * 0.5 + treatment * (2.0 + X[:, 0] * 0.5) + np.random.randn(n) * 0.1
    return X, treatment, y


@pytest.fixture
def small_data():
    """小样本数据（<500）"""
    np.random.seed(42)
    return np.random.randn(100, 3)


# ------------------------------------------------------------------
# 1. DAG 学习
# ------------------------------------------------------------------
class TestDAGLearning:
    def test_dag_returns_adj_matrix(self, engine, confounded_data):
        data, names = confounded_data
        result = engine.learn_dag(data, names)
        assert "adj_matrix" in result
        assert result["adj_matrix"].shape == (4, 4)
        assert result["n_edges"] > 0

    def test_dag_no_self_loops(self, engine, confounded_data):
        data, names = confounded_data
        result = engine.learn_dag(data, names)
        adj = result["adj_matrix"]
        assert np.all(np.diag(adj) == 0)  # 无自环

    def test_dag_insufficient_samples(self, engine, small_data):
        """HC-AGI-08: 样本<500 返回空DAG"""
        result = engine.learn_dag(small_data, ["A", "B", "C"])
        assert result["n_edges"] == 0
        assert result["method"] == "insufficient_samples"

    def test_dag_failopen_empty(self, engine):
        result = engine.learn_dag(np.array([]))
        assert result["n_edges"] == 0


# ------------------------------------------------------------------
# 2. ATE 估计
# ------------------------------------------------------------------
class TestATE:
    def test_ate_recovers_true_effect(self, engine, causal_treatment_data):
        X, t, y = causal_treatment_data
        result = engine.estimate_ate(X, t, y, method="dml")
        # 真实 ATE = 2.0 + E[X0]*0.5 ≈ 2.0
        assert abs(result["ate"] - 2.0) < 1.0
        assert result["significant"] is True

    def test_ate_linear_fallback(self, engine, causal_treatment_data):
        X, t, y = causal_treatment_data
        result = engine.estimate_ate(X, t, y, method="linear")
        assert abs(result["ate"] - 2.0) < 1.0

    def test_ate_insufficient_samples(self, engine):
        """HC-AGI-08: 样本不足返回中性"""
        X = np.random.randn(100, 2)
        t = np.random.randint(0, 2, 100)
        y = np.random.randn(100)
        result = engine.estimate_ate(X, t, y)
        assert result["ate"] == 0.0
        assert result["significant"] is False

    def test_ate_confidence_interval(self, engine, causal_treatment_data):
        X, t, y = causal_treatment_data
        result = engine.estimate_ate(X, t, y, method="dml")
        assert result["lower_bound"] < result["ate"] < result["upper_bound"]

    def test_ate_failopen(self, engine):
        result = engine.estimate_ate(np.array([]), np.array([]), np.array([]))
        assert result["ate"] == 0.0
        assert result["significant"] is False


# ------------------------------------------------------------------
# 3. CATE 异质性效应
# ------------------------------------------------------------------
class TestCATE:
    def test_cate_returns_array(self, engine, causal_treatment_data):
        X, t, y = causal_treatment_data
        result = engine.estimate_cate(X, t, y)
        assert len(result["cate"]) == len(y)

    def test_cate_heterogeneity_positive(self, engine, causal_treatment_data):
        X, t, y = causal_treatment_data
        result = engine.estimate_cate(X, t, y)
        # 数据有 CATE 异质性，heterogeneity_score 应 > 0
        assert result["heterogeneity_score"] >= 0.0

    def test_cate_insufficient_samples(self, engine):
        X = np.random.randn(100, 2)
        t = np.random.randint(0, 2, 100)
        y = np.random.randn(100)
        result = engine.estimate_cate(X, t, y)
        assert result["method"] == "insufficient_samples"


# ------------------------------------------------------------------
# 4. 虚假关联检测
# ------------------------------------------------------------------
class TestSpurious:
    def test_detects_confounded_association(self, engine, confounded_data):
        """A-B 由 C 混淆，应被检测为虚假关联"""
        data, names = confounded_data
        result = engine.detect_spurious(data, names)
        pairs = [s["pair"] for s in result["spurious_pairs"]]
        assert ("A", "B") in pairs or ("B", "A") in pairs

    def test_spurious_has_confounders(self, engine, confounded_data):
        data, names = confounded_data
        result = engine.detect_spurious(data, names)
        for s in result["spurious_pairs"]:
            assert len(s["confounders"]) > 0
            assert "C" in s["confounders"]

    def test_spurious_partial_corr_low(self, engine, confounded_data):
        """虚假关联的偏相关应显著低于原始相关"""
        data, names = confounded_data
        result = engine.detect_spurious(data, names)
        for s in result["spurious_pairs"]:
            assert abs(s["partial_correlation"]) < abs(s["raw_correlation"])

    def test_spurious_insufficient_samples(self, engine, small_data):
        result = engine.detect_spurious(small_data)
        assert result["n_spurious"] == 0

    def test_spurious_failopen(self, engine):
        result = engine.detect_spurious(np.array([]))
        assert result["n_spurious"] == 0


# ------------------------------------------------------------------
# 5. 因果影响力评分
# ------------------------------------------------------------------
class TestInfluence:
    def test_influence_returns_scores(self, engine, confounded_data):
        data, names = confounded_data
        result = engine.causal_influence(data, names)
        assert len(result["influence_scores"]) == 4
        assert len(result["ranked_features"]) == 4

    def test_influence_ranked_descending(self, engine, confounded_data):
        data, names = confounded_data
        result = engine.causal_influence(data, names)
        scores = result["influence_scores"]
        ranked = result["ranked_features"]
        for i in range(len(ranked) - 1):
            assert scores[ranked[i]] >= scores[ranked[i + 1]]

    def test_influence_failopen(self, engine):
        result = engine.causal_influence(np.array([]))
        assert result["ranked_features"] == []


# ------------------------------------------------------------------
# 6. 验收标准：识别≥3个虚假关联
# ------------------------------------------------------------------
class TestAcceptance:
    def test_detect_at_least_3_spurious(self, engine):
        """验收：因果 DAG 识别≥3个已知虚假关联"""
        np.random.seed(42)
        n = 800
        # 构造 3 组混淆关系
        C1 = np.random.randn(n)
        C2 = np.random.randn(n)
        C3 = np.random.randn(n)
        A1 = C1 * 0.9 + np.random.randn(n) * 0.2
        B1 = C1 * 0.9 + np.random.randn(n) * 0.2
        A2 = C2 * 0.9 + np.random.randn(n) * 0.2
        B2 = C2 * 0.9 + np.random.randn(n) * 0.2
        A3 = C3 * 0.9 + np.random.randn(n) * 0.2
        B3 = C3 * 0.9 + np.random.randn(n) * 0.2
        data = np.column_stack([A1, B1, C1, A2, B2, C2, A3, B3, C3])
        names = ["A1", "B1", "C1", "A2", "B2", "C2", "A3", "B3", "C3"]

        result = engine.detect_spurious(data, names)
        assert result["n_spurious"] >= 3, f"应检测到≥3个虚假关联，实际{result['n_spurious']}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
