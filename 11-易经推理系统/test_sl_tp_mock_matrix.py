#!/usr/bin/env python3
"""
SL/TP 连续调制综合验证 — Mock 数据矩阵

覆盖场景：
  - 3 种 ATR 基线（低波动 1%、中波动 3%、高波动 6%）
  - 3 种杠杆（3x、5x、10x）
  - 5 种风险分数（0.10 极低 / 0.25 低 / 0.50 中 / 0.75 高 / 1.00 极高）
  - 5 种价值分数（0.00 极低 / 0.30 低 / 0.50 中 / 0.85 高 / 1.00 极高）
  - 4 种离场动作（LOWER_SL / RAISE_TP / TIGHTEN_SL / LOWER_TP）

验证点：
  1. 调制后 SL/TP 是否以 ATR 基线为基准（非硬编码 2%/15%）
  2. ATR 基线下限保护是否生效（≥ base × 0.7）
  3. 连续性：相近风险/价值分数的调制因子差值合理
  4. 极端值不越界（clamp [0.5, 2.0]）
"""

import sys
import os

# 先锁 stdlib inspect，防止本地 inspect.py 覆盖
import inspect as _stdlib_inspect
sys.modules["inspect"] = _stdlib_inspect

_l4_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "scripts", "memory_l4"
)
if _l4_path not in sys.path:
    sys.path.insert(0, _l4_path)

from yijing_exit_system import YijingExitSystem

# ── 测试参数矩阵 ──────────────────────────────────────────────────

# Mock 场景：模拟不同币种 × 不同杠杆下的 ATR 基线
MOCK_SCENARIOS = [
    # (名称, 入场价, 波动率, 杠杆, ATR_SL倍数, ATR_TP倍数)
    # ATR 基线 = price × volatility × mult
    # base_sl_roi = sl_mult × volatility × leverage（订单收益率）
    # base_tp_roi = tp_mult × volatility × leverage
    ("BTC-低波动-3x",  95000, 0.012, 3,  3.0, 6.0),   # base_sl=10.8%, base_tp=21.6%
    ("BTC-中波动-5x",  95000, 0.030, 5,  3.0, 6.0),   # base_sl=45.0%, base_tp=90.0%
    ("ETH-中波动-10x",  3200, 0.035, 10, 3.0, 6.0),   # base_sl=105%, base_tp=210%
    ("OKB-低波动-10x",    52, 0.004, 10, 3.0, 6.0),   # base_sl=12%,  base_tp=24%
    ("SOL-高波动-5x",    145, 0.060, 5,  3.0, 6.0),   # base_sl=90%,  base_tp=180%
    ("DOGE-高波动-10x",  0.12, 0.080, 10, 3.0, 6.0),  # base_sl=240%, base_tp=480%
]

RISK_SCORES = [0.10, 0.25, 0.50, 0.75, 1.00]
VALUE_SCORES = [0.00, 0.30, 0.50, 0.85, 1.00]

FLOOR_RATIO = 0.7

_passed = 0
_failed = 0
_errors = []


def check(name, condition, details=""):
    global _passed, _failed
    if condition:
        _passed += 1
    else:
        _failed += 1
        _errors.append((name, details))
        print(f"  ✗ FAIL {name}")
        if details:
            print(f"      {details}")


def approx(a, b, eps=0.01):
    return abs(a - b) < eps


# ── 核心计算函数（模拟 polling_trader 中的逻辑）─────────────────────

def calc_atr_base_roi(price, volatility, mult, leverage):
    """计算 ATR 基线 ROI（订单收益率）
    ATR = price × volatility
    price_change = mult × volatility
    roi = price_change × leverage
    """
    return mult * volatility * leverage


def modulate_sl(base_sl_roi, risk_score):
    """模拟 LOWER_SL / TIGHTEN_SL 路径"""
    modulation = YijingExitSystem.risk_to_sl_modulation(risk_score)
    new_sl_roi = base_sl_roi * modulation
    # ATR 基线下限保护
    floor = base_sl_roi * FLOOR_RATIO
    final_sl_roi = max(new_sl_roi, floor)
    return modulation, new_sl_roi, floor, final_sl_roi


