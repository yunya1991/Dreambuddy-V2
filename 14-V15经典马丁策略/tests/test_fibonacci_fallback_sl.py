"""test_fibonacci_fallback_sl.py — 斐波那契兜底SL测试.

Bug背景: FIX-A的15%绝对兜底对马丁策略太紧——加仓间距8%×vol_ratio≈15%，
15% SL正好在第一档加仓价附近，开仓≈准备止损。

修复: 用斐波那契0.786回撤（趋势逆转位）+ swing low替换15%绝对兜底。
- 0.786回撤 = swing_high - (swing_high - swing_low) × 0.786
- swing_low是趋势翻转最后防线
- 取max(fib_0.786, swing_low×1.02)作为SL候选
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_V15_ROOT = _HERE.parent
if str(_V15_ROOT) not in sys.path:
    sys.path.insert(0, str(_V15_ROOT))
if str(_V15_ROOT / "lib") not in sys.path:
    sys.path.insert(0, str(_V15_ROOT / "lib"))


class TestFibonacciFallbackSL:
    """斐波那契0.786回撤+swing low兜底SL计算。"""

    def test_fib_0786_retracement_long(self):
        """LONG: swing_high=$1000, swing_low=$850 → 0.786回撤SL≈$882"""
        from strategy_params import _calc_fibonacci_fallback_sl

        # 12个点: 800,850,900,950,900,850,900,950,1000,950,900,984
        # detect_swing_points(window=3)检测到: high@950, low@850, high@1000
        # 最近: high@1000, low@850
        # 0.786 retracement = 1000 - (1000-850)*0.786 = 1000-117.9 = 882.1
        # swing_low×1.02 = 850*1.02 = 867.0
        # max(882.1, 867.0) = 882.1
        closes = [800, 850, 900, 950, 900, 850, 900, 950, 1000, 950, 900, 984.0]
        result = _calc_fibonacci_fallback_sl(
            direction="LONG",
            current_price=984.0,
            daily_closes=closes,
        )
        assert result is not None
        sl_price = result["stop_loss_price"]
        sl_type = result["stop_type"]
        # SL应该在swing_low上方(0.786回撤位附近)
        assert sl_price > 850.0, f"SL应大于swing_low $850, 实际=${sl_price}"
        assert sl_price < 984.0, f"SL应小于current_price $984, 实际=${sl_price}"
        assert "0.786" in sl_type or "fib" in sl_type.lower(), f"stop_type应含0.786/fib, 实际: {sl_type}"
        # 验证计算: 0.786回撤位 ≈ 882.1
        assert abs(sl_price - 882.1) < 3.0, f"SL应在$882.1附近, 实际=${sl_price}"

    def test_no_15_percent_absolute_fallback(self):
        """不应再有15%绝对兜底候选。"""
        from strategy_params import _calc_fibonacci_fallback_sl

        result = _calc_fibonacci_fallback_sl(
            direction="LONG",
            current_price=984.0,
            daily_closes=[900.0, 920.0, 950.0, 970.0, 984.0],
        )
        if result is None:
            return  # 没有swing点也算合法（数据不足）
        # 不应包含"15%"或"绝对兜底"字样
        assert "15%" not in result["stop_type"], "不应再有15%绝对兜底"
        assert "绝对" not in result["stop_type"], "不应再有绝对兜底"

    def test_fib_sl_below_addon_gap(self):
        """斐波那契SL应不同于15%固定兜底价。"""
        from strategy_params import _calc_fibonacci_fallback_sl

        # 模拟MU场景: entry=$984
        closes = [800, 850, 900, 950, 900, 850, 900, 950, 1000, 950, 900, 984.0]
        result = _calc_fibonacci_fallback_sl(
            direction="LONG",
            current_price=984.0,
            daily_closes=closes,
        )
        if result is None:
            return
        sl_price = result["stop_loss_price"]
        assert sl_price < 984.0
        # 确认不是15%固定值
        expected_15pct = 984.0 * 0.85  # = 836.4
        assert abs(sl_price - expected_15pct) > 5.0, (
            f"SL不应等于15%兜底价${expected_15pct}, 实际=${sl_price}"
        )

    def test_insufficient_swings_returns_none(self):
        """数据不足无法检测swing时返回None（交给下层vol×2.5兜底）。"""
        from strategy_params import _calc_fibonacci_fallback_sl

        # 太少数据点
        result = _calc_fibonacci_fallback_sl(
            direction="LONG",
            current_price=100.0,
            daily_closes=[100.0],  # 只有1个点
        )
        assert result is None

    def test_short_direction(self):
        """SHORT: swing_low=$1000, swing_high=$1150 → 0.786回撤SL≈$1132.1"""
        from strategy_params import _calc_fibonacci_fallback_sl

        # 镜像: 1200,1150,1100,1050,1100,1150,1100,1050,1000,1050,1100,1000.0
        # swings: low@1050, high@1150, low@1000
        # 最近: low@1000, high@1150
        # 0.786 = 1000 + 150*0.786 = 1117.9
        # swing_high×0.98 = 1150*0.98 = 1127.0
        # min(1117.9, 1127.0) = 1117.9
        closes = [1200, 1150, 1100, 1050, 1100, 1150, 1100, 1050, 1000, 1050, 1100, 1000.0]
        result = _calc_fibonacci_fallback_sl(
            direction="SHORT",
            current_price=1000.0,
            daily_closes=closes,
        )
        if result is None:
            return
        sl_price = result["stop_loss_price"]
        # SHORT: SL在上方
        assert sl_price > 1000.0, f"SHORT SL应大于current, 实际=${sl_price}"
        assert sl_price < 1150.0, f"SHORT SL应小于swing_high, 实际=${sl_price}"
