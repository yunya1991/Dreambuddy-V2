"""路径D TDD: 因子池扩展测试

SPEC-自进化系统做空能力疏通探讨 §4 路径D：
  扩展三因子池子，新增 3 个做空因子。

新因子:
  1. 资金费率因子: funding_rate > 0.1%（多头过度拥挤，做空赔率高）
  2. OI-Price 背离因子: OI↑ + Price↓（持仓量上升但价格下跌，空头主力进场）
  3. 清算热力图因子: 降级为可选（需 POC 确认数据可用性）

每个因子独立开关（默认 False）:
  - enable_funding_rate_factor
  - enable_oi_price_divergence_factor
  - enable_liquidation_heatmap_factor

安全侧 FAIL-OPEN: 异常/缺失 → 因子不满足
"""
import sys
from pathlib import Path

import pytest

# ---- path inject ----
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


@pytest.fixture(autouse=True)
def _auto_enable_factor_switches():
    """自动开启所有路径D因子开关。

    单因子开关测试类内部会 set_switch 覆盖此 fixture。
    """
    from dreambuddy_evolution.agi_config import set_switch, get_switch
    _orig_fr = get_switch("enable_funding_rate_factor")
    _orig_oi = get_switch("enable_oi_price_divergence_factor")
    _orig_lq = get_switch("enable_liquidation_heatmap_factor")
    set_switch("enable_funding_rate_factor", True)
    set_switch("enable_oi_price_divergence_factor", True)
    set_switch("enable_liquidation_heatmap_factor", True)
    yield
    set_switch("enable_funding_rate_factor", _orig_fr)
    set_switch("enable_oi_price_divergence_factor", _orig_oi)
    set_switch("enable_liquidation_heatmap_factor", _orig_lq)


class TestResultFields:
    """结果数据类字段验证"""

    def test_result_has_required_fields(self):
        """ExpandedFactorResult 包含所有必要字段"""
        from dreambuddy_evolution.engines.factor_pool_expansion import (
            FactorPoolExpansion,
            ExpandedFactorResult,
        )
        fp = FactorPoolExpansion()
        result = fp.evaluate(
            funding_rate=0.002,
            oi_change_pct=0.05,
            price_change_pct=-0.02,
        )
        assert hasattr(result, "funding_rate_satisfied")
        assert hasattr(result, "oi_price_divergence_satisfied")
        assert hasattr(result, "liquidation_heatmap_satisfied")
        assert hasattr(result, "new_factors_satisfied")
        assert hasattr(result, "funding_rate_value")
        assert hasattr(result, "oi_change_pct")
        assert hasattr(result, "price_change_pct")


class TestFundingRateFactor:
    """资金费率因子: funding_rate > 0.1% (0.001)"""

    def test_funding_rate_above_threshold(self):
        """funding_rate=0.2% > 0.1% → 满足"""
        from dreambuddy_evolution.engines.factor_pool_expansion import (
            FactorPoolExpansion,
        )
        fp = FactorPoolExpansion()
        result = fp.evaluate(funding_rate=0.002, oi_change_pct=0.0, price_change_pct=0.0)
        assert result.funding_rate_satisfied is True

    def test_funding_rate_below_threshold(self):
        """funding_rate=0.05% < 0.1% → 不满足"""
        from dreambuddy_evolution.engines.factor_pool_expansion import (
            FactorPoolExpansion,
        )
        fp = FactorPoolExpansion()
        result = fp.evaluate(funding_rate=0.0005, oi_change_pct=0.0, price_change_pct=0.0)
        assert result.funding_rate_satisfied is False

    def test_funding_rate_boundary(self):
        """funding_rate=0.1% = 阈值 → 不满足（严格大于）"""
        from dreambuddy_evolution.engines.factor_pool_expansion import (
            FactorPoolExpansion,
        )
        fp = FactorPoolExpansion()
        result = fp.evaluate(funding_rate=0.001, oi_change_pct=0.0, price_change_pct=0.0)
        assert result.funding_rate_satisfied is False

    def test_funding_rate_negative(self):
        """funding_rate=-0.05%（负值，空头拥挤）→ 不满足"""
        from dreambuddy_evolution.engines.factor_pool_expansion import (
            FactorPoolExpansion,
        )
        fp = FactorPoolExpansion()
        result = fp.evaluate(funding_rate=-0.0005, oi_change_pct=0.0, price_change_pct=0.0)
        assert result.funding_rate_satisfied is False

    def test_funding_rate_none(self):
        """funding_rate=None → 不满足（FAIL-OPEN）"""
        from dreambuddy_evolution.engines.factor_pool_expansion import (
            FactorPoolExpansion,
        )
        fp = FactorPoolExpansion()
        result = fp.evaluate(funding_rate=None, oi_change_pct=0.0, price_change_pct=0.0)
        assert result.funding_rate_satisfied is False

    def test_funding_rate_switch_off(self):
        """开关关闭 → 因子不满足"""
        from dreambuddy_evolution.agi_config import set_switch
        from dreambuddy_evolution.engines.factor_pool_expansion import (
            FactorPoolExpansion,
        )
        set_switch("enable_funding_rate_factor", False)
        fp = FactorPoolExpansion()
        result = fp.evaluate(funding_rate=0.002, oi_change_pct=0.0, price_change_pct=0.0)
        assert result.funding_rate_satisfied is False


