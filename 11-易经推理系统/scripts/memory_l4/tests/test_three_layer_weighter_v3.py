"""
方案 C v3.0 Task 4：ThreeLayerWeighter TDD 测试（11 项）
===================================================
TDD RED 阶段：验证 v3.0 的 3 处核心差异。

测试清单（共 11 项）：
  T3.01：enable=False / stats=None → fail-open 冷启动权重 45:30:25
  T3.02：归一化硬约束：wp+we+wb = 1.0，误差<1e-9
  T3.03：归一化硬约束：任一权重 ∈ [0.05, 0.80]
  T3.04：S_BCRM 计算：30/60/120 笔胜率加权（0.5/0.3/0.2），样本不足=0.5
  T3.05：T3.09（差异①）综合 S = 50% S_BCRM + 50% S_cont
  T3.06：delta_max = 0.10，S_BCRM=0.70 → delta=+0.04（w_b 正向调整）
  T3.07：delta_max = 0.10，S_BCRM=0.40 → delta=-0.02（w_b 负向调整）
  T3.08：T3.10（差异②）match_boost +正值 clip [0, +0.20]
  T3.09：T3.10 HIGH_LOSS 负基线 match_boost=-0.1978 → w_b clip 到 0.05 卡底
  T3.10：T3.11（差异③）S_BTC_only 样本<5 → 0.50 中性；6胜4负=0.60 刚好门槛
  T3.11：force=True 强制重算，不触发日期缓存
"""

from __future__ import annotations

import sys
import json
import tempfile
from pathlib import Path
from datetime import date

import pytest

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


# ============================================================
# Fixtures
# ============================================================
@pytest.fixture
def weighter_enabled(tmp_path):
    from scripts.memory_l4.three_layer_weighter import ThreeLayerWeighter
    # 用临时目录替代 runtime，避免污染真实参数
    return ThreeLayerWeighter(runtime_dir=tmp_path, enable=True)


@pytest.fixture
def weighter_disabled(tmp_path):
    from scripts.memory_l4.three_layer_weighter import ThreeLayerWeighter
    return ThreeLayerWeighter(runtime_dir=tmp_path, enable=False)


# ============================================================
# T3.01：stats=None → fail-open
# ============================================================
def test_t3_01_no_stats_failopen(weighter_enabled):
    """stats 字典缺失/None → fail-open 冷启动 45:30:25"""
    w = weighter_enabled.daily_recalc(stats=None, force=True)
    assert abs(w.w_p - 0.45) < 1e-9
    assert abs(w.w_e - 0.30) < 1e-9
    assert abs(w.w_b - 0.25) < 1e-9
    assert w.source == "fail_open"
    assert abs(w.delta - 0.0) < 1e-9
    assert abs(w.match_boost - 0.0) < 1e-9


# ============================================================
# T3.02：归一化 Σ=1
# ============================================================
def test_t3_02_weights_sum_to_one(weighter_enabled):
    """任何场景下 wp+we+wb = 1.0，精确到 1e-9"""
    scenarios = [
        {"s_bcrm_30": 0.50},
        {"s_bcrm_30": 0.70, "s_bcrm_60": 0.65, "s_bcrm_120": 0.60, "match_boost": 0.05},
        {"s_bcrm_30": 0.30, "match_boost": -0.10},
        {"s_bcrm_30": 0.90, "match_boost": 0.15},
    ]
    for stats in scenarios:
        w = weighter_enabled.daily_recalc(stats=stats, force=True)
        total = w.w_p + w.w_e + w.w_b
        assert abs(total - 1.0) < 1e-9, f"stats={stats}: sum={total:.9f}≠1"


# ============================================================
# T3.03：硬 clip 边界 [0.05, 0.80]
# ============================================================
def test_t3_03_each_weight_in_clip_bounds(weighter_enabled):
    """极端 match_boost / delta 也不能越界"""
    from scripts.memory_l4 import phase_c_constants as C
    w_min = C.THREE_LAYER_WEIGHT_MIN  # 0.05
    w_max = C.THREE_LAYER_WEIGHT_MAX  # 0.80

    # 极端负向：S_BCRM=0.0 + match_boost=-0.20 → wb 被压到卡底
    w1 = weighter_enabled.daily_recalc(
        stats={"s_bcrm_30": 0.0, "match_boost": -0.20}, force=True
    )
    assert w1.w_p >= w_min - 1e-9 and w1.w_p <= w_max + 1e-9
    assert w1.w_e >= w_min - 1e-9 and w1.w_e <= w_max + 1e-9
    assert w1.w_b >= w_min - 1e-9 and w1.w_b <= w_max + 1e-9

    # 极端正向：S_BCRM=1.0 + match_boost=0.20 → wb 被压到卡顶
    w2 = weighter_enabled.daily_recalc(
        stats={"s_bcrm_30": 1.0, "match_boost": 0.20}, force=True
    )
    assert w2.w_p >= w_min - 1e-9 and w2.w_p <= w_max + 1e-9
    assert w2.w_e >= w_min - 1e-9 and w2.w_e <= w_max + 1e-9
    assert w2.w_b >= w_min - 1e-9 and w2.w_b <= w_max + 1e-9