def modulate_tp(base_tp_roi, value_score):
    """模拟 RAISE_TP / LOWER_TP 路径"""
    modulation = YijingExitSystem.value_to_tp_modulation(value_score)
    new_tp_roi = base_tp_roi * modulation
    # ATR 基线下限保护
    floor = base_tp_roi * FLOOR_RATIO
    final_tp_roi = max(new_tp_roi, floor)
    return modulation, new_tp_roi, floor, final_tp_roi


# ── 测试用例 ──────────────────────────────────────────────────────

def test_modulation_clamp_bounds():
    """1. 调制因子 clamp 到 [0.5, 2.0]"""
    print("\n── 1. 调制因子边界 clamp ──")
    for risk in [-10, -1, 0, 0.5, 1, 2, 100]:
        m = YijingExitSystem.risk_to_sl_modulation(risk)
        check(f"sl_modulation({risk}) in [0.5, 2.0]", 0.5 <= m <= 2.0,
              f"got {m}")
    for value in [-10, -1, 0, 0.5, 1, 2, 100]:
        m = YijingExitSystem.value_to_tp_modulation(value)
        check(f"tp_modulation({value}) in [0.5, 2.0]", 0.5 <= m <= 2.0,
              f"got {m}")


def test_atr_base_not_hardcoded():
    """2. 验证 SL/TP 基于 ATR 基线（非硬编码 2%/15%）"""
    print("\n── 2. ATR 基线验证（非硬编码 2%/15%）──")
    for name, price, vol, lev, sl_mult, tp_mult in MOCK_SCENARIOS:
        base_sl = calc_atr_base_roi(price, vol, sl_mult, lev)
        base_tp = calc_atr_base_roi(price, vol, tp_mult, lev)

        # risk=0.25 → sl_modulation=1.5，LOWER_SL 应 = base × 1.5
        _, _, _, final_sl = modulate_sl(base_sl, 0.25)
        # 不应等于硬编码的 0.03（3%）
        check(f"{name} LOWER_SL≠3%", not approx(final_sl, 0.03),
              f"base_sl={base_sl:.2%}, final={final_sl:.2%}")

        # value=0.85 → tp_modulation=1.775，RAISE_TP 应 = base × 1.775
        _, _, _, final_tp = modulate_tp(base_tp, 0.85)
        # 不应等于硬编码的 0.15（15%）
        check(f"{name} RAISE_TP≠15%", not approx(final_tp, 0.15),
              f"base_tp={base_tp:.2%}, final={final_tp:.2%}")


def test_atr_floor_protection():
    """3. ATR 基线下限保护：调整后 ROI ≥ base × 0.7"""
    print("\n── 3. ATR 基线下限保护 ──")
    for name, price, vol, lev, sl_mult, tp_mult in MOCK_SCENARIOS:
        base_sl = calc_atr_base_roi(price, vol, sl_mult, lev)
        base_tp = calc_atr_base_roi(price, vol, tp_mult, lev)

        # 极高风险 → sl_modulation=0.5，应被 floor 托住
        _, new_sl, floor_sl, final_sl = modulate_sl(base_sl, 1.0)
        check(f"{name} SL floor (risk=1.0)",
              final_sl >= floor_sl - 0.001,
              f"new={new_sl:.4f}, floor={floor_sl:.4f}, final={final_sl:.4f}")

        # 极低价值 → tp_modulation=0.5，应被 floor 托住
        _, new_tp, floor_tp, final_tp = modulate_tp(base_tp, 0.0)
        check(f"{name} TP floor (value=0.0)",
              final_tp >= floor_tp - 0.001,
              f"new={new_tp:.4f}, floor={floor_tp:.4f}, final={final_tp:.4f}")


