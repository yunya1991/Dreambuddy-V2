"""BDSM 战术小仓策略测试 — TDD 先红后绿。

验证：
- tactical_entry_check：5 条入场条件
- tactical_exit_check：5 条退出条件
"""
import sys
from pathlib import Path

_L4_DIR = Path(__file__).resolve().parent.parent
if str(_L4_DIR) not in sys.path:
    sys.path.insert(0, str(_L4_DIR))

from force_vector.bdsm_tactical_position import (
    tactical_entry_check,
    tactical_exit_check,
    TACTICAL_MICRO_BUDGET_USDT,
    TACTICAL_STOP_LOSS_PCT,
    TACTICAL_E8_EXIT_THRESHOLD,
)


def _make_entry(**overrides):
    """构造一个默认合格的 coin_entry，再用 overrides 覆盖。"""
    entry = {
        "bds_score": 0.4,
        "phase": "P2_REVENUE_EXPANSION",
        "cvs": 0.2,           # < 0.3 → 非标准仓覆盖
        "valuation_percentile": 85.0,  # > 80 → 非标准仓覆盖
        "technical_assessment": {"rsi_14": 75.0},  # > 70 → 非标准仓覆盖
        "trend_stop": {"action": "none"},
        "value_exit": {"action": "reduce30"},
        "e8_cross_sector_valuation": 0.2,
    }
    entry.update(overrides)
    return entry


class TestTacticalEntryCheck:
    """战术小仓入场条件。"""

    def test_entry_pass_when_all_conditions_met(self):
        """全部满足 → True。"""
        assert tactical_entry_check(_make_entry()) is True

    def test_entry_fail_when_bds_below_threshold(self):
        """bds_score < 0.3 → False。"""
        assert tactical_entry_check(_make_entry(bds_score=0.2)) is False

    def test_entry_fail_when_phase_not_eligible(self):
        """phase 不在 P1/P2 → False。"""
        assert tactical_entry_check(_make_entry(phase="P3_VALUATION_RECOVERY")) is False

    def test_entry_fail_when_trend_stop_active(self):
        """trend_stop.action != none → False。"""
        assert tactical_entry_check(
            _make_entry(trend_stop={"action": "reduce30"})
        ) is False

    def test_entry_fail_when_value_exit_full_exit(self):
        """value_exit.action == full_exit → False。"""
        assert tactical_entry_check(
            _make_entry(value_exit={"action": "full_exit"})
        ) is False

    def test_entry_fail_when_standard_covered(self):
        """标准仓已覆盖（cvs≥0.3 且估值≤80 且 rsi≤70）→ False。"""
        assert tactical_entry_check(
            _make_entry(cvs=0.5, valuation_percentile=70.0,
                        technical_assessment={"rsi_14": 60.0})
        ) is False

    def test_entry_fail_on_missing_data(self):
        """缺失数据 → False（FAIL-OPEN）。"""
        assert tactical_entry_check({}) is False


class TestTacticalExitCheck:
    """战术小仓退出条件。"""

    def test_no_exit_when_none_triggered(self):
        """无退出条件触发 → (False, 'none')。"""
        pos = {"current_price": 10.0, "avg_entry_price": 8.0, "ma50": 9.0}
        entry = _make_entry()
        should_exit, reason = tactical_exit_check(pos, entry)
        assert should_exit is False
        assert reason == "none"

    def test_exit_on_bdsm_full_exit(self):
        """BDSM full_exit → 退出。"""
        pos = {"current_price": 10.0, "avg_entry_price": 8.0, "ma50": 9.0}
        entry = _make_entry(value_exit={"action": "full_exit"})
        should_exit, reason = tactical_exit_check(pos, entry)
        assert should_exit is True
        assert "full_exit" in reason

    def test_exit_on_e8_sector_overvalued(self):
        """E8 < -0.3 → 退出。"""
        pos = {"current_price": 10.0, "avg_entry_price": 8.0, "ma50": 9.0}
        entry = _make_entry(e8_cross_sector_valuation=-0.5)
        should_exit, reason = tactical_exit_check(pos, entry)
        assert should_exit is True
        assert "sector_overvalued" in reason

    def test_exit_on_ma50_break(self):
        """跌破 MA50 → 退出。"""
        pos = {"current_price": 8.5, "avg_entry_price": 8.0, "ma50": 9.0}
        entry = _make_entry()
        should_exit, reason = tactical_exit_check(pos, entry)
        assert should_exit is True
        assert "ma50_break" in reason

    def test_exit_on_stop_loss(self):
        """亏损 ≥ 15% → 退出（MA50 设低避免优先触发）。"""
        pos = {"current_price": 6.5, "avg_entry_price": 8.0, "ma50": 6.0}
        entry = _make_entry()
        should_exit, reason = tactical_exit_check(pos, entry)
        assert should_exit is True
        assert "stop_loss" in reason

    def test_exit_on_bds_deterioration(self):
        """BDS 连续 2 快照下滑 > 0.1 → 退出。"""
        pos = {"current_price": 10.0, "avg_entry_price": 8.0, "ma50": 9.0}
        entry = _make_entry()
        should_exit, reason = tactical_exit_check(pos, entry, bds_history=[0.5, 0.35])
        assert should_exit is True
        assert "bds_deterioration" in reason

    def test_no_exit_on_small_bds_decline(self):
        """BDS 下滑 ≤ 0.1 → 不退出。"""
        pos = {"current_price": 10.0, "avg_entry_price": 8.0, "ma50": 9.0}
        entry = _make_entry()
        should_exit, _ = tactical_exit_check(pos, entry, bds_history=[0.5, 0.45])
        assert should_exit is False


class TestTacticalConstants:
    """默认参数合理性。"""

    def test_budget_is_small(self):
        """小仓预算应远小于 BDSM 标准仓 167U。"""
        assert TACTICAL_MICRO_BUDGET_USDT < 100.0

    def test_stop_loss_reasonable(self):
        """止损在 10%-20% 之间。"""
        assert 0.10 <= TACTICAL_STOP_LOSS_PCT <= 0.20

    def test_e8_threshold_negative(self):
        """E8 退出阈值应为负（板块高估）。"""
        assert TACTICAL_E8_EXIT_THRESHOLD < 0.0
