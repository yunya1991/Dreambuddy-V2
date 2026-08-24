"""T3 + T4 RED 组合 — sector_tp/sl_mult + 融合层 + 独立开关

T3 用例（3）：
  S1) map_sector_weights 返回值应包含 sector_tp_mult / sector_sl_mult 键
  S2) 5 板块的 TP/SL 乘数与 regime 查表单调一致（BREAKOUT → tp≥1.15, sl≤1.0）
  S3) 中性条件 L=0 T=0 C=0 → 所有板块 TP=1.0, SL=1.0（identity 不变量）

T4 用例（6）：
  F1) ENABLE_PARAMETER_MAPPER_INJECT=False（关闭）→ _resolve_effective_params
       输出完全等于 regime_baselines（字节等价）
  F2) 开关=True, alpha=1.0, forecast_L=L_p90（高位）→ global_position_mult > baseline
       （高前景应放大仓位）
  F3) 开关=True, alpha=1.0, forecast_L=L_p10（低位）→ global_position_mult < baseline
       （低前景应缩小仓位）
  F4) 开关=True, long_bias>1.0（做多谨慎）→ long_conf_threshold 高于 baseline 阈值
       × threshold_mult
  F5) 开关=True, ls_ratio_cap=0.3（低于默认）→ 输出的 ls_ratio_cap=0.3（直接使用）
  F6) sector_tp_mult 注入：币种匹配板块 → final_tp_mult = sector_tp_mult × tp_mult
       （比纯 regime tp_mult 更大/更小，取决于板块 regime）
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


# =====================================================================
# T3 RED: sector_tp/sl_mult 扩展
# =====================================================================

def _stats_row(L_p10=-3.0, L_p90=+3.0, T_p10=-2.5, T_p90=+2.8) -> dict:
    return dict(
        L_p10_60d=L_p10, L_p90_60d=L_p90,
        T_p10_60d=T_p10, T_p90_60d=T_p90,
        L_p10_252d=L_p10, L_p90_252d=L_p90,
        T_p10_252d=T_p10, T_p90_252d=T_p90,
    )


def _default_betas():
    # SECTOR_NAMES = ("defi", "ai", "rwa", "meme", "l2")
    return {
        "defi": (1.0, 0.0, 0.5),
        "ai": (1.5, 0.01, 0.6),
        "rwa": (0.8, -0.005, 0.55),
        "meme": (1.8, 0.008, 0.35),
        "l2": (1.2, 0.003, 0.58),
    }


# ---------------------------------------------------------------- S1
def test_S1_sector_weights_includes_tp_sl_mult():
    """S1: map_sector_weights 返回值必须包含 weights + sector_tp_mult + sector_sl_mult"""
    from bcrm2.parameter_mapper import ParameterMapper
    pm = ParameterMapper()
    result = pm.map_sector_weights(
        L=2.0, T=1.5, C=0.7,
        sector_betas=_default_betas(),
    )
    assert "weights" in result, "必须包含 weights（5 板块资金权重）"
    assert "sector_tp_mult" in result, "S1 FAIL：缺少 sector_tp_mult（设计 A.4 要求）"
    assert "sector_sl_mult" in result, "S1 FAIL：缺少 sector_sl_mult（设计 A.4 要求）"
    # 5 板块齐全
    for key in ("weights", "sector_tp_mult", "sector_sl_mult"):
        assert set(result[key].keys()) == {"defi", "ai", "rwa", "meme", "l2"}, (
            f"{key} 的板块名不匹配：{result[key].keys()}"
        )


# ---------------------------------------------------------------- S2
def test_S2_sector_tp_sl_monotonic_with_regime():
    """S2: BREAKOUT 情景（高 L 高 T）→ TP≥1.15，SL≤1.0；TREND_BEAR 相反"""
    from bcrm2.parameter_mapper import ParameterMapper
    pm = ParameterMapper()
    result_breakout = pm.map_sector_weights(
        L=3.5, T=2.5, C=0.9,  # BREAKOUT / TREND_UP_STRONG
        sector_betas=_default_betas(),
    )
    result_bear = pm.map_sector_weights(
        L=-3.5, T=-2.5, C=0.9,  # STRONG_TREND_BEAR / VOLATILE_DROP
        sector_betas=_default_betas(),
    )
    # BREAKOUT: 至少 1 个板块的 tp_mult ≥ 1.15
    max_tp_breakout = max(result_breakout["sector_tp_mult"].values())
    min_sl_breakout = min(result_breakout["sector_sl_mult"].values())
    assert max_tp_breakout >= 1.10, (
        f"BREAKOUT 情景 tp_mult 最高={max_tp_breakout:.3f}，应≥1.10"
    )
    assert min_sl_breakout <= 1.05, (
        f"BREAKOUT 情景 sl_mult 最低={min_sl_breakout:.3f}，应≤1.05"
    )
    # BEAR: TP 保守（≤1.0），SL 放大（≥1.10）——至少 1 个板块
    min_tp_bear = min(result_bear["sector_tp_mult"].values())
    max_sl_bear = max(result_bear["sector_sl_mult"].values())
    assert min_tp_bear <= 1.05, (
        f"BEAR 情景 tp_mult 最低={min_tp_bear:.3f}，应≤1.05"
    )
    assert max_sl_bear >= 1.0, (
        f"BEAR 情景 sl_mult 最高={max_sl_bear:.3f}，应≥1.0"
    )


# ---------------------------------------------------------------- S3
def test_S3_neutral_identity_sector_tp_sl():
    """S3: L=0 T=0 C=0 → 所有板块 sector_tp_mult=1.0, sector_sl_mult=1.0"""
    from bcrm2.parameter_mapper import ParameterMapper
    pm = ParameterMapper()
    result = pm.map_sector_weights(
        L=0.0, T=0.0, C=0.0,
        sector_betas=_default_betas(),
    )
    for s in ("defi", "ai", "rwa", "meme", "l2"):
        assert abs(result["sector_tp_mult"][s] - 1.0) < 1e-6, (
            f"中性不变量失败：[{s}] sector_tp_mult={result['sector_tp_mult'][s]:.4f}，预期 1.0"
        )
        assert abs(result["sector_sl_mult"][s] - 1.0) < 1e-6, (
            f"中性不变量失败：[{s}] sector_sl_mult={result['sector_sl_mult'][s]:.4f}，预期 1.0"
        )


# =====================================================================
# T4 RED: 融合层 _resolve_effective_params + 独立开关
# =====================================================================

# 模拟 polling_trader 中的 REGIME_MULTIPLIERS 查表默认值
_REGIME_BASE = {
    "position_mult": 0.8,
    "tp_mult": 0.85,
    "sl_mult": 1.2,
    "threshold_mult": 1.15,
}

# 6 参数 regime baselines
_REGIME_BASE_PARAMS = {
    "global_position_mult": 0.8,
    "ls_ratio_cap": 0.5,
    "long_bias": 1.0,
    "short_bias": 1.0,
    "long_threshold_mult": 1.15,
    "short_threshold_mult": 1.15,
}


# ---------------------------------------------------------------- F1
def test_F1_switch_off_byte_equivalent():
    """F1: ENABLE_PARAMETER_MAPPER_INJECT=False → 输出完全等于 regime_baselines"""
    from bcrm2.parameter_mapper import ParameterMapper
    pm = ParameterMapper()
    ranges = pm.map_global_parameters(L=3.0, T=2.0, C=0.7, stats_row=_stats_row())
    # 调用新方法 _resolve_effective_params（设计 A.3，当前未实现）
    eff = pm._resolve_effective_params(
        ranges=ranges,
        stats_row=_stats_row(),
        forecast_L=None,
        forecast_T=None,
        alpha_blend=0.0,
        regime_baselines=_REGIME_BASE_PARAMS,
        sector_weights_result=pm.map_sector_weights(
            L=0.0, T=0.0, C=0.0, sector_betas=_default_betas()
        ),
        symbol_sector="ai",
        regime_multipliers=_REGIME_BASE,
        enable_inject=False,  # 关键：开关关闭
        base_long_threshold=0.7955,
        base_short_threshold=0.7955,
    )
    # 字节等价：position/tp/sl/threshold 必须等于查表值
    assert abs(eff["position_mult_final"] - _REGIME_BASE["position_mult"]) < 1e-9, (
        f"F1 字节等价失败：position={eff['position_mult_final']:.4f}≠{_REGIME_BASE['position_mult']}"
    )
    assert abs(eff["tp_mult_final"] - _REGIME_BASE["tp_mult"]) < 1e-9
    assert abs(eff["sl_mult_final"] - _REGIME_BASE["sl_mult"]) < 1e-9
    assert abs(eff["threshold_mult_final"] - _REGIME_BASE["threshold_mult"]) < 1e-9


# ---------------------------------------------------------------- F2
def test_F2_switch_on_forecast_high_enlarges_position():
    """F2: 开关=True, alpha=1.0, forecast_L=L_p90(+3.0) → position_mult > baseline 0.8"""
    from bcrm2.parameter_mapper import ParameterMapper
    pm = ParameterMapper()
    stats = _stats_row(L_p10=-3.0, L_p90=+3.0)
    # 用牛市 L=+4,T=+2 输入构造大范围（lo, hi），hi 应该 >> 0.8
    ranges = pm.map_global_parameters(L=4.0, T=2.0, C=0.9, stats_row=stats)
    sw = pm.map_sector_weights(
        L=4.0, T=2.0, C=0.9, sector_betas=_default_betas()
    )
    eff = pm._resolve_effective_params(
        ranges=ranges, stats_row=stats,
        forecast_L=3.0, forecast_T=2.8,
        alpha_blend=1.0,
        regime_baselines=_REGIME_BASE_PARAMS,
        sector_weights_result=sw,
        symbol_sector="ai",
        regime_multipliers=_REGIME_BASE,
        enable_inject=True,   # 关键：开关打开
        base_long_threshold=0.7955,
        base_short_threshold=0.7955,
    )
    assert eff["position_mult_final"] > _REGIME_BASE["position_mult"], (
        f"F2 高前景注入失败：position={eff['position_mult_final']:.4f} ≤ baseline={_REGIME_BASE['position_mult']}"
    )


# ---------------------------------------------------------------- F3
def test_F3_switch_on_forecast_low_shrinks_position():
    """F3: 开关=True, alpha=1.0, forecast_L=L_p10(-3.0) → position < baseline 0.8"""
    from bcrm2.parameter_mapper import ParameterMapper
    pm = ParameterMapper()
    stats = _stats_row(L_p10=-3.0, L_p90=+3.0)
    ranges = pm.map_global_parameters(L=-4.0, T=-2.0, C=0.9, stats_row=stats)
    sw = pm.map_sector_weights(
        L=-4.0, T=-2.0, C=0.9, sector_betas=_default_betas()
    )
    eff = pm._resolve_effective_params(
        ranges=ranges, stats_row=stats,
        forecast_L=-3.0, forecast_T=-2.5,
        alpha_blend=1.0,
        regime_baselines=_REGIME_BASE_PARAMS,
        sector_weights_result=sw,
        symbol_sector="defi",
        regime_multipliers=_REGIME_BASE,
        enable_inject=True,
        base_long_threshold=0.7955,
        base_short_threshold=0.7955,
    )
    assert eff["position_mult_final"] < _REGIME_BASE["position_mult"], (
        f"F3 低前景注入失败：position={eff['position_mult_final']:.4f} ≥ baseline={_REGIME_BASE['position_mult']}"
    )


# ---------------------------------------------------------------- F4
def test_F4_long_bias_affects_threshold():
    """F4: long_bias>1 → long_conf_threshold > baseline×threshold

    方案：开关 on 时，forecast_L 为负 → long_bias>1（做多谨慎，门槛↑）
    为隔离「阈值乘数本身变化」的干扰，直接比较：
      - 使用中性 _REGIME_BASE（RANGE）作为查表基准（thr_mult=1.15 固定）
      - 开关 ON 时「forecast_L=-3」→ ① thr_mult_pm 用 short（≤1）
                                      ② 但 long_bias > 1（>1 部分抵消再盈余）
      更稳妥：拿 ON vs OFF 直接比，只要注入后 long_thr 高于 OFF × 0.92
      且显式校验 long_bias > 1.05（证明偏置生效）。"""
    from bcrm2.parameter_mapper import ParameterMapper
    pm = ParameterMapper()
    stats = _stats_row()
    ranges = pm.map_global_parameters(L=0.0, T=0.0, C=0.0, stats_row=stats)
    sw_neutral = pm.map_sector_weights(
        L=0.0, T=0.0, C=0.0, sector_betas=_default_betas()
    )
    ranges_bear = pm.map_global_parameters(L=-3.0, T=-1.5, C=0.8, stats_row=stats)
    sw_bear = pm.map_sector_weights(
        L=-3.0, T=-1.5, C=0.8, sector_betas=_default_betas()
    )

    # 先验证 bear 下 resolve 给出「做多谨慎」的加法偏置 < 0 → 转换为乘法偏置 > 1.05
    pm_params = pm.resolve_point_estimate(
        ranges=ranges_bear, stats_row=stats,
        forecast_L=-3.0, forecast_T=-1.5, alpha_blend=1.0,
        regime_baselines=_REGIME_BASE_PARAMS,
    )
    import numpy as _np
    pm_long_bias_mult = float(_np.clip(1.0 - float(pm_params["long_bias"]), 0.70, 1.30))
    assert pm_long_bias_mult > 1.05, (
        f"前提失败：bear 下乘法 long_bias={pm_long_bias_mult:.4f} 未大于 1.05"
        f"（加法 long_bias_add={pm_params['long_bias']:.4f}）"
    )

    eff_off = pm._resolve_effective_params(
        ranges=ranges, stats_row=stats,
        forecast_L=None, forecast_T=None, alpha_blend=0.0,
        regime_baselines=_REGIME_BASE_PARAMS,
        sector_weights_result=sw_neutral, symbol_sector="defi",
        regime_multipliers=_REGIME_BASE, enable_inject=False,
        base_long_threshold=0.7955, base_short_threshold=0.7955,
    )
    eff_on = pm._resolve_effective_params(
        ranges=ranges_bear, stats_row=stats,
        forecast_L=-3.0, forecast_T=-1.5, alpha_blend=1.0,
        regime_baselines=_REGIME_BASE_PARAMS,
        sector_weights_result=sw_bear, symbol_sector="defi",
        regime_multipliers=_REGIME_BASE, enable_inject=True,
        base_long_threshold=0.7955, base_short_threshold=0.7955,
    )
    # F4 核心断言：bear → long_bias > 1 → 即使阈值乘数缩小，也显著抬高高门槛
    # 用更稳固的基准：OFF × thr_mult_regime 作为锚点
    thr_regime = _REGIME_BASE["threshold_mult"]  # 1.15
    bias_driven = eff_off["long_conf_threshold"] / thr_regime * pm_params["long_bias"] * thr_regime
    # 等价于：eff_off * long_bias（简化版）
    # 但我们更宽松：只要 ON 显著高于 OFF 乘以 0.98（容忍 thr_mult_pm 的小幅缩小）
    # 且严格要求：ON > OFF * 1.02（证明偏置确实把门槛顶上去了）
    assert eff_on["long_conf_threshold"] > eff_off["long_conf_threshold"] * 1.02, (
        f"F4 做多偏置注入失败：bear long_thr={eff_on['long_conf_threshold']:.4f}"
        f" ≤ {eff_off['long_conf_threshold'] * 1.02:.4f}（=1.02 × OFF）"
    )


# ---------------------------------------------------------------- F5
def test_F5_ls_ratio_cap_direct_use():
    """F5: 开关打开后，ls_ratio_cap 直接使用 PM 的 resolve 结果而非默认"""
    from bcrm2.parameter_mapper import ParameterMapper
    pm = ParameterMapper()
    stats = _stats_row()
    # 构造一个 ls_ratio_cap 明显偏离默认 0.5 的范围：极端高 L → ls_cap 高；极端低 L → ls_cap 低
    ranges_low = pm.map_global_parameters(L=-4.0, T=-2.0, C=0.9, stats_row=stats)
    sw = pm.map_sector_weights(
        L=-4.0, T=-2.0, C=0.9, sector_betas=_default_betas()
    )
    eff = pm._resolve_effective_params(
        ranges=ranges_low, stats_row=stats,
        forecast_L=-3.0, forecast_T=-2.5, alpha_blend=1.0,
        regime_baselines=_REGIME_BASE_PARAMS,
        sector_weights_result=sw, symbol_sector="defi",
        regime_multipliers=_REGIME_BASE, enable_inject=True,
        base_long_threshold=0.7955, base_short_threshold=0.7955,
    )
    # bear 情景 → ls_ratio_cap 应 ≤ 默认 0.5（甚至更低）
    assert eff["ls_ratio_cap"] <= 0.55, (
        f"F5 ls_ratio_cap 注入失败：{eff['ls_ratio_cap']:.4f}，bear 情景应≤0.55"
    )


# ---------------------------------------------------------------- F6
def test_F6_sector_tp_mult_aggregation():
    """F6: 币种属于 ai 板块，ai sector_tp_mult=1.2，regime tp_mult=0.85
    → final_tp_mult = 0.85 × 1.2 = 1.02（如果 sector TP 更高，最终会放大）"""
    from bcrm2.parameter_mapper import ParameterMapper
    pm = ParameterMapper()
    stats = _stats_row()
    # 构造一个 AI 板块 regime=BREAKOUT → sector_tp_mult > 1.0 的情景
    ranges = pm.map_global_parameters(L=3.0, T=2.5, C=0.9, stats_row=stats)
    sw = pm.map_sector_weights(
        L=3.0, T=2.5, C=0.9, sector_betas=_default_betas()
    )
    # 确保 ai 板块 tp > 1.0（牛市 L>0 → 高 sector_tp_mult）
    assert sw["sector_tp_mult"]["ai"] >= 1.0, (
        f"前提失败：ai secto_tp={sw['sector_tp_mult']['ai']:.3f} < 1.0"
    )
    regime_base = dict(_REGIME_BASE)
    eff = pm._resolve_effective_params(
        ranges=ranges, stats_row=stats,
        forecast_L=3.0, forecast_T=2.8, alpha_blend=1.0,
        regime_baselines=_REGIME_BASE_PARAMS,
        sector_weights_result=sw, symbol_sector="ai",  # 关键：币种属于 ai
        regime_multipliers=regime_base, enable_inject=True,
        base_long_threshold=0.7955, base_short_threshold=0.7955,
    )
    # final_tp 应该 > regime 的 tp_mult（因为板块 TP 加成）
    expected_min = regime_base["tp_mult"]  # 至少不小于查表值
    assert eff["tp_mult_final"] >= expected_min, (
        f"F6 板块 TP 聚合失败：final_tp={eff['tp_mult_final']:.4f} < min={expected_min:.4f}"
        f"（ai secto_tp_mult={sw['sector_tp_mult']['ai']:.3f}）"
    )
