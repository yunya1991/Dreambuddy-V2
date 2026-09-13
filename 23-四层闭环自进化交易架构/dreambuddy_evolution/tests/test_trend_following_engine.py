"""
Phase B TDD 测试：TrendFollowingEngine + 正金字塔加仓 + 2N 止损

覆盖：
  T1. TrendFollowingEngine 模块可导入
  T2. DonchianChannel.breakout_signal(kline_data) → 20日/55日突破
  T3. ATRStopCalculator.calc_stop(entry_price, atr, direction) → 2×ATR 止损
  T4. ATRStopCalculator 下限保护：2×ATR < 4% 时 SL=4%（HC-TF-01）
  T5. ATRStopCalculator 上限保护：2×ATR > 15% 时 SL=15%（HC-TF-01）
  T6. PyramidingPositionSizer.calc_unit(account, atr, point_value) → Unit 仓位
  T7. PyramidingPositionSizer.calc_addon_tiers → 0.5N 加仓阶梯，最多 4 Unit（HC-TF-02）
  T8. TrendExitRule.check_exit：跌破 10 日低点 → 离场
  T9. TrendFollowingEngine.evaluate → 生成 trade_signal
  T10. FAIL-OPEN：异常输入 → 返回中性兜底（HC-TF-07）

参考：SPEC-趋势跟踪正金字塔与网格策略落地.md Phase B
硬约束：HC-TF-01（SL 2×ATR 4-15%）、HC-TF-02（4 Unit 0.5N）、HC-TF-07（FAIL-OPEN）
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


# ====================================================================
# T1. TrendFollowingEngine 模块可导入
# ====================================================================
def test_trend_following_engine_importable():
    """T1: TrendFollowingEngine 模块可导入"""
    from dreambuddy_evolution.engines.trend_following import (
        TrendFollowingEngine,
        DonchianChannel,
        ATRStopCalculator,
        PyramidingPositionSizer,
        TrendExitRule,
    )
    assert TrendFollowingEngine is not None
    assert DonchianChannel is not None
    assert ATRStopCalculator is not None
    assert PyramidingPositionSizer is not None
    assert TrendExitRule is not None


# ====================================================================
# T2. DonchianChannel 突破信号
# ====================================================================
def test_donchian_channel_breakout():
    """T2: DonchianChannel 突破信号"""
    from dreambuddy_evolution.engines.trend_following import DonchianChannel

    # 20 日通道，上轨=119，收盘价=120 > 119 → LONG
    highs = list(range(100, 120))
    lows = list(range(90, 110))
    closes = [105.0] * 19 + [120.0]
    kline_data = {"high": highs, "low": lows, "close": closes}
    signal = DonchianChannel.breakout_signal(kline_data, period=20)
    assert signal in ("LONG", "SHORT", "NEUTRAL")
    assert signal == "LONG", f"突破上轨应为 LONG，实际={signal}"


# ====================================================================
# T3. ATRStopCalculator 2×ATR 止损
# ====================================================================
def test_atr_stop_basic():
    """T3: 2×ATR 止损价计算（多头）"""
    from dreambuddy_evolution.engines.trend_following import ATRStopCalculator

    entry_price = 100.0
    atr = 3.0  # 2×ATR = 6%
    direction = "LONG"
    stop = ATRStopCalculator.calc_stop(entry_price, atr, direction)
    # 多头止损 = entry - 2×ATR = 100 - 6 = 94
    assert abs(stop - 94.0) < 0.01, f"多头止损应为 94.0，实际={stop}"


# ====================================================================
# T4. ATRStopCalculator 下限保护（HC-TF-01）
# ====================================================================
def test_atr_stop_floor():
    """T4: 2×ATR < 4% 时，SL = 4% 下限保护"""
    from dreambuddy_evolution.engines.trend_following import ATRStopCalculator

    entry_price = 100.0
    atr = 1.0  # 2×ATR = 2.0% < 4% 下限
    direction = "LONG"
    stop = ATRStopCalculator.calc_stop(entry_price, atr, direction)
    # 下限保护：SL ≥ 4% → 止损价 = 100 × (1 - 0.04) = 96.0
    assert abs(stop - 96.0) < 0.01, f"下限保护止损应为 96.0，实际={stop}"


# ====================================================================
# T5. ATRStopCalculator 上限保护（HC-TF-01）
# ====================================================================
def test_atr_stop_cap():
    """T5: 2×ATR > 15% 时，SL = 15% 上限保护"""
    from dreambuddy_evolution.engines.trend_following import ATRStopCalculator

    entry_price = 100.0
    atr = 10.0  # 2×ATR = 20% > 15% 上限
    direction = "LONG"
    stop = ATRStopCalculator.calc_stop(entry_price, atr, direction)
    # 上限保护：SL ≤ 15% → 止损价 = 100 × (1 - 0.15) = 85.0
    assert abs(stop - 85.0) < 0.01, f"上限保护止损应为 85.0，实际={stop}"


# ====================================================================
# T6. PyramidingPositionSizer Unit 仓位
# ====================================================================
def test_pyramiding_unit():
    """T6: Unit = (Account × 1%) / (ATR × PointValue)"""
    from dreambuddy_evolution.engines.trend_following import PyramidingPositionSizer

    account = 10000.0  # 10000 USDT
    atr = 5.0          # ATR = 5 USDT
    point_value = 1.0  # 1 USDT/单位
    unit = PyramidingPositionSizer.calc_unit(account, atr, point_value)
    # Unit = (10000 × 0.01) / (5 × 1) = 100 / 5 = 20
    assert abs(unit - 20.0) < 0.01, f"Unit 应为 20.0，实际={unit}"


# ====================================================================
# T7. PyramidingPositionSizer 0.5N 加仓阶梯（HC-TF-02）
# ====================================================================
def test_pyramiding_addon_tiers():
    """T7: 0.5N 加仓阶梯，最多 4 Unit"""
    from dreambuddy_evolution.engines.trend_following import PyramidingPositionSizer

    entry_price = 100.0
    atr = 2.0
    direction = "LONG"
    tiers = PyramidingPositionSizer.calc_addon_tiers(entry_price, atr, direction)
    # 最多 4 个加仓阶梯
    assert len(tiers) <= 4, f"加仓阶梯应 ≤ 4，实际={len(tiers)}"
    # 每个阶梯间隔 0.5×ATR = 1.0
    if len(tiers) >= 2:
        # 多头加仓价格应递增（顺势加仓）
        assert tiers[1] > tiers[0], f"多头加仓价格应递增，tiers={tiers}"


# ====================================================================
# T8. TrendExitRule 跌破 10 日低点离场
# ====================================================================
def test_trend_exit_rule():
    """T8: 跌破 10 日低点 → 离场信号"""
    from dreambuddy_evolution.engines.trend_following import TrendExitRule

    # 10 日低点 = 90，当前收盘 = 89 < 90 → 离场
    lows = list(range(90, 110))  # 90..109
    closes = [105.0] * 9 + [89.0]  # 最后一根收盘 89，跌破 10 日低点 90
    kline_data = {"low": lows, "close": closes}
    should_exit = TrendExitRule.check_exit(kline_data, period=10)
    assert should_exit is True, "跌破 10 日低点应触发离场"


# ====================================================================
# T9. TrendFollowingEngine.evaluate 生成 trade_signal
# ====================================================================
def test_trend_following_engine_evaluate():
    """T9: evaluate 生成 trade_signal"""
    from dreambuddy_evolution.engines.trend_following import TrendFollowingEngine

    # 构造趋势突破场景：20 日通道上轨=119，收盘=120
    highs = list(range(100, 120))
    lows = list(range(90, 110))
    closes = [105.0] * 19 + [120.0]
    kline_data = {"high": highs, "low": lows, "close": closes, "volume": [100.0] * 20}
    account_state = {"equity": 10000.0, "point_value": 1.0}
    signal = TrendFollowingEngine.evaluate(kline_data, account_state)
    assert signal is not None
    assert isinstance(signal, dict)
    assert "action" in signal
    assert signal["action"] in ("LONG", "SHORT", "WAIT")


# ====================================================================
# T10. FAIL-OPEN：异常输入 → 中性兜底（HC-TF-07）
# ====================================================================
def test_trend_following_engine_fail_open():
    """T10: 异常输入 → 中性兜底，不抛异常"""
    from dreambuddy_evolution.engines.trend_following import TrendFollowingEngine

    # 空 kline_data
    signal = TrendFollowingEngine.evaluate({}, {})
    assert signal is not None
    assert signal.get("action") == "WAIT"

    # None 输入
    signal2 = TrendFollowingEngine.evaluate(None, None)
    assert signal2 is not None
    assert signal2.get("action") == "WAIT"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
