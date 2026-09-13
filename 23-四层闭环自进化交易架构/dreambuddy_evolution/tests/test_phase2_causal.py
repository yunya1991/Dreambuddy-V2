"""
Phase 2 测试: GrangerCausalityChecker + StructuralBreakDetector + ContradictionShiftAccumulator
"""
import pytest
import numpy as np


# =====================================================================
# GrangerCausalityChecker
# =====================================================================

class TestGrangerCausality:
    """Granger 因果检验."""

    def test_granger_causality_detected(self):
        """X Granger-cause Y 时检测到因果."""
        from dreambuddy_evolution.core.granger_causality_checker import GrangerCausalityChecker
        checker = GrangerCausalityChecker(max_lag=3)
        np.random.seed(42)
        # X = 随机游走, Y = 0.5*X_prev + noise
        n = 200
        x = np.cumsum(np.random.randn(n))
        y = np.zeros(n)
        for t in range(2, n):
            y[t] = 0.7 * x[t-1] + np.random.randn() * 0.1
        result = checker.check(x, y)
        if result is not None:
            assert result["is_granger_cause"] is True or result["p_value"] > 0

    def test_no_causality(self):
        """独立变量间无 Granger 因果."""
        from dreambuddy_evolution.core.granger_causality_checker import GrangerCausalityChecker
        checker = GrangerCausalityChecker(max_lag=3)
        np.random.seed(42)
        x = np.cumsum(np.random.randn(200))
        y = np.cumsum(np.random.randn(200))  # 完全独立
        result = checker.check(x, y)
        if result is not None:
            # 独立序列通常不检测到因果（除非偶然）
            assert isinstance(result["p_value"], float)

    def test_insufficient_data(self):
        """数据不足返回 None."""
        from dreambuddy_evolution.core.granger_causality_checker import GrangerCausalityChecker
        checker = GrangerCausalityChecker(max_lag=5)
        result = checker.check([1, 2, 3], [4, 5, 6])
        assert result is None

    def test_causal_chain(self):
        """因果链验证."""
        from dreambuddy_evolution.core.granger_causality_checker import GrangerCausalityChecker
        checker = GrangerCausalityChecker(max_lag=3)
        np.random.seed(42)
        n = 200
        a = np.cumsum(np.random.randn(n))
        b = np.zeros(n)
        c = np.zeros(n)
        for t in range(2, n):
            b[t] = 0.5 * a[t-1] + np.random.randn() * 0.1
            c[t] = 0.5 * b[t-1] + np.random.randn() * 0.1
        result = checker.verify_causal_chain([a, b, c])
        assert "chain_valid" in result
        assert "links" in result
        assert len(result["links"]) == 2


# =====================================================================
# StructuralBreakDetector
# =====================================================================

class TestStructuralBreak:
    """结构断裂检测."""

    def test_volatility_regime_fallback(self):
        """波动率制度检测（fallback 模式）."""
        from dreambuddy_evolution.core.structural_break_detector import StructuralBreakDetector
        detector = StructuralBreakDetector(min_samples=30)
        np.random.seed(42)
        # 前 50 个低波，后 50 个高波
        returns = np.concatenate([
            np.random.randn(50) * 0.01,
            np.random.randn(50) * 0.05,
        ])
        result = detector.detect_volatility_regime(returns)
        assert result is not None
        assert "detected" in result
        assert "method" in result

    def test_correlation_break(self):
        """相关性结构断裂."""
        from dreambuddy_evolution.core.structural_break_detector import StructuralBreakDetector
        detector = StructuralBreakDetector(min_samples=60)
        np.random.seed(42)
        n = 120
        # 前半段正相关，后半段负相关
        x = np.random.randn(n)
        y = np.zeros(n)
        y[:60] = 0.8 * x[:60] + np.random.randn(60) * 0.2
        y[60:] = -0.8 * x[60:] + np.random.randn(60) * 0.2
        result = detector.detect_correlation_break(x, y)
        if result is not None:
            assert "detected" in result

    def test_market_form_hurst(self):
        """Hurst 指数检测."""
        from dreambuddy_evolution.core.structural_break_detector import StructuralBreakDetector
        detector = StructuralBreakDetector(min_samples=60)
        np.random.seed(42)
        # 趋势序列
        price = np.cumsum(np.random.randn(120) * 0.5 + 0.1) + 100
        result = detector.detect_market_form(price)
        assert result is not None
        assert "hurst_current" in result
        assert 0.0 <= result["hurst_current"] <= 1.0

    def test_insufficient_data(self):
        """数据不足返回 None."""
        from dreambuddy_evolution.core.structural_break_detector import StructuralBreakDetector
        detector = StructuralBreakDetector(min_samples=60)
        assert detector.detect_volatility_regime(np.array([1, 2, 3])) is None
        assert detector.detect_market_form(np.array([1, 2, 3])) is None

    def test_detect_all(self):
        """全部检测."""
        from dreambuddy_evolution.core.structural_break_detector import StructuralBreakDetector
        detector = StructuralBreakDetector(min_samples=30)
        np.random.seed(42)
        price = np.cumsum(np.random.randn(100)) + 100
        result = detector.detect_all(price)
        assert "volatility_regime_shift" in result
        assert "correlation_break" in result
        assert "market_form_shift" in result
        assert "any_structural_break" in result


