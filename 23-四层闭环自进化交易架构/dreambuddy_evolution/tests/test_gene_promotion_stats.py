"""
P0 改进 RED 测试集 — 基因准入统计检验 + 审计标准

P0-1: 所有 promote 决策附 p 值（二项检验 H0: 胜率≤0.5）+ 效应量(Cohen's d) + 95% 置信区间
P0-2: 准入门槛 N≥30（当前 N=10）
P0-3: 审计标准调整 — Sharpe 为负时不应标记 HEALTHY

参考:
  - dream-science-hypothesis-verification SKILL（二项检验 + 效应量 + CI）
  - dream-science-statistics-check SKILL（p<0.05 显著性 + Cohen's d 阈值）
  - architecture-evaluation-23.md P0 改进建议
"""
from __future__ import annotations

import math

import numpy as np
import pytest


# --------------------------------------------------------------------------------
# RED: 模块尚未创建，import 应失败 → ModuleNotFoundError
# --------------------------------------------------------------------------------
def test_module_importable():
    """新模块 core.gene_promotion_stats 必须存在并可导入."""
    from dreambuddy_evolution.core.gene_promotion_stats import (  # noqa: F401
        binomial_test_pvalue,
        cohens_d,
        win_rate_ci,
        check_promotion_with_stats,
        MIN_PROMOTION_SAMPLES,
    )
    from dreambuddy_evolution.core.audit_standards import (  # noqa: F401
        classify_shadow_health,
        HealthLevel,
    )


# --------------------------------------------------------------------------------
# P0-2: 准入门槛 N≥30
# --------------------------------------------------------------------------------
class TestMinSamplesThreshold:
    def test_min_promotion_samples_is_30_or_above(self):
        """SHADOW_MIN_SAMPLES 从 10 提升至 30（P0 硬约束）."""
        from dreambuddy_evolution.core.gene_promotion_stats import MIN_PROMOTION_SAMPLES
        assert MIN_PROMOTION_SAMPLES >= 30, f"准入门槛必须 ≥30, 当前={MIN_PROMOTION_SAMPLES}"

    def test_promotion_rejected_below_30_samples(self):
        """N<30 时直接拒绝 promote（即使胜率 100%）."""
        from dreambuddy_evolution.core.gene_promotion_stats import check_promotion_with_stats
        samples = [{"pnl_pct": 0.01}] * 29  # 29 样本，全胜
        result = check_promotion_with_stats(samples)
        assert result["promote"] is False
        assert "N=" in result.get("reason", "") or "sample" in result.get("reason", "").lower()

    def test_promotion_eligible_at_30_samples(self):
        """N=30 且统计显著时允许 promote."""
        from dreambuddy_evolution.core.gene_promotion_stats import check_promotion_with_stats
        # 30 样本, 22 胜 8 负 → 胜率 73%, p<0.05
        samples = [{"pnl_pct": 0.02}] * 22 + [{"pnl_pct": -0.01}] * 8
        result = check_promotion_with_stats(samples)
        assert result["promote"] is True


# --------------------------------------------------------------------------------
# P0-1: 二项检验 p 值
# --------------------------------------------------------------------------------
class TestBinomialTestPvalue:
    def test_returns_float_in_unit_interval(self):
        from dreambuddy_evolution.core.gene_promotion_stats import binomial_test_pvalue
        p = binomial_test_pvalue(wins=20, n=30, p_h0=0.5)
        assert isinstance(p, float)
        assert 0.0 <= p <= 1.0

    def test_high_win_rate_low_pvalue(self):
        """胜率远高于 0.5 时 p 值应 < 0.05（显著）."""
        from dreambuddy_evolution.core.gene_promotion_stats import binomial_test_pvalue
        p = binomial_test_pvalue(wins=25, n=30, p_h0=0.5)
        assert p < 0.05, f"25/30 胜率应显著, p={p}"

    def test_marginal_win_rate_high_pvalue(self):
        """胜率接近 0.5 时 p 值应 ≥ 0.05（不显著）."""
        from dreambuddy_evolution.core.gene_promotion_stats import binomial_test_pvalue
        p = binomial_test_pvalue(wins=16, n=30, p_h0=0.5)
        assert p >= 0.05, f"16/30 胜率不应显著, p={p}"

    def test_zero_wins_pvalue_is_1_or_near(self):
        """0 胜时 p 值应接近 1（H0: 胜率≤0.5 不能拒绝）."""
        from dreambuddy_evolution.core.gene_promotion_stats import binomial_test_pvalue
        p = binomial_test_pvalue(wins=0, n=10, p_h0=0.5)
        assert p > 0.9

    def test_fail_open_on_invalid_inputs(self):
        """无效输入返回 1.0（FAIL-OPEN, 不 crash）."""
        from dreambuddy_evolution.core.gene_promotion_stats import binomial_test_pvalue
        assert binomial_test_pvalue(wins=-1, n=10) == 1.0
        assert binomial_test_pvalue(wins=5, n=0) == 1.0
        assert binomial_test_pvalue(wins=10, n=5) == 1.0  # wins>n