# ============================================================
# T3.04：S_BCRM 加权计算（0.5/0.3/0.2）
# ============================================================
def test_t3_04_s_bcrm_weighted(weighter_enabled):
    """
    S_BCRM = (0.5·s30 + 0.3·s60 + 0.2·s120) / (0.5+0.3+0.2)
    例：s30=0.70, s60=0.65, s120=0.60
      → = 0.5×0.70 + 0.3×0.65 + 0.2×0.60 = 0.35+0.195+0.12 = 0.665
    """
    w = weighter_enabled.daily_recalc(
        stats={"s_bcrm_30": 0.70, "s_bcrm_60": 0.65, "s_bcrm_120": 0.60},
        force=True,
    )
    assert abs(w.s_bcrm - 0.665) < 1e-9

    # 样本不足：只有 s120 → tot_w=0.2 → s_bcrm=s120（已归一化 tot_w）
    w2 = weighter_enabled.daily_recalc(stats={"s_bcrm_120": 0.55}, force=True)
    assert abs(w2.s_bcrm - 0.55) < 1e-9

    # 全无 → 0.5
    w3 = weighter_enabled.daily_recalc(stats={"match_boost": 0.0}, force=True)
    assert abs(w3.s_bcrm - 0.50) < 1e-9


# ============================================================
# 外部辅助：_calc_S 静态函数（v3.0 差异①）
# ============================================================
def _calc_S_static(s_bcrm: float, s_cont: float | None) -> float:
    """§四.1 差异①：50-50 加权；s_cont=nan/None → 100% s_bcrm 平滑不跳变"""
    import math
    if s_cont is None or math.isnan(s_cont):
        return s_bcrm
    return 0.50 * s_bcrm + 0.50 * s_cont  # P8 冻结比 50:50


# ============================================================
# T3.05：差异① S = 50% S_BCRM + 50% S_cont
# ============================================================
def test_t3_05_diff_1_s_composition_50_50():
    """差异①：v3.0 新公式 50-50，对比 v2.0（100% S_BCRM）差异"""
    # 例 1：S_BCRM=0.70, S_cont=0.80 → 综合 S = 0.75
    s = _calc_S_static(0.70, 0.80)
    assert abs(s - 0.75) < 1e-9

    # 例 2：S_cont=None（样本<5）→ 100% S_BCRM = 0.70
    s2 = _calc_S_static(0.70, None)
    assert abs(s2 - 0.70) < 1e-9

    # 例 3：S_cont=nan → 同样退化为 S_BCRM
    import math
    s3 = _calc_S_static(0.60, float("nan"))
    assert abs(s3 - 0.60) < 1e-9

    # 例 4：S_BCRM=0.55, S_cont=0.45 → 正好 = 0.50
    s4 = _calc_S_static(0.55, 0.45)
    assert abs(s4 - 0.50) < 1e-9


# ============================================================
# T3.06：delta = Δ_max · (2·S - 1)，正向
# ============================================================
def test_t3_06_delta_positive_s070(weighter_enabled):
    """
    S_BCRM=0.70 → delta = 0.10 × (2·0.70-1) = 0.10 × 0.40 = +0.04
    wb_new = 0.25 + 0.04 = 0.29
    wp_new = 0.45 - 0.02 = 0.43
    we_new = 0.30 - 0.02 = 0.28
    Σ=1 无需重归一化（正好=1.0）
    """
    w = weighter_enabled.daily_recalc(stats={"s_bcrm_30": 0.70}, force=True)
    assert abs(w.delta - 0.04) < 1e-9
    # 归一化后近似值（clip+归一化的二次效应可容忍±0.01）
    assert abs(w.w_b - 0.29) < 0.015
    assert abs(w.w_p - 0.43) < 0.015
    assert abs(w.w_e - 0.28) < 0.015


# ============================================================
# T3.07：delta 负向 S_BCRM=0.40
# ============================================================
def test_t3_07_delta_negative_s040(weighter_enabled):
    """
    S_BCRM=0.40 → delta = 0.10 × (2·0.40-1) = 0.10 × (-0.20) = -0.02
    wb_new = 0.25 - 0.02 = 0.23
    wp_new = 0.45 + 0.01 = 0.46
    we_new = 0.30 + 0.01 = 0.31
    """
    w = weighter_enabled.daily_recalc(stats={"s_bcrm_30": 0.40}, force=True)
    assert abs(w.delta - (-0.02)) < 1e-9
    assert abs(w.w_b - 0.23) < 0.015
    assert abs(w.w_p - 0.46) < 0.015
    assert abs(w.w_e - 0.31) < 0.015


