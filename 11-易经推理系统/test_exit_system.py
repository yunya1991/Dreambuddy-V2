#!/usr/bin/env python3
"""
经典指标离场系统功能验证测试

测试场景：
1. 最大持仓时间触发 L0 硬退出
2. 最大亏损触发 L0 硬退出
3. Triple Barrier 止损/止盈触发
4. 跟踪止损触发
5. TSTP 时间止盈触发
6. L1/L2 价值-风险评估（hold_risk/hold_value）
7. 风险闸门（armed + cooldown）
8. 冷却机制（inflight/post-close）
9. 不同市场状态（趋势/震荡）下的行为
"""

import sys
import os

_classic_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "10-经典指标系统"
)
if _classic_path not in sys.path:
    sys.path.insert(0, _classic_path)

from classic_exit_system import (
    ClassicExitSystem,
    PositionState,
    ExitAction,
    ExitConfig,
    TrendShape,
)

import time


def log_test(name, passed, details=""):
    status = "✓ PASS" if passed else "✗ FAIL"
    print(f"  {status} {name}")
    if details:
        print(f"      {details}")


def generate_test_candles(trend_type="up", count=100, start_price=10000):
    """生成测试用 K 线数据"""
    candles = []
    price = start_price
    for i in range(count):
        if trend_type == "up":
            change = 0.002 + (i % 5 == 0) * 0.01
            price *= (1 + change)
        elif trend_type == "down":
            change = -0.002 - (i % 5 == 0) * 0.01
            price *= (1 + change)
        elif trend_type == "chop":
            change = (i % 3 - 1) * 0.003
            price *= (1 + change)
        elif trend_type == "reversal_up_to_down":
            if i < count // 2:
                change = 0.003
                price *= (1 + change)
            else:
                change = -0.005
                price *= (1 + change)
        
        candles.append({
            "c": price,
            "o": price * 0.9995,
            "h": price * 1.001,
            "l": price * 0.999,
            "v": 1000000 + i * 1000,
            "t": int(time.time()) - (count - i) * 3600,
        })
    return candles


def test_l0_max_hold():
    """测试 L0 最大持仓时间触发"""
    exit_cfg = ExitConfig(l0_max_hold_sec=3600)
    system = ClassicExitSystem(config=exit_cfg)
    
    pos = PositionState(
        coin="BTC",
        side="long",
        entry_price=10000,
        current_price=10100,
        position_age_sec=3700,
        unrealized_pnl_pct=0.01,
        leverage=3.0,
    )
    
    decision = system.evaluate_full(pos, candles_1h=[], regime="trend")
    
    passed = decision.action == ExitAction.CLOSE and decision.l0_triggered
    log_test("L0 最大持仓时间", passed,
             f"action={decision.action.value}, reason={decision.reason}")
    return passed


def test_l0_max_loss():
    """测试 L0 最大亏损触发"""
    exit_cfg = ExitConfig(l0_max_loss_pct=-0.05)
    system = ClassicExitSystem(config=exit_cfg)
    
    pos = PositionState(
        coin="BTC",
        side="long",
        entry_price=10000,
        current_price=9400,
        position_age_sec=1000,
        unrealized_pnl_pct=-0.06,
        leverage=3.0,
    )
    
    decision = system.evaluate_full(pos, candles_1h=[], regime="trend")
    
    passed = decision.action == ExitAction.CLOSE and decision.l0_triggered
    log_test("L0 最大亏损", passed,
             f"action={decision.action.value}, reason={decision.reason}")
    return passed


def test_l0_max_loss_leverage():
    """测试 L0 最大亏损（杠杆口径）"""
    exit_cfg = ExitConfig(l0_max_loss_pct=-0.15, apply_leverage_to_thresholds=True)
    system = ClassicExitSystem(config=exit_cfg)
    
    pos = PositionState(
        coin="BTC",
        side="long",
        entry_price=10000,
        current_price=9600,
        position_age_sec=1000,
        unrealized_pnl_pct=-0.04,
        leverage=10.0,
    )
    
    decision = system.evaluate_full(pos, candles_1h=[], regime="trend")
    
    passed = decision.action == ExitAction.CLOSE and decision.l0_triggered
    log_test("L0 最大亏损（杠杆口径，10x杠杆）", passed,
             f"action={decision.action.value}, reason={decision.reason}, pnl_eff={pos.pnl_eff:.2%}")
    return passed


