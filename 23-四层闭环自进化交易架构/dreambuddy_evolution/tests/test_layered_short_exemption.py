"""路径B TDD: 三因子分层豁免测试

SPEC-自进化系统做空能力疏通探讨 §4 路径B：
  将三因子豁免从 AND 逻辑（全满足才豁免）升级为分层豁免。

分层规则:
  - 3 因子全满足 → 全豁免，仓位 0.7x，止损 0.5x，允许加仓
  - 2 因子满足 → 试探豁免，仓位 0.2x，止损 0.5x，禁止加仓
  - 1 因子满足 → 不豁免，维持 SHORT_BAN
  - 0 因子满足 → 不豁免，维持 SHORT_BAN

三因子条件（与 ThreeFactorShortDetector 一致）:
  1. pattern_factor <= -0.5  (头肩顶看跌)
  2. btc_regime == "WEAK"     (BTC 与美股高相关弱市)
  3. etf_flow_norm < -0.1     (ETF 净流出)

安全侧 FAIL-OPEN: 异常/缺失 → 不豁免（维持 SHORT_BAN 铁律）
开关: enable_layered_short_exemption（默认 False → 回退 AND 逻辑：仅 3 因子全满足才豁免）
"""
import sys
from pathlib import Path

import pytest

# ---- path inject ----
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


@pytest.fixture(autouse=True)
def _auto_enable_layered_short():
    """自动开启 enable_layered_short_exemption 开关。

    Switch 回退测试类内部会 set_switch 覆盖此 fixture。
    """
    from dreambuddy_evolution.agi_config import set_switch, get_switch
    _orig = get_switch("enable_layered_short_exemption")
    set_switch("enable_layered_short_exemption", True)
    yield
    set_switch("enable_layered_short_exemption", _orig)


# ---- 因子常量（与 ThreeFactorShortDetector 一致）----
PF_BEARISH = -0.8      # pattern_factor 满足（<= -0.5）
PF_NEUTRAL = -0.3      # pattern_factor 不满足（> -0.5）
REGIME_WEAK = "WEAK"
REGIME_STRONG = "STRONG"
ETF_OUTFLOW = -0.3     # etf_flow_norm 满足（< -0.1）
ETF_INFLOW = 0.2       # etf_flow_norm 不满足（>= -0.1）


class TestLayeredExemptionResult:
    """结果数据类字段验证"""

    def test_result_has_required_fields(self):
        """LayeredExemptionResult 包含 layer/exempted/position_multiplier/stop_loss_multiplier/factors_satisfied/allow_add_position"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
            LayeredExemptionResult,
        )
        le = LayeredShortExemption()
        result = le.evaluate(PF_BEARISH, REGIME_WEAK, ETF_OUTFLOW)
        assert hasattr(result, "layer")
        assert hasattr(result, "exempted")
        assert hasattr(result, "position_multiplier")
        assert hasattr(result, "stop_loss_multiplier")
        assert hasattr(result, "factors_satisfied")
        assert hasattr(result, "allow_add_position")


class TestSwitchOffFallback:
    """开关关闭时回退到 AND 逻辑（仅 3 因子全满足才豁免）"""

    def test_switch_off_3_factors_exempted(self):
        """开关关闭 + 3 因子全满足 → 全豁免（AND 逻辑回退）"""
        from dreambuddy_evolution.agi_config import set_switch
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        set_switch("enable_layered_short_exemption", False)
        le = LayeredShortExemption()
        result = le.evaluate(PF_BEARISH, REGIME_WEAK, ETF_OUTFLOW)
        assert result.exempted is True
        assert result.layer == 2
        assert result.position_multiplier == pytest.approx(0.7)

    def test_switch_off_2_factors_not_exempted(self):
        """开关关闭 + 2 因子满足 → 不豁免（AND 逻辑：2 因子不够）"""
        from dreambuddy_evolution.agi_config import set_switch
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        set_switch("enable_layered_short_exemption", False)
        le = LayeredShortExemption()
        result = le.evaluate(PF_BEARISH, REGIME_WEAK, ETF_INFLOW)
        assert result.exempted is False
        assert result.layer == 0
        assert result.position_multiplier == pytest.approx(0.0)

    def test_switch_off_1_factor_not_exempted(self):
        """开关关闭 + 1 因子满足 → 不豁免"""
        from dreambuddy_evolution.agi_config import set_switch
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        set_switch("enable_layered_short_exemption", False)
        le = LayeredShortExemption()
        result = le.evaluate(PF_BEARISH, REGIME_STRONG, ETF_INFLOW)
        assert result.exempted is False

    def test_switch_off_0_factors_not_exempted(self):
        """开关关闭 + 0 因子满足 → 不豁免"""
        from dreambuddy_evolution.agi_config import set_switch
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        set_switch("enable_layered_short_exemption", False)
        le = LayeredShortExemption()
        result = le.evaluate(PF_NEUTRAL, REGIME_STRONG, ETF_INFLOW)
        assert result.exempted is False


class TestSwitchOnFullExemption:
    """开关开启 + 3 因子全满足 → 全豁免"""

    def test_3_factors_full_exemption_layer(self):
        """3 因子全满足 → layer=2（全豁免）"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(PF_BEARISH, REGIME_WEAK, ETF_OUTFLOW)
        assert result.layer == 2
        assert result.exempted is True

    def test_3_factors_position_07(self):
        """3 因子全满足 → 仓位 0.7x"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(PF_BEARISH, REGIME_WEAK, ETF_OUTFLOW)
        assert result.position_multiplier == pytest.approx(0.7)

    def test_3_factors_stop_loss_05(self):
        """3 因子全满足 → 止损 0.5x"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(PF_BEARISH, REGIME_WEAK, ETF_OUTFLOW)
        assert result.stop_loss_multiplier == pytest.approx(0.5)

    def test_3_factors_allow_add_position(self):
        """3 因子全满足 → 允许加仓"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(PF_BEARISH, REGIME_WEAK, ETF_OUTFLOW)
        assert result.allow_add_position is True

    def test_3_factors_factors_satisfied_3(self):
        """3 因子全满足 → factors_satisfied=3"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(PF_BEARISH, REGIME_WEAK, ETF_OUTFLOW)
        assert result.factors_satisfied == 3


