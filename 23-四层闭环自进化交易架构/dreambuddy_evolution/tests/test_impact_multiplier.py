"""
Phase 2 RED/GREEN: ImpactMultiplier 因子影响力时间衰减测试

验证 SPEC §8 设计:
  factor_effective = factor_raw × impact_multiplier(cycle_phase, dimension)

覆盖:
  - ImpactMultiplier 查表逻辑 (8 维度 × 7 阶段 + 3 repricing 子阶段)
  - FAIL-OPEN: cycle_phase=None/neutral/unknown → 1.0
  - FAIL-OPEN: dimension 未知 → 1.0
  - repricing 子阶段 (relief/verification/trend) 查表
  - get_multipliers 与 factor_names 对齐
  - apply_impact_multiplier 应用 + FAIL-OPEN
  - 衰减系数符合 §8.2 文档关键值
"""
from __future__ import annotations

import numpy as np
import pytest


class TestImpactMultiplierImport:
    """导入测试。"""

    def test_impact_multiplier_class_importable(self):
        """ImpactMultiplier 类可导入。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            ImpactMultiplier,
        )  # noqa: F401

    def test_apply_function_importable(self):
        """apply_impact_multiplier 函数可导入。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            apply_impact_multiplier,
        )  # noqa: F401


class TestGetMultiplier:
    """get_multiplier 单值查询测试。"""

    def test_neutral_returns_1_for_all_dimensions(self):
        """neutral 阶段所有维度返回 1.0 (无衰减)。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            ImpactMultiplier,
        )

        im = ImpactMultiplier()
        for dim in ImpactMultiplier.DIMENSIONS:
            assert im.get_multiplier("neutral", dim) == 1.0, (
                f"neutral 阶段 {dim} 应为 1.0"
            )

    def test_none_phase_returns_1(self):
        """cycle_phase=None → 1.0 (FAIL-OPEN)。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            ImpactMultiplier,
        )

        im = ImpactMultiplier()
        assert im.get_multiplier(None, "C1") == 1.0
        assert im.get_multiplier("", "C4") == 1.0

    def test_unknown_dimension_returns_1(self):
        """未知维度 → 1.0 (FAIL-OPEN)。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            ImpactMultiplier,
        )

        im = ImpactMultiplier()
        assert im.get_multiplier("event", "UNKNOWN_DIM") == 1.0
        assert im.get_multiplier("expectation_jump", "C5") == 1.0  # C5 不在表中

    def test_unknown_phase_returns_1(self):
        """未知阶段 → 1.0 (FAIL-OPEN)。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            ImpactMultiplier,
        )

        im = ImpactMultiplier()
        assert im.get_multiplier("unknown_phase", "C1") == 1.0

    def test_expectation_jump_c4_amplified(self):
        """expectation_jump 阶段 C4 宏观面放大 (§8.2: 1.5)。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            ImpactMultiplier,
        )

        im = ImpactMultiplier()
        assert im.get_multiplier("expectation_jump", "C4") == 1.5

    def test_event_c1_c2_news_amplified(self):
        """event 阶段 C1/C2/news 主导 (§8.2: 1.5/1.4/1.5)。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            ImpactMultiplier,
        )

        im = ImpactMultiplier()
        assert im.get_multiplier("event", "C1") == 1.5
        assert im.get_multiplier("event", "C2") == 1.4
        assert im.get_multiplier("event", "news") == 1.5

    def test_expectation_build_c4_attenuated(self):
        """expectation_build 阶段 C4 宏观面衰减 (§8.2: 0.3)。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            ImpactMultiplier,
        )

        im = ImpactMultiplier()
        assert im.get_multiplier("expectation_build", "C4") == 0.3


class TestRepricingSubPhase:
    """repricing 子阶段查表测试。"""

    def test_repricing_relief_uses_relief_table(self):
        """repricing + relief 子阶段查 repricing_relief 表。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            ImpactMultiplier,
        )

        im = ImpactMultiplier()
        # repricing_relief: C1=1.2, C2=1.3, C4=0.3
        assert im.get_multiplier("repricing", "C1", "relief") == 1.2
        assert im.get_multiplier("repricing", "C2", "relief") == 1.3
        assert im.get_multiplier("repricing", "C4", "relief") == 0.3

    def test_repricing_verification_uses_verification_table(self):
        """repricing + verification 子阶段查 repricing_verification 表。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            ImpactMultiplier,
        )

        im = ImpactMultiplier()
        # repricing_verification: C1=1.0, C4=0.2, news=1.2
        assert im.get_multiplier("repricing", "C1", "verification") == 1.0
        assert im.get_multiplier("repricing", "C4", "verification") == 0.2
        assert im.get_multiplier("repricing", "news", "verification") == 1.2

    def test_repricing_trend_uses_trend_table(self):
        """repricing + trend 子阶段查 repricing_trend 表。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            ImpactMultiplier,
        )

        im = ImpactMultiplier()
        # repricing_trend: C1=0.9, C4=0.1, news=1.0
        assert im.get_multiplier("repricing", "C1", "trend") == 0.9
        assert im.get_multiplier("repricing", "C4", "trend") == 0.1
        assert im.get_multiplier("repricing", "news", "trend") == 1.0

    def test_repricing_default_subphase_is_relief(self):
        """repricing + 子阶段缺失/none → 默认 relief。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            ImpactMultiplier,
        )

        im = ImpactMultiplier()
        # 子阶段为 "none" → 默认 relief
        assert im.get_multiplier("repricing", "C1", "none") == 1.2  # relief 值
        # 子阶段为 None → 默认 relief
        assert im.get_multiplier("repricing", "C2", None) == 1.3  # relief 值
        # 子阶段为未知值 → 默认 relief
        assert im.get_multiplier("repricing", "C4", "unknown") == 0.3  # relief 值

    def test_repricing_c4_attenuates_across_subphases(self):
        """repricing 阶段 C4 宏观面逐子阶段衰减 (0.3→0.2→0.1)。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            ImpactMultiplier,
        )

        im = ImpactMultiplier()
        relief = im.get_multiplier("repricing", "C4", "relief")
        verification = im.get_multiplier("repricing", "C4", "verification")
        trend = im.get_multiplier("repricing", "C4", "trend")
        # §8.2: 0.3 → 0.2 → 0.1 单调衰减
        assert relief > verification > trend
        assert relief == 0.3
        assert verification == 0.2
        assert trend == 0.1


