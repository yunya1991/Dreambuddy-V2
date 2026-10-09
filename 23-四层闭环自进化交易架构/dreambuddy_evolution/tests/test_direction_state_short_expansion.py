"""路径C TDD: direction_state 解锁扩展测试

SPEC-自进化系统做空能力疏通探讨 §4 路径C：
  当前仅 direction_state == "SHORT_ONLY" 才解除 SHORT_BAN。
  扩展为多状态部分解锁 + 集中度限制。

状态映射（SPEC C.6 基于历史数据修订）:
  - SHORT_ONLY → 全解锁（仓位 1.0x）[现有行为]
  - TREND_BEAR (btc_regime == "WEAK") → 部分解锁（仓位 0.5x）[开关 ON]
  - REVERSAL → 不解锁（历史 0% 胜率，负期望）[即使开关 ON 也不解锁]
  - 其他状态 → 不解锁

集中度限制: 做空总仓位 / 总仓位 ≤ 30%（探讨值）

安全侧 FAIL-OPEN: 异常/缺失 → 不解锁（维持 SHORT_BAN）
开关: enable_direction_state_short_expansion（默认 False → 回退到仅 SHORT_ONLY 解锁）
"""
import sys
from pathlib import Path

import pytest

# ---- path inject ----
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


@pytest.fixture(autouse=True)
def _auto_enable_direction_state_expansion():
    """自动开启 enable_direction_state_short_expansion 开关。

    Switch 回退测试类内部会 set_switch 覆盖此 fixture。
    """
    from dreambuddy_evolution.agi_config import set_switch, get_switch
    _orig = get_switch("enable_direction_state_short_expansion")
    set_switch("enable_direction_state_short_expansion", True)
    yield
    set_switch("enable_direction_state_short_expansion", _orig)


class TestResultFields:
    """结果数据类字段验证"""

    def test_result_has_required_fields(self):
        """DirectionStateShortResult 包含 unlocked/position_multiplier/state/concentration_limit/concentration_exceeded"""
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
            DirectionStateShortResult,
        )
        exp = DirectionStateShortExpansion()
        result = exp.evaluate("SHORT_ONLY", "WEAK", 0.0)
        assert hasattr(result, "unlocked")
        assert hasattr(result, "position_multiplier")
        assert hasattr(result, "state")
        assert hasattr(result, "concentration_limit")
        assert hasattr(result, "concentration_exceeded")


class TestSwitchOffFallback:
    """开关关闭时回退到仅 SHORT_ONLY 解锁（现有行为）"""

    def test_switch_off_short_only_unlocked(self):
        """开关关闭 + SHORT_ONLY → 全解锁 1.0x"""
        from dreambuddy_evolution.agi_config import set_switch
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        set_switch("enable_direction_state_short_expansion", False)
        exp = DirectionStateShortExpansion()
        result = exp.evaluate("SHORT_ONLY", "WEAK", 0.0)
        assert result.unlocked is True
        assert result.position_multiplier == pytest.approx(1.0)

    def test_switch_off_trend_bear_not_unlocked(self):
        """开关关闭 + btc_regime=WEAK → 不解锁（TREND_BEAR 需开关 ON）"""
        from dreambuddy_evolution.agi_config import set_switch
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        set_switch("enable_direction_state_short_expansion", False)
        exp = DirectionStateShortExpansion()
        result = exp.evaluate("OTHER", "WEAK", 0.0)
        assert result.unlocked is False

    def test_switch_off_reversal_not_unlocked(self):
        """开关关闭 + REVERSAL → 不解锁"""
        from dreambuddy_evolution.agi_config import set_switch
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        set_switch("enable_direction_state_short_expansion", False)
        exp = DirectionStateShortExpansion()
        result = exp.evaluate("REVERSAL", "WEAK", 0.0)
        assert result.unlocked is False