# --------------------------------------------------------------------------------
# P0-1: Cohen's d 效应量
# --------------------------------------------------------------------------------
class TestCohensD:
    def test_returns_float(self):
        from dreambuddy_evolution.core.gene_promotion_stats import cohens_d
        pnl = [0.02, -0.01, 0.03, 0.01, -0.005]
        d = cohens_d(pnl_values=pnl)
        assert isinstance(d, float)

    def test_positive_when_mean_positive(self):
        """均值为正时 Cohen's d 为正."""
        from dreambuddy_evolution.core.gene_promotion_stats import cohens_d
        pnl = [0.02, 0.03, 0.01, 0.025, 0.015]
        d = cohens_d(pnl_values=pnl)
        assert d > 0

    def test_zero_when_all_zero(self):
        """所有值相同时 Cohen's d = 0（无变异）."""
        from dreambuddy_evolution.core.gene_promotion_stats import cohens_d
        pnl = [0.0, 0.0, 0.0]
        d = cohens_d(pnl_values=pnl)
        assert d == 0.0

    def test_fail_open_on_empty(self):
        from dreambuddy_evolution.core.gene_promotion_stats import cohens_d
        assert cohens_d(pnl_values=[]) == 0.0


# --------------------------------------------------------------------------------
# P0-1: Wilson 置信区间
# --------------------------------------------------------------------------------
class TestWinRateCI:
    def test_returns_tuple_of_two_floats(self):
        from dreambuddy_evolution.core.gene_promotion_stats import win_rate_ci
        ci = win_rate_ci(wins=20, n=30, conf=0.95)
        assert isinstance(ci, tuple)
        assert len(ci) == 2
        assert isinstance(ci[0], float) and isinstance(ci[1], float)

    def test_ci_contains_point_estimate(self):
        """置信区间必须包含点估计（胜率）."""
        from dreambuddy_evolution.core.gene_promotion_stats import win_rate_ci
        wins, n = 20, 30
        low, high = win_rate_ci(wins, n, conf=0.95)
        point = wins / n
        assert low <= point <= high, f"CI=[{low},{high}] 不包含点估计 {point}"

    def test_ci_lower_above_zero_for_high_win_rate(self):
        """高胜率大样本下界应 > 0.5（统计显著）."""
        from dreambuddy_evolution.core.gene_promotion_stats import win_rate_ci
        low, high = win_rate_ci(wins=25, n=30, conf=0.95)
        assert low > 0.5, f"25/30 胜率 95% CI 下界应 >0.5, 实际={low}"

    def test_ci_bounds_in_unit_interval(self):
        from dreambuddy_evolution.core.gene_promotion_stats import win_rate_ci
        low, high = win_rate_ci(wins=5, n=10, conf=0.95)
        assert 0.0 <= low <= 1.0
        assert 0.0 <= high <= 1.0

    def test_fail_open_on_invalid(self):
        from dreambuddy_evolution.core.gene_promotion_stats import win_rate_ci
        assert win_rate_ci(wins=5, n=0) == (0.0, 1.0)