class TestOiPriceDivergenceFactor:
    """OI-Price 背离因子: OI↑ + Price↓"""

    def test_oi_up_price_down_satisfied(self):
        """OI↑5% + Price↓2% → 满足"""
        from dreambuddy_evolution.engines.factor_pool_expansion import (
            FactorPoolExpansion,
        )
        fp = FactorPoolExpansion()
        result = fp.evaluate(funding_rate=0.0, oi_change_pct=0.05, price_change_pct=-0.02)
        assert result.oi_price_divergence_satisfied is True

    def test_oi_up_price_up_not_satisfied(self):
        """OI↑5% + Price↑2% → 不满足（价格没跌）"""
        from dreambuddy_evolution.engines.factor_pool_expansion import (
            FactorPoolExpansion,
        )
        fp = FactorPoolExpansion()
        result = fp.evaluate(funding_rate=0.0, oi_change_pct=0.05, price_change_pct=0.02)
        assert result.oi_price_divergence_satisfied is False

    def test_oi_down_price_down_not_satisfied(self):
        """OI↓5% + Price↓2% → 不满足（OI没升）"""
        from dreambuddy_evolution.engines.factor_pool_expansion import (
            FactorPoolExpansion,
        )
        fp = FactorPoolExpansion()
        result = fp.evaluate(funding_rate=0.0, oi_change_pct=-0.05, price_change_pct=-0.02)
        assert result.oi_price_divergence_satisfied is False

    def test_oi_down_price_up_not_satisfied(self):
        """OI↓5% + Price↑2% → 不满足"""
        from dreambuddy_evolution.engines.factor_pool_expansion import (
            FactorPoolExpansion,
        )
        fp = FactorPoolExpansion()
        result = fp.evaluate(funding_rate=0.0, oi_change_pct=-0.05, price_change_pct=0.02)
        assert result.oi_price_divergence_satisfied is False

    def test_oi_zero_price_down_not_satisfied(self):
        """OI=0 + Price↓2% → 不满足（OI没升）"""
        from dreambuddy_evolution.engines.factor_pool_expansion import (
            FactorPoolExpansion,
        )
        fp = FactorPoolExpansion()
        result = fp.evaluate(funding_rate=0.0, oi_change_pct=0.0, price_change_pct=-0.02)
        assert result.oi_price_divergence_satisfied is False

    def test_oi_up_price_flat_not_satisfied(self):
        """OI↑5% + Price=0 → 不满足（价格没跌）"""
        from dreambuddy_evolution.engines.factor_pool_expansion import (
            FactorPoolExpansion,
        )
        fp = FactorPoolExpansion()
        result = fp.evaluate(funding_rate=0.0, oi_change_pct=0.05, price_change_pct=0.0)
        assert result.oi_price_divergence_satisfied is False

    def test_oi_none_not_satisfied(self):
        """oi_change_pct=None → 不满足（FAIL-OPEN）"""
        from dreambuddy_evolution.engines.factor_pool_expansion import (
            FactorPoolExpansion,
        )
        fp = FactorPoolExpansion()
        result = fp.evaluate(funding_rate=0.0, oi_change_pct=None, price_change_pct=-0.02)
        assert result.oi_price_divergence_satisfied is False

    def test_price_none_not_satisfied(self):
        """price_change_pct=None → 不满足（FAIL-OPEN）"""
        from dreambuddy_evolution.engines.factor_pool_expansion import (
            FactorPoolExpansion,
        )
        fp = FactorPoolExpansion()
        result = fp.evaluate(funding_rate=0.0, oi_change_pct=0.05, price_change_pct=None)
        assert result.oi_price_divergence_satisfied is False

    def test_oi_price_switch_off(self):
        """开关关闭 → 因子不满足"""
        from dreambuddy_evolution.agi_config import set_switch
        from dreambuddy_evolution.engines.factor_pool_expansion import (
            FactorPoolExpansion,
        )
        set_switch("enable_oi_price_divergence_factor", False)
        fp = FactorPoolExpansion()
        result = fp.evaluate(funding_rate=0.0, oi_change_pct=0.05, price_change_pct=-0.02)
        assert result.oi_price_divergence_satisfied is False