def test_tb_stop_loss():
    """测试 Triple Barrier 止损"""
    exit_cfg = ExitConfig(
        tb_enabled=True, 
        tb_sl_atr_mult=0.5, 
        tb_sl_min_pct=0.02,
        tb_tp_min_pct=0.50,
        trailing_enabled=False,
        tstp_enabled=False,
        l1_enabled=False,
        l0_max_loss_pct=-0.50,
        apply_leverage_to_thresholds=False,
    )
    system = ClassicExitSystem(config=exit_cfg)
    
    candles = generate_test_candles("up", count=50)
    entry_price = candles[-30]["c"]
    current_price = entry_price * 0.97
    
    pos = PositionState(
        coin="BTC",
        side="long",
        entry_price=entry_price,
        current_price=current_price,
        position_age_sec=3600,
        unrealized_pnl_pct=(current_price - entry_price) / entry_price,
        leverage=3.0,
        atr_pct=0.02,
    )
    
    decision = system.evaluate_full(pos, candles_1h=candles, regime="trend")
    
    passed = decision.action == ExitAction.CLOSE and decision.tb_sl_hit
    log_test("Triple Barrier 止损", passed,
             f"action={decision.action.value}, reason={decision.reason}, tb_sl_hit={decision.tb_sl_hit}")
    return passed


def test_tb_take_profit():
    """测试 Triple Barrier 止盈"""
    exit_cfg = ExitConfig(
        tb_enabled=True, 
        tb_tp_atr_mult=0.5, 
        tb_tp_min_pct=0.02,
        tb_sl_min_pct=0.50,
        trailing_enabled=False,
        tstp_enabled=False,
        l1_enabled=False,
    )
    system = ClassicExitSystem(config=exit_cfg)
    
    candles = generate_test_candles("up", count=50)
    entry_price = candles[-30]["c"]
    current_price = entry_price * 1.05
    
    pos = PositionState(
        coin="BTC",
        side="long",
        entry_price=entry_price,
        current_price=current_price,
        position_age_sec=3600,
        unrealized_pnl_pct=(current_price - entry_price) / entry_price,
        leverage=3.0,
        atr_pct=0.015,
    )
    
    decision = system.evaluate_full(pos, candles_1h=candles, regime="trend")
    
    passed = decision.action == ExitAction.REDUCE and decision.tb_tp_hit
    log_test("Triple Barrier 止盈（reduce优先）", passed,
             f"action={decision.action.value}, reason={decision.reason}, reduce_frac={decision.reduce_frac:.0%}")
    return passed


def test_trailing_stop():
    """测试跟踪止损"""
    exit_cfg = ExitConfig(
        trailing_enabled=True,
        trailing_arm_profit_pct=0.01,
        trailing_retrace_pct=0.02,
        tb_enabled=False,
        tstp_enabled=False,
        l1_enabled=False,
    )
    system = ClassicExitSystem(config=exit_cfg)
    
    entry_price = 10000
    peak_price = entry_price * 1.06
    current_price = peak_price * 0.97
    
    pos = PositionState(
        coin="BTC",
        side="long",
        entry_price=entry_price,
        current_price=current_price,
        position_age_sec=7200,
        unrealized_pnl_pct=(current_price - entry_price) / entry_price,
        mfe_pnl_pct=(peak_price - entry_price) / entry_price,
        leverage=3.0,
        trailing_armed=True,
        trailing_stop_price=peak_price * 0.98,
    )
    
    decision = system.evaluate_full(pos, candles_1h=[], regime="trend")
    
    passed = decision.action == ExitAction.CLOSE and decision.trailing_triggered
    log_test("跟踪止损触发", passed,
             f"action={decision.action.value}, reason={decision.reason}, trailing_stop={decision.trailing_stop_price:.2f}")
    return passed


def test_tstp_trend():
    """测试 TSTP 时间止盈（趋势模式）"""
    exit_cfg = ExitConfig(
        tstp_enabled=True,
        tb_enabled=False,
        trailing_enabled=False,
        l1_enabled=False,
        tstp_trend_plan={
            3600: (2.0, 0.50, "reduce"),
        },
    )
    system = ClassicExitSystem(config=exit_cfg)
    
    entry_price = 10000
    current_price = entry_price * 1.06
    
    pos = PositionState(
        coin="BTC",
        side="long",
        entry_price=entry_price,
        current_price=current_price,
        position_age_sec=7200,
        unrealized_pnl_pct=0.06,
        leverage=3.0,
        atr_pct=0.02,
    )
    
    decision = system.evaluate_full(pos, candles_1h=[], regime="trend")
    
    passed = decision.action == ExitAction.REDUCE and decision.tstp_triggered
    log_test("TSTP 时间止盈（趋势模式）", passed,
             f"action={decision.action.value}, reason={decision.reason}, stage={decision.tstp_stage}")
    return passed