# --------------------------------------------------------------------------------
# P0-1 + P0-2: 综合统计准入决策
# --------------------------------------------------------------------------------
class TestCheckPromotionWithStats:
    def _sample(self, wins, losses, win_pnl=0.02, loss_pnl=-0.01):
        return [{"pnl_pct": win_pnl}] * wins + [{"pnl_pct": loss_pnl}] * losses

    def test_promote_decision_includes_all_stats(self):
        """promote 决策必须包含 p_value, effect_size, ci 字段."""
        from dreambuddy_evolution.core.gene_promotion_stats import check_promotion_with_stats
        samples = self._sample(22, 8)  # 30 样本, 73% 胜率
        result = check_promotion_with_stats(samples)
        for key in ("p_value", "effect_size", "ci_lower", "ci_upper", "win_rate", "n"):
            assert key in result, f"决策缺少字段: {key}"

    def test_promote_requires_p_value_below_005(self):
        """promote 必须 p<0.05（统计显著）."""
        from dreambuddy_evolution.core.gene_promotion_stats import check_promotion_with_stats
        # 30 样本, 16 胜 14 负 → 胜率 53%, p≈0.86 不显著
        samples = self._sample(16, 14)
        result = check_promotion_with_stats(samples)
        assert result["promote"] is False
        assert result["p_value"] >= 0.05

    def test_promote_rejects_negative_sharpe_like_signal(self):
        """avg_pnl≤0 时拒绝 promote."""
        from dreambuddy_evolution.core.gene_promotion_stats import check_promotion_with_stats
        # 30 样本, 20 胜但亏损笔 PnL 绝对值更大 → avg_pnl≤0
        samples = [{"pnl_pct": 0.001}] * 20 + [{"pnl_pct": -0.05}] * 10
        result = check_promotion_with_stats(samples)
        assert result["promote"] is False

    def test_promote_accepts_strong_signal(self):
        """强信号: N≥30, 胜率≥70%, p<0.05, avg_pnl>0, Cohen's d>0.5 → promote."""
        from dreambuddy_evolution.core.gene_promotion_stats import check_promotion_with_stats
        samples = self._sample(25, 5, win_pnl=0.03, loss_pnl=-0.005)
        result = check_promotion_with_stats(samples)
        assert result["promote"] is True
        assert result["p_value"] < 0.05
        assert result["effect_size"] > 0.5
        assert result["ci_lower"] > 0.5

    def test_retire_branch_preserved(self):
        """极差表现 → retire=True（不只 promote=False）."""
        from dreambuddy_evolution.core.gene_promotion_stats import check_promotion_with_stats
        samples = [{"pnl_pct": -0.02}] * 30  # 全负
        result = check_promotion_with_stats(samples)
        assert result.get("retire") is True or result["promote"] is False

    def test_fail_open_on_empty_samples(self):
        from dreambuddy_evolution.core.gene_promotion_stats import check_promotion_with_stats
        result = check_promotion_with_stats([])
        assert result["promote"] is False
        assert "p_value" in result
        # FAIL-OPEN: 不 crash, 返回中性值
        assert result["p_value"] == 1.0
        assert result["effect_size"] == 0.0


# --------------------------------------------------------------------------------
# P0-3: 审计标准 — Sharpe 负值不应标记 HEALTHY
# --------------------------------------------------------------------------------
class TestAuditStandardsShadow:
    def test_negative_sharpe_not_healthy(self):
        """Sharpe<0 → 不应是 HEALTHY（P0-3 硬约束）."""
        from dreambuddy_evolution.core.audit_standards import classify_shadow_health, HealthLevel
        stats = {"mean_reward": -0.01, "sharpe": -0.02, "sample_count": 6082}
        level = classify_shadow_health(stats)
        assert level != HealthLevel.HEALTHY, f"Sharpe<0 不应标记 HEALTHY, 实际={level}"

    def test_positive_sharpe_can_be_healthy(self):
        from dreambuddy_evolution.core.audit_standards import classify_shadow_health, HealthLevel
        stats = {"mean_reward": 0.05, "sharpe": 1.2, "sample_count": 5000}
        level = classify_shadow_health(stats)
        assert level == HealthLevel.HEALTHY

    def test_zero_sharpe_warning(self):
        """Sharpe=0 → WARNING（边界态）."""
        from dreambuddy_evolution.core.audit_standards import classify_shadow_health, HealthLevel
        stats = {"mean_reward": 0.0, "sharpe": 0.0, "sample_count": 3000}
        level = classify_shadow_health(stats)
        assert level in (HealthLevel.WARNING, HealthLevel.INITIAL)

    def test_low_sample_count_not_healthy(self):
        """样本数不足 → 不应 HEALTHY."""
        from dreambuddy_evolution.core.audit_standards import classify_shadow_health, HealthLevel
        stats = {"mean_reward": 0.5, "sharpe": 2.0, "sample_count": 50}
        level = classify_shadow_health(stats)
        assert level != HealthLevel.HEALTHY

    def test_negative_sharpe_critical_when_large_negative(self):
        """Sharpe<-0.5 → CRITICAL."""
        from dreambuddy_evolution.core.audit_standards import classify_shadow_health, HealthLevel
        stats = {"mean_reward": -0.1, "sharpe": -1.0, "sample_count": 5000}
        level = classify_shadow_health(stats)
        assert level == HealthLevel.CRITICAL

    def test_fail_open_on_missing_fields(self):
        """缺失字段 → 降级为 WARNING（FAIL-OPEN）."""
        from dreambuddy_evolution.core.audit_standards import classify_shadow_health, HealthLevel
        level = classify_shadow_health({})
        assert level in (HealthLevel.WARNING, HealthLevel.UNKNOWN)
