"""
方案 C v3.0 Task 5：ElasticGate3L TDD 测试（12 项）
=================================================
TDD RED 阶段：验证弹性放行矩阵的 Score 共识 + F1~F4 铁则。

测试清单（共 12 项）：
  T5.01：异常/不完整输入 → fail-open base_mult=0.10
  T5.02：独立评分映射（P1 3档 + Elder 5档 + Score_B clip）
  T5.03：加权共识（默认 45:30:25）验证 Σ 权重归一化
  T5.04：三段式 base_pos_mult 映射区间（<0.20 / 0.20~0.70 / ≥0.70）
  T5.05：F1 永不 BLOCK：最终 final ≥ 0.05（铁则底线）
  T5.06：F2 P1 BLOCK 硬上限：P1=BLOCK → final ≤ 0.10（即使全满）
  T5.07：F3 Elder=DIVERGE_SEVERE → final × 0.70 折扣
  T5.08：F4 CBR 基线家族命中（sim≥0.80）→ final × 1.20 红利
  T5.09：F4 不触发（sim<0.80 或 top1 非家族）→ 不乘 1.20
  T5.10：全局 final_pos_mult clip ∈ [0.05, 1.50]
  T5.11：R-07 BTC/COIN 今早信号回放 → final 合理范围
  T5.12：未知档位兜底 / Score_B 越界 clip / 权重和为 0 旁路
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


# ============================================================
# Fixture
# ============================================================
@pytest.fixture
def gate_enabled():
    from scripts.memory_l4.elastic_gate_3l import ElasticGate3L
    return ElasticGate3L(enable=True)


@pytest.fixture
def cold_weights_dict():
    """默认冷启动权重 45:30:25（dict 形式）"""
    return {"w_p": 0.45, "w_e": 0.30, "w_b": 0.25}


# ============================================================
# T5.01：fail-open 返回 0.10
# ============================================================
def test_t5_01_failopen_base_mult_010(gate_enabled, cold_weights_dict):
    """异常输入触发 fail-open → base_mult = FAILOPEN_ELASTIC_MULT = 0.10"""
    # 构造一个触发异常的输入：score_b 传入字符串且不可 float()
    with pytest.raises(Exception):
        float(None)  # 验证 None 不能转 float
    # 直接让内部 weights=None，但用了异常参数 — 换个方式：手工构造异常
    # 方法：把 score_b 设为 NaN 字符串，内部 float(score_b) 不报错（float('nan')合法）
    # 所以用更直接的方式：传入 weights 为不可 getattr 也不可 isinstance dict 的奇怪对象
    class Weird:
        pass
    # 验证 compute 本身 fail-open：直接传一个会导致内部 getattr 抛出异常的对象
    from scripts.memory_l4.elastic_gate_3l import ElasticGate3L
    # 替换权重提取逻辑以触发异常 — 换思路，直接传非法参数组合
    # 更简单：enable=False 时也走正常路径，fail-open 只在 Exception 时触发
    # 所以我们用 monkey patch 模拟一个异常
    import scripts.memory_l4.elastic_gate_3l as eg_mod
    orig = eg_mod.ElasticGate3L._score_p1
    def _boom(self, p1_out):
        raise RuntimeError("BOOM")
    eg_mod.ElasticGate3L._score_p1 = _boom
    try:
        out = gate_enabled.compute(
            p1_out="STANDARD", elder_grade="NEUTRAL", score_b=0.65,
            weights=cold_weights_dict,
        )
        from scripts.memory_l4 import phase_c_constants as C
        assert abs(out.base_pos_mult - C.FAILOPEN_ELASTIC_MULT) < 1e-9
        assert out.source.startswith("fail_open:")
    finally:
        eg_mod.ElasticGate3L._score_p1 = orig


# ============================================================
# T5.02：独立评分映射
# ============================================================
def test_t5_02_independent_scores(gate_enabled):
    """P1 3档、Elder 5档、Score_B clip 精确映射"""
    # P1 档位
    assert abs(gate_enabled._score_p1("STANDARD") - 1.00) < 1e-9
    assert abs(gate_enabled._score_p1("WEAK") - 0.60) < 1e-9
    assert abs(gate_enabled._score_p1("BLOCK") - 0.10) < 1e-9
    # 未知 P1 → 默认 0.60（WEAK 等价）
    assert abs(gate_enabled._score_p1("UNKNOWN") - 0.60) < 1e-9

    # Elder 五级
    assert abs(gate_enabled._score_elder("ALIGN_FULL") - 1.00) < 1e-9
    assert abs(gate_enabled._score_elder("ALIGN_BASIC") - 0.85) < 1e-9
    assert abs(gate_enabled._score_elder("NEUTRAL") - 0.65) < 1e-9
    assert abs(gate_enabled._score_elder("DIVERGE_BASIC") - 0.45) < 1e-9
    assert abs(gate_enabled._score_elder("DIVERGE_SEVERE") - 0.30) < 1e-9
    # 未知 Elder → 默认 0.65
    assert abs(gate_enabled._score_elder("XXX") - 0.65) < 1e-9


# ============================================================
# T5.03：加权共识（默认冷启动权重）
# ============================================================
def test_t5_03_consensus_weights_45_30_25(gate_enabled, cold_weights_dict):
    """
    标准共识：SP=1.00, SE=0.85, SB=0.80
    Consensus = 0.45×1.00 + 0.30×0.85 + 0.25×0.80
              = 0.45 + 0.255 + 0.20 = 0.905
    """
    out = gate_enabled.compute(
        p1_out="STANDARD", elder_grade="ALIGN_BASIC", score_b=0.80,
        weights=cold_weights_dict,
    )
    assert abs(out.score_p - 1.00) < 1e-9
    assert abs(out.score_e - 0.85) < 1e-9
    assert abs(out.score_b - 0.80) < 1e-9
    expected_cons = 0.45*1.00 + 0.30*0.85 + 0.25*0.80
    assert abs(out.score_consensus - expected_cons) < 1e-9, (
        f"consensus={out.score_consensus:.6f} expected={expected_cons:.6f}"
    )


# ============================================================
# T5.04：三段式 base_pos_mult 映射
# ============================================================
def test_t5_04_base_mapping_three_segments(gate_enabled):
    """
    三段式：
      s < 0.20          → 0.05
      0.20 ≤ s < 0.70   → 线性 0.05 ~ 0.85（s=0.20→0.05, s=0.70→0.85）
      s ≥ 0.70          → 线性 0.85 ~ 1.50（s=0.70→0.85, s=1.0→1.50）
    """
    _map = gate_enabled._consensus_to_base
    # 段一：紧贴 0.05 底
    assert abs(_map(0.00) - 0.05) < 1e-9
    assert abs(_map(0.10) - 0.05) < 1e-9
    assert abs(_map(0.199) - 0.05) < 1e-3

    # 段二：中点 s=0.45 → (0.45-0.20)/0.50 = 0.5 → 0.05 + 0.80*0.5 = 0.45
    assert abs(_map(0.45) - 0.45) < 1e-3, f"0.45 -> {_map(0.45):.4f}"
    # 段二左边界 s=0.20 → 0.05
    assert abs(_map(0.20) - 0.05) < 1e-3
    # 段二右边界 s=0.70 → 0.85
    assert abs(_map(0.70) - 0.85) < 1e-3, f"0.70 -> {_map(0.70):.4f}"

    # 段三：s=1.0 → 1.50
    assert abs(_map(1.0) - 1.50) < 1e-3, f"1.0 -> {_map(1.0):.4f}"
    # 段三中点 s=0.85 → (0.85-0.70)/0.30=0.5 → 0.85 + 0.65*0.5 = 1.175
    assert abs(_map(0.85) - 1.175) < 1e-3, f"0.85 -> {_map(0.85):.4f}"


# ============================================================
# F1~F4 铁则：需要在 ElasticGate3L 增加 apply_fuses(final_pos_mult) 接口
# ============================================================

# ---------- F1: 永不 BLOCK ----------
def test_t5_05_f1_never_block_floor(gate_enabled):
    """即使极端反信，apply_fuses 输出 ≥ F1_NEVER_BLOCK_FLOOR = 0.05"""
    from scripts.memory_l4 import phase_c_constants as C
    # 构造极端输入：base=0.02（假想低于底线），无任何正向 fuse
    final = gate_enabled.apply_fuses(
        base_pos_mult=0.02,
        p1_out="BLOCK",
        elder_grade="DIVERGE_SEVERE",
        f4_hit=False, f4_similarity=0.0,
    )
    assert final >= C.F1_NEVER_BLOCK_FLOOR - 1e-9, (
        f"final={final:.9f} < floor={C.F1_NEVER_BLOCK_FLOOR}"
    )


# ---------- F2: P1 BLOCK 硬上限 ----------
def test_t5_06_f2_p1_block_cap(gate_enabled):
    """P1=BLOCK → final ≤ F2_P1_BLOCK_CAP_DEFAULT = 0.10（即使 base=1.50 全满）"""
    from scripts.memory_l4 import phase_c_constants as C
    final = gate_enabled.apply_fuses(
        base_pos_mult=1.50,  # 理论最大 base
        p1_out="BLOCK",
        elder_grade="ALIGN_FULL",
        f4_hit=True, f4_similarity=0.90,
    )
    assert final <= C.F2_P1_BLOCK_CAP_DEFAULT + 1e-9, (
        f"final={final:.9f} > cap={C.F2_P1_BLOCK_CAP_DEFAULT}"
    )


# ---------- F3: Elder DIVERGE_SEVERE 0.70 折扣 ----------
def test_t5_07_f3_diverge_severe_discount(gate_enabled):
    """
    Elder=DIVERGE_SEVERE → base × 0.70
    对比测试：相同 base，Elder=ALIGN_FULL vs DIVERGE_SEVERE
    """
    from scripts.memory_l4 import phase_c_constants as C
    base = 0.80
    # 对照组：Elder 非严重反信，无 F2/F4 作用
    ctrl = gate_enabled.apply_fuses(
        base_pos_mult=base,
        p1_out="STANDARD",
        elder_grade="ALIGN_FULL",
        f4_hit=False, f4_similarity=0.0,
    )
    # F3 组：严重反信
    case = gate_enabled.apply_fuses(
        base_pos_mult=base,
        p1_out="STANDARD",
        elder_grade="DIVERGE_SEVERE",
        f4_hit=False, f4_similarity=0.0,
    )
    # 对照应该就是 base（clip 后），case 应该 = base×0.70
    assert abs(case - ctrl * C.F3_DIVERGE_SEVERE_MULT) < 1e-9, (
        f"case={case:.6f} != ctrl*{C.F3_DIVERGE_SEVERE_MULT}"
    )
    assert abs(ctrl - base) < 1e-9  # 对照无折扣


# ---------- F4: CBR 基线家族 1.20 红利 ----------
def test_t5_08_f4_baseline_bonus(gate_enabled):
    """
    F4 命中：f4_hit=True 且 similarity ≥ F4_BASELINE_SIM_THRESHOLD=0.80
    → × 1.20
    """
    from scripts.memory_l4 import phase_c_constants as C
    base = 0.60
    ctrl = gate_enabled.apply_fuses(
        base_pos_mult=base,
        p1_out="STANDARD", elder_grade="NEUTRAL",
        f4_hit=False, f4_similarity=0.0,
    )
    case = gate_enabled.apply_fuses(
        base_pos_mult=base,
        p1_out="STANDARD", elder_grade="NEUTRAL",
        f4_hit=True, f4_similarity=0.80,  # 刚好门槛
    )
    assert abs(case - ctrl * C.F4_BASELINE_BONUS_MULT) < 1e-5, (
        f"case={case:.6f} != ctrl×{C.F4_BASELINE_BONUS_MULT}={ctrl*C.F4_BASELINE_BONUS_MULT:.6f}"
    )


# ---------- F4 不触发 ----------
def test_t5_09_f4_not_triggered(gate_enabled):
    """
    F4 不触发的两种情况：
    ① f4_hit=False（top1 不是家族），即使 sim=0.95
    ② f4_hit=True，但 sim<0.80（例如 sim=0.75）
    """
    base = 0.75
    # 基准：无 fuse
    base_final = gate_enabled.apply_fuses(
        base_pos_mult=base, p1_out="STANDARD", elder_grade="NEUTRAL",
        f4_hit=False, f4_similarity=0.0,
    )
    # 情况①：top1 非家族
    no_hit = gate_enabled.apply_fuses(
        base_pos_mult=base, p1_out="STANDARD", elder_grade="NEUTRAL",
        f4_hit=False, f4_similarity=0.95,
    )
    # 情况②：家族命中但相似度不够
    low_sim = gate_enabled.apply_fuses(
        base_pos_mult=base, p1_out="STANDARD", elder_grade="NEUTRAL",
        f4_hit=True, f4_similarity=0.75,
    )
    assert abs(no_hit - base_final) < 1e-9, "① f4_hit=False 不应触发红利"
    assert abs(low_sim - base_final) < 1e-9, "② sim<0.80 不应触发红利"


# ---------- 全局 clip ----------
def test_t5_10_global_clip_bounds(gate_enabled):
    """
    极端情况：F4 叠加 Elder 全满 → 可能超过 1.50，需 clip 到 1.50
    极端负向：F2+F3 叠加 → 可能破 0.05，需 clip 到 0.05
    """
    from scripts.memory_l4 import phase_c_constants as C
    # 极端正向：base=1.50 + F4=1.20 → 理论 1.80 → clip 到 1.50
    high = gate_enabled.apply_fuses(
        base_pos_mult=1.50, p1_out="STANDARD", elder_grade="ALIGN_FULL",
        f4_hit=True, f4_similarity=0.90,
    )
    assert high <= C.FINAL_POS_MULT_CLIP_HIGH_DEFAULT + 1e-9
    # 极端负向：P1=BLOCK（F2≤0.10） + Elder DIVERGE_SEVERE（×0.70）→ 0.07 不低于 0.05
    low = gate_enabled.apply_fuses(
        base_pos_mult=1.0, p1_out="BLOCK", elder_grade="DIVERGE_SEVERE",
        f4_hit=False, f4_similarity=0.0,
    )
    assert low >= C.FINAL_POS_MULT_CLIP_LOW - 1e-9


# ---------- R-07 BTC/COIN 回放 ----------
def test_t5_11_r07_btc_coin_this_morning(gate_enabled, cold_weights_dict):
    """
    R-07 验收：BTC/COIN 今早信号的弹性放行矩阵
    实际场景：
      BTC：P1=WEAK（弱共振放宽后），Elder=ALIGN_BASIC（Elder-ray 中周期微反信），
           Score_B=0.82（BCRM 单笔置信 0.7955 + 连续性 ALIGN_BASIC）
      COIN：P1=STANDARD（COIN 路由 BTC 趋势，不看美股大盘），Elder=NEUTRAL，
            Score_B=0.90（单笔置信 0.95）
    预期：两个币种 final_pos_mult ≥ 0.30（允许小仓），BTC < COIN
    """
    # BTC 场景
    btc = gate_enabled.compute_with_fuses(
        p1_out="WEAK", elder_grade="ALIGN_BASIC", score_b=0.82,
        weights=cold_weights_dict,
        f4_hit=False, f4_similarity=0.0,
    )
    # COIN 场景
    coin = gate_enabled.compute_with_fuses(
        p1_out="STANDARD", elder_grade="NEUTRAL", score_b=0.90,
        weights=cold_weights_dict,
        f4_hit=False, f4_similarity=0.0,
    )
    # 两个都 ≥ 0.30（小仓放行）
    assert btc >= 0.30, f"BTC final={btc:.4f} < 0.30"
    assert coin >= 0.30, f"COIN final={coin:.4f} < 0.30"
    # BTC 因为 P1=WEAK，所以应该比 COIN 小
    assert btc < coin, (
        f"BTC({btc:.4f}) 应 < COIN({coin:.4f})，因为 P1 WEAK < STANDARD"
    )


# ---------- T5.12：边界兜底 ----------
def test_t5_12_edge_cases(gate_enabled, cold_weights_dict):
    """Score_B 越界 clip、未知档位默认、权重和=0 旁路"""
    # Score_B 越界：2.5 → clip 到 1.0；-0.3 → clip 到 0.0
    out_high = gate_enabled.compute(
        p1_out="STANDARD", elder_grade="NEUTRAL", score_b=2.5,
        weights=cold_weights_dict,
    )
    out_low = gate_enabled.compute(
        p1_out="STANDARD", elder_grade="NEUTRAL", score_b=-0.3,
        weights=cold_weights_dict,
    )
    assert abs(out_high.score_b - 1.0) < 1e-9
    assert abs(out_low.score_b - 0.0) < 1e-9

    # 未知 P1 和 Elder → 默认兜底值
    out_unknown = gate_enabled.compute(
        p1_out="FOO_BAR", elder_grade="BAZ_QUX", score_b=0.5,
        weights=cold_weights_dict,
    )
    # 未知 P1 默认 0.60，未知 Elder 默认 0.65
    assert abs(out_unknown.score_p - 0.60) < 1e-9
    assert abs(out_unknown.score_e - 0.65) < 1e-9

    # 权重和为 0 → 旁路归一化（w_sum = 1.0），结果不会 NaN
    zero_w = {"w_p": 0.0, "w_e": 0.0, "w_b": 0.0}
    out_zero = gate_enabled.compute(
        p1_out="STANDARD", elder_grade="NEUTRAL", score_b=0.7,
        weights=zero_w,
    )
    import math
    assert math.isfinite(out_zero.score_consensus)
    assert math.isfinite(out_zero.base_pos_mult)
