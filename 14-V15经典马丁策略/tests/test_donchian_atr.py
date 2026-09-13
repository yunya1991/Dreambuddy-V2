"""
Phase A TDD 测试：Donchian 通道 + ATR 计算模块

覆盖：
  T1. calc_atr 基本计算：14 日 ATR 与 talib 对齐（无 talib 时验证数学正确性）
  T2. calc_atr 数据不足（< period）返回中性默认值（不抛异常）
  T3. calc_atr 极端值（全相同价格）返回 0.0 不报错
  T4. calc_donchian 基本计算：20 日通道（上轨=20日最高，下轨=20日最低）
  T5. calc_donchian 55 日通道（慢系统）
  T6. calc_donchian 数据不足返回中性默认值
  T7. calc_donchian 突破信号：收盘价 > 上轨 → LONG_SIGNAL
  T8. calc_donchian 突破信号：收盘价 < 下轨 → SHORT_SIGNAL
  T9. calc_donchian 价格在通道内 → NEUTRAL

参考：SPEC-趋势跟踪正金字塔与网格策略落地.md Phase A
硬约束：HC-TF-01（SL≥4% 下限保护依赖 ATR）
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "lib"))
sys.path.insert(0, str(BASE_DIR / "core"))


# ====================================================================
# T1. calc_atr 基本计算
# ====================================================================
def test_calc_atr_basic():
    """T1: 14 日 ATR 数学正确性验证"""
    from v15_signal import calc_atr

    # 构造 20 根 K 线，每根 True Range = H-L = 10
    highs = [110.0] * 20
    lows = [100.0] * 20
    closes = [105.0] * 20
    atr = calc_atr(highs, lows, closes, period=14)
    # ATR 应为 10.0（True Range = H-L = 10，无缺口）
    assert atr is not None
    assert abs(atr - 10.0) < 0.01, f"ATR 应为 10.0，实际={atr}"


# ====================================================================
# T2. calc_atr 数据不足返回中性默认值
# ====================================================================
def test_calc_atr_insufficient_data():
    """T2: 数据不足（< period）返回中性默认值，不抛异常"""
    from v15_signal import calc_atr

    highs = [110.0, 111.0]
    lows = [100.0, 101.0]
    closes = [105.0, 106.0]
    # period=14 但只有 2 根 K 线 → 应返回 0.0 或中性值，不抛异常
    atr = calc_atr(highs, lows, closes, period=14)
    assert atr is not None
    assert atr == 0.0 or atr >= 0.0, f"数据不足时 ATR 应为 0.0 或非负，实际={atr}"


# ====================================================================
# T3. calc_atr 极端值（全相同价格）
# ====================================================================
def test_calc_atr_flat_market():
    """T3: 全相同价格（无波动）ATR=0.0，不报错"""
    from v15_signal import calc_atr

    highs = [100.0] * 30
    lows = [100.0] * 30
    closes = [100.0] * 30
    atr = calc_atr(highs, lows, closes, period=14)
    assert atr == 0.0, f"无波动时 ATR 应为 0.0，实际={atr}"


# ====================================================================
# T4. calc_donchian 20 日通道（快系统）
# ====================================================================
def test_calc_donchian_20day():
    """T4: 20 日 Donchian 通道（上轨=20日最高，下轨=20日最低）"""
    from v15_signal import calc_donchian

    highs = list(range(100, 120))  # 100..119
    lows = list(range(90, 110))     # 90..109
    channel = calc_donchian(highs, lows, period=20)
    assert channel is not None
    # 上轨 = 最近 20 日最高 = 119
    assert channel["upper"] == 119.0, f"上轨应为 119，实际={channel['upper']}"
    # 下轨 = 最近 20 日最低 = 90
    assert channel["lower"] == 90.0, f"下轨应为 90，实际={channel['lower']}"
    # 中轨 = (上轨+下轨)/2
    assert channel["mid"] == 104.5, f"中轨应为 104.5，实际={channel['mid']}"


# ====================================================================
# T5. calc_donchian 55 日通道（慢系统）
# ====================================================================
def test_calc_donchian_55day():
    """T5: 55 日 Donchian 通道（海龟慢系统）"""
    from v15_signal import calc_donchian

    highs = list(range(100, 156))  # 100..155 (56 个，取后 55 个 = 101..155)
    lows = list(range(90, 146))   # 90..145 (56 个，取后 55 个 = 91..145)
    channel = calc_donchian(highs, lows, period=55)
    assert channel is not None
    assert channel["upper"] == 155.0, f"上轨应为 155，实际={channel['upper']}"
    # 后 55 个 lows = 91..145，最小 91
    assert channel["lower"] == 91.0, f"下轨应为 91（后55个），实际={channel['lower']}"


# ====================================================================
# T6. calc_donchian 数据不足返回中性默认值
# ====================================================================
def test_calc_donchian_insufficient_data():
    """T6: 数据不足返回中性默认值，不抛异常"""
    from v15_signal import calc_donchian

    highs = [100.0, 101.0]
    lows = [90.0, 91.0]
    channel = calc_donchian(highs, lows, period=20)
    # 数据不足时应返回 None 或中性 dict，不抛异常
    assert channel is None or isinstance(channel, dict)


# ====================================================================
# T7. Donchian 突破信号：收盘价 > 上轨 → LONG
# ====================================================================
def test_donchian_breakout_long():
    """T7: 收盘价突破上轨 → LONG 信号"""
    from v15_signal import calc_donchian, donchian_breakout_signal

    # 20 日通道，上轨=119，收盘价=120 > 119
    highs = list(range(100, 120))
    lows = list(range(90, 110))
    closes = [105.0] * 19 + [120.0]  # 最后一根收盘 120，突破上轨 119
    signal = donchian_breakout_signal(closes, highs, lows, period=20)
    assert signal == "LONG", f"收盘价>上轨应为 LONG，实际={signal}"


# ====================================================================
# T8. Donchian 突破信号：收盘价 < 下轨 → SHORT
# ====================================================================
def test_donchian_breakout_short():
    """T8: 收盘价跌破下轨 → SHORT 信号"""
    from v15_signal import donchian_breakout_signal

    highs = list(range(100, 120))
    lows = list(range(90, 110))
    closes = [105.0] * 19 + [89.0]  # 最后一根收盘 89，跌破下轨 90
    signal = donchian_breakout_signal(closes, highs, lows, period=20)
    assert signal == "SHORT", f"收盘价<下轨应为 SHORT，实际={signal}"


# ====================================================================
# T9. Donchian 价格在通道内 → NEUTRAL
# ====================================================================
def test_donchian_breakout_neutral():
    """T9: 价格在通道内 → NEUTRAL"""
    from v15_signal import donchian_breakout_signal

    highs = list(range(100, 120))
    lows = list(range(90, 110))
    closes = [105.0] * 20  # 收盘价 105，在 90~119 之间
    signal = donchian_breakout_signal(closes, highs, lows, period=20)
    assert signal == "NEUTRAL", f"价格在通道内应为 NEUTRAL，实际={signal}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