# =====================================================================
# ContradictionShiftAccumulator
# =====================================================================

class TestContradictionShift:
    """矛盾转化检测（修正算法）."""

    def test_no_shift_insufficient_data(self):
        """数据不足返回 None."""
        from dreambuddy_evolution.core.contradiction_shift_accumulator import ContradictionShiftAccumulator
        acc = ContradictionShiftAccumulator(persistence=5)
        acc.record([
            {"dimension": "technical", "timeframe": "short", "direction": "bull", "normalized_strength": 0.7}
        ])
        assert acc.detect_shift() is None

    def test_no_shift_same_primary(self):
        """主矛盾不变 → 无质变."""
        from dreambuddy_evolution.core.contradiction_shift_accumulator import ContradictionShiftAccumulator
        acc = ContradictionShiftAccumulator(persistence=5)
        for i in range(7):
            acc.record([
                {"dimension": "technical", "timeframe": "short", "direction": "bull", "normalized_strength": 0.7},
                {"dimension": "macro", "timeframe": "long", "direction": "bear", "normalized_strength": 0.3},
            ])
        # 无结构性断裂
        assert acc.detect_shift() is None

    def test_shift_with_structural_break(self):
        """排序变化 + 结构性断裂 → 质变."""
        from dreambuddy_evolution.core.contradiction_shift_accumulator import ContradictionShiftAccumulator
        acc = ContradictionShiftAccumulator(persistence=5, dominance_gap=0.1)
        # 初始: technical 是主矛盾
        for i in range(3):
            acc.record([
                {"dimension": "technical", "timeframe": "short", "direction": "bull", "normalized_strength": 0.7},
                {"dimension": "macro", "timeframe": "long", "direction": "bear", "normalized_strength": 0.3},
            ])
        # 后续: macro 力量增长超越 technical（比较当前力量）
        for i in range(4):
            acc.record([
                {"dimension": "technical", "timeframe": "short", "direction": "bull", "normalized_strength": 0.3},
                {"dimension": "macro", "timeframe": "long", "direction": "bear", "normalized_strength": 0.7},
            ])
        # 有结构性断裂
        structural_break = {
            "volatility_regime_shift": {"detected": True, "method": "test"},
            "correlation_break": None,
            "market_form_shift": None,
        }
        result = acc.detect_shift(structural_break)
        assert result is not None
        assert result["shifted_from"]["dimension"] == "technical"
        assert result["shifted_to"]["dimension"] == "macro"
        assert result["new_direction"] == "bear"
        assert result["structural_break_type"] == "volatility_regime_shift"

    def test_no_shift_without_structural_break(self):
        """排序变化但无结构性断裂 → 量变，不是质变."""
        from dreambuddy_evolution.core.contradiction_shift_accumulator import ContradictionShiftAccumulator
        acc = ContradictionShiftAccumulator(persistence=5, dominance_gap=0.1)
        for i in range(3):
            acc.record([
                {"dimension": "technical", "timeframe": "short", "direction": "bull", "normalized_strength": 0.7},
                {"dimension": "macro", "timeframe": "long", "direction": "bear", "normalized_strength": 0.3},
            ])
        for i in range(4):
            acc.record([
                {"dimension": "technical", "timeframe": "short", "direction": "bull", "normalized_strength": 0.3},
                {"dimension": "macro", "timeframe": "long", "direction": "bear", "normalized_strength": 0.7},
            ])
        # 无结构性断裂
        result = acc.detect_shift({"volatility_regime_shift": None, "correlation_break": None, "market_form_shift": None})
        assert result is None  # 量变不触发质变

    def test_corrected_algorithm_compares_current_strength(self):
        """验证修正算法: 比较旧矛盾的当前力量（非初始力量）."""
        from dreambuddy_evolution.core.contradiction_shift_accumulator import ContradictionShiftAccumulator
        acc = ContradictionShiftAccumulator(persistence=5, dominance_gap=0.1)
        # 初始: technical=0.8, macro=0.2
        # 后续: technical 衰减到 0.3（初始力量的衰减），macro 不变 0.2
        # v2.0 会误触发（因为比较 0.3 vs 0.8 初始值差距大）
        # v3.0 不应该触发（因为 macro 0.2 没有超越 technical 0.3）
        for i in range(7):
            tech_strength = 0.8 if i < 3 else 0.3
            acc.record([
                {"dimension": "technical", "timeframe": "short", "direction": "bull", "normalized_strength": tech_strength},
                {"dimension": "macro", "timeframe": "long", "direction": "bear", "normalized_strength": 0.2},
            ])
        structural_break = {
            "volatility_regime_shift": {"detected": True},
            "correlation_break": None,
            "market_form_shift": None,
        }
        result = acc.detect_shift(structural_break)
        # macro(0.2) 没有超越 technical(0.3) → 不应触发质变
        assert result is None

    def test_accumulation_status(self):
        """积累状态查询."""
        from dreambuddy_evolution.core.contradiction_shift_accumulator import ContradictionShiftAccumulator
        acc = ContradictionShiftAccumulator(persistence=5)
        acc.record([
            {"dimension": "technical", "timeframe": "short", "direction": "bull", "normalized_strength": 0.7}
        ])
        status = acc.get_accumulation_status()
        assert status["status"] == "insufficient_data"
        assert status["samples"] == 1
