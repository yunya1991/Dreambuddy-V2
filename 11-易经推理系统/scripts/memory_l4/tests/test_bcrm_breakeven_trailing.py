# -*- coding: utf-8 -*-
"""BCRM ClassicExitSystem 保本位 + trailing 阈值优化 TDD 测试集.

修复项:
  P1-1: BCRM 新增保本位（盈利≥2% → SL 移到 entry_price 保本）
  P1-2: BCRM trailing arm 9%→4%（降低激活门槛）

每个新测试 **先失败** → 对应代码实现后 **再通过**。
"""
import sys
from pathlib import Path

import pytest

_MEMORY_L4 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MEMORY_L4))


class TestBCRMBreakEvenAndTrailing:
    """BCRM 保本位 + trailing 阈值"""

    @pytest.fixture
    def engine(self):
        from classic_exit_system import ClassicExitSystem, ExitConfig
        cfg = ExitConfig()
        return ClassicExitSystem(config=cfg)

    def _make_pos(self, **kw):
        from classic_exit_system import PositionState
        defaults = dict(
            coin="ETH", side="long",
            entry_price=100.0, current_price=100.0,
            unrealized_pnl_pct=0.0, leverage=10.0,
            trailing_stop_price=96.0, trailing_armed=False,
            position_age_sec=10 * 3600,  # > min_hold_bars 8h
        )
        defaults.update(kw)
        return PositionState(**defaults)

    def test_break_even_long_moves_sl_to_entry(self, engine):
        """P1-1: 多头盈利3%≥2%，SL=96<entry=100 → new_trailing_stop=100（保本）"""
        from classic_exit_system import ExitFeatureSet
        pos = self._make_pos(
            unrealized_pnl_pct=0.03, current_price=103.0,
            trailing_stop_price=96.0,
        )
        decision = engine._check_trailing_stop(pos, ExitFeatureSet())
        # 保本位应将 SL 上移到 entry_price
        assert decision.new_trailing_stop == pytest.approx(100.0, abs=1e-6)
        assert decision.action.value == "hold"  # 保本位只调 SL，不平仓

    def test_break_even_short_moves_sl_to_entry(self, engine):
        """P1-1: 空头盈利3%≥2%，SL=104>entry=100 → new_trailing_stop=100（保本）"""
        from classic_exit_system import ExitFeatureSet
        pos = self._make_pos(
            side="short", unrealized_pnl_pct=0.03, current_price=97.0,
            trailing_stop_price=104.0,
        )
        decision = engine._check_trailing_stop(pos, ExitFeatureSet())
        assert decision.new_trailing_stop == pytest.approx(100.0, abs=1e-6)

    def test_trailing_arm_at_four_pct(self, engine):
        """P1-2: trailing arm 9%→4%，盈利5%≥4% → new_trailing_stop 被设置"""
        from classic_exit_system import ExitFeatureSet
        pos = self._make_pos(
            unrealized_pnl_pct=0.05, current_price=105.0,
            trailing_stop_price=95.0, trailing_armed=True,  # 当前SL < calc_stop，会被上移
        )
        decision = engine._check_trailing_stop(pos, ExitFeatureSet())
        # trailing: SL = current_price * (1 - 5%) = 105 * 0.95 = 99.75
        expected = 105.0 * (1 - 0.05)
        assert decision.new_trailing_stop == pytest.approx(expected, abs=1e-6)

    def test_trailing_not_armed_below_four_pct(self, engine):
        """P1-2: 盈利3%<4% arm → 不触发 trailing（但保本位仍生效）"""
        from classic_exit_system import ExitFeatureSet
        pos = self._make_pos(
            unrealized_pnl_pct=0.03, current_price=103.0,
            trailing_stop_price=96.0, trailing_armed=False,
        )
        decision = engine._check_trailing_stop(pos, ExitFeatureSet())
        # 保本位生效：SL→entry=100；但 trailing 未 armed
        assert decision.new_trailing_stop == pytest.approx(100.0, abs=1e-6)
        assert decision.trailing_triggered is False

    def test_break_even_skips_when_sl_already_above_entry(self, engine):
        """P1-1: SL 已在 entry 上方（已保本/trailing）→ 保本位不覆盖更低的 trailing SL"""
        from classic_exit_system import ExitFeatureSet
        pos = self._make_pos(
            unrealized_pnl_pct=0.05, current_price=105.0,
            trailing_stop_price=102.0,  # SL 已在 entry 上方
            trailing_armed=True,
        )
        decision = engine._check_trailing_stop(pos, ExitFeatureSet())
        # trailing 计算: 105 * 0.95 = 99.75，但 max(102, 99.75) = 102
        # 保本位不应把 SL 拉低到 100
        assert decision.new_trailing_stop >= 100.0
