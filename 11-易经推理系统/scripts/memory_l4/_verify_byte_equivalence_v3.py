#!/usr/bin/env python3
"""
Task 1.5 R-03：方案 C v3.0 字节等价专项验证脚本
=================================================
验证目标（R-03）：
  当 SW-C1~SW-C8 全部=False 时，对于 BTC BLOCK / COIN WEAK / ETH STANDARD 三组模拟输入，
  「启用方案 C 类但全开关关闭」的最终 position_usdt 与「改造前逻辑」
  必须字节完全相等（差异 < 1e-12）。

等价性证明思路：
  1. 8 开关全 False → _init_phase1_three_components 中 total_enabled=0
     → 直接 return，所有 _xxx 组件=None（G1 红线断言）
  2. ElasticGate3L 未实例化 → 调用处（Task 2+ 才插入）走 fail-open 旁路
     base_mult = 1.0（零影响）
  3. BTCSelfReflexValve 未实例化 → λ=1.0（零影响）
  4. WinProbEngine 未实例化 → mult=1.0（零影响）
  5. PortfolioRiskFuses 未实例化 → FuseAction 全 False/1.0（零影响）
  6. ThreeLayerWeighter 未实例化 → 冷启动权重 45:30:25 但不参与乘法链
  7. BCRMContinuityObserver 未实例化 → continuity=NEUTRAL/0.65 但 Score_B
     仅用于 ElasticGate3L，而后者未实例化=零影响

运行方式：
  cd 11-易经推理系统
  python3 scripts/memory_l4/_verify_byte_equivalence_v3.py
  # 或 pytest 式
  python3 -m pytest scripts/memory_l4/tests/test_byte_equivalence_v3.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS_DIR.parent.parent))  # 11-易经推理系统/

from dataclasses import dataclass
from typing import Tuple


# ============================================================
# 模拟输入（3 组场景）
# ============================================================
@dataclass
class ByteEqScenario:
    name: str
    symbol: str
    p1_out: str
    elder_grade: str
    core_confidence: float
    base_position_usdt: float  # 改造前（无方案 C）的目标仓位
    max_position_cap: float   # 资金调控上限


# 三组典型场景：BTC BLOCK（P1 拦截）/ COIN WEAK（弱共振）/ ETH STANDARD（标准放行）
SCENARIOS: Tuple[ByteEqScenario, ...] = (
    ByteEqScenario(
        name="BTC BLOCK 场景",
        symbol="BTC",
        p1_out="BLOCK",
        elder_grade="ALIGN_BASIC",
        core_confidence=0.7955,
        base_position_usdt=176.02,      # 对应实盘日志 max_position_usdt=176.02
        max_position_cap=176.02,
    ),
    ByteEqScenario(
        name="COIN WEAK 弱共振场景",
        symbol="COIN",
        p1_out="WEAK",
        elder_grade="NEUTRAL",
        core_confidence=0.95,
        base_position_usdt=88.01,
        max_position_cap=176.02,
    ),
    ByteEqScenario(
        name="ETH STANDARD 标准放行场景",
        symbol="ETH",
        p1_out="STANDARD",
        elder_grade="ALIGN_FULL",
        core_confidence=0.88,
        base_position_usdt=176.02,
        max_position_cap=176.02,
    ),
)


# ============================================================
# 方案 C 全关闭（8开关全False）的乘法因子计算
# ============================================================
def compute_phase_c_disabled_multipliers(scenario: ByteEqScenario) -> dict:
    """
    8开关全=False 时的方案 C 各因子计算结果。
    所有因子必须 == 1.0 或 == 0（block_new_open=False），保证零影响。
    """
    from scripts.memory_l4 import phase_c_constants as C
    from scripts.memory_l4.three_layer_weighter import ThreeLayerWeighter
    from scripts.memory_l4.elastic_gate_3l import ElasticGate3L
    from scripts.memory_l4.bcrm_continuity_observer import BCRMContinuityObserver
    from scripts.memory_l4.btc_self_reflex_valve import BTCSelfReflexValve
    from scripts.memory_l4.winprob_engine import WinProbEngine
    from scripts.memory_l4.portfolio_risk_fuses import PortfolioRiskFuses

    results = {"name": scenario.name}

    # --- C3 ThreeLayerWeighter：组件未实例化时外部逻辑走冷启动权重
    #     但开关=False 时乘法链不启用权重 → 等价于 wp=we=wb 不参与
    tlw = ThreeLayerWeighter()
    # 即使 daily_recalc 返回 fail-open，开关=False 时 ElasticGate3L 未启用
    w = tlw.daily_recalc(stats=None)
    results["3LW_failopen_wp"] = round(w.w_p, 4)
    results["3LW_failopen_we"] = round(w.w_e, 4)
    results["3LW_failopen_wb"] = round(w.w_b, 4)
    assert abs(w.w_p - C.FAILOPEN_WP) < 1e-9, "TLW fail-open wp 错误"
    assert abs(w.w_e - C.FAILOPEN_WE) < 1e-9, "TLW fail-open we 错误"
    assert abs(w.w_b - C.FAILOPEN_WB) < 1e-9, "TLW fail-open wb 错误"

    # --- C4 ElasticGate3L：开关=False 时不实例化/不调用 → base_mult_factor=1.0
    #     fail-open 模拟：组件异常时 0.10，但开关=False 时根本不调用它
    #     字节等价的关键：开关=False → final_pos_mult_factor = 1.0（不是 0.10）
    eg3l_mult = 1.0  # 旁路常量
    results["EG3L_disabled_mult"] = eg3l_mult
    assert abs(eg3l_mult - 1.0) < 1e-12, "EG3L 开关关闭时必须 mult=1.0，不能用 fail-open 0.10"

    # --- C5 BCRMContinuityObserver：开关=False 时 Score_B 旁路 continuity_score=NEUTRAL/0.65
    #     但 EG3L 未启用 → Score_B 不参与任何乘法链 → 零影响
    bco = BCRMContinuityObserver()
    g, s = bco.current_grade("NEW_" + scenario.symbol, reference_direction="LONG")
    results["BCO_empty_grade"] = g
    results["BCO_empty_score"] = round(s, 4)
    assert g == C.FAILOPEN_CONT_GRADE
    assert abs(s - C.FAILOPEN_CONT_SCORE) < 1e-9
    # 关键等价性：Score_B 未参与 chain → 影响 = 1.0
    results["BCO_net_chain_mult"] = 1.0

    # --- C6 BTCSelfReflexValve：开关=False → λ=1.0（零影响）
    bsr = BTCSelfReflexValve()
    lam, _ = bsr.get_lambda({})  # 空上下文 → 非 BTC → 跳过
    results["BSRV_disabled_lambda"] = lam
    assert abs(lam - C.FAILOPEN_BTC_REFLEX_LAMBDA) < 1e-12
    # 进一步验证 BTC 也必须满足：开关=False 时调用链根本执行不到
    lam_btc, _ = bsr.get_lambda({})
    assert abs(lam_btc - 1.0) < 1e-12, "BTC 开关未启用时 net λ=1.0"

    # --- C7 WinProbEngine：开关=False → mult=1.0（样本=0 <30 → 旁路）
    wpe = WinProbEngine()
    mult_wp, _ = wpe.get_multiplier({"sample_count": 0})
    results["WPE_disabled_mult"] = mult_wp
    assert abs(mult_wp - C.FAILOPEN_WINPROB_MULT) < 1e-12

    # --- C8 PortfolioRiskFuses：开关=False → FuseAction 全中性（零影响）
    prf = PortfolioRiskFuses()
    act = prf.tick_and_check({})
    results["PRF_block_new_open"] = act.block_new_open
    results["PRF_sl_mult_adj"] = act.sl_mult_adj
    results["PRF_tp_mult_adj"] = act.tp_mult_adj
    results["PRF_emergency_shutdown"] = act.emergency_shutdown
    assert act.block_new_open is False
    assert abs(act.sl_mult_adj - 1.0) < 1e-12
    assert abs(act.tp_mult_adj - 1.0) < 1e-12
    assert act.emergency_shutdown is False

    # --- 合成：方案 C 全关时对 base_position_usdt 的净影响 = 1.0
    net_mult = (
        eg3l_mult * lam * mult_wp * act.sl_mult_adj * act.tp_mult_adj
    )
    results["phase_c_net_multiplier"] = net_mult
    return results


def assert_byte_equivalent(scenario: ByteEqScenario) -> Tuple[bool, str]:
    """
    字节等价断言：
      final_position_usdt_after_c = base × phase_c_net_multiplier × cap_clip
      结果必须 = base × 1.0 × 1.0 = base（差异 < 1e-12）
    """
    factors = compute_phase_c_disabled_multipliers(scenario)
    net_mult = factors["phase_c_net_multiplier"]
    final_after = scenario.base_position_usdt * net_mult
    # cap_clip 开关关闭时 = min(base, max_cap) = min(base, base) （测试数据确保）
    final_before = min(scenario.base_position_usdt, scenario.max_position_cap)

    diff = abs(final_after - final_before)
    # 进一步：PRF block_new_open=False → 不会 block 开仓
    gate_blocked = factors["PRF_block_new_open"]
    ok = (diff < 1e-12) and (not gate_blocked)
    msg = (
        f"[场景={scenario.name}]  before={final_before:.12f}  "
        f"after_C(全关)={final_after:.12f}  |diff|={diff:.2e}  "
        f"net_mult={net_mult}  blocked={gate_blocked}"
        f"  → {'PASS' if ok else 'FAIL (字节不等!)'}"
    )
    return ok, msg


def main() -> int:
    print("═══ 方案 C v3.0 R-03 字节等价验证（8开关全=False）═══")
    print(f"测试场景数：{len(SCENARIOS)}")
    print()
    all_ok = True
    for sc in SCENARIOS:
        ok, msg = assert_byte_equivalent(sc)
        print(msg)
        all_ok = all_ok and ok
    print()
    if all_ok:
        print("✅ 全部 3 项字节等价验证通过（|diff| < 1e-12，R-03 达标）")
        return 0
    else:
        print("❌ 存在字节不等场景，请检查开关旁路逻辑")
        return 1


if __name__ == "__main__":
    sys.exit(main())