def test_tstp_chop():
    """测试 TSTP 时间止盈（震荡模式）"""
    exit_cfg = ExitConfig(
        tstp_enabled=True,
        tb_enabled=False,
        trailing_enabled=False,
        l1_enabled=False,
        tstp_chop_plan={
            1800: (2.0, 0.50, "reduce"),
        },
    )
    system = ClassicExitSystem(config=exit_cfg)
    
    entry_price = 10000
    current_price = entry_price * 1.05
    
    pos = PositionState(
        coin="BTC",
        side="long",
        entry_price=entry_price,
        current_price=current_price,
        position_age_sec=3600,
        unrealized_pnl_pct=0.05,
        leverage=3.0,
        atr_pct=0.025,
    )
    
    decision = system.evaluate_full(pos, candles_1h=[], regime="chop")
    
    passed = decision.action == ExitAction.REDUCE and decision.tstp_triggered
    log_test("TSTP 时间止盈（震荡模式）", passed,
             f"action={decision.action.value}, reason={decision.reason}, stage={decision.tstp_stage}")
    return passed


def test_l1_value_risk():
    """测试 L1/L2 价值-风险评估"""
    exit_cfg = ExitConfig(
        l1_enabled=True,
        l2_close_threshold=0.75,
        l2_reduce_threshold=0.55,
        l2_confirm_n=1,
    )
    system = ClassicExitSystem(config=exit_cfg)
    
    candles = generate_test_candles("reversal_up_to_down", count=100)
    entry_price = candles[-50]["c"]
    current_price = candles[-1]["c"]
    
    pos = PositionState(
        coin="BTC",
        side="long",
        entry_price=entry_price,
        current_price=current_price,
        position_age_sec=10800,
        unrealized_pnl_pct=(current_price - entry_price) / entry_price,
        leverage=3.0,
    )
    
    decision = system.evaluate_full(pos, candles_1h=candles, regime="trend")
    
    has_features = decision.features is not None
    risk_in_range = 0.0 <= (decision.features.hold_risk if has_features else 0) <= 1.0
    value_in_range = 0.0 <= (decision.features.hold_value if has_features else 0) <= 1.0
    
    passed = has_features and risk_in_range and value_in_range
    details = ""
    if has_features:
        details = f"hold_risk={decision.features.hold_risk:.2f}, hold_value={decision.features.hold_value:.2f}, action={decision.action.value}"
    log_test("L1/L2 价值-风险评估", passed, details)
    return passed


def test_risk_gate():
    """测试风险闸门（armed + cooldown）"""
    exit_cfg = ExitConfig(
        l0_risk_gate_enabled=True,
        l0_risk_gate_cooldown_min=0,
        l0_risk_gate_long_thr=0.50,
        l0_risk_gate_confirm_n=1,
    )
    system = ClassicExitSystem(config=exit_cfg)
    
    candles = generate_test_candles("down", count=80)
    entry_price = candles[-30]["c"]
    current_price = candles[-1]["c"]
    
    pos = PositionState(
        coin="BTC",
        side="long",
        entry_price=entry_price,
        current_price=current_price,
        position_age_sec=7200,
        unrealized_pnl_pct=(current_price - entry_price) / entry_price,
        leverage=3.0,
    )
    
    decision = system.evaluate_full(pos, candles_1h=candles, regime="trend")
    
    passed = decision.action == ExitAction.REDUCE or decision.action == ExitAction.CLOSE
    log_test("风险闸门（高风险场景）", passed,
             f"action={decision.action.value}, reason={decision.reason}, confidence={decision.confidence:.2f}")
    return passed


def test_inflight_cooldown():
    """测试 inflight 冷却机制"""
    exit_cfg = ExitConfig(inflight_cooldown_sec=300)
    system = ClassicExitSystem(config=exit_cfg)
    
    pos = PositionState(
        coin="BTC",
        side="long",
        entry_price=10000,
        current_price=9400,
        position_age_sec=1000,
        unrealized_pnl_pct=-0.06,
        leverage=3.0,
    )
    
    now = time.time()
    
    decision1 = system.evaluate_full(pos, candles_1h=[], regime="trend", now_ts=now)
    decision2 = system.evaluate_full(pos, candles_1h=[], regime="trend", now_ts=now + 100)
    
    passed = decision1.action == ExitAction.CLOSE and decision2.action == ExitAction.HOLD
    log_test("Inflight 冷却（5分钟内阻止重复动作）", passed,
             f"first_action={decision1.action.value}, second_action={decision2.action.value}, blocked={decision2.gate_reason}")
    return passed


