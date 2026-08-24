"""Phase 1 TDD 测试 · ParameterMapper 方案 A 纯连续函数映射

覆盖验收：
  T12) test_parameter_mapper_ranges_monotonic
       4 条单调性：
         • C=1.0 的 6 参数区间宽度 ≤ C=0.0 的（共识高→范围窄）
         • L=+4,T=+4 → global_position_mult 中心 ≥ 1.4
         • L=-4,T=-4 → global_position_mult 中心 ≤ 0.5
         • BTC 牛市 L=+3,T=+2 → long_threshold_mult 中心 ≤ 1.0（降低做多门槛）
  T14) test_sector_weights_sum_to_one_and_monotonic_beta
       5 板块 Σ=1；L=+3 场景 β=1.5 板块权重 ÷ β=0.5 板块权重 ≥ 1.15。
  T_IDENTITY) test_parameter_mapper_neutral_identity_passthrough
       【核心不变量·三层兼容】L=0,T=0,C=0（无偏/无共识）时：
         • 6 参数中心 == 直通默认值（mult=1.0, ls_cap=0.5, bias=0, threshold_mult=1.0）
         • 5 板块权重 == 均匀 (各 0.20)
       确保「前置层无偏 → 系统等价于直通」，不干扰 BCRM + 弹簧力场原链路。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_THIS_DIR = Path(__file__).resolve().parent
_BCRM2_ROOT = _THIS_DIR.parent
assert _BCRM2_ROOT.name == "memory_l4"
if str(_BCRM2_ROOT) not in sys.path:
    sys.path.insert(0, str(_BCRM2_ROOT))


def _stats_row(L_p10=-3.0, L_p90=+3.0, T_p10=-2.5, T_p90=+2.8) -> dict:
    """合成 1 行 stats_row（用于 ParameterMapper.map_global_parameters 的 stats 锚点）"""
    return dict(
        L_p10_60d=L_p10, L_p90_60d=L_p90,
        T_p10_60d=T_p10, T_p90_60d=T_p90,
        L_p10_252d=L_p10, L_p90_252d=L_p90,
        T_p10_252d=T_p10, T_p90_252d=T_p90,
    )


def _ranges_center(rng: tuple[float, float]) -> float:
    return 0.5 * (rng[0] + rng[1])


def _ranges_width(rng: tuple[float, float]) -> float:
    return rng[1] - rng[0]


# ================================================================
# T12) 范围映射 4 条单调性
# ================================================================
def test_parameter_mapper_ranges_monotonic():
    from bcrm2.parameter_mapper import ParameterMapper
    pm = ParameterMapper()

    # (1) C=1 → 带宽 ≤ C=0
    r_lowC = pm.map_global_parameters(L=0.0, T=0.0, C=0.0, stats_row=_stats_row())
    r_hiC = pm.map_global_parameters(L=0.0, T=0.0, C=1.0, stats_row=_stats_row())
    for k in ("global_position_mult", "ls_ratio_cap", "long_bias", "short_bias",
              "long_threshold_mult", "short_threshold_mult"):
        assert _ranges_width(r_hiC[k]) <= _ranges_width(r_lowC[k]), (
            f"{k}: C=1 带宽={_ranges_width(r_hiC[k]):.4f} > C=0 带宽={_ranges_width(r_lowC[k]):.4f}，违反"
            "「共识越高范围越窄」规则"
        )

    # (2) L=+4,T=+4 → mult 中心 ≥ 1.4
    r_bull = pm.map_global_parameters(L=4.0, T=4.0, C=0.8, stats_row=_stats_row())
    assert _ranges_center(r_bull["global_position_mult"]) >= 1.4, (
        f"L=+4,T=+4 的 global_position_mult 中心 = {_ranges_center(r_bull['global_position_mult']):.3f} < 1.4"
    )

    # (3) L=-4,T=-4 → mult 中心 ≤ 0.5
    r_bear = pm.map_global_parameters(L=-4.0, T=-4.0, C=0.8, stats_row=_stats_row())
    assert _ranges_center(r_bear["global_position_mult"]) <= 0.5, (
        f"L=-4,T=-4 的 global_position_mult 中心 = {_ranges_center(r_bear['global_position_mult']):.3f} > 0.5"
    )

    # (4) BTC 牛市 L=+3,T=+2 → long_threshold_mult 中心 ≤ 1.0（降低做多门槛）
    r_bull2 = pm.map_global_parameters(L=3.0, T=2.0, C=0.9, stats_row=_stats_row())
    assert _ranges_center(r_bull2["long_threshold_mult"]) <= 1.0, (
        f"BTC 牛市 long_threshold_mult 中心 = {_ranges_center(r_bull2['long_threshold_mult']):.3f} > 1.0"
    )
    # 熊市 L=-3,T=-2 → short_threshold_mult 中心 ≤ 1.0
    r_bear2 = pm.map_global_parameters(L=-3.0, T=-2.0, C=0.9, stats_row=_stats_row())
    assert _ranges_center(r_bear2["short_threshold_mult"]) <= 1.0, (
        f"BTC 熊市 short_threshold_mult 中心 = {_ranges_center(r_bear2['short_threshold_mult']):.3f} > 1.0"
    )


# ================================================================
# T14) 板块权重 Σ=1 & β 高权重大
# ================================================================
def test_sector_weights_sum_to_one_and_monotonic_beta():
    from bcrm2.parameter_mapper import ParameterMapper
    pm = ParameterMapper()
    # L=+3 牛市：DeFi β=1.5 α=+0.05；MEME β=0.5 α=-0.03；其他 1.0
    betas = {
        "defi": (1.5, 0.05, 0.8),
        "ai":   (1.0, 0.02, 0.75),
        "rwa":  (1.1, 0.00, 0.7),
        "meme": (0.5, -0.03, 0.6),
        "l2":   (1.0, 0.01, 0.72),
    }
    sw_result = pm.map_sector_weights(L=3.0, T=2.0, C=0.8, sector_betas=betas)
    # 兼容新结构 {weights, sector_tp_mult, sector_sl_mult} 与旧 {sector: weight}
    if isinstance(sw_result, dict) and "weights" in sw_result:
        w = sw_result["weights"]
    else:
        w = sw_result  # type: ignore[assignment]
    assert set(w.keys()) == {"defi", "ai", "rwa", "meme", "l2"}
    total = sum(w.values())
    assert abs(total - 1.0) < 1e-9, f"板块权重和 = {total:.9f} != 1.0"
    # β=1.5 的 defi 权重 ÷ β=0.5 的 meme 权重 ≥ 1.15
    ratio = w["defi"] / w["meme"]
    assert ratio >= 1.15, (
        f"L=+3 场景下 defi(β=1.5) 权重 / meme(β=0.5) 权重 = {ratio:.3f} < 1.15。"
        f" defi={w['defi']:.3f} meme={w['meme']:.3f}"
    )
    # 所有权重要么 >0（softmax 特性），确保不是硬编码
    for k, v in w.items():
        assert 0.0 < v < 1.0, f"{k} 权重 {v} 不在 (0,1) 开区间内"


# ================================================================
# T_IDENTITY) 中性直通 Identity Passthrough 【三层兼容核心不变量】
#   L=0, T=0, C=0 → 6 参数中心 == 直通默认值；5 板块权重均匀 == 0.20
#   确保「前置层无偏时，BCRM + 弹簧力场链路等价于直通」
# ================================================================
def test_parameter_mapper_neutral_identity_passthrough():
    from bcrm2.parameter_mapper import ParameterMapper
    pm = ParameterMapper()

    # --- 6 个全局范围参数：中心必须严格等于默认直通值 ---
    r_neutral = pm.map_global_parameters(L=0.0, T=0.0, C=0.0, stats_row=_stats_row())

    DEFAULTS = {
        "global_position_mult": 1.0,
        "ls_ratio_cap":         0.5,
        "long_bias":            0.0,
        "short_bias":           0.0,
        "long_threshold_mult":  1.0,
        "short_threshold_mult": 1.0,
    }
    for k, expected_center in DEFAULTS.items():
        center = _ranges_center(r_neutral[k])
        assert abs(center - expected_center) < 1e-6, (
            f"【中性直通】{k} 中心 = {center:.6f} ≠ 默认直通 {expected_center}。"
            " 前置层无偏时必须等价于 identity，否则干扰 BCRM + 弹簧力场原链路。"
        )

    # --- 5 板块权重：必须均匀 0.20 ---
    # 中性直通下，所有板块的 β/α/corr 差异都应被「共识极低」平滑为均匀分配
    betas_uniform_scan = {
        "defi": (1.5, 0.05, 0.8),     # 故意差异大
        "ai":   (1.0, 0.02, 0.75),
        "rwa":  (1.1, 0.00, 0.7),
        "meme": (0.5, -0.03, 0.6),
        "l2":   (0.9, 0.01, 0.72),
    }
    sw_result = pm.map_sector_weights(L=0.0, T=0.0, C=0.0, sector_betas=betas_uniform_scan)
    # 兼容新返回结构 {weights, sector_tp_mult, sector_sl_mult} 与旧 flat
    if isinstance(sw_result, dict) and "weights" in sw_result:
        w = sw_result["weights"]
    else:
        w = sw_result  # type: ignore[assignment]
    total = sum(w.values())
    assert abs(total - 1.0) < 1e-9
    for k, v in w.items():
        assert abs(v - 0.20) < 1e-4, (
            f"【中性直通】板块 {k} 权重 = {v:.5f} ≠ 均匀 0.20。"
            " C=0（无共识）时必须均匀分配，否则引入未知板块偏置。"
        )
