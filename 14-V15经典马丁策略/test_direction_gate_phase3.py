#!/usr/bin/env python3
"""
DirectionGate 力学化 Phase 3 TDD 测试集
=====================================
swing 高低点 = 高斯势垒/势阱 + 解析梯度力叠加到 F_net
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "lib"))
sys.path.insert(0, str(Path(__file__).parent / "core"))

passed = 0
failed = 0
def expect(label):
    print(f"  🟡 {label} ", end="", flush=True)
    return {"label": label}
def check(ctx, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"\r  ✅ {ctx['label']} ")
    else:
        failed += 1
        print(f"\r  ❌ {ctx['label']}  ← {detail or '断言失败'}")


# ================================================================
# 测试 1: detect_swing_points 窗口极值法 (window=3)
# ================================================================
def test_detect_swing_points():
    ctx = expect("swing检测window=3: 中心比前后各3根高/低")
    from direction_gate import detect_swing_points, SwingPoint

    # 构造: i=7是高点(max)，i=12是低点(min)，前后3根不干扰
    closes = [95, 96, 97, 98, 99, 100, 101, 110, 101, 100, 99, 98, 80, 98, 99, 100, 101, 102, 103, 104]
    pts = detect_swing_points(closes, window=3)
    check(ctx, len(pts) >= 2, f"应至少检测出2个swing点，实际={len(pts)}")
    highs = [p.price for p in pts if p.type == "high"]
    lows  = [p.price for p in pts if p.type == "low"]
    check(ctx, 110 in highs,   f"swing high=110 应被检出，实际highs={highs}")
    check(ctx, 80  in lows,    f"swing low=80  应被检出，实际lows={lows}")

    # 长度不足：len<2*window+1 → 空
    pts_short = detect_swing_points([100, 101, 100], window=3)
    check(ctx, len(pts_short) == 0, f"数据过短应返回空，实际={len(pts_short)}")

    # None/空 → 空
    check(ctx, len(detect_swing_points([], window=3)) == 0, "空输入→空")


# ================================================================
# 测试 2: _swing_point_force 方向验证 (关键物理正确性)
# ================================================================
def test_swing_point_force_directions():
    ctx = expect("swing力方向: high排斥 low吸引")
    from direction_gate import _swing_point_force

    # 1) 当前价 100，上方 swing_high = 110 (+10%)
    #   在势垒下方，势垒应产生"向下排斥" → F<0 不推向上
    F_high_above = _swing_point_force(price=100, swing_price=110, swing_type="high")
    check(ctx, F_high_above < 0, f"swing_high在上方(110>100)应向下排斥, F={F_high_above:.6f}")

    # 2) 当前价 120，下方 swing_high = 110 (-8.33%)
    #   在势垒上方，应"向上排斥" → F>0 (想把价格推离阻力位)
    F_high_below = _swing_point_force(price=120, swing_price=110, swing_type="high")
    check(ctx, F_high_below > 0, f"swing_high在下方(110<120)应向上排斥, F={F_high_below:.6f}")

    # 3) 当前价 100，下方 swing_low = 90 (-10%)
    #   在势阱上方，价格受"向下吸引" → F<0 (拉向支撑)
    F_low_below = _swing_point_force(price=100, swing_price=90, swing_type="low")
    check(ctx, F_low_below < 0, f"swing_low在下方(90<100)应向下吸引, F={F_low_below:.6f}")

    # 4) 当前价 80，上方 swing_low = 90 (+12.5%)
    #   在势阱下方，应"向上吸引" → F>0
    F_low_above = _swing_point_force(price=80, swing_price=90, swing_type="low")
    check(ctx, F_low_above > 0, f"swing_low在上方(90>80)应向上吸引, F={F_low_above:.6f}")

    # 5) 距离极远(50%+)→ 力≈0 (高斯exp衰减)
    F_far = _swing_point_force(price=100, swing_price=200, swing_type="high")
    check(ctx, abs(F_far) < 0.01, f"距离50%+力应近0, F={F_far:.6f}")

    # 6) 距离极近(0.01%)→ 力最大但方向正确（非爆炸）
    F_near = _swing_point_force(price=100.01, swing_price=100, swing_type="high")
    check(ctx, F_near > 0, f"swing_high刚好在价下, 应向上排斥, F={F_near:.6f}")


# ================================================================
# 测试 3: _compute_swing_force_field + 上下阻力分量
# ================================================================
def test_swing_force_field_components():
    ctx = expect("swing合力分量: 上方阻力 vs 下方吸引 分解")
    from direction_gate import _compute_swing_force_field, SwingPoint

    # 场景: 当前价100, 上方 swing_high 110 + 115, 下方 swing_low 90 + 85
    price = 100
    swings = [
        SwingPoint(price=110, type="high", dist_pct=(100-110)/110*100),
        SwingPoint(price=115, type="high", dist_pct=(100-115)/115*100),
        SwingPoint(price=90,  type="low",  dist_pct=(100-90)/90*100),
        SwingPoint(price=85,  type="low",  dist_pct=(100-85)/85*100),
    ]
    sf = _compute_swing_force_field(price, swings)
    check(ctx, sf.F_swing_net != 0, f"swing合力非零 F_net={sf.F_swing_net:.6f}")
    check(ctx, sf.upward_barrier  != 0, "upward_barrier 应非零 (上方阻力)")
    check(ctx, sf.downward_pull   != 0, "downward_pull  应非零 (下方吸引)")
    check(ctx, len(sf.swing_points) == 4, f"swing数量正确, {len(sf.swing_points)}")


# ================================================================
# 测试 4: DirectionGate.evaluate() 完整合力（MA+swing）偏转验证
# ================================================================
def test_evaluate_phase3_full_force():
    ctx = expect("完整evaluate: swing开启时F_net相对swing关闭时发生偏转")
    from direction_gate import DirectionGate, VelocityIntegrator

    # 构造30条收盘价，含已知 swing high/low
    base = list(range(80, 100))           # 80..99 阶梯升
    base_with_sh = base + [110, 105, 100, 98, 100, 99, 80, 85, 90, 92, 94, 96, 97, 98, 99, 100]
    closes_30 = base_with_sh[-30:]

    gate = DirectionGate(allow_short=True, use_mechanistic=True)
    vi = VelocityIntegrator()
    price = 100.0
    ma128 = 95.0     # 价格在均线上方(+5.26%)，MA弹簧向上支撑
    ma200 = 90.0

    # A) 不传 recent_closes_for_swing → 相当于 Phase2（无swing力）
    rA = gate.evaluate(
        current_price=price, daily_ma128=ma128, weekly_ma200=ma200,
        recent_daily_closes=closes_30[-3:],
        btc_short_enabled=True, velocity_integrator=vi,
    )
    F_A = rA.mechanistic_diag.get("F_net") if rA.mechanistic_diag else None

    # B) 传 recent_closes_for_swing → Phase3（MA+swing合力）
    vi.reset()
    rB = gate.evaluate(
        current_price=price, daily_ma128=ma128, weekly_ma200=ma200,
        recent_daily_closes=closes_30[-3:],
        btc_short_enabled=True, velocity_integrator=vi,
        recent_closes_for_swing=closes_30,   # Phase3 新参数
    )
    F_B = rB.mechanistic_diag.get("F_net") if rB.mechanistic_diag else None
    F_swing = rB.mechanistic_diag.get("F_swing_net") if rB.mechanistic_diag else None

    check(ctx, F_A is not None and F_B is not None, f"F_A={F_A}, F_B={F_B}")
    check(ctx, F_swing != 0, f"F_swing_net 应非零 (swing力被加入), 实际={F_swing}")
    # 关键断言: 因为closes_30含 swing_high=110(上方) & swing_low=80(下方)，
    #   所以 F_B 相较 F_A 应发生可测量的偏转
    check(ctx, abs(F_B - F_A) > 1e-6,
          f"swing开启时F_net应偏转: ΔF={abs(F_B-F_A):.6f}")

    # 向后兼容: regime结果返回格式不变
    check(ctx, rB.regime is not None, "regime字段存在")


# ================================================================
# 运行
# ================================================================
if __name__ == "__main__":
    print("\n============================================================")
    print("Phase 3 TDD —— RED (先失败)")
    print("============================================================\n")
    for fn in [test_detect_swing_points,
               test_swing_point_force_directions,
               test_swing_force_field_components,
               test_evaluate_phase3_full_force]:
        try:
            fn()
        except Exception as e:
            failed += 1
            print(f"  ❌ {fn.__name__}  异常: {type(e).__name__}: {e}")
    print(f"\n结果: {passed}/{passed+failed} 通过, {failed} 失败")
    sys.exit(0 if failed == 0 else 1)
