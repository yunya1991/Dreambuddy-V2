"""
方案 C v3.0 Task 7：WinProbEngine TDD 测试（12 项）
===================================================
TDD RED 阶段：验证盈亏概率动态权重的四步计算法 + 旁路/熔断。

测试清单（共 12 项）：
  T7.01：enable=False / ctx=None → fail-open 旁路 mult=1.0
  T7.02：P17 G-2 样本不足 < 30 → 旁路 1.0，reason=bypass_samples_*
  T7.03：G-3 Brier > 0.25 → 强制旁路 24h（设置 bypass_until_ts）
  T7.04：G-3 24h 冷却期内，Brier 就算降低也继续旁路；过期后恢复
  T7.05：四步精确：sample_count=50, pred_win_rate=0.70, Brier=0.10
         → mult = 1 + 1.0 * (0.70-0.5) * 2 = 1.40 → clip 到 1.20
  T7.06：四步精确：pred_win_rate=0.30 → mult = 1 + 1.0*(-0.20)*2 = 0.60 → clip 到 0.80
  T7.07：四步精确：pred_win_rate=0.55 → mult=1 + 1.0*(0.05)*2 = 1.10（在 [0.80,1.20] 内，不 clip）
  T7.08：knn_topk 模式：Σ sim·win / Σ sim 计算 pred_win_rate
         例：(0.9,True),(0.7,False),(0.5,True)
         → (0.9*1 + 0.7*0 + 0.5*1)/(0.9+0.7+0.5) = 1.4/2.1 = 0.666...
  T7.09：knn_topk 空列表 → 旁路 mult=1.0，reason=bypass_no_knn
  T7.10：pred_win_rate 越界 clip（-0.3→0；1.5→1.0），避免极端乘法
  T7.11：异常 q_vec 触发 fail-open → mult=1.0，reason=fail_open:*
  T7.12：Σ=0 的 knn_topk（所有 sim=0）→ 退化 pred_win_rate=0.5, mult=1.0
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


# ============================================================
# Fixtures
# ============================================================
@pytest.fixture
def wp_enabled():
    from scripts.memory_l4.winprob_engine import WinProbEngine
    w = WinProbEngine(enable=True)
    # 重置 Brier 旁路时间
    w._brier_force_bypass_until_ts = 0.0
    return w


# ============================================================
# T7.01：ctx=None → 样本数=0 < 30 → bypass_samples
# ============================================================
def test_t7_01_none_qvec_bypass(wp_enabled):
    """q_vec=None → sample_count=0 → G-2 旁路，mult=1.0"""
    mult, sh = wp_enabled.get_multiplier(None)
    assert abs(mult - 1.0) < 1e-9
    assert "bypass_samples" in sh.get("reason", "")


# ============================================================
# T7.02：样本数 < 30 → 旁路
# ============================================================
def test_t7_02_sample_count_lt_30_bypass(wp_enabled):
    """sample_count=29 < 30 → 旁路；sample_count=30 → 放行"""
    from scripts.memory_l4 import phase_c_constants as C
    # 29 条 → 旁路
    mult, sh = wp_enabled.get_multiplier({
        "sample_count": C.WINPROB_G2_MIN_SAMPLES - 1,  # 29
        "pred_win_rate": 0.90,
        "brier_score": 0.10,
    })
    assert abs(mult - 1.0) < 1e-9
    assert sh["reason"].startswith("bypass_samples_")
    # 30 条 → 放行（非 bypass_samples）
    mult2, sh2 = wp_enabled.get_multiplier({
        "sample_count": C.WINPROB_G2_MIN_SAMPLES,  # 30
        "pred_win_rate": 0.55,
        "brier_score": 0.10,
    })
    assert "bypass_samples" not in sh2["reason"], (
        f"sample=30 应放行，reason={sh2['reason']}"
    )


# ============================================================
# T7.03：Brier > 0.25 → 强制旁路 24h
# ============================================================
def test_t7_03_brier_gt_025_force_bypass_24h(wp_enabled):
    """Brier=0.26 > 0.25 → 设置 _brier_force_bypass_until_ts 并旁路本次"""
    mult, sh = wp_enabled.get_multiplier({
        "sample_count": 50,
        "pred_win_rate": 0.80,  # 就算预测极好也不生效
        "brier_score": 0.26,  # > G3_MAX_BRIER=0.25
    })
    # 本次调用已经旁路
    assert abs(mult - 1.0) < 1e-9
    assert sh["reason"].startswith("bypass_brier_gt_025_remain_")
    # 时间戳已经被设置为未来 24h
    assert wp_enabled._brier_force_bypass_until_ts > time.time() + 86400 - 10


# ============================================================
# T7.04：24h 冷却期内一直旁路；过期后恢复
# ============================================================
def test_t7_04_bypass_24h_period_then_recover(wp_enabled):
    from scripts.memory_l4 import phase_c_constants as C
    # 先触发一次 Brier 超阈值，进入 24h 旁路
    wp_enabled.get_multiplier({
        "sample_count": 50, "pred_win_rate": 0.55, "brier_score": 0.30,
    })
    # 立刻第二次调用：哪怕 Brier=0.00（完美）也还是旁路
    mult, sh = wp_enabled.get_multiplier({
        "sample_count": 50, "pred_win_rate": 0.60, "brier_score": 0.00,
    })
    assert abs(mult - 1.0) < 1e-9
    assert sh["reason"].startswith("bypass_brier_gt_025_remain_")
    # 手动把 bypass_until_ts 拨到过去（模拟 24h 到期）
    wp_enabled._brier_force_bypass_until_ts = time.time() - 1
    mult2, sh2 = wp_enabled.get_multiplier({
        "sample_count": 50, "pred_win_rate": 0.60, "brier_score": 0.10,
    })
    # 现在应该 applied，结果 = 1.20（因为 (0.60-0.5)*2=0.20 → 1.20 刚好 clip 顶）
    assert sh2["reason"] == "applied"
    # pred_win_rate=0.60 → raw_mult=1+1*(0.10)*2=1.20 → clip [0.80,1.20] → 1.20
    assert abs(mult2 - C.WINPROB_MULT_HIGH) < 1e-5


# ============================================================
# T7.05：pred_win_rate=0.70 → raw=1.40 → clip 到 1.20
# ============================================================
def test_t7_05_pred_070_clip_high(wp_enabled):
    from scripts.memory_l4 import phase_c_constants as C
    mult, sh = wp_enabled.get_multiplier({
        "sample_count": 100,
        "pred_win_rate": 0.70,
        "brier_score": 0.10,
    })
    assert sh["reason"] == "applied"
    assert abs(mult - C.WINPROB_MULT_HIGH) < 1e-6, (
        f"mult={mult:.6f} != {C.WINPROB_MULT_HIGH}"
    )
    assert abs(sh["final_winprob_mult"] - C.WINPROB_MULT_HIGH) < 1e-6


# ============================================================
# T7.06：pred_win_rate=0.30 → raw=0.60 → clip 到 0.80
# ============================================================
def test_t7_06_pred_030_clip_low(wp_enabled):
    from scripts.memory_l4 import phase_c_constants as C
    mult, sh = wp_enabled.get_multiplier({
        "sample_count": 100,
        "pred_win_rate": 0.30,
        "brier_score": 0.10,
    })
    assert sh["reason"] == "applied"
    assert abs(mult - C.WINPROB_MULT_LOW) < 1e-6, (
        f"mult={mult:.6f} != {C.WINPROB_MULT_LOW}"
    )


# ============================================================
# T7.07：pred_win_rate=0.55 → raw=1.10（不 clip）
# ============================================================
def test_t7_07_pred_055_mid_no_clip(wp_enabled):
    """pred_win_rate=0.55 → mult = 1 + 1.0*(0.05)*2 = 1.10 ∈ [0.80,1.20]"""
    mult, sh = wp_enabled.get_multiplier({
        "sample_count": 50,
        "pred_win_rate": 0.55,
        "brier_score": 0.10,
    })
    assert sh["reason"] == "applied"
    assert abs(mult - 1.10) < 1e-6


# ============================================================
# T7.08：knn_topk 模式计算 Σ sim·win / Σ sim
# ============================================================
def test_t7_08_knn_topk_weighted_win_rate(wp_enabled):
    """
    topk = [(0.9, True), (0.7, False), (0.5, True)]
    num = 0.9*1 + 0.7*0 + 0.5*1 = 1.4
    den = 0.9+0.7+0.5 = 2.1
    pred_win_rate = 1.4/2.1 = 0.666666...
    → raw_mult = 1 + 1*(0.166666)*2 = 1.333 → clip 到 1.20
    """
    from scripts.memory_l4 import phase_c_constants as C
    topk = [(0.9, True), (0.7, False), (0.5, True)]
    mult, sh = wp_enabled.get_multiplier({
        "sample_count": 50,
        "brier_score": 0.10,
        "knn_topk": topk,
    })
    # 不直接传 pred_win_rate → 内部用 knn_topk 计算
    expected_pwr = 1.4 / 2.1
    assert abs(sh["pred_win_rate"] - expected_pwr) < 1e-5, (
        f"pred_win_rate={sh['pred_win_rate']:.6f} expected={expected_pwr:.6f}"
    )
    assert sh["reason"] == "applied"
    # raw_mult = 1 + 1*(1.4/2.1 - 0.5)*2 = 1 + 2*(1.4/2.1 - 0.5)
    raw = 1.0 + 2.0 * (1.4/2.1 - 0.5)  # ≈ 1.333
    assert raw > C.WINPROB_MULT_HIGH  # 超过上限
    assert abs(mult - C.WINPROB_MULT_HIGH) < 1e-5  # 被 clip 到 1.20


# ============================================================
# T7.09：knn_topk 空列表 → bypass_no_knn
# ============================================================
def test_t7_09_knn_empty_bypass(wp_enabled):
    """sample_count≥30 但 knn_topk=[] 且不传 pred_win_rate → bypass"""
    mult, sh = wp_enabled.get_multiplier({
        "sample_count": 50,
        "brier_score": 0.10,
        "knn_topk": [],
    })
    assert abs(mult - 1.0) < 1e-9
    assert sh["reason"] == "bypass_no_knn"


# ============================================================
# T7.10：pred_win_rate 越界 clip
# ============================================================
def test_t7_10_pred_win_rate_out_of_bounds_clip(wp_enabled):
    """pred_win_rate=-0.3 → 0；pred_win_rate=1.5 → 1.0"""
    # 负胜率：clip 到 0 → mult = 1 + 1*(0-0.5)*2 = 0 → clip 到 0.80
    from scripts.memory_l4 import phase_c_constants as C
    mult, sh = wp_enabled.get_multiplier({
        "sample_count": 50, "pred_win_rate": -0.30, "brier_score": 0.10,
    })
    assert abs(sh["pred_win_rate"] - 0.0) < 1e-9
    assert abs(mult - C.WINPROB_MULT_LOW) < 1e-6
    # 胜率>1：clip 到 1.0 → raw = 1 + 1*(0.5)*2 = 2.0 → clip 到 1.20
    mult2, sh2 = wp_enabled.get_multiplier({
        "sample_count": 50, "pred_win_rate": 1.50, "brier_score": 0.10,
    })
    assert abs(sh2["pred_win_rate"] - 1.0) < 1e-9
    assert abs(mult2 - C.WINPROB_MULT_HIGH) < 1e-6


# ============================================================
# T7.11：异常 fail-open
# ============================================================
def test_t7_11_exception_failopen(wp_enabled):
    """q_vec 中 sample_count 传入不可 int 字符串 → ValueError → fail-open 1.0"""
    mult, sh = wp_enabled.get_multiplier({
        "sample_count": "not_an_int",
        "pred_win_rate": 0.60,
        "brier_score": 0.10,
    })
    assert abs(mult - 1.0) < 1e-9
    assert str(sh.get("reason", "")).startswith("fail_open:")


# ============================================================
# T7.12：knn_topk Σ similarity = 0 → 退化到 0.5，mult=1.0
# ============================================================
def test_t7_12_knn_sum_zero_degrade(wp_enabled):
    """topk = [(0, True), (0, False)] → den=0 → pred_win_rate=0.5 → mult=1.0"""
    topk = [(0.0, True), (0.0, False)]
    mult, sh = wp_enabled.get_multiplier({
        "sample_count": 50,
        "brier_score": 0.10,
        "knn_topk": topk,
    })
    assert abs(sh["pred_win_rate"] - 0.5) < 1e-9
    # den=0 时走旁路逻辑？代码里返回 1.0（bypass_no_knn？或者 applied 但 raw=1.0）
    # 按代码：num=0, den=0 → pred_win_rate = 0.5；然后 raw_mult = 1 + 1*(0.5-0.5)*2 = 1.0
    assert abs(mult - 1.0) < 1e-9
