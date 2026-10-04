#!/usr/bin/env python3
"""三大结构性亏损修复的回归测试（TDD RED→GREEN）。

修复1: trial_trend_reverse — 试错仓降杠杆（避免 -3% 阈值被高杠杆放大）
修复2: loss_risk_joint    — 同步单观察期（避免启动即割）
修复3: s3_prep_exit       — 浮亏不触发时间离场（避免被动割肉）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.memory_l4.polling_trader import PollingTrader


def _trader():
    return PollingTrader.__new__(PollingTrader)


# ═══════════════════════════════════════════════════════════
# 修复1: 试错仓杠杆限制 — is_trial 时 effective_leverage ≤ 2
# ═══════════════════════════════════════════════════════════

def test_trial_leverage_capped_at_2x():
    """试错仓即使 leverage_factor 很高，最终杠杆也不得超过 2x。"""
    t = _trader()
    # 默认 3x × factor 2.0 = 6x，但试错仓必须降到 2x
    lev = t._compute_effective_leverage(
        base_leverage=3, leverage_factor=2.0, is_trial=True
    )
    assert lev <= 2, f"试错仓杠杆应≤2x，实际={lev}"


def test_trial_leverage_keeps_low_when_already_low():
    """试错仓原本杠杆≤2时保持不变。"""
    t = _trader()
    lev = t._compute_effective_leverage(
        base_leverage=1, leverage_factor=1.0, is_trial=True
    )
    assert lev == 1


def test_normal_position_no_cap():
    """非试错仓不受 2x 上限约束。"""
    t = _trader()
    lev = t._compute_effective_leverage(
        base_leverage=3, leverage_factor=2.0, is_trial=False
    )
    assert lev == 6


# ═══════════════════════════════════════════════════════════
# 修复2: 同步单观察期 — 观察期内不触发 loss_risk_joint
# ═══════════════════════════════════════════════════════════

def test_sync_position_skipped_in_observe_period():
    """同步单(hexagram='已存在持仓')在观察期内不触发 loss_risk_joint。"""
    t = _trader()
    t.SYNC_POSITION_OBSERVE_SEC = 6 * 3600
    # 同步单 + 持仓 1h < 6h 观察期 → 跳过
    assert t._is_sync_pos_in_observe_period(
        hexagram="已存在持仓", position_age_sec=3600
    ) is True


def test_sync_position_outside_observe_period_not_skipped():
    """同步单超过观察期后允许正常触发 loss_risk_joint。"""
    t = _trader()
    t.SYNC_POSITION_OBSERVE_SEC = 6 * 3600
    assert t._is_sync_pos_in_observe_period(
        hexagram="已存在持仓", position_age_sec=7 * 3600
    ) is False


def test_non_sync_position_not_skipped():
    """非同步单（正常开仓）不受观察期保护。"""
    t = _trader()
    t.SYNC_POSITION_OBSERVE_SEC = 6 * 3600
    assert t._is_sync_pos_in_observe_period(
        hexagram="水风井", position_age_sec=3600
    ) is False


# ═══════════════════════════════════════════════════════════
# 修复3: s3_prep_exit 盈利保护 — 浮亏时不触发时间离场
# ═══════════════════════════════════════════════════════════

def test_s3_prep_exit_blocked_when_loss():
    """浮亏(upl_ratio<0)时即使 PREP_EXIT 也不触发离场。"""
    t = _trader()
    assert t._should_run_s3_prep_exit(
        h_action="PREP_EXIT", in_protection=False, upl_ratio=-0.05
    ) is False


def test_s3_prep_exit_allowed_when_profit():
    """浮盈(upl_ratio≥0)且非保护期时正常触发。"""
    t = _trader()
    assert t._should_run_s3_prep_exit(
        h_action="PREP_EXIT", in_protection=False, upl_ratio=0.02
    ) is True


def test_s3_prep_exit_blocked_during_protection():
    """保护期内即使浮盈也不触发。"""
    t = _trader()
    assert t._should_run_s3_prep_exit(
        h_action="PREP_EXIT", in_protection=True, upl_ratio=0.05
    ) is False


def test_s3_prep_exit_ignored_when_not_prep():
    """非 PREP_EXIT 动作不触发。"""
    t = _trader()
    assert t._should_run_s3_prep_exit(
        h_action="HOLD", in_protection=False, upl_ratio=0.05
    ) is False


if __name__ == "__main__":
    test_trial_leverage_capped_at_2x()
    test_trial_leverage_keeps_low_when_already_low()
    test_normal_position_no_cap()
    test_sync_position_skipped_in_observe_period()
    test_sync_position_outside_observe_period_not_skipped()
    test_non_sync_position_not_skipped()
    test_s3_prep_exit_blocked_when_loss()
    test_s3_prep_exit_allowed_when_profit()
    test_s3_prep_exit_blocked_during_protection()
    test_s3_prep_exit_ignored_when_not_prep()
    print("✅ 三大亏损修复测试通过")
