#!/usr/bin/env python3
"""
P3.5 移动止盈 (Trailing Take Profit) 单元测试

验证范围：
1. 实盘侧 ClassicExitSystem._check_trailing_tp 边界场景
   - 激活阈值 (arm_pct=1.5%)
   - 回撤比例 (retrace_ratio=40%)
   - 最小锁定利润 (min_lock_pct=0.3%)
   - 配置开关
   - 杠杆有效口径
2. 回测侧 WalkForwardBacktester._evaluate_classic_exit P3.5 触发
   - 构造 mock 数据使 P2/P3 不触发，仅 P3.5 触发
"""

import os
import sys

# 注入路径
_L4_PATH = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "memory_l4")
)
if _L4_PATH not in sys.path:
    sys.path.insert(0, _L4_PATH)

import numpy as np

from classic_exit_system import (
    ClassicExitSystem,
    PositionState,
    ExitAction,
    ExitConfig,
    ExitFeatureSet,
)


def _make_pos(
    entry_price: float = 100.0,
    current_price: float = 100.0,
    mfe_pnl_pct: float = 0.0,
    unrealized_pnl_pct: float = 0.0,
    leverage: float = 1.0,
) -> PositionState:
    """构造一个最小化的 PositionState（仅含 P3.5 关心的字段）"""
    return PositionState(
        coin="TEST",
        side="long",
        entry_price=entry_price,
        current_price=current_price,
        unrealized_pnl_pct=unrealized_pnl_pct,
        leverage=leverage,
        atr_pct=0.02,
        mfe_pnl_pct=mfe_pnl_pct,
    )


def _make_features() -> ExitFeatureSet:
    return ExitFeatureSet()


# ──────────────────────────────────────────────────────────────────
# 实盘侧 _check_trailing_tp 边界场景
# ──────────────────────────────────────────────────────────────────

def test_live_mfe_below_arm_pct_holds():
    """Case A: MFE < 1.5% → HOLD（未激活）"""
    sys_obj = ClassicExitSystem(config=ExitConfig())
    pos = _make_pos(unrealized_pnl_pct=0.005, mfe_pnl_pct=0.01)  # MFE 1.0%
    d = sys_obj._check_trailing_tp(pos, _make_features())
    assert d.action == ExitAction.HOLD, f"expected HOLD got {d.action} ({d.reason})"


def test_live_mfe_just_at_arm_pct_retrace_low_holds():
    """Case B: MFE = 1.5%，回撤 < 40% → HOLD"""
    sys_obj = ClassicExitSystem(config=ExitConfig())
    # MFE=1.5%, pnl_now=1.2% → retrace = (1.5-1.2)/1.5 = 20% < 40%
    pos = _make_pos(unrealized_pnl_pct=0.012, mfe_pnl_pct=0.015)
    d = sys_obj._check_trailing_tp(pos, _make_features())
    assert d.action == ExitAction.HOLD, f"expected HOLD got {d.action} ({d.reason})"


def test_live_retrace_enough_but_lock_too_low_holds():
    """Case C: 回撤 ≥ 40% 但当前盈利低于 0.3% → HOLD（最小锁定保护）"""
    sys_obj = ClassicExitSystem(config=ExitConfig())
    # MFE=2.0%, pnl_now=0.2% → retrace = (2.0-0.2)/2.0 = 90% ≥ 40%, 但 pnl < 0.3%
    pos = _make_pos(unrealized_pnl_pct=0.002, mfe_pnl_pct=0.02)
    d = sys_obj._check_trailing_tp(pos, _make_features())
    assert d.action == ExitAction.HOLD, f"expected HOLD got {d.action} ({d.reason})"


def test_live_triggers_close_when_all_conditions_met():
    """Case D: MFE=2%, 回撤=50%, pnl_now=1.0% ≥ 0.3% → CLOSE"""
    sys_obj = ClassicExitSystem(config=ExitConfig())
    # MFE=2.0%, pnl_now=1.0% → retrace = (2.0-1.0)/2.0 = 50% ≥ 40%, pnl ≥ 0.3%
    pos = _make_pos(unrealized_pnl_pct=0.01, mfe_pnl_pct=0.02)
    d = sys_obj._check_trailing_tp(pos, _make_features())
    assert d.action == ExitAction.CLOSE, f"expected CLOSE got {d.action} ({d.reason})"
    assert "TRAILING_TP" in d.reason, f"reason should contain TRAILING_TP: {d.reason}"
    assert d.confidence == 0.75