def test_regime_differentiation():
    """测试不同市场状态下的行为差异"""
    exit_cfg = ExitConfig(tstp_enabled=True, tb_enabled=True)
    system_trend = ClassicExitSystem(config=exit_cfg)
    system_chop = ClassicExitSystem(config=exit_cfg)
    
    candles_trend = generate_test_candles("up", count=80)
    candles_chop = generate_test_candles("chop", count=80)
    
    entry_price_trend = candles_trend[-30]["c"]
    entry_price_chop = candles_chop[-30]["c"]
    
    pos_trend = PositionState(
        coin="BTC",
        side="long",
        entry_price=entry_price_trend,
        current_price=candles_trend[-1]["c"] * 1.05,
        position_age_sec=7200,
        unrealized_pnl_pct=0.05,
        leverage=3.0,
        atr_pct=0.015,
    )
    
    pos_chop = PositionState(
        coin="BTC",
        side="long",
        entry_price=entry_price_chop,
        current_price=candles_chop[-1]["c"] * 1.05,
        position_age_sec=7200,
        unrealized_pnl_pct=0.05,
        leverage=3.0,
        atr_pct=0.025,
    )
    
    decision_trend = system_trend.evaluate_full(pos_trend, candles_1h=candles_trend, regime="trend")
    decision_chop = system_chop.evaluate_full(pos_chop, candles_1h=candles_chop, regime="chop")
    
    trend_features = decision_trend.features
    chop_features = decision_chop.features
    
    trend_is_up = trend_features and trend_features.trend_shape in (TrendShape.UP_STRONG, TrendShape.UP_REVERSAL)
    chop_is_chop = chop_features and chop_features.trend_shape == TrendShape.CHOP
    
    passed = trend_is_up and chop_is_chop
    details = ""
    if trend_features and chop_features:
        details = f"trend_shape(trend)={trend_features.trend_shape.value}, trend_shape(chop)={chop_features.trend_shape.value}"
    log_test("市场状态识别（趋势vs震荡）", passed, details)
    return passed


def test_short_side():
    """测试空头持仓处理"""
    exit_cfg = ExitConfig(tb_enabled=True, trailing_enabled=True)
    system = ClassicExitSystem(config=exit_cfg)
    
    candles = generate_test_candles("down", count=50)
    entry_price = candles[-30]["c"]
    current_price = candles[-1]["c"] * 0.95
    
    pos = PositionState(
        coin="BTC",
        side="short",
        entry_price=entry_price,
        current_price=current_price,
        position_age_sec=3600,
        unrealized_pnl_pct=(entry_price - current_price) / entry_price,
        leverage=3.0,
        atr_pct=0.02,
    )
    
    decision = system.evaluate_full(pos, candles_1h=candles, regime="trend")
    
    has_features = decision.features is not None
    risk_in_range = 0.0 <= (decision.features.hold_risk if has_features else 0) <= 1.0
    
    passed = has_features and risk_in_range
    details = ""
    if has_features:
        details = f"side=short, hold_risk={decision.features.hold_risk:.2f}, action={decision.action.value}"
    log_test("空头持仓处理", passed, details)
    return passed


def test_no_candles_fallback():
    """测试无K线数据时的降级行为"""
    exit_cfg = ExitConfig(l0_max_loss_pct=-0.05)
    system = ClassicExitSystem(config=exit_cfg)
    
    pos = PositionState(
        coin="BTC",
        side="long",
        entry_price=10000,
        current_price=10100,
        position_age_sec=1000,
        unrealized_pnl_pct=0.01,
        leverage=3.0,
    )
    
    decision = system.evaluate_full(pos, candles_1h=[], regime="trend")
    
    passed = decision.action == ExitAction.HOLD and decision.gate_passed
    log_test("无K线数据降级（安全兜底）", passed,
             f"action={decision.action.value}, features={decision.features is not None}")
    return passed


def main():
    print("=" * 60)
    print("经典指标离场系统功能验证测试")
    print("=" * 60)
    
    tests = [
        test_l0_max_hold,
        test_l0_max_loss,
        test_l0_max_loss_leverage,
        test_tb_stop_loss,
        test_tb_take_profit,
        test_trailing_stop,
        test_tstp_trend,
        test_tstp_chop,
        test_l1_value_risk,
        test_risk_gate,
        test_inflight_cooldown,
        test_regime_differentiation,
        test_short_side,
        test_no_candles_fallback,
    ]
    
    results = []
    for test_fn in tests:
        try:
            results.append(test_fn())
        except Exception as e:
            print(f"  ✗ FAIL {test_fn.__name__}")
            print(f"      Exception: {e}")
            results.append(False)
    
    passed_count = sum(results)
    total_count = len(results)
    
    print("=" * 60)
    print(f"测试结果: {passed_count}/{total_count} 通过")
    print("=" * 60)
    
    if passed_count == total_count:
        print("\n✓ 所有测试通过！离场系统功能正常。")
        return 0
    else:
        print(f"\n✗ 有 {total_count - passed_count} 个测试失败，请检查相关模块。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