def test_lower_sl_high_risk_not_tighter():
    """4. LOWER_SL（低风险放宽）不应比 TIGHTEN_SL（高风险收紧）更紧"""
    print("\n── 4. LOWER_SL vs TIGHTEN_SL 方向性 ──")
    for name, price, vol, lev, sl_mult, tp_mult in MOCK_SCENARIOS:
        base_sl = calc_atr_base_roi(price, vol, sl_mult, lev)

        _, _, _, lower_final = modulate_sl(base_sl, 0.10)   # 极低风险 → 放宽
        _, _, _, tighten_final = modulate_sl(base_sl, 0.90)  # 高风险 → 收紧
        check(f"{name} LOWER(0.10) ≥ TIGHTEN(0.90)",
              lower_final >= tighten_final - 0.001,
              f"lower={lower_final:.4f}, tighten={tighten_final:.4f}")


def test_raise_tp_higher_than_lower_tp():
    """5. RAISE_TP（高价值）应比 LOWER_TP（低价值）更高"""
    print("\n── 5. RAISE_TP vs LOWER_TP 方向性 ──")
    for name, price, vol, lev, sl_mult, tp_mult in MOCK_SCENARIOS:
        base_tp = calc_atr_base_roi(price, vol, tp_mult, lev)

        _, _, _, raise_final = modulate_tp(base_tp, 0.85)   # 高价值 → 提高
        _, _, _, lower_final = modulate_tp(base_tp, 0.10)   # 低价值 → 降低
        check(f"{name} RAISE(0.85) ≥ LOWER(0.10)",
              raise_final >= lower_final - 0.001,
              f"raise={raise_final:.4f}, lower={lower_final:.4f}")


def test_full_matrix():
    """6. 完整矩阵：打印所有场景的 SL/TP 计算结果"""
    print("\n── 6. 完整矩阵输出 ──")
    print(f"{'场景':<20} {'base_sl':>8} {'base_tp':>8} │"
          f" {'risk':>5} {'sl_mod':>6} {'new_sl':>8} │"
          f" {'value':>5} {'tp_mod':>6} {'new_tp':>8}")
    print("─" * 95)

    for name, price, vol, lev, sl_mult, tp_mult in MOCK_SCENARIOS:
        base_sl = calc_atr_base_roi(price, vol, sl_mult, lev)
        base_tp = calc_atr_base_roi(price, vol, tp_mult, lev)

        for risk in RISK_SCORES:
            sl_mod, new_sl, floor_sl, final_sl = modulate_sl(base_sl, risk)
            for value in VALUE_SCORES:
                tp_mod, new_tp, floor_tp, final_tp = modulate_tp(base_tp, value)

                # 验证：final 不小于 floor
                ok_sl = final_sl >= floor_sl - 0.001
                ok_tp = final_tp >= floor_tp - 0.001
                check(f"{name} r={risk:.2f} v={value:.2f} floor",
                      ok_sl and ok_tp,
                      f"sl_final={final_sl:.4f} sl_floor={floor_sl:.4f} | "
                      f"tp_final={final_tp:.4f} tp_floor={floor_tp:.4f}")

        # 打印一组代表性数据（risk=0.25, value=0.85）
        sl_mod, new_sl, _, final_sl = modulate_sl(base_sl, 0.25)
        tp_mod, new_tp, _, final_tp = modulate_tp(base_tp, 0.85)
        print(f"{name:<20} {base_sl:>7.1%} {base_tp:>7.1%} │"
              f" {0.25:>5.2f} {sl_mod:>6.2f} {final_sl:>7.1%} │"
              f" {0.85:>5.2f} {tp_mod:>6.2f} {final_tp:>7.1%}")

    # 补充：极端对比
    print("─" * 95)
    print("极端对比（BTC-中波动-5x）:")
    name, price, vol, lev, sl_mult, tp_mult = MOCK_SCENARIOS[1]
    base_sl = calc_atr_base_roi(price, vol, sl_mult, lev)
    base_tp = calc_atr_base_roi(price, vol, tp_mult, lev)
    for risk in [0.10, 0.50, 0.90]:
        sl_mod, new_sl, floor_sl, final_sl = modulate_sl(base_sl, risk)
        print(f"  risk={risk:.2f}: sl_mod={sl_mod:.2f}, "
              f"new_sl={new_sl:.1%}, floor={floor_sl:.1%}, final={final_sl:.1%}")
    for value in [0.00, 0.50, 0.85]:
        tp_mod, new_tp, floor_tp, final_tp = modulate_tp(base_tp, value)
        print(f"  value={value:.2f}: tp_mod={tp_mod:.2f}, "
              f"new_tp={new_tp:.1%}, floor={floor_tp:.1%}, final={final_tp:.1%}")


