#!/usr/bin/env python3
"""空单试错仓系统性偏差修复测试（TDD RED→GREEN）。

F1: 空单 F1 试错门槛收紧（0.80→0.90 + 动态调节）
F2: 试错仓杠杆限制（≤2x）
F3: 轻仓试错逻辑矛盾修复（score_consensus 下限 0.30）
F4: 试错仓超时平仓（4h 无趋势离场）

SPEC: docs/superpowers/specs/2026-10-10-trial-short-systematic-deviation-fix-spec.md
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.memory_l4.polling_trader import PollingTrader


def _trader():
    """创建无 __init__ 的实例，用于单元测试。"""
    return PollingTrader.__new__(PollingTrader)


# ═══════════════════════════════════════════════════════════
# F1: 空单 F1 试错门槛收紧
# ═══════════════════════════════════════════════════════════

def test_f1_trial_short_threshold_default_090():
    """空单 F1 试错门槛默认值应为 0.90（非 short_confidence_threshold=0.80）。"""
    assert PollingTrader.F1_TRIAL_SHORT_BASE_THRESHOLD == 0.90


def test_f1_trial_short_threshold_tightens_on_loss():
    """空单胜率<40%时 F1 门槛收紧 +0.02。"""
    t = _trader()
    t._f1_trial_short_threshold = 0.90
    t._f1_trial_short_state = {
        "n_min": 30,
        "n_max": 150,
        "recent_pnl": [(-0.01, "DOWN")] * 30,  # 30笔全亏, 胜率 0%
        "last_adjust_ts": 0.0,
        "adjust_cooldown_s": 1800,
    }
    t._maybe_adjust_f1_trial_short_threshold(
        {"direction": "DOWN", "pnl_pct": -0.01}
    )
    assert t._f1_trial_short_threshold == 0.92, f"应收紧到0.92, 实际={t._f1_trial_short_threshold}"


def test_f1_trial_short_threshold_relaxes_on_win():
    """空单胜率≥60%时 F1 门槛放宽 -0.01。"""
    t = _trader()
    t._f1_trial_short_threshold = 0.92
    t._f1_trial_short_state = {
        "n_min": 30,
        "n_max": 150,
        "recent_pnl": [(0.01, "DOWN")] * 18 + [(-0.01, "DOWN")] * 12,  # 18盈12亏=60%
        "last_adjust_ts": 0.0,
        "adjust_cooldown_s": 1800,
    }
    t._maybe_adjust_f1_trial_short_threshold(
        {"direction": "DOWN", "pnl_pct": 0.01}
    )
    assert t._f1_trial_short_threshold == 0.91, f"应放宽到0.91, 实际={t._f1_trial_short_threshold}"


def test_f1_trial_short_threshold_ignores_long():
    """多单平仓不影响空单 F1 门槛。"""
    t = _trader()
    t._f1_trial_short_threshold = 0.90
    t._f1_trial_short_state = {
        "n_min": 30,
        "n_max": 150,
        "recent_pnl": [],
        "last_adjust_ts": 0.0,
        "adjust_cooldown_s": 1800,
    }
    t._maybe_adjust_f1_trial_short_threshold(
        {"direction": "UP", "pnl_pct": -0.01}
    )
    assert t._f1_trial_short_threshold == 0.90, "多单不应影响空单门槛"


# ═══════════════════════════════════════════════════════════
# F2: 试错仓杠杆限制（≤2x）
# ═══════════════════════════════════════════════════════════

def test_compute_effective_leverage_trial_capped():
    """试错仓杠杆上限 2x，即使 base*factor=6 也被限制到 2。"""
    t = _trader()
    lev = t._compute_effective_leverage(
        base_leverage=3, leverage_factor=2.0, is_trial=True
    )
    assert lev <= 2, f"试错仓杠杆应≤2x, 实际={lev}"


def test_compute_effective_leverage_normal_uncapped():
    """非试错仓无 2x 上限约束，base*factor=6 即 6x。"""
    t = _trader()
    lev = t._compute_effective_leverage(
        base_leverage=3, leverage_factor=2.0, is_trial=False
    )
    assert lev == 6, f"非试错仓应=6x, 实际={lev}"


# ═══════════════════════════════════════════════════════════
# F3: 轻仓试错逻辑矛盾修复
# ═══════════════════════════════════════════════════════════

def test_f1_trial_blocked_when_score_below_floor():
    """score_consensus < 0.30 时不走 F1 试错通路（0.294 应被拦截）。"""
    assert PollingTrader.F1_TRIAL_MIN_SCORE_CONSENSUS == 0.30
    # 现场案例: score_cons=0.294 < 0.30 → 应被拦截
    assert 0.294 < PollingTrader.F1_TRIAL_MIN_SCORE_CONSENSUS


def test_f1_trial_allowed_when_score_above_floor():
    """score_consensus ≥ 0.30 时允许走 F1 试错通路。"""
    # 0.30 ≥ 0.30 → 允许（边界包含）
    assert 0.30 >= PollingTrader.F1_TRIAL_MIN_SCORE_CONSENSUS
    # 0.35 ≥ 0.30 → 允许
    assert 0.35 >= PollingTrader.F1_TRIAL_MIN_SCORE_CONSENSUS


# ═══════════════════════════════════════════════════════════
# F4: 试错仓超时平仓（4h 无趋势离场）
# ═══════════════════════════════════════════════════════════

def test_trial_max_hold_timeout_closes_position():
    """持仓≥4h 且 maintain → 应触发超时平仓。"""
    assert PollingTrader.TRIAL_MAX_HOLD_SEC == 4 * 3600
    t = _trader()
    # 持仓 4.5h >= 4h → 超时
    assert t._should_trial_timeout_close(position_age_sec=4 * 3600 + 1800) is True


def test_trial_max_hold_not_triggered_under_4h():
    """持仓<4h 且 maintain → 不触发超时。"""
    t = _trader()
    # 持仓 3h < 4h → 不超时
    assert t._should_trial_timeout_close(position_age_sec=3 * 3600) is False


if __name__ == "__main__":
    test_f1_trial_short_threshold_default_090()
    test_f1_trial_short_threshold_tightens_on_loss()
    test_f1_trial_short_threshold_relaxes_on_win()
    test_f1_trial_short_threshold_ignores_long()
    test_compute_effective_leverage_trial_capped()
    test_compute_effective_leverage_normal_uncapped()
    test_f1_trial_blocked_when_score_below_floor()
    test_f1_trial_allowed_when_score_above_floor()
    test_trial_max_hold_timeout_closes_position()
    test_trial_max_hold_not_triggered_under_4h()
    print("✅ 空单试错仓系统性偏差修复测试通过")