class TestSwitchOnTrialExemption:
    """开关开启 + 2 因子满足 → 试探豁免"""

    def test_2_factors_trial_layer(self):
        """2 因子满足 → layer=1（试探豁免）"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(PF_BEARISH, REGIME_WEAK, ETF_INFLOW)
        assert result.layer == 1
        assert result.exempted is True

    def test_2_factors_position_02(self):
        """2 因子满足 → 仓位 0.2x"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(PF_BEARISH, REGIME_WEAK, ETF_INFLOW)
        assert result.position_multiplier == pytest.approx(0.2)

    def test_2_factors_stop_loss_05(self):
        """2 因子满足 → 止损 0.5x"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(PF_BEARISH, REGIME_WEAK, ETF_INFLOW)
        assert result.stop_loss_multiplier == pytest.approx(0.5)

    def test_2_factors_no_add_position(self):
        """2 因子满足 → 禁止加仓（试探仓不追加）"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(PF_BEARISH, REGIME_WEAK, ETF_INFLOW)
        assert result.allow_add_position is False

    def test_2_factors_factors_satisfied_2(self):
        """2 因子满足 → factors_satisfied=2"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(PF_BEARISH, REGIME_WEAK, ETF_INFLOW)
        assert result.factors_satisfied == 2

    def test_2_factors_pattern_regime_only(self):
        """因子1+因子2 满足（因子3不满足）→ 试探豁免"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(PF_BEARISH, REGIME_WEAK, ETF_INFLOW)
        assert result.layer == 1

    def test_2_factors_pattern_etf_only(self):
        """因子1+因子3 满足（因子2不满足）→ 试探豁免"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(PF_BEARISH, REGIME_STRONG, ETF_OUTFLOW)
        assert result.layer == 1

    def test_2_factors_regime_etf_only(self):
        """因子2+因子3 满足（因子1不满足）→ 试探豁免"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(PF_NEUTRAL, REGIME_WEAK, ETF_OUTFLOW)
        assert result.layer == 1


