#!/usr/bin/env python3
"""
易经离场 SL/TP 连续调制设计 — TDD 测试

测试范围：
1. risk_to_sl_modulation: 风险分 → SL 调制因子（连续函数）
2. value_to_tp_modulation: 价值分 → TP 调制因子（连续函数）
3. ATR 基线下限保护
4. LOWER_SL 使用 ATR 基线（非硬编码 2%）
5. RAISE_TP 使用 ATR 基线（非硬编码 15%）
"""

import sys
import os
import math

# 先 import stdlib inspect（防止本地 inspect.py 覆盖）
import inspect as _stdlib_inspect
sys.modules["inspect"] = _stdlib_inspect

_l4_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "scripts", "memory_l4"
)
if _l4_path not in sys.path:
    sys.path.insert(0, _l4_path)

from yijing_exit_system import YijingExitSystem

_passed = 0
_failed = 0


def check(name, condition, details=""):
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  ✓ PASS {name}")
    else:
        _failed += 1
        print(f"  ✗ FAIL {name}")
    if details:
        print(f"      {details}")


def approx(a, b, eps=0.001):
    return abs(a - b) < eps


# ── 1. risk_to_sl_modulation ──────────────────────────────────────────

def test_risk_to_sl_modulation_low():
    """risk=0.25 → sl_modulation=1.5（放宽50%）"""
    m = YijingExitSystem.risk_to_sl_modulation(0.25)
    check("risk_to_sl_modulation_low", approx(m, 1.5),
          f"expected 1.5, got {m}")


def test_risk_to_sl_modulation_mid():
    """risk=0.50 → sl_modulation=1.0（保持基线）"""
    m = YijingExitSystem.risk_to_sl_modulation(0.50)
    check("risk_to_sl_modulation_mid", approx(m, 1.0),
          f"expected 1.0, got {m}")


def test_risk_to_sl_modulation_high():
    """risk=0.75 → sl_modulation=0.5（收紧50%）"""
    m = YijingExitSystem.risk_to_sl_modulation(0.75)
    check("risk_to_sl_modulation_high", approx(m, 0.5),
          f"expected 0.5, got {m}")


def test_risk_to_sl_modulation_clamp_high():
    """risk=-1（极低风险）→ sl_modulation=2.0（上限）"""
    m = YijingExitSystem.risk_to_sl_modulation(-1.0)
    check("risk_to_sl_modulation_clamp_high", approx(m, 2.0),
          f"expected 2.0, got {m}")


def test_risk_to_sl_modulation_clamp_low():
    """risk=2.0（极高风险）→ sl_modulation=0.5（下限）"""
    m = YijingExitSystem.risk_to_sl_modulation(2.0)
    check("risk_to_sl_modulation_clamp_low", approx(m, 0.5),
          f"expected 0.5, got {m}")


def test_risk_to_sl_modulation_zero():
    """risk=0 → sl_modulation=2.0（上限）"""
    m = YijingExitSystem.risk_to_sl_modulation(0.0)
    check("risk_to_sl_modulation_zero", approx(m, 2.0),
          f"expected 2.0, got {m}")


def test_risk_to_sl_modulation_one():
    """risk=1.0 → sl_modulation=0.5（下限）"""
    m = YijingExitSystem.risk_to_sl_modulation(1.0)
    check("risk_to_sl_modulation_one", approx(m, 0.5),
          f"expected 0.5, got {m}")


# ── 2. value_to_tp_modulation ─────────────────────────────────────────

def test_value_to_tp_modulation_high():
    """value=0.85 → tp_modulation=1.775（提高78%）"""
    m = YijingExitSystem.value_to_tp_modulation(0.85)
    check("value_to_tp_modulation_high", approx(m, 1.775),
          f"expected 1.775, got {m}")


def test_value_to_tp_modulation_mid():
    """value=0.50 → tp_modulation=1.25（提高25%）"""
    m = YijingExitSystem.value_to_tp_modulation(0.50)
    check("value_to_tp_modulation_mid", approx(m, 1.25),
          f"expected 1.25, got {m}")


def test_value_to_tp_modulation_low():
    """value=0.30 → tp_modulation=0.95（基本保持）"""
    m = YijingExitSystem.value_to_tp_modulation(0.30)
    check("value_to_tp_modulation_low", approx(m, 0.95),
          f"expected 0.95, got {m}")


def test_value_to_tp_modulation_clamp_low():
    """value=-1（极低价值）→ tp_modulation=0.5（下限）"""
    m = YijingExitSystem.value_to_tp_modulation(-1.0)
    check("value_to_tp_modulation_clamp_low", approx(m, 0.5),
          f"expected 0.5, got {m}")


def test_value_to_tp_modulation_clamp_high():
    """value=2.0（极高价值）→ tp_modulation=2.0（上限）"""
    m = YijingExitSystem.value_to_tp_modulation(2.0)
    check("value_to_tp_modulation_clamp_high", approx(m, 2.0),
          f"expected 2.0, got {m}")


def test_value_to_tp_modulation_zero():
    """value=0 → tp_modulation=0.5（下限）"""
    m = YijingExitSystem.value_to_tp_modulation(0.0)
    check("value_to_tp_modulation_zero", approx(m, 0.5),
          f"expected 0.5, got {m}")