def test_live_disabled_config_holds():
    """Case E: trailing_tp_enabled=False → HOLD（即使条件全部满足）"""
    cfg = ExitConfig()
    cfg.trailing_tp_enabled = False
    sys_obj = ClassicExitSystem(config=cfg)
    pos = _make_pos(unrealized_pnl_pct=0.01, mfe_pnl_pct=0.02)  # 同 Case D
    d = sys_obj._check_trailing_tp(pos, _make_features())
    assert d.action == ExitAction.HOLD, f"disabled config should HOLD, got {d.action}"


def test_live_leverage_applied():
    """Case F: 杠杆有效口径 — 裸 MFE=0.5%, leverage=5x → mfe_eff=2.5% (>1.5%)"""
    sys_obj = ClassicExitSystem(config=ExitConfig())
    # pnl_now=0.2% (裸) → pnl_eff = 0.2% * 5 = 1.0% ≥ 0.3%
    # retrace = (2.5 - 1.0) / 2.5 = 60% ≥ 40% → CLOSE
    pos = _make_pos(unrealized_pnl_pct=0.002, mfe_pnl_pct=0.005, leverage=5.0)
    d = sys_obj._check_trailing_tp(pos, _make_features())
    assert d.action == ExitAction.CLOSE, f"leverage path should CLOSE, got {d.action} ({d.reason})"


def test_live_no_leverage_when_apply_leverage_false():
    """Case G: apply_leverage_to_thresholds=False → 使用裸值（不放大）"""
    cfg = ExitConfig()
    cfg.apply_leverage_to_thresholds = False
    sys_obj = ClassicExitSystem(config=cfg)
    # 裸 MFE=0.5% < 1.5% → HOLD（即使 leverage=5x 也不放大）
    pos = _make_pos(unrealized_pnl_pct=0.002, mfe_pnl_pct=0.005, leverage=5.0)
    d = sys_obj._check_trailing_tp(pos, _make_features())
    assert d.action == ExitAction.HOLD, f"no-leverage path should HOLD, got {d.action} ({d.reason})"


# ──────────────────────────────────────────────────────────────────
# 回测侧 _evaluate_classic_exit P3.5 触发
# ──────────────────────────────────────────────────────────────────

def _make_backtester():
    """构造一个 WalkForwardBacktester 实例（不实际运行回测，仅用其方法）"""
    from bcrm2.walk_forward_backtester import WalkForwardBacktester
    return WalkForwardBacktester(symbol="TEST", n_folds=1)


def test_backtest_trailing_tp_triggers():
    """回测侧 P3.5 触发：MFE=2%, pnl_now=1% → classic_trailing_tp"""
    bt = _make_backtester()
    # 构造数据：entry=100, current=101 → pnl_now = 1.0%
    # 之前已记录 mfe_pnl_pct = 2.0%（peak 时记录）
    # 回撤 = (2.0 - 1.0) / 2.0 = 50% ≥ 40%, pnl_now=1.0% ≥ 0.3% → 触发
    entry_price = 100.0
    current_price = 101.0
    high = np.array([100.5, 101.0])  # 不触发 TP（tp_price 设很高）
    low = np.array([99.8, 100.8])    # 不触发 SL（sl_price 设很低）
    atr_values = np.array([0.0, 0.0])  # ATR=0 → 跳过 P3 跟踪止损
    position = {"mfe_pnl_pct": 0.02}  # 已记录的 MFE = 2.0%

    result = bt._evaluate_classic_exit(
        direction=1,
        entry_price=entry_price,
        current_price=current_price,
        high=high,
        low=low,
        bar_idx=1,
        hold_bars=10,
        max_hold=60,
        tp_price=200.0,  # 高到不会触发
        sl_price=50.0,   # 低到不会触发
        atr_values=atr_values,
        position=position,
    )

    assert result["action"] == "close", f"expected close got {result}"
    assert result["exit_reason"] == "classic_trailing_tp", (
        f"expected classic_trailing_tp got {result['exit_reason']}"
    )
    assert result["exit_price"] == current_price


