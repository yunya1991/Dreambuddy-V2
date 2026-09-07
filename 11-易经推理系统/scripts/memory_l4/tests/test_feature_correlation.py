"""TC: 特征-价格关联度计算器测试。

验证 IC / MI / 综合排名 / 最优权重 / Beta融合 + FAIL-OPEN。
对应 Spec §三 Step 4 特征关联度。
"""
import sys
from pathlib import Path

import numpy as np
import pytest

# 将 memory_l4 加入 sys.path（force_vector 包所在目录）
_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))

# 将 9-基本面分析 加入 sys.path（导入 engines.signal_engine）
_ROOT = _L4_DIR.parent.parent.parent  # dreambuddy-v2
_9_FUND = _ROOT / "9-基本面分析"
if _9_FUND.is_dir() and str(_9_FUND) not in sys.path:
    sys.path.insert(0, str(_9_FUND))

from force_vector.feature_correlation_calculator import FeatureCorrelationCalculator
from force_vector.models import FeatureCorrelation
from engines.signal_engine import SignalEngine


class TestComputeIC:
    """TC4: 信息系数 IC 计算（Spearman 秩相关，滞后对齐）。"""

    def test_ic_positive_correlation(self):
        """feature 与 returns 同向递增 → IC > 0。"""
        calc = FeatureCorrelationCalculator()
        feature = np.arange(1, 31, dtype=float)
        returns = np.arange(1, 31, dtype=float)
        ic = calc.compute_ic(feature, returns)
        assert ic > 0.0

    def test_ic_negative_correlation(self):
        """feature 递增、returns 递减 → IC < 0。"""
        calc = FeatureCorrelationCalculator()
        feature = np.arange(1, 31, dtype=float)
        returns = np.arange(30, 0, -1, dtype=float)
        ic = calc.compute_ic(feature, returns)
        assert ic < 0.0

    def test_ic_in_range(self):
        """IC ∈ [-1, 1]。"""
        calc = FeatureCorrelationCalculator()
        feature = np.arange(1, 31, dtype=float)
        returns = np.arange(1, 31, dtype=float)
        ic = calc.compute_ic(feature, returns)
        assert -1.0 <= ic <= 1.0

    def test_ic_failopen_on_short_data(self):
        """样本不足 → 返回 0.0。"""
        calc = FeatureCorrelationCalculator()
        ic = calc.compute_ic(np.array([1.0, 2.0]), np.array([1.0, 2.0]))
        assert ic == pytest.approx(0.0)


class TestComputeMINormalized:
    """TC5: 互信息 MI（非线性关联度，归一化 [0,1]）。"""

    def test_mi_threshold_nonlinear_high_mi_low_ic(self):
        """阈值效应 returns=where(feature>0.5,1,-1) → MI_norm>0.3 但 |IC|<0.2。"""
        calc = FeatureCorrelationCalculator()
        rng = np.random.default_rng(42)
        feature = rng.uniform(0.0, 1.0, size=100)
        returns = np.where(feature > 0.5, 1.0, -1.0).astype(float)
        ic = calc.compute_ic(feature, returns)
        mi = calc.compute_mi_normalized(feature, returns)
        assert mi > 0.3
        assert abs(ic) < 0.2

    def test_mi_in_range(self):
        """MI_normalized ∈ [0, 1]。"""
        calc = FeatureCorrelationCalculator()
        rng = np.random.default_rng(7)
        feature = rng.uniform(0.0, 1.0, size=80)
        returns = np.where(feature > 0.5, 1.0, -1.0).astype(float)
        mi = calc.compute_mi_normalized(feature, returns)
        assert 0.0 <= mi <= 1.0

    def test_mi_failopen_on_short_data(self):
        """样本不足 → 返回 0.0。"""
        calc = FeatureCorrelationCalculator()
        mi = calc.compute_mi_normalized(np.array([1.0, 2.0]), np.array([1.0, 2.0]))
        assert mi == pytest.approx(0.0)


