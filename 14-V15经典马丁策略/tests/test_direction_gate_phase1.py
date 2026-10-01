#!/usr/bin/env python3
"""
DirectionGate Phase 1 力学化改造 — TDD 测试集

先运行所有测试，验证全部失败（RED阶段），再逐一实现使其通过。
"""
from __future__ import annotations

import sys
from pathlib import Path
from dataclasses import dataclass

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE / "lib"))

# ===================================================================
# 测试辅助：极简断言框架
# ===================================================================
_results = []

def expect(name):
    ctx = {"name": name, "passed": True, "error": None}
    _results.append(ctx)
    return ctx

def check(ctx, cond, msg=""):
    if not cond:
        ctx["passed"] = False
        ctx["error"] = msg or "断言失败"

def report():
    total = len(_results)
    passed = sum(1 for r in _results if r["passed"])
    failed = total - passed
    print(f"\n{'='*60}")
    print(f"测试结果: {passed}/{total} 通过, {failed} 失败")
    print(f"{'='*60}")
    for r in _results:
        icon = "✅" if r["passed"] else "❌"
        line = f"{icon}  {r['name']}"
        if not r["passed"]:
            line += f"  ← {r['error']}"
        print(line)
    print()
    return failed == 0

def approx(a, b, eps=1e-4):
    return abs(a - b) < eps

# ===================================================================
# 测试 1: 弹簧力方向正确性 —— 价格高于均线 → 力向下(被拉回)
# ===================================================================
def test_spring_force_direction():
    ctx = expect("弹簧力方向：价格高于均线，力向下")
    from direction_gate import _ma_spring_force
    price = 110.0
    ma = 100.0
    F = _ma_spring_force(price, ma, spring_k=2.0)
    # price > ma，偏离为正，弹簧应该"拉回" → F<0（向下）
    check(ctx, F < 0, f"F={F:.4f} 应为负数(向下拉回)")
    check(ctx, approx(F, -0.2, eps=0.01),
          f"F={F:.4f}, 期望≈-0.2 (= -2 × 0.1)")

# ===================================================================
# 测试 2: 弹簧力方向 —— 价格低于均线 → 力向上(被拉回)
# ===================================================================
def test_spring_force_upward():
    ctx = expect("弹簧力方向：价格低于均线，力向上")
    from direction_gate import _ma_spring_force
    price = 90.0
    ma = 100.0
    F = _ma_spring_force(price, ma, spring_k=2.0)
    check(ctx, F > 0, f"F={F:.4f} 应为正数(向上拉回)")
    check(ctx, approx(F, +0.2, eps=0.01),
          f"F={F:.4f}, 期望≈+0.2")

# ===================================================================
# 测试 3: 距离权重反比 —— 离均线越近权重越大
# ===================================================================
def test_distance_weight_inverse():
    ctx = expect("距离权重：距离越近权重越大")
    from direction_gate import _distance_weight
    w_near = _distance_weight(1.0)   # 距离1%
    w_far  = _distance_weight(10.0)  # 距离10%
    check(ctx, w_near > w_far,
          f"近距离权重={w_near:.3f} 应大于远距离权重={w_far:.3f}")
    check(ctx, 0.0 < w_near <= 1.0, f"w_near={w_near:.3f} 应在(0,1]")
    check(ctx, 0.0 < w_far  <= 1.0, f"w_far={w_far:.3f} 应在(0,1]")

# ===================================================================
# 测试 4: 合力计算 —— 双均线加权求和
# ===================================================================
def test_net_force_composition():
    ctx = expect("双均线合力：加权求和")
    from direction_gate import _compute_ma_force_field
    # 场景：价格在两线之间，离MA128近(-1%)，离MA200远(+5%)
    # MA128在上方 → 阻力向下F负，MA200在下方 → 支撑向上F正
    result = _compute_ma_force_field(
        price=99.0,
        daily_ma128=100.0,  # 距离 -1%（上方，近）
        weekly_ma200=94.29, # 距离 +5%（下方，远）=(99-94.29)/94.29≈5%
        spring_k=2.0,
    )
    check(ctx, hasattr(result, "F_daily"),
          "结果对象缺少 F_daily")
    check(ctx, hasattr(result, "F_net"),
          "结果对象缺少 F_net")
    # MA128: price<ma, F>0 (向上拉回)
    check(ctx, result.F_daily > 0, f"F_daily={result.F_daily:.4f} 应为正")
    # MA200: price>ma, F<0 (向下拉回)
    check(ctx, result.F_weekly < 0, f"F_weekly={result.F_weekly:.4f} 应为负")