class TestGetMultipliers:
    """get_multipliers 批量查询测试。"""

    def test_returns_array_aligned_with_factor_names(self):
        """返回的 multipliers 与 factor_names 长度对齐。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            CROSS_ATTENTION_FACTOR_METRICS,
            ImpactMultiplier,
        )

        im = ImpactMultiplier()
        factor_names = [m[2] for m in CROSS_ATTENTION_FACTOR_METRICS]
        multipliers = im.get_multipliers("event", factor_names)
        assert multipliers.shape == (len(factor_names),)
        assert multipliers.dtype == np.float64

    def test_neutral_returns_all_ones(self):
        """neutral 阶段所有因子 multiplier = 1.0。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            CROSS_ATTENTION_FACTOR_METRICS,
            ImpactMultiplier,
        )

        im = ImpactMultiplier()
        factor_names = [m[2] for m in CROSS_ATTENTION_FACTOR_METRICS]
        multipliers = im.get_multipliers("neutral", factor_names)
        assert np.all(multipliers == 1.0)

    def test_event_amplifies_c1_factors(self):
        """event 阶段 C1 维度因子 multiplier = 1.5。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            CROSS_ATTENTION_FACTOR_METRICS,
            ImpactMultiplier,
        )

        im = ImpactMultiplier()
        factor_names = [m[2] for m in CROSS_ATTENTION_FACTOR_METRICS]
        multipliers = im.get_multipliers("event", factor_names)

        # C1 因子 (前 7 个) 应为 1.5
        for i, entry in enumerate(CROSS_ATTENTION_FACTOR_METRICS):
            if entry[3] == "C1":
                assert multipliers[i] == 1.5, (
                    f"C1 因子 {entry[2]} 在 event 阶段应为 1.5, 实际 {multipliers[i]}"
                )

    def test_unknown_factor_name_returns_1(self):
        """不在 CROSS_ATTENTION_FACTOR_METRICS 中的因子名 → 1.0 (FAIL-OPEN)。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            ImpactMultiplier,
        )

        im = ImpactMultiplier()
        # 传入不在元数据中的因子名
        multipliers = im.get_multipliers(
            "event", ["unknown_factor_1", "unknown_factor_2"]
        )
        assert np.all(multipliers == 1.0)