class TestComputeCombinedScore:
    """综合关联度 = |IC| * w_linear + MI * w_nonlinear。"""

    def test_combined_score_formula(self):
        """combined = |IC|*0.6 + MI*0.4。"""
        calc = FeatureCorrelationCalculator()
        score = calc.compute_combined_score(ic=0.8, mi=0.5, w_linear=0.6, w_nonlinear=0.4)
        assert score == pytest.approx(abs(0.8) * 0.6 + 0.5 * 0.4)

    def test_combined_score_default_weights(self):
        """默认权重 0.6/0.4。"""
        calc = FeatureCorrelationCalculator()
        score_default = calc.compute_combined_score(0.8, 0.5)
        score_explicit = calc.compute_combined_score(0.8, 0.5, 0.6, 0.4)
        assert score_default == pytest.approx(score_explicit)

    def test_combined_score_uses_abs_ic(self):
        """负 IC 也取绝对值参与综合分。"""
        calc = FeatureCorrelationCalculator()
        assert calc.compute_combined_score(-0.8, 0.5) == pytest.approx(
            calc.compute_combined_score(0.8, 0.5))


class TestRankFeatures:
    """TC6: 按 combined_score 降序排名，rank 从 1 开始。"""

    @staticmethod
    def _make_feature(name, ic, mi):
        return FeatureCorrelation(
            feature_name=name, dimension="fa", ic_30d=ic, mi_30d=mi,
            combined_score=abs(ic) * 0.6 + mi * 0.4,
            rank=0, ic_weight=0.0, beta_weight=1.0, final_weight=0.0,
        )

    def test_rank_descending_top1_rank1(self):
        """5 个特征不同 IC/MI → combined_score 降序，top-1 rank=1。"""
        calc = FeatureCorrelationCalculator()
        corr = [
            self._make_feature("f1", 0.8, 0.1),  # 0.52
            self._make_feature("f2", 0.6, 0.2),  # 0.44
            self._make_feature("f3", 0.4, 0.3),  # 0.36
            self._make_feature("f4", 0.2, 0.4),  # 0.28
            self._make_feature("f5", 0.1, 0.5),  # 0.26
        ]
        ranked = calc.rank_features(corr)
        assert ranked[0].rank == 1
        assert ranked[0].feature_name == "f1"
        scores = [c.combined_score for c in ranked]
        assert scores == sorted(scores, reverse=True)
        assert [c.rank for c in ranked] == [1, 2, 3, 4, 5]

    def test_rank_failopen_empty(self):
        """空列表 → 返回空列表。"""
        calc = FeatureCorrelationCalculator()
        assert calc.rank_features([]) == []


class TestComputeOptimalWeights:
    """TC7: IC 最优权重 = |IC|^alpha 归一化，和≈1.0，每个 ∈ [0.02, 0.40]。"""

    @staticmethod
    def _make_corr(name, ic):
        return FeatureCorrelation(
            feature_name=name, dimension="fa", ic_30d=ic, mi_30d=0.0,
            combined_score=abs(ic), rank=0, ic_weight=0.0, beta_weight=1.0, final_weight=0.0,
        )

    def test_weights_sum_to_one_and_in_bounds(self):
        """5 个特征 IC 权重和≈1.0，每个 ∈ [0.02, 0.40]。"""
        calc = FeatureCorrelationCalculator()
        corr = [self._make_corr(f"f{i+1}", ic)
                for i, ic in enumerate([0.5, 0.45, 0.4, 0.35, 0.3])]
        weights = calc.compute_optimal_weights(corr, alpha=1.0)
        assert len(weights) == 5
        assert sum(weights.values()) == pytest.approx(1.0, abs=1e-6)
        for w in weights.values():
            assert 0.02 <= w <= 0.40

    def test_weights_higher_ic_gets_higher_weight(self):
        """IC 高的特征权重更大。"""
        calc = FeatureCorrelationCalculator()
        corr = [self._make_corr(f"f{i+1}", ic)
                for i, ic in enumerate([0.5, 0.45, 0.4, 0.35, 0.3])]
        weights = calc.compute_optimal_weights(corr, alpha=1.0)
        assert weights["f1"] > weights["f5"]

    def test_weights_alpha_squashing(self):
        """alpha=2.0 → 头部权重占比上升。"""
        calc = FeatureCorrelationCalculator()
        corr = [self._make_corr(f"f{i+1}", ic)
                for i, ic in enumerate([0.5, 0.45, 0.4, 0.35, 0.3])]
        w1 = calc.compute_optimal_weights(corr, alpha=1.0)
        w2 = calc.compute_optimal_weights(corr, alpha=2.0)
        assert w2["f1"] > w1["f1"]

    def test_weights_failopen_empty(self):
        """空列表 → 返回空 dict。"""
        calc = FeatureCorrelationCalculator()
        assert calc.compute_optimal_weights([]) == {}