def test_monotonicity():
    """7. 单调性：风险递增 → SL 递减；价值递增 → TP 递增"""
    print("\n── 7. 单调性验证 ──")
    for name, price, vol, lev, sl_mult, tp_mult in MOCK_SCENARIOS:
        base_sl = calc_atr_base_roi(price, vol, sl_mult, lev)
        base_tp = calc_atr_base_roi(price, vol, tp_mult, lev)

        # SL 随 risk 递增应递减（或被 floor 托平）
        prev = float('inf')
        for risk in [0.10, 0.25, 0.50, 0.75, 0.90]:
            _, _, _, final = modulate_sl(base_sl, risk)
            check(f"{name} SL monotonic risk={risk:.2f}",
                  final <= prev + 0.001,
                  f"prev={prev:.4f}, curr={final:.4f}")
            prev = final

        # TP 随 value 递增应递增
        prev = -1
        for value in [0.00, 0.10, 0.30, 0.50, 0.85]:
            _, _, _, final = modulate_tp(base_tp, value)
            check(f"{name} TP monotonic value={value:.2f}",
                  final >= prev - 0.001,
                  f"prev={prev:.4f}, curr={final:.4f}")
            prev = final


def test_old_bug_regression():
    """8. 回归测试：确认修复前的 Bug 不再出现"""
    print("\n── 8. Bug 回归验证 ──")
    # Bug A: LOWER_SL with base=12% should NOT produce 3%
    base_sl = 0.12  # OKB-like: 3.0 × 0.4% × 10x = 12%
    _, _, _, final = modulate_sl(base_sl, 0.25)  # risk=0.25 → mod=1.5
    check("Bug A: LOWER_SL 12%×1.5=18% (not 3%)",
          approx(final, 0.18) and not approx(final, 0.03),
          f"expected 0.18, got {final:.4f}")

    # Bug B: RAISE_TP with base=24% should NOT produce 15%
    base_tp = 0.24  # OKB-like: 6.0 × 0.4% × 10x = 24%
    _, _, _, final = modulate_tp(base_tp, 0.85)  # value=0.85 → mod=1.775
    check("Bug B: RAISE_TP 24%×1.775=42.6% (not 15%)",
          approx(final, 0.426) and not approx(final, 0.15),
          f"expected 0.426, got {final:.4f}")

    # Bug C: 非离散跳变 — risk=0.30→0.31 差值应远小于 0.30→0.35
    m_030 = YijingExitSystem.risk_to_sl_modulation(0.30)
    m_031 = YijingExitSystem.risk_to_sl_modulation(0.31)
    m_035 = YijingExitSystem.risk_to_sl_modulation(0.35)
    diff_small = abs(m_030 - m_031)
    diff_large = abs(m_030 - m_035)
    check("Bug C: 连续性 (0.30→0.31 diff << 0.30→0.35 diff)",
          diff_small < diff_large and diff_small < 0.03,
          f"small={diff_small:.4f}, large={diff_large:.4f}")


if __name__ == "__main__":
    print("=" * 95)
    print("SL/TP 连续调制 — Mock 数据矩阵综合验证")
    print("=" * 95)

    test_modulation_clamp_bounds()
    test_atr_base_not_hardcoded()
    test_atr_floor_protection()
    test_lower_sl_high_risk_not_tighter()
    test_raise_tp_higher_than_lower_tp()
    test_full_matrix()
    test_monotonicity()
    test_old_bug_regression()

    print(f"\n{'=' * 95}")
    print(f"结果: {_passed} passed, {_failed} failed")
    if _errors:
        print("\n失败详情:")
        for name, detail in _errors:
            print(f"  ✗ {name}: {detail}")
    print(f"{'=' * 95}")
    sys.exit(1 if _failed > 0 else 0)