class TestApplyImpactMultiplier:
    """apply_impact_multiplier 应用测试。"""

    def test_none_multipliers_returns_original(self):
        """multipliers=None → 原样返回 (FAIL-OPEN)。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            apply_impact_multiplier,
        )

        factors = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        result = apply_impact_multiplier(factors, None)
        assert np.array_equal(result, factors)

    def test_basic_multiplication(self):
        """基本乘法: (N,F) × (F,) → (N,F)。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            apply_impact_multiplier,
        )

        factors = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
        multipliers = np.array([2.0, 0.5, 1.0])
        result = apply_impact_multiplier(factors, multipliers)
        expected = np.array([[2.0, 1.0, 3.0], [8.0, 2.5, 6.0]])
        assert np.allclose(result, expected)

    def test_does_not_modify_input(self):
        """不修改输入 factors 数组。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            apply_impact_multiplier,
        )

        factors = np.array([[1.0, 2.0], [3.0, 4.0]])
        factors_copy = factors.copy()
        multipliers = np.array([0.5, 2.0])
        _ = apply_impact_multiplier(factors, multipliers)
        assert np.array_equal(factors, factors_copy), "输入 factors 不应被修改"

    def test_dimension_mismatch_returns_original(self):
        """multipliers 维度与 factors 不匹配 → 原样返回 (FAIL-OPEN)。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            apply_impact_multiplier,
        )

        factors = np.array([[1.0, 2.0, 3.0]])  # (1, 3)
        multipliers = np.array([0.5, 2.0])  # (2,) — 不匹配
        result = apply_impact_multiplier(factors, multipliers)
        assert np.array_equal(result, factors)

    def test_empty_factors_returns_empty(self):
        """空 factors → 原样返回。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            apply_impact_multiplier,
        )

        factors = np.zeros((0, 5))
        multipliers = np.array([0.5, 1.0, 1.5, 2.0, 0.1])
        result = apply_impact_multiplier(factors, multipliers)
        assert result.shape == (0, 5)


class TestEndToEndDecay:
    """端到端衰减测试: ImpactMultiplier → apply_impact_multiplier。"""

    def test_neutral_no_change(self):
        """neutral 阶段因子矩阵不变。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            CROSS_ATTENTION_FACTOR_METRICS,
            ImpactMultiplier,
            apply_impact_multiplier,
        )

        im = ImpactMultiplier()
        factor_names = [m[2] for m in CROSS_ATTENTION_FACTOR_METRICS]
        multipliers = im.get_multipliers("neutral", factor_names)

        factors = np.ones((10, len(factor_names)), dtype=np.float64)
        result = apply_impact_multiplier(factors, multipliers)
        assert np.allclose(result, factors)

    def test_event_amplifies_c1_attenuates_c6(self):
        """event 阶段 C1 放大 1.5, C6 衰减 0.9。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            CROSS_ATTENTION_FACTOR_METRICS,
            ImpactMultiplier,
            apply_impact_multiplier,
        )

        im = ImpactMultiplier()
        factor_names = [m[2] for m in CROSS_ATTENTION_FACTOR_METRICS]
        multipliers = im.get_multipliers("event", factor_names)

        factors = np.ones((1, len(factor_names)), dtype=np.float64)
        result = apply_impact_multiplier(factors, multipliers)

        for i, entry in enumerate(CROSS_ATTENTION_FACTOR_METRICS):
            dim = entry[3]
            if dim == "C1":
                assert result[0, i] == 1.5
            elif dim == "C6":
                assert result[0, i] == 0.9

    def test_repricing_trend_c4_almost_zero(self):
        """repricing/trend 阶段 C4 宏观面几乎归零 (0.1)。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            CROSS_ATTENTION_FACTOR_METRICS,
            ImpactMultiplier,
            apply_impact_multiplier,
        )

        im = ImpactMultiplier()
        factor_names = [m[2] for m in CROSS_ATTENTION_FACTOR_METRICS]
        multipliers = im.get_multipliers(
            "repricing", factor_names, "trend"
        )

        factors = np.ones((1, len(factor_names)), dtype=np.float64)
        result = apply_impact_multiplier(factors, multipliers)

        for i, entry in enumerate(CROSS_ATTENTION_FACTOR_METRICS):
            if entry[3] == "C4":
                assert result[0, i] == 0.1, (
                    f"repricing/trend C4 因子 {entry[2]} 应为 0.1"
                )


class TestBuildExogenousFactorsWithDecay:
    """build_exogenous_factors_for_cross_attention 集成测试.

    这些测试验证函数接受 impact_multipliers 参数 (FAIL-OPEN, 不依赖 DAL).
    """

    def test_function_accepts_impact_multipliers_param(self):
        """build_exogenous_factors_for_cross_attention 接受 impact_multipliers 参数。"""
        from datetime import datetime, timezone

        from dreambuddy_evolution.core.exogenous_data_bridge import (
            build_exogenous_factors_for_cross_attention,
        )

        now = datetime.now(timezone.utc)
        # 传入 None multipliers — 不应报错 (即使 DAL 不可用, FAIL-OPEN 返回全 0)
        factors, names = build_exogenous_factors_for_cross_attention(
            timestamps=[now],
            impact_multipliers=None,
        )
        # DAL 可用时返回 36 因子; 不可用时返回 0 列 (FAIL-OPEN)
        assert factors.shape[0] == 1

    def test_empty_timestamps_returns_empty(self):
        """空 timestamps → 空矩阵 (FAIL-OPEN)。"""
        from dreambuddy_evolution.core.exogenous_data_bridge import (
            build_exogenous_factors_for_cross_attention,
        )

        factors, names = build_exogenous_factors_for_cross_attention(
            timestamps=[],
            impact_multipliers=np.array([0.5, 1.0, 1.5]),
        )
        assert factors.size == 0