class TestSwitchOnNoExemption:
    """开关开启 + 1/0 因子满足 → 不豁免"""

    def test_1_factor_not_exempted(self):
        """1 因子满足 → 不豁免（layer=0）"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(PF_BEARISH, REGIME_STRONG, ETF_INFLOW)
        assert result.exempted is False
        assert result.layer == 0

    def test_1_factor_position_zero(self):
        """1 因子满足 → 仓位 0.0"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(PF_BEARISH, REGIME_STRONG, ETF_INFLOW)
        assert result.position_multiplier == pytest.approx(0.0)

    def test_1_factor_stop_loss_zero(self):
        """1 因子满足 → 止损 0.0"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(PF_BEARISH, REGIME_STRONG, ETF_INFLOW)
        assert result.stop_loss_multiplier == pytest.approx(0.0)

    def test_1_factor_no_add_position(self):
        """1 因子满足 → 禁止加仓"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(PF_BEARISH, REGIME_STRONG, ETF_INFLOW)
        assert result.allow_add_position is False

    def test_0_factors_not_exempted(self):
        """0 因子满足 → 不豁免"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(PF_NEUTRAL, REGIME_STRONG, ETF_INFLOW)
        assert result.exempted is False
        assert result.layer == 0
        assert result.factors_satisfied == 0


class TestFactorBoundary:
    """因子边界值测试"""

    def test_pattern_boundary_minus_05_satisfied(self):
        """pattern_factor=-0.5（边界值）→ 满足（<= -0.5）"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(-0.5, REGIME_WEAK, ETF_OUTFLOW)
        assert result.factors_satisfied == 3

    def test_pattern_boundary_minus_049_not_satisfied(self):
        """pattern_factor=-0.49（边界值）→ 不满足（> -0.5）"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(-0.49, REGIME_WEAK, ETF_OUTFLOW)
        assert result.factors_satisfied == 2

    def test_etf_boundary_minus_01_not_satisfied(self):
        """etf_flow_norm=-0.1（边界值）→ 不满足（< -0.1 严格小于）"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(PF_BEARISH, REGIME_WEAK, -0.1)
        assert result.factors_satisfied == 2

    def test_etf_boundary_minus_011_satisfied(self):
        """etf_flow_norm=-0.11（边界值）→ 满足（< -0.1）"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(PF_BEARISH, REGIME_WEAK, -0.11)
        assert result.factors_satisfied == 3

    def test_regime_case_insensitive(self):
        """btc_regime 大小写不敏感（weak/WEAK/Weak 均满足）"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        for regime in ("weak", "WEAK", "Weak"):
            result = le.evaluate(PF_BEARISH, regime, ETF_OUTFLOW)
            assert result.factors_satisfied == 3, f"regime={regime} should satisfy"


class TestFailOpen:
    """FAIL-OPEN: 异常/缺失 → 不豁免（维持 SHORT_BAN）"""

    def test_none_pattern_factor(self):
        """pattern_factor=None → 不豁免"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(None, REGIME_WEAK, ETF_OUTFLOW)
        assert result.exempted is False

    def test_none_btc_regime(self):
        """btc_regime=None → 不豁免"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(PF_BEARISH, None, ETF_OUTFLOW)
        assert result.exempted is False

    def test_none_etf_flow_norm(self):
        """etf_flow_norm=None → 不豁免"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(PF_BEARISH, REGIME_WEAK, None)
        assert result.exempted is False

    def test_all_none(self):
        """全部 None → 不豁免"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(None, None, None)
        assert result.exempted is False

    def test_string_pattern_factor(self):
        """pattern_factor 传字符串 → 不豁免"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate("not_a_number", REGIME_WEAK, ETF_OUTFLOW)
        assert result.exempted is False

    def test_nan_pattern_factor(self):
        """pattern_factor=NaN → 不豁免"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(float("nan"), REGIME_WEAK, ETF_OUTFLOW)
        assert result.exempted is False

    def test_inf_etf_flow_norm(self):
        """etf_flow_norm=inf → 不豁免"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        result = le.evaluate(PF_BEARISH, REGIME_WEAK, float("inf"))
        assert result.exempted is False


class TestSwitchCrash:
    """开关检查异常 → FAIL-OPEN 不豁免"""

    def test_switch_check_exception_not_exempted(self):
        """开关检查抛异常 → 不豁免"""
        from dreambuddy_evolution.engines.layered_short_exemption import (
            LayeredShortExemption,
        )
        le = LayeredShortExemption()
        # 模拟开关检查异常：patch get_switch 抛异常
        import dreambuddy_evolution.agi_config as agi_config
        original = agi_config.get_switch

        def _crash(*a, **kw):
            raise RuntimeError("simulated crash")

        agi_config.get_switch = _crash
        try:
            result = le.evaluate(PF_BEARISH, REGIME_WEAK, ETF_OUTFLOW)
            assert result.exempted is False
        finally:
            agi_config.get_switch = original