class TestFuseWithBeta:
    """TC7: Beta 后验权重融合，signal_engine=None 直接返回 ic_weights。"""

    @staticmethod
    def _make_corr(name, ic):
        return FeatureCorrelation(
            feature_name=name, dimension="fa", ic_30d=ic, mi_30d=0.0,
            combined_score=abs(ic), rank=0, ic_weight=0.0, beta_weight=1.0, final_weight=0.0,
        )

    def test_fuse_none_signal_engine_returns_ic_weights(self):
        """signal_engine=None → 直接返回 ic_weights（不报错）。"""
        calc = FeatureCorrelationCalculator()
        corr = [self._make_corr(f"f{i+1}", ic)
                for i, ic in enumerate([0.5, 0.45, 0.4, 0.35, 0.3])]
        ic_weights = calc.compute_optimal_weights(corr, alpha=1.0)
        module_names = {f"f{i+1}": "news" for i in range(5)}
        final = calc.fuse_with_beta(ic_weights, None, module_names)
        assert final == ic_weights

    def test_fuse_with_signal_engine_preserves_constraints(self):
        """Beta 融合后仍满足：和≈1.0，每个 ∈ [0.02, 0.40]。"""
        calc = FeatureCorrelationCalculator()
        corr = [self._make_corr(f"f{i+1}", ic)
                for i, ic in enumerate([0.5, 0.45, 0.4, 0.35, 0.3])]
        ic_weights = calc.compute_optimal_weights(corr, alpha=1.0)

        se = SignalEngine()
        for _ in range(6):  # news 达到 predictions>=5，自适应生效
            se.update_module_performance("news", True)
        module_names = {"f1": "news", "f2": "sentiment", "f3": "sentiment",
                        "f4": "sentiment", "f5": "sentiment"}
        final = calc.fuse_with_beta(ic_weights, se, module_names)
        assert sum(final.values()) == pytest.approx(1.0, abs=1e-6)
        for w in final.values():
            assert 0.02 <= w <= 0.40

    def test_fuse_with_engine_modifies_weights(self):
        """自适应权重上调的模块 → 对应特征 final 权重占比上升。"""
        calc = FeatureCorrelationCalculator()
        corr = [self._make_corr(f"f{i+1}", ic)
                for i, ic in enumerate([0.5, 0.45, 0.4, 0.35, 0.3])]
        ic_weights = calc.compute_optimal_weights(corr, alpha=1.0)

        se = SignalEngine()
        for _ in range(6):
            se.update_module_performance("news", True)
        module_names = {"f1": "news", "f2": "sentiment", "f3": "sentiment",
                        "f4": "sentiment", "f5": "sentiment"}
        final = calc.fuse_with_beta(ic_weights, se, module_names)
        assert final["f1"] > ic_weights["f1"]

    def test_fuse_failopen_on_missing_module_mapping(self):
        """module_names 缺失某特征 → 该特征按 beta=1.0 处理（FAIL-OPEN）。"""
        calc = FeatureCorrelationCalculator()
        # 3 个合规特征（2 个特征无法同时满足 sum=1 与 each<=0.40）
        ic_weights = {"f1": 0.30, "f2": 0.30, "f3": 0.40}
        se = SignalEngine()
        final = calc.fuse_with_beta(ic_weights, se, {})  # module_names 为空
        # 缺失映射 → beta=1.0 → 权重不变，仍满足约束
        assert sum(final.values()) == pytest.approx(1.0, abs=1e-6)
        for w in final.values():
            assert 0.02 <= w <= 0.40