# ===================================================================
# 测试 5: 当前BTC场景 —— 价格在MA128下方且距MA200仅+2%，合力应向上
# 这是用户指出的核心场景：不应机械判定SHORT_ALLOWED
# ===================================================================
def test_btc_scenario_force_direction():
    ctx = expect("BTC实时场景：合力方向应为向上(支持LONG)")
    from direction_gate import _compute_ma_force_field
    result = _compute_ma_force_field(
        price=64860.0,
        daily_ma128=69317.42,   # 距离 -6.43%
        weekly_ma200=63507.25,  # 距离 +2.13%
        spring_k=2.0,
    )
    check(ctx, result.F_net > 0,
          f"F_net={result.F_net:.4f} 应为正(MA200支撑更强)，实际合力={result.F_net:.4f}")
    check(ctx, result.dominant_ma == "weekly_ma200",
          f"主导均线应为 weekly_ma200，实际={result.dominant_ma}")

# ===================================================================
# 测试 6: 速度积分器 —— 正向持续力产生向上速度
# ===================================================================
def test_velocity_integrator_upward():
    ctx = expect("速度积分：持续正力 → 正向速度累积")
    from direction_gate import VelocityIntegrator
    vi = VelocityIntegrator(decay=0.85, market_mass=1.0)
    # 连续5步正力
    for _ in range(5):
        v = vi.step(acceleration=+0.1)
    check(ctx, vi.velocity > 0.01,
          f"5步正力后速度={vi.velocity:.4f}，应>0.01")

# ===================================================================
# 测试 7: 速度积分器 —— 摩擦衰减：无外力后速度应衰减趋近0
# ===================================================================
def test_velocity_decay():
    ctx = expect("摩擦衰减：无外力时速度指数衰减")
    from direction_gate import VelocityIntegrator
    vi = VelocityIntegrator(decay=0.85, market_mass=1.0)
    # 先加速
    vi.velocity = 0.1
    v0 = vi.velocity
    # 3步无外力
    for _ in range(3):
        v = vi.step(acceleration=0.0)
    check(ctx, vi.velocity < v0,
          f"3步无外力: 速度{v0:.4f}→{vi.velocity:.4f}，应衰减")
    check(ctx, vi.velocity > 0, "速度不应变负（摩擦不改变方向）")

# ===================================================================
# 测试 8: 速度 → 形态映射（向后兼容 MarketRegime）
# ===================================================================
def test_velocity_to_regime_mapping():
    ctx = expect("速度映射：v>阈值→LONG_PREFERRED，<→SHORT_ALLOWED，|v|<阈值→NEAR_SUPPORT")
    from direction_gate import _velocity_to_regime, MarketRegime
    r_up = _velocity_to_regime(0.05, threshold=0.02)
    r_dn = _velocity_to_regime(-0.05, threshold=0.02)
    r_nr = _velocity_to_regime(0.005, threshold=0.02)
    check(ctx, r_up == MarketRegime.LONG_PREFERRED,
          f"v=+0.05 → {r_up}, 期望 LONG_PREFERRED")
    check(ctx, r_dn == MarketRegime.SHORT_ALLOWED,
          f"v=-0.05 → {r_dn}, 期望 SHORT_ALLOWED")
    # NEAR_SUPPORT 是新增的过渡态，但映射时应退化为 LONG_ONLY_FORCE（表示支撑区做多）
    check(ctx, r_nr in (MarketRegime.LONG_ONLY_FORCE, MarketRegime.LONG_PREFERRED),
          f"v≈0 → {r_nr}, 应映射为支撑区形态")