class TestLiquidationHeatmapFactor:
    """清算热力图因子: 降级为可选（需 POC）"""

    def test_liquidation_not_satisfied_without_poc(self):
        """无 POC 数据 → 不满足（降级为可选因子）"""
        from dreambuddy_evolution.engines.factor_pool_expansion import (
            FactorPoolExpansion,
        )
        fp = FactorPoolExpansion()
        result = fp.evaluate(funding_rate=0.0, oi_change_pct=0.0, price_change_pct=0.0)
        assert result.liquidation_heatmap_satisfied is False

    def test_liquidation_switch_off_not_satisfied(self):
        """开关关闭 → 不满足"""
        from dreambuddy_evolution.agi_config import set_switch
        from dreambuddy_evolution.engines.factor_pool_expansion import (
            FactorPoolExpansion,
        )
        set_switch("enable_liquidation_heatmap_factor", False)
        fp = FactorPoolExpansion()
        result = fp.evaluate(funding_rate=0.0, oi_change_pct=0.0, price_change_pct=0.0)
        assert result.liquidation_heatmap_satisfied is False


class TestNewFactorsCount:
    """新因子满足计数"""

    def test_all_3_satisfied(self):
        """3 因子全满足 → new_factors_satisfied=2（清算热力图降级不算）"""
        from dreambuddy_evolution.engines.factor_pool_expansion import (
            FactorPoolExpansion,
        )
        fp = FactorPoolExpansion()
        result = fp.evaluate(funding_rate=0.002, oi_change_pct=0.05, price_change_pct=-0.02)
        # 资金费率 + OI-Price 背离 = 2（清算热力图降级为可选，始终 False）
        assert result.new_factors_satisfied == 2

    def test_1_satisfied(self):
        """仅资金费率满足 → new_factors_satisfied=1"""
        from dreambuddy_evolution.engines.factor_pool_expansion import (
            FactorPoolExpansion,
        )
        fp = FactorPoolExpansion()
        result = fp.evaluate(funding_rate=0.002, oi_change_pct=-0.05, price_change_pct=0.02)
        assert result.new_factors_satisfied == 1

    def test_0_satisfied(self):
        """都不满足 → new_factors_satisfied=0"""
        from dreambuddy_evolution.engines.factor_pool_expansion import (
            FactorPoolExpansion,
        )
        fp = FactorPoolExpansion()
        result = fp.evaluate(funding_rate=0.0005, oi_change_pct=-0.05, price_change_pct=0.02)
        assert result.new_factors_satisfied == 0

    def test_all_switches_off_count_0(self):
        """所有开关关闭 → new_factors_satisfied=0"""
        from dreambuddy_evolution.agi_config import set_switch
        from dreambuddy_evolution.engines.factor_pool_expansion import (
            FactorPoolExpansion,
        )
        set_switch("enable_funding_rate_factor", False)
        set_switch("enable_oi_price_divergence_factor", False)
        set_switch("enable_liquidation_heatmap_factor", False)
        fp = FactorPoolExpansion()
        result = fp.evaluate(funding_rate=0.002, oi_change_pct=0.05, price_change_pct=-0.02)
        assert result.new_factors_satisfied == 0


class TestFailOpen:
    """FAIL-OPEN: 异常/缺失 → 因子不满足"""

    def test_nan_funding_rate(self):
        """funding_rate=NaN → 不满足"""
        from dreambuddy_evolution.engines.factor_pool_expansion import (
            FactorPoolExpansion,
        )
        fp = FactorPoolExpansion()
        result = fp.evaluate(funding_rate=float("nan"), oi_change_pct=0.0, price_change_pct=0.0)
        assert result.funding_rate_satisfied is False

    def test_inf_oi_change(self):
        """oi_change_pct=inf → 不满足"""
        from dreambuddy_evolution.engines.factor_pool_expansion import (
            FactorPoolExpansion,
        )
        fp = FactorPoolExpansion()
        result = fp.evaluate(funding_rate=0.0, oi_change_pct=float("inf"), price_change_pct=-0.02)
        assert result.oi_price_divergence_satisfied is False

    def test_string_funding_rate(self):
        """funding_rate 传字符串 → 不满足"""
        from dreambuddy_evolution.engines.factor_pool_expansion import (
            FactorPoolExpansion,
        )
        fp = FactorPoolExpansion()
        result = fp.evaluate(funding_rate="not_a_number", oi_change_pct=0.0, price_change_pct=0.0)
        assert result.funding_rate_satisfied is False

    def test_switch_crash_not_satisfied(self):
        """开关检查抛异常 → 因子不满足"""
        from dreambuddy_evolution.engines.factor_pool_expansion import (
            FactorPoolExpansion,
        )
        fp = FactorPoolExpansion()
        import dreambuddy_evolution.agi_config as agi_config
        original = agi_config.get_switch

        def _crash(*a, **kw):
            raise RuntimeError("simulated crash")

        agi_config.get_switch = _crash
        try:
            result = fp.evaluate(funding_rate=0.002, oi_change_pct=0.05, price_change_pct=-0.02)
            assert result.funding_rate_satisfied is False
            assert result.oi_price_divergence_satisfied is False
            assert result.new_factors_satisfied == 0
        finally:
            agi_config.get_switch = original