class TestSwitchOnShortOnly:
    """开关开启 + SHORT_ONLY → 全解锁"""

    def test_short_only_unlocked(self):
        """SHORT_ONLY → 全解锁"""
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        exp = DirectionStateShortExpansion()
        result = exp.evaluate("SHORT_ONLY", "STRONG", 0.0)
        assert result.unlocked is True

    def test_short_only_position_1x(self):
        """SHORT_ONLY → 仓位 1.0x"""
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        exp = DirectionStateShortExpansion()
        result = exp.evaluate("SHORT_ONLY", "STRONG", 0.0)
        assert result.position_multiplier == pytest.approx(1.0)

    def test_short_only_state_label(self):
        """SHORT_ONLY → state='SHORT_ONLY'"""
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        exp = DirectionStateShortExpansion()
        result = exp.evaluate("SHORT_ONLY", "STRONG", 0.0)
        assert result.state == "SHORT_ONLY"


class TestSwitchOnTrendBear:
    """开关开启 + TREND_BEAR (btc_regime=WEAK) → 部分解锁"""

    def test_trend_bear_unlocked(self):
        """btc_regime=WEAK + 非 SHORT_ONLY → TREND_BEAR 部分解锁"""
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        exp = DirectionStateShortExpansion()
        result = exp.evaluate("OTHER", "WEAK", 0.0)
        assert result.unlocked is True

    def test_trend_bear_position_05(self):
        """TREND_BEAR → 仓位 0.5x"""
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        exp = DirectionStateShortExpansion()
        result = exp.evaluate("OTHER", "WEAK", 0.0)
        assert result.position_multiplier == pytest.approx(0.5)

    def test_trend_bear_state_label(self):
        """TREND_BEAR → state='TREND_BEAR'"""
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        exp = DirectionStateShortExpansion()
        result = exp.evaluate("OTHER", "WEAK", 0.0)
        assert result.state == "TREND_BEAR"

    def test_trend_bear_regime_not_weak_not_unlocked(self):
        """btc_regime != WEAK + 非 SHORT_ONLY → 不解锁"""
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        exp = DirectionStateShortExpansion()
        result = exp.evaluate("OTHER", "STRONG", 0.0)
        assert result.unlocked is False

    def test_trend_bear_regime_neutral_not_unlocked(self):
        """btc_regime=NEUTRAL + 非 SHORT_ONLY → 不解锁"""
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        exp = DirectionStateShortExpansion()
        result = exp.evaluate("OTHER", "NEUTRAL", 0.0)
        assert result.unlocked is False

    def test_trend_bear_regime_case_insensitive(self):
        """btc_regime 大小写不敏感（weak/WEAK/Weak 均触发 TREND_BEAR）"""
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        exp = DirectionStateShortExpansion()
        for regime in ("weak", "WEAK", "Weak"):
            result = exp.evaluate("OTHER", regime, 0.0)
            assert result.unlocked is True, f"regime={regime} should trigger TREND_BEAR"


class TestSwitchOnReversal:
    """开关开启 + REVERSAL → 不解锁（历史负期望）"""

    def test_reversal_not_unlocked_even_switch_on(self):
        """REVERSAL + btc_regime=WEAK → 不解锁（即使开关 ON）"""
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        exp = DirectionStateShortExpansion()
        result = exp.evaluate("REVERSAL", "WEAK", 0.0)
        assert result.unlocked is False

    def test_reversal_position_zero(self):
        """REVERSAL → 仓位 0.0"""
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        exp = DirectionStateShortExpansion()
        result = exp.evaluate("REVERSAL", "WEAK", 0.0)
        assert result.position_multiplier == pytest.approx(0.0)

    def test_reversal_state_label(self):
        """REVERSAL → state='REVERSAL'"""
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        exp = DirectionStateShortExpansion()
        result = exp.evaluate("REVERSAL", "WEAK", 0.0)
        assert result.state == "REVERSAL"