# ===================================================================
# 测试 9: VelocityIntegrator 状态序列化/反序列化
# ===================================================================
def test_velocity_integrator_state():
    ctx = expect("速度积分器：save/load 状态一致")
    from direction_gate import VelocityIntegrator
    vi = VelocityIntegrator(decay=0.85, market_mass=1.5, threshold=0.02)
    vi.velocity = 0.07
    vi.step_count = 42
    st = vi.save_state()
    vi2 = VelocityIntegrator.load_state(st)
    check(ctx, approx(vi2.velocity, vi.velocity), f"velocity {vi2.velocity}!={vi.velocity}")
    check(ctx, approx(vi2.decay, 0.85), "decay 错误")
    check(ctx, approx(vi2.market_mass, 1.5), "market_mass 错误")
    check(ctx, vi2.step_count == 42, f"step_count={vi2.step_count}!=42")

# ===================================================================
# 测试 10: DirectionGate.evaluate() 力学化版本 —— BTC场景不返回SHORT_ALLOWED
# 核心测试：用户指出的"BTC长期在MA128下方，但更靠近MA200支撑时，不应机械SHORT_ALLOWED"
# ===================================================================
def test_direction_gate_mechanistic_btc_scenario():
    ctx = expect("DirectionGate力学化：BTC实时场景 → 非SHORT_ALLOWED(支撑区)")
    from direction_gate import DirectionGate, MarketRegime
    gate = DirectionGate(allow_short=True, use_mechanistic=True)
    # 不传 VelocityIntegrator 触发全新的瞬时形态判断（用F_net作为velocity代理）
    r = gate.evaluate(
        current_price=64860.0,
        daily_ma128=69317.42,
        weekly_ma200=63507.25,
        recent_daily_closes=[64088.0, 64351.0, 64599.0, 64884.8, 65046.3],
        btc_short_enabled=True,  # 自举开启
    )
    # 合力>0，形态不应为 SHORT_ALLOWED
    check(ctx, hasattr(r, 'regime'), "GateResult 缺少 regime 属性")
    check(ctx, r.regime != MarketRegime.SHORT_ALLOWED,
          f"regime={r.regime}，力学化下BTC实时场景不应为SHORT_ALLOWED")
    check(ctx, hasattr(r, "mechanistic_diag"),
          "GateResult 缺失力学诊断字段 mechanistic_diag")

# ===================================================================
# 执行测试
# ===================================================================
if __name__ == "__main__":
    import traceback
    tests = [
        test_spring_force_direction,
        test_spring_force_upward,
        test_distance_weight_inverse,
        test_net_force_composition,
        test_btc_scenario_force_direction,
        test_velocity_integrator_upward,
        test_velocity_decay,
        test_velocity_to_regime_mapping,
        test_velocity_integrator_state,
        test_direction_gate_mechanistic_btc_scenario,
    ]
    for fn in tests:
        try:
            fn()
        except Exception as e:
            # 测试未通过（预期的，因为代码还没写）
            for ctx in reversed(_results):
                if ctx["name"] == fn.__doc__ or ctx["name"] in (
                    "弹簧力方向：价格高于均线，力向下",
                    "弹簧力方向：价格低于均线，力向上",
                    "距离权重：距离越近权重越大",
                    "双均线合力：加权求和",
                    "BTC实时场景：合力方向应为向上(支持LONG)",
                    "速度积分：持续正力 → 正向速度累积",
                    "摩擦衰减：无外力时速度指数衰减",
                    "速度映射：v>阈值→LONG_PREFERRED，<→SHORT_ALLOWED，|v|<阈值→NEAR_SUPPORT",
                    "速度积分器：save/load 状态一致",
                    "DirectionGate力学化：BTC实时场景 → 非SHORT_ALLOWED(支撑区)",
                ):
                    if ctx["passed"] is True and ctx["error"] is None:
                        ctx["passed"] = False
                        ctx["error"] = f"导入/运行异常: {type(e).__name__}: {e}"
                    break
    ok = report()
    sys.exit(0 if ok else 1)
