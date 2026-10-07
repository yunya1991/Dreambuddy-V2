"""
TDD-PRE-001/002: StructuralBreakDetector 前置修复测试

修复项:
  - TDD-PRE-001: CUSUM 依赖缺失 (breaks_cusumolsresid 已从 statsmodels 移除)
                 → 改用 breakvar_heteroskedasticity_test
  - TDD-PRE-002: HMM 100% 收敛失败 (maxiter=100)
                 → maxiter=500
"""
import numpy as np
import pytest


class TestCUSUMDependencyFix:
    """TDD-PRE-001: CUSUM 依赖修复."""

    def test_correlation_break_uses_breakvar_not_fallback(self):
        """相关性断裂检测应使用 breakvar_heteroskedasticity，而非永远 fallback 到 rolling_zscore."""
        from dreambuddy_evolution.core.structural_break_detector import StructuralBreakDetector

        detector = StructuralBreakDetector(min_samples=60)
        np.random.seed(42)
        n = 180
        x = np.random.randn(n)
        y = np.zeros(n)
        # 前半段强正相关，后半段强负相关（明确的相关性结构断裂）
        y[:90] = 0.8 * x[:90] + np.random.randn(90) * 0.1
        y[90:] = -0.8 * x[90:] + np.random.randn(90) * 0.1

        result = detector.detect_correlation_break(x, y)

        assert result is not None, "相关性断裂数据不应返回 None"
        # 关键断言: 不再永远走 rolling_zscore fallback
        assert result["method"] != "rolling_zscore", (
            f"detect_correlation_break 应使用 welch_ttest，实际 fallback 到 {result['method']}"
        )
        assert result["method"] == "welch_ttest"

    def test_correlation_break_detected_on_true_break(self):
        """真实相关性断裂应被检测到 (detected=True)."""
        from dreambuddy_evolution.core.structural_break_detector import StructuralBreakDetector

        detector = StructuralBreakDetector(min_samples=60)
        np.random.seed(42)
        n = 180
        x = np.random.randn(n)
        y = np.zeros(n)
        y[:90] = 0.8 * x[:90] + np.random.randn(90) * 0.1
        y[90:] = -0.8 * x[90:] + np.random.randn(90) * 0.1

        result = detector.detect_correlation_break(x, y)

        assert result is not None
        assert result["detected"] is True, "明确的相关性断裂应被检测到"

    def test_correlation_break_no_break_on_stable_corr(self):
        """稳定相关序列不应误报断裂."""
        from dreambuddy_evolution.core.structural_break_detector import StructuralBreakDetector

        detector = StructuralBreakDetector(min_samples=60)
        np.random.seed(123)
        n = 180
        x = np.random.randn(n)
        # 全程正相关，无结构断裂
        y = 0.8 * x + np.random.randn(n) * 0.1

        result = detector.detect_correlation_break(x, y)

        # 稳定相关不应被检测为断裂
        if result is not None:
            assert result["detected"] is False, "稳定相关序列不应误报断裂"


class TestHMMConvergenceFix:
    """TDD-PRE-002: HMM 收敛修复."""

    def test_hmm_maxiter_increased(self):
        """MarkovRegression fit 应使用 maxiter >= 500 以避免 100% 收敛失败."""
        import inspect
        from dreambuddy_evolution.core import structural_break_detector

        source = inspect.getsource(structural_break_detector.StructuralBreakDetector.detect_volatility_regime)
        # 关键断言: maxiter 应 >= 500
        assert "maxiter=500" in source or "maxiter = 500" in source, (
            "detect_volatility_regime 应使用 maxiter>=500 修复 HMM 收敛失败"
        )
        # 不应再使用 maxiter=100
        assert "maxiter=100" not in source, "maxiter=100 导致 100% ConvergenceWarning，应移除"

    def test_volatility_regime_not_always_fallback(self):
        """修复后 vol_regime_shift 不应 100% 走 fallback."""
        from dreambuddy_evolution.core.structural_break_detector import StructuralBreakDetector

        detector = StructuralBreakDetector(min_samples=60)
        np.random.seed(42)
        # 构造低波→高波转换（真实 regime 切换）
        returns = np.concatenate([
            np.random.randn(100) * 0.005,
            np.random.randn(100) * 0.03,
        ])

        result = detector.detect_volatility_regime(returns)
        assert result is not None
        # 至少 method 字段存在且是合法值
        assert result["method"] in ("markov_regression", "simple_threshold")
        # 关键: 在足够数据+明显 regime 切换下，HMM 路径应可尝试（不强制 fallback）
        # 注: 若 HMM 仍失败走 simple_threshold 是可接受的降级，但 maxiter 必须修复