def test_backtest_trailing_tp_no_trigger_when_mfe_below_arm():
    """回测侧 P3.5 未触发：MFE=1.0% < 1.5% → 进入 P1（hold）"""
    bt = _make_backtester()
    entry_price = 100.0
    current_price = 100.5  # pnl_now = 0.5%
    high = np.array([100.5, 100.5])
    low = np.array([100.0, 100.3])
    atr_values = np.array([0.0, 0.0])
    position = {"mfe_pnl_pct": 0.01}  # MFE=1.0% < 1.5%

    result = bt._evaluate_classic_exit(
        direction=1,
        entry_price=entry_price,
        current_price=current_price,
        high=high,
        low=low,
        bar_idx=1,
        hold_bars=10,
        max_hold=60,
        tp_price=200.0,
        sl_price=50.0,
        atr_values=atr_values,
        position=position,
    )

    # P3.5 不触发，应进入 P1（小盈利、未到期 → hold）
    assert result["action"] == "hold", f"expected hold got {result}"
    assert result["exit_reason"] == "hold"


def test_backtest_mfe_updated_inplace():
    """回测侧：当 pnl_now 超过历史 MFE 时，position['mfe_pnl_pct'] 应被更新"""
    bt = _make_backtester()
    entry_price = 100.0
    current_price = 103.0  # pnl_now = 3.0%
    high = np.array([100.5, 103.0])
    low = np.array([99.8, 102.5])
    atr_values = np.array([0.0, 0.0])
    position = {"mfe_pnl_pct": 0.01}  # 历史 MFE = 1.0%，应被更新为 3.0%

    # 由于 pnl_now=3% > 历史 MFE 1%，会先更新 mfe_pnl_pct = 3%
    # 然后 retrace = (3-3)/3 = 0 < 40% → 不触发 P3.5 → 进入 P1
    # P1: pnl > 0.01 且 hold_bars(10) >= max_hold*0.8(48)? 否 → hold
    result = bt._evaluate_classic_exit(
        direction=1,
        entry_price=entry_price,
        current_price=current_price,
        high=high,
        low=low,
        bar_idx=1,
        hold_bars=10,
        max_hold=60,
        tp_price=200.0,
        sl_price=50.0,
        atr_values=atr_values,
        position=position,
    )

    assert position["mfe_pnl_pct"] == 0.03, f"MFE should be updated to 3.0%, got {position['mfe_pnl_pct']}"
    assert result["action"] == "hold", f"expected hold (retrace=0), got {result}"


# ──────────────────────────────────────────────────────────────────
# 主测试入口
# ──────────────────────────────────────────────────────────────────

def run_all():
    tests = [
        ("live.mfe_below_arm_holds", test_live_mfe_below_arm_pct_holds),
        ("live.retrace_low_holds", test_live_mfe_just_at_arm_pct_retrace_low_holds),
        ("live.lock_too_low_holds", test_live_retrace_enough_but_lock_too_low_holds),
        ("live.all_conditions_close", test_live_triggers_close_when_all_conditions_met),
        ("live.disabled_holds", test_live_disabled_config_holds),
        ("live.leverage_applied_close", test_live_leverage_applied),
        ("live.no_leverage_when_disabled", test_live_no_leverage_when_apply_leverage_false),
        ("backtest.triggers_classic_trailing_tp", test_backtest_trailing_tp_triggers),
        ("backtest.no_trigger_below_arm", test_backtest_trailing_tp_no_trigger_when_mfe_below_arm),
        ("backtest.mfe_updated_inplace", test_backtest_mfe_updated_inplace),
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  \u2713 PASS  {name}")
            passed += 1
        except AssertionError as e:
            print(f"  \u2717 FAIL  {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  \u2717 ERROR {name}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n=== Summary: {passed} passed, {failed} failed, {passed + failed} total ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_all())