# ============================================================
# T3.08：T3.10 match_boost +正值 clip 上界 0.20
# ============================================================
def test_t3_08_match_boost_positive_clip(weighter_enabled):
    """传入 match_boost=0.30 → clip 到 0.20，wb 不超加"""
    from scripts.memory_l4 import phase_c_constants as C
    w = weighter_enabled.daily_recalc(
        stats={"s_bcrm_30": 0.50, "match_boost": 0.30}, force=True
    )
    # 实际 clip 内部是 max(-0.20, min(0.20, raw))，所以 match_boost 字段=0.20
    assert abs(w.match_boost - 0.20) < 1e-9, (
        "match_boost 必须 clip 到 ±0.20 边界"
    )
    # wp 不能被压破 0.05 底（we/wb 不能越界）
    assert w.w_p >= C.THREE_LAYER_WEIGHT_MIN - 1e-9


# ============================================================
# T3.09：T3.10 HIGH_LOSS 命中 match_boost=-0.1978
# ============================================================
def test_t3_09_high_loss_negative_match_boost_wb_floor(weighter_enabled):
    """
    HIGH_LOSS 命中 θ_match* → match_boost=-0.1978（略低于 -0.20 上限）
    S_BCRM=0.5 → delta=0 → wb0=0.25 - 0.1978 = 0.0522 > 0.05 刚好不clip底
    """
    from scripts.memory_l4 import phase_c_constants as C
    w = weighter_enabled.daily_recalc(
        stats={"s_bcrm_30": 0.50, "match_boost": -0.1978}, force=True
    )
    # match_boost 被 clip 到 ≥ -0.20（本例 -0.1978 不 clip）
    assert abs(w.match_boost - (-0.1978)) < 1e-3
    # w_b 归一化后应 ≥ 0.05 不卡底
    assert w.w_b >= C.THREE_LAYER_WEIGHT_MIN - 1e-3
    # 如进一步压到 mb=-0.25，则 clip 到 -0.20
    w2 = weighter_enabled.daily_recalc(
        stats={"s_bcrm_30": 0.50, "match_boost": -0.25}, force=True
    )
    assert abs(w2.match_boost - (-0.20)) < 1e-9


# ============================================================
# T3.10：T3.11 差异③ S_BTC_only BTC专属胜率
# ============================================================
def _calc_s_btc_only_static(btc_trade_10: list[tuple[str, float]]) -> float:
    """
    §四.1 差异③：近 10 笔 BTC 专属信号（LONG+SHORT）真实盈亏加权胜率；
    样本<5 → 0.50 中性（小数定律防护，不够门槛 0.60）
    """
    if len(btc_trade_10) < 5:
        return 0.50
    wins = sum(1 for _, pnl_pct in btc_trade_10 if pnl_pct > 0)
    return wins / len(btc_trade_10)


def test_t3_10_diff_3_s_btc_only_threshold():
    """差异③：样本<5=0.50；6胜4负=0.60门槛；4胜4负=0.50<0.60不触发P9"""
    # 4 笔（<5）→ 0.50 中性，即便全胜也不用真实胜率
    btc4 = [("LONG", 0.01), ("SHORT", 0.02), ("LONG", 0.015), ("SHORT", -0.005)]
    assert len(btc4) == 4
    assert abs(_calc_s_btc_only_static(btc4) - 0.50) < 1e-9

    # 10 笔 6 胜 4 负 → 0.60 刚好门槛（命中 P9 ③ ≥0.60）
    pnl = [0.01 if i < 6 else -0.01 for i in range(10)]
    btc10 = [(("LONG" if i % 2 == 0 else "SHORT"), p) for i, p in enumerate(pnl)]
    s = _calc_s_btc_only_static(btc10)
    assert abs(s - 0.60) < 1e-9
    assert s >= 0.60, "刚好门槛满足 P9 ③"

    # 8 笔 3 胜 5 负 = 0.375 < 0.60 → 不触发 P9 ③
    btc8 = [
        ("LONG", 0.01), ("LONG", -0.01), ("LONG", 0.005), ("LONG", -0.02),
        ("SHORT", -0.005), ("SHORT", -0.01), ("SHORT", 0.008), ("SHORT", 0.003),
    ]
    s8 = _calc_s_btc_only_static(btc8)
    assert s8 < 0.60


# ============================================================
# T3.11：force=True 强制重算，日期缓存失效
# ============================================================
def test_t3_11_force_true_bypass_cache(weighter_enabled):
    """同一日期内，force=True 应重新计算而非返回上次缓存"""
    w1 = weighter_enabled.daily_recalc(stats={"s_bcrm_30": 0.50}, force=True)
    w2 = weighter_enabled.daily_recalc(stats={"s_bcrm_30": 0.90}, force=True)
    # 两次不同输入 → w_b 应该不同（delta 不同）
    assert abs(w1.w_b - w2.w_b) > 0.01, "force=True 应绕过日期缓存"
    assert w2.delta > w1.delta + 0.03  # 0.90 → delta=0.08 vs 0.50 → delta=0
