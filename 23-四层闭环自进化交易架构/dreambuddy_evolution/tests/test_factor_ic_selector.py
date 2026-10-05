"""
C1 RED: 因子 IC 筛选器测试

测试 FactorICSelector 的核心能力：
  1. Spearman RankIC 计算
  2. IC_IR = mean(IC) / std(IC)
  3. 筛选逻辑：|IC_mean| > 0.03 且 |IC_IR| > 0.5 且胜率 > 55%
  4. VIF 共线性检验（VIF > 10 剔除）
  5. 因子排行榜输出（按 |IC_IR| 降序）

RED 阶段：factor_ic_selector 模块尚不存在 → 所有测试 ModuleNotFoundError
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


class TestFactorICSelector:
    """C1 RED: 验证 factor_ic_selector 模块可导入且核心逻辑正确。"""

    def test_module_importable(self):
        """RED: 模块应可导入（当前不存在 → ModuleNotFoundError）。"""
        from dreambuddy_evolution.core.factor_ic_selector import FactorICSelector  # noqa: F401

    def test_compute_rank_ic(self):
        """Spearman RankIC 计算正确性。"""
        from dreambuddy_evolution.core.factor_ic_selector import _compute_rank_ic

        # 完全正相关
        f = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        r = np.array([0.01, 0.02, 0.03, 0.04, 0.05])
        ic = _compute_rank_ic(f, r)
        assert abs(ic - 1.0) < 1e-6

        # 完全负相关
        r_neg = np.array([0.05, 0.04, 0.03, 0.02, 0.01])
        ic_neg = _compute_rank_ic(f, r_neg)
        assert abs(ic_neg + 1.0) < 1e-6

        # 无相关
        r_rand = np.array([0.03, 0.01, 0.05, 0.02, 0.04])
        ic_rand = _compute_rank_ic(f, r_rand)
        assert abs(ic_rand) < 0.5  # 大致无相关

    def test_compute_ic_ir(self):
        """IC_IR = mean(IC) / std(IC)。"""
        from dreambuddy_evolution.core.factor_ic_selector import _compute_ic_ir

        ic_series = [0.05, 0.06, 0.04, 0.07, 0.05]
        ic_mean, ic_ir = _compute_ic_ir(ic_series)
        assert abs(ic_mean - 0.054) < 1e-3
        # std ≈ 0.0114, ic_ir ≈ 4.74
        assert ic_ir > 3.0

        # 全零 IC → ic_ir = 0
        ic_zero = [0.0, 0.0, 0.0, 0.0, 0.0]
        _, ic_ir_zero = _compute_ic_ir(ic_zero)
        assert ic_ir_zero == 0.0

    def test_select_factors_significant(self):
        """显著因子应被选中，不显著的应剔除。"""
        from dreambuddy_evolution.core.factor_ic_selector import FactorICSelector

        # 构造数据：因子A 与未来1日收益强正相关（显著），因子B 弱相关（不显著）
        np.random.seed(42)
        n = 500
        dates = pd.date_range("2023-01-01", periods=n, freq="D")

        # 价格
        returns = np.random.randn(n) * 0.02
        prices = 100 * np.exp(np.cumsum(returns))

        # 因子A：与未来1日收益正相关
        forward_ret_1d = np.concatenate([returns[1:], np.zeros(1)])
        factor_a = forward_ret_1d + np.random.randn(n) * 0.001

        # 因子B：纯噪声
        factor_b = np.random.randn(n)

        # 因子C：与未来1日收益负相关，但加入足够独立噪声避免与 factor_a 共线
        factor_c = -forward_ret_1d + np.random.randn(n) * 0.05

        factors_df = pd.DataFrame(
            {"factor_a": factor_a, "factor_b": factor_b, "factor_c": factor_c},
            index=dates,
        )

        selector = FactorICSelector(dal_path=":memory:", price_path="")
        # 注入测试数据（不依赖 DAL）
        selector._price_df = pd.DataFrame({"close": prices}, index=dates)
        selector._factors_df = factors_df

        result = selector.select_factors(
            candidate_metrics=[("test", "factor_a"), ("test", "factor_b"), ("test", "factor_c")],
            horizons=[1],
            ic_threshold=0.1,  # 严格阈值，确保噪声因子被剔除
            ir_threshold=0.5,
            win_rate_threshold=0.55,
            vif_threshold=10.0,
            top_k=10,
        )

        # factor_a 和 factor_c 应显著（与未来收益相关），factor_b 不应
        selected = result.selected_factors
        assert "factor_a" in selected
        assert "factor_c" in selected
        assert "factor_b" not in selected

    def test_vif_collinearity_removal(self):
        """VIF > 10 的共线因子应被剔除（保留 IC_IR 更高者）。"""
        from dreambuddy_evolution.core.factor_ic_selector import FactorICSelector

        np.random.seed(42)
        n = 500
        dates = pd.date_range("2023-01-01", periods=n, freq="D")

        returns = np.random.randn(n) * 0.02
        prices = 100 * np.exp(np.cumsum(returns))
        forward_ret_1d = np.concatenate([returns[1:], np.zeros(1)])

        # factor_a 和 factor_x 高度共线（factor_x = 2 * factor_a + 噪声）
        factor_a = forward_ret_1d + np.random.randn(n) * 0.001
        factor_x = 2.0 * factor_a + np.random.randn(n) * 0.0001  # 几乎完全共线

        factors_df = pd.DataFrame(
            {"factor_a": factor_a, "factor_x": factor_x}, index=dates
        )

        selector = FactorICSelector(dal_path=":memory:", price_path="")
        selector._price_df = pd.DataFrame({"close": prices}, index=dates)
        selector._factors_df = factors_df

        result = selector.select_factors(
            candidate_metrics=[("test", "factor_a"), ("test", "factor_x")],
            horizons=[1],
            ic_threshold=0.03,
            ir_threshold=0.5,
            win_rate_threshold=0.55,
            vif_threshold=10.0,  # 严格共线性阈值
            top_k=10,
        )

        # 两个因子中只能保留一个（共线性）
        assert len(result.selected_factors) <= 1
        # 被剔除的应在 excluded 列表中
        excluded_names = [e["name"] for e in result.excluded]
        assert any("vif" in str(e.get("reason", "")).lower() for e in result.excluded)

    def test_ranking_sorted_by_abs_ic_ir(self):
        """排行榜应按 |IC_IR| 降序排列。"""
        from dreambuddy_evolution.core.factor_ic_selector import FactorICSelector

        np.random.seed(42)
        n = 500
        dates = pd.date_range("2023-01-01", periods=n, freq="D")

        returns = np.random.randn(n) * 0.02
        prices = 100 * np.exp(np.cumsum(returns))
        forward_ret_1d = np.concatenate([returns[1:], np.zeros(1)])

        # 强因子
        factor_strong = forward_ret_1d + np.random.randn(n) * 0.001
        # 中等因子
        factor_med = 0.5 * forward_ret_1d + np.random.randn(n) * 0.01
        # 弱因子
        factor_weak = np.random.randn(n)

        factors_df = pd.DataFrame(
            {"strong": factor_strong, "med": factor_med, "weak": factor_weak},
            index=dates,
        )

        selector = FactorICSelector(dal_path=":memory:", price_path="")
        selector._price_df = pd.DataFrame({"close": prices}, index=dates)
        selector._factors_df = factors_df

        result = selector.select_factors(
            candidate_metrics=[("test", "strong"), ("test", "med"), ("test", "weak")],
            horizons=[1],
            ic_threshold=0.03,
            ir_threshold=0.5,
            win_rate_threshold=0.55,
            vif_threshold=10.0,
            top_k=10,
        )

        ranking = result.ranking
        # strong 的 |IC_IR| 应最大
        assert ranking.iloc[0]["name"] == "strong"
        # med 应在中间
        assert ranking.iloc[1]["name"] == "med"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