class TestConcentrationLimit:
    """集中度限制: 做空总仓位 / 总仓位 ≤ 30%"""

    def test_concentration_below_limit_unlocked(self):
        """集中度 20% < 30% → 正常解锁"""
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        exp = DirectionStateShortExpansion()
        result = exp.evaluate("SHORT_ONLY", "STRONG", 0.2)
        assert result.unlocked is True
        assert result.concentration_exceeded is False

    def test_concentration_at_limit_blocked(self):
        """集中度 30% = 上限 → 不解锁（已达上限）"""
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        exp = DirectionStateShortExpansion()
        result = exp.evaluate("SHORT_ONLY", "STRONG", 0.3)
        assert result.unlocked is False
        assert result.concentration_exceeded is True

    def test_concentration_above_limit_blocked(self):
        """集中度 50% > 30% → 不解锁"""
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        exp = DirectionStateShortExpansion()
        result = exp.evaluate("SHORT_ONLY", "STRONG", 0.5)
        assert result.unlocked is False
        assert result.concentration_exceeded is True

    def test_concentration_limit_value(self):
        """concentration_limit = 0.3 (30%)"""
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        exp = DirectionStateShortExpansion()
        result = exp.evaluate("SHORT_ONLY", "STRONG", 0.0)
        assert result.concentration_limit == pytest.approx(0.3)

    def test_concentration_blocks_trend_bear(self):
        """集中度超限 → 即使 TREND_BEAR 也不解锁"""
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        exp = DirectionStateShortExpansion()
        result = exp.evaluate("OTHER", "WEAK", 0.35)
        assert result.unlocked is False
        assert result.concentration_exceeded is True


class TestFailOpen:
    """FAIL-OPEN: 异常/缺失 → 不解锁（维持 SHORT_BAN）"""

    def test_none_direction_state(self):
        """direction_state=None → 不解锁"""
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        exp = DirectionStateShortExpansion()
        result = exp.evaluate(None, "WEAK", 0.0)
        assert result.unlocked is False

    def test_none_btc_regime(self):
        """btc_regime=None → 不解锁（除非 SHORT_ONLY）"""
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        exp = DirectionStateShortExpansion()
        # SHORT_ONLY + None regime → should still unlock (SHORT_ONLY doesn't need regime)
        result = exp.evaluate("SHORT_ONLY", None, 0.0)
        assert result.unlocked is True
        # non-SHORT_ONLY + None regime → should not unlock
        result = exp.evaluate("OTHER", None, 0.0)
        assert result.unlocked is False

    def test_none_concentration_ratio(self):
        """current_short_ratio=None → 不解锁"""
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        exp = DirectionStateShortExpansion()
        result = exp.evaluate("SHORT_ONLY", "STRONG", None)
        assert result.unlocked is False

    def test_nan_concentration_ratio(self):
        """current_short_ratio=NaN → 不解锁"""
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        exp = DirectionStateShortExpansion()
        result = exp.evaluate("SHORT_ONLY", "STRONG", float("nan"))
        assert result.unlocked is False

    def test_string_concentration_ratio(self):
        """current_short_ratio 传字符串 → 不解锁"""
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        exp = DirectionStateShortExpansion()
        result = exp.evaluate("SHORT_ONLY", "STRONG", "not_a_number")
        assert result.unlocked is False

    def test_switch_crash_not_unlocked(self):
        """开关检查抛异常 → 不解锁"""
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        exp = DirectionStateShortExpansion()
        import dreambuddy_evolution.agi_config as agi_config
        original = agi_config.get_switch

        def _crash(*a, **kw):
            raise RuntimeError("simulated crash")

        agi_config.get_switch = _crash
        try:
            result = exp.evaluate("SHORT_ONLY", "STRONG", 0.0)
            assert result.unlocked is False
        finally:
            agi_config.get_switch = original


class TestShortOnlyIndependentOfRegime:
    """SHORT_ONLY 不依赖 btc_regime（现有行为保持）"""

    def test_short_only_regime_strong_unlocked(self):
        """SHORT_ONLY + btc_regime=STRONG → 全解锁"""
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        exp = DirectionStateShortExpansion()
        result = exp.evaluate("SHORT_ONLY", "STRONG", 0.0)
        assert result.unlocked is True
        assert result.position_multiplier == pytest.approx(1.0)

    def test_short_only_regime_weak_unlocked_1x(self):
        """SHORT_ONLY + btc_regime=WEAK → 仍全解锁 1.0x（SHORT_ONLY 优先级高于 TREND_BEAR）"""
        from dreambuddy_evolution.engines.direction_state_short_expansion import (
            DirectionStateShortExpansion,
        )
        exp = DirectionStateShortExpansion()
        result = exp.evaluate("SHORT_ONLY", "WEAK", 0.0)
        assert result.unlocked is True
        assert result.position_multiplier == pytest.approx(1.0)
        assert result.state == "SHORT_ONLY"