def test_value_to_tp_modulation_one():
    """value=1.0 → tp_modulation=2.0（上限）"""
    m = YijingExitSystem.value_to_tp_modulation(1.0)
    check("value_to_tp_modulation_one", approx(m, 2.0),
          f"expected 2.0, got {m}")


# ── 3. ATR 基线下限保护 ───────────────────────────────────────────────

def test_atr_floor_protection_sl():
    """risk=1.0, base_sl_roi=0.12 → new_sl ≥ 0.084（12%×0.7）"""
    base_sl_roi = 0.12
    modulation = YijingExitSystem.risk_to_sl_modulation(1.0)  # 0.5
    new_sl_roi = base_sl_roi * modulation  # 0.06
    floor = base_sl_roi * 0.7  # 0.084
    final_sl_roi = max(new_sl_roi, floor)
    check("atr_floor_protection_sl",
          final_sl_roi >= floor and approx(final_sl_roi, 0.084),
          f"new_sl={new_sl_roi}, floor={floor}, final={final_sl_roi}")


def test_atr_floor_protection_tp():
    """value=0, base_tp_roi=0.60 → new_tp ≥ 0.42（60%×0.7）"""
    base_tp_roi = 0.60
    modulation = YijingExitSystem.value_to_tp_modulation(0.0)  # 0.5
    new_tp_roi = base_tp_roi * modulation  # 0.30
    floor = base_tp_roi * 0.7  # 0.42
    final_tp_roi = max(new_tp_roi, floor)
    check("atr_floor_protection_tp",
          final_tp_roi >= floor and approx(final_tp_roi, 0.42),
          f"new_tp={new_tp_roi}, floor={floor}, final={final_tp_roi}")


# ── 4. LOWER_SL 使用 ATR 基线（非硬编码 2%）──────────────────────────

def test_lower_sl_uses_atr_base():
    """ATR base=12%, risk=0.25 → new_sl=18%（非 3%）"""
    base_sl_roi = 0.12
    modulation = YijingExitSystem.risk_to_sl_modulation(0.25)  # 1.5
    new_sl_roi = base_sl_roi * modulation  # 0.18
    floor = base_sl_roi * 0.7  # 0.084
    final_sl_roi = max(new_sl_roi, floor)
    check("lower_sl_uses_atr_base",
          approx(final_sl_roi, 0.18) and not approx(final_sl_roi, 0.03),
          f"expected 0.18 (not 0.03), got {final_sl_roi}")


# ── 5. RAISE_TP 使用 ATR 基线（非硬编码 15%）─────────────────────────

def test_raise_tp_uses_atr_base():
    """ATR base=60%, value=0.85 → new_tp=106.5%（非 15%）"""
    base_tp_roi = 0.60
    modulation = YijingExitSystem.value_to_tp_modulation(0.85)  # 1.775
    new_tp_roi = base_tp_roi * modulation  # 1.065
    floor = base_tp_roi * 0.7  # 0.42
    final_tp_roi = max(new_tp_roi, floor)
    check("raise_tp_uses_atr_base",
          approx(final_tp_roi, 1.065) and not approx(final_tp_roi, 0.15),
          f"expected 1.065 (not 0.15), got {final_tp_roi}")


# ── 6. 连续性验证（非离散跳变）──────────────────────────────────────

def test_modulation_is_continuous():
    """risk=0.30 和 risk=0.31 的调制因子差值应 <0.02（连续，非跳变）"""
    m1 = YijingExitSystem.risk_to_sl_modulation(0.30)
    m2 = YijingExitSystem.risk_to_sl_modulation(0.31)
    check("modulation_is_continuous",
          abs(m1 - m2) <= 0.021,
          f"m(0.30)={m1}, m(0.31)={m2}, diff={abs(m1-m2)}")


if __name__ == "__main__":
    print("=" * 60)
    print("易经离场 SL/TP 连续调制 — TDD 测试")
    print("=" * 60)

    print("\n── risk_to_sl_modulation ──")
    test_risk_to_sl_modulation_low()
    test_risk_to_sl_modulation_mid()
    test_risk_to_sl_modulation_high()
    test_risk_to_sl_modulation_clamp_high()
    test_risk_to_sl_modulation_clamp_low()
    test_risk_to_sl_modulation_zero()
    test_risk_to_sl_modulation_one()

    print("\n── value_to_tp_modulation ──")
    test_value_to_tp_modulation_high()
    test_value_to_tp_modulation_mid()
    test_value_to_tp_modulation_low()
    test_value_to_tp_modulation_clamp_low()
    test_value_to_tp_modulation_clamp_high()
    test_value_to_tp_modulation_zero()
    test_value_to_tp_modulation_one()

    print("\n── ATR 基线下限保护 ──")
    test_atr_floor_protection_sl()
    test_atr_floor_protection_tp()

    print("\n── LOWER_SL/RAISE_TP 使用 ATR 基线 ──")
    test_lower_sl_uses_atr_base()
    test_raise_tp_uses_atr_base()

    print("\n── 连续性验证 ──")
    test_modulation_is_continuous()

    print(f"\n{'=' * 60}")
    print(f"结果: {_passed} passed, {_failed} failed")
    print(f"{'=' * 60}")
    sys.exit(1 if _failed > 0 else 0)
