"""T1 RED — ParameterMapper.resolve_point_estimate() 测试（5 用例）

覆盖行为：
  R1) test_resolve_identity_neutral
        L=0,T=0,C=0, alpha=0, forecast=None → 6 参数全为 regime_baseline（字节等价兜底）

  R2) test_resolve_lo_position_when_forecast_at_lo
        forecast_L 正好位于历史 level_lo → value_raw = range.lo
        alpha=1.0 → 输出 value_raw（纯形态锚定）

  R3) test_resolve_hi_position_when_forecast_at_hi
        forecast_L 正好位于历史 level_hi → value_raw = range.hi
        alpha=1.0 → 输出 range.hi

  R4) test_resolve_blend_at_alpha_half
        alpha=0.5, forecast=L_mid → value_raw = range.mid
        输出 = 0.5*baseline + 0.5*mid

  R5) test_resolve_forecast_missing_uses_baseline
        forecast_L=None, alpha=1.0 → 仍然返回 baseline（兜底不崩溃）

注意：resolve_point_estimate() 是设计中新方法，当前版本未实现 → 预期 FAIL。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_THIS_DIR = Path(__file__).resolve().parent
_BCRM2_ROOT = _THIS_DIR.parent
assert _BCRM2_ROOT.name == "memory_l4"
if str(_BCRM2_ROOT) not in sys.path:
    sys.path.insert(0, str(_BCRM2_ROOT))


def _stats_row(L_p10=-3.0, L_p90=+3.0, T_p10=-2.5, T_p90=+2.8) -> dict:
    return dict(
        L_p10_60d=L_p10, L_p90_60d=L_p90,
        T_p10_60d=T_p10, T_p90_60d=T_p90,
        L_p10_252d=L_p10, L_p90_252d=L_p90,
        T_p10_252d=T_p10, T_p90_252d=T_p90,
    )


# regime_baselines 模拟 REGIME_MULTIPLIERS["RANGE_BOUND"] 的查表默认值
# 对应 polling_trader.py L1704 定义
_REGIME_BASE_RANGES = {
    "global_position_mult": 0.8,      # RANGE_BOUND: position_mult=0.8
    "ls_ratio_cap": 0.5,              # 直通默认
    "long_bias": 1.0,                 # 直通默认
    "short_bias": 1.0,                # 直通默认
    "long_threshold_mult": 1.15,      # RANGE_BOUND: threshold_mult=1.15 (long)
    "short_threshold_mult": 1.15,     # RANGE_BOUND: threshold_mult=1.15 (short)
}


# ---------------------------------------------------------------- R1
def test_resolve_identity_neutral():
    """L=0,T=0,C=0, alpha=0, forecast=None → 输出等于 regime_baseline。
    这是字节等价核心不变量：关闭注入 → 完全等价于 REGIME_MULTIPLIERS 查表。"""
    from bcrm2.parameter_mapper import ParameterMapper
    pm = ParameterMapper()

    ranges = pm.map_global_parameters(L=0.0, T=0.0, C=0.0, stats_row=_stats_row())
    # 调用新方法 resolve_point_estimate（设计中方法，当前未实现）
    result = pm.resolve_point_estimate(
        ranges=ranges,
        stats_row=_stats_row(),
        forecast_L=None,
        forecast_T=None,
        alpha_blend=0.0,
        regime_baselines=_REGIME_BASE_RANGES,
    )

    for k in ("global_position_mult", "ls_ratio_cap", "long_bias", "short_bias",
              "long_threshold_mult", "short_threshold_mult"):
        assert abs(result[k] - _REGIME_BASE_RANGES[k]) < 1e-9, (
            f"R1 字节等价失败：{k}={result[k]:.4f}，预期 baseline={_REGIME_BASE_RANGES[k]:.4f}"
        )


# ---------------------------------------------------------------- R2
def test_resolve_lo_position_when_forecast_at_lo():
    """forecast_L = L_p10（最底部）→ value_raw = range.lo
    alpha=1.0 → 纯形态锚定，输出 lo。"""
    from bcrm2.parameter_mapper import ParameterMapper
    pm = ParameterMapper()

    stats = _stats_row(L_p10=-3.0, L_p90=+3.0)
    ranges = pm.map_global_parameters(L=-4.0, T=-4.0, C=0.8, stats_row=stats)
    # forecast_L 准确在 L_p10（历史最低位）
    forecast_L = -3.0
    forecast_T = -2.5

    result = pm.resolve_point_estimate(
        ranges=ranges,
        stats_row=stats,
        forecast_L=forecast_L,
        forecast_T=forecast_T,
        alpha_blend=1.0,
        regime_baselines=_REGIME_BASE_RANGES,
    )

    # L 维度参数（global_position_mult, long_bias, short_bias, ls_ratio_cap,
    #              long_threshold_mult, short_threshold_mult）的 lo 应被选中
    for k in ("global_position_mult", "long_bias", "short_bias",
              "long_threshold_mult", "short_threshold_mult", "ls_ratio_cap"):
        lo = ranges[k][0]
        assert abs(result[k] - lo) < 1e-6, (
            f"R2 lo 映射失败：{k} result={result[k]:.4f}，lo={lo:.4f}"
        )


# ---------------------------------------------------------------- R3
def test_resolve_hi_position_when_forecast_at_hi():
    """forecast_L = L_p90（最顶部）→ value_raw = range.hi
    alpha=1.0 → 输出 hi。"""
    from bcrm2.parameter_mapper import ParameterMapper
    pm = ParameterMapper()

    stats = _stats_row(L_p10=-3.0, L_p90=+3.0)
    ranges = pm.map_global_parameters(L=4.0, T=4.0, C=0.8, stats_row=stats)
    # forecast_L 准确在 L_p90（历史最高位）
    forecast_L = 3.0
    forecast_T = 2.8

    result = pm.resolve_point_estimate(
        ranges=ranges,
        stats_row=stats,
        forecast_L=forecast_L,
        forecast_T=forecast_T,
        alpha_blend=1.0,
        regime_baselines=_REGIME_BASE_RANGES,
    )

    for k in ("global_position_mult", "long_bias", "short_bias",
              "long_threshold_mult", "short_threshold_mult", "ls_ratio_cap"):
        hi = ranges[k][1]
        assert abs(result[k] - hi) < 1e-6, (
            f"R3 hi 映射失败：{k} result={result[k]:.4f}，hi={hi:.4f}"
        )


# ---------------------------------------------------------------- R4
def test_resolve_blend_at_alpha_half():
    """alpha=0.5, forecast_L 正好在 (lo+hi)/2 处 → value_raw = range.mid
    输出 = 0.5*baseline + 0.5*mid"""
    from bcrm2.parameter_mapper import ParameterMapper
    pm = ParameterMapper()

    stats = _stats_row(L_p10=-4.0, L_p90=+4.0)
    ranges = pm.map_global_parameters(L=0.0, T=0.0, C=0.0, stats_row=stats)
    # forecast_L = 0，正好在 lo=-4 与 hi=+4 中间 → norm_L = 0.5
    forecast_L = 0.0
    forecast_T = 0.0

    result = pm.resolve_point_estimate(
        ranges=ranges,
        stats_row=stats,
        forecast_L=forecast_L,
        forecast_T=forecast_T,
        alpha_blend=0.5,
        regime_baselines=_REGIME_BASE_RANGES,
    )

    for k in ("global_position_mult", "long_bias", "short_bias",
              "long_threshold_mult", "short_threshold_mult", "ls_ratio_cap"):
        lo, hi = ranges[k][0], ranges[k][1]
        mid = 0.5 * (lo + hi)
        expected = 0.5 * _REGIME_BASE_RANGES[k] + 0.5 * mid
        assert abs(result[k] - expected) < 1e-6, (
            f"R4 混合失败：{k} result={result[k]:.4f}，预期={expected:.4f}"
            f" (baseline={_REGIME_BASE_RANGES[k]:.4f}, mid={mid:.4f})"
        )


# ---------------------------------------------------------------- R5
def test_resolve_forecast_missing_uses_baseline():
    """forecast_L=None, alpha=1.0 → 仍然返回 baseline，不崩溃。"""
    from bcrm2.parameter_mapper import ParameterMapper
    pm = ParameterMapper()

    ranges = pm.map_global_parameters(L=3.0, T=2.0, C=0.7, stats_row=_stats_row())

    result = pm.resolve_point_estimate(
        ranges=ranges,
        stats_row=_stats_row(),
        forecast_L=None,          # 形态预测缺失
        forecast_T=None,
        alpha_blend=1.0,          # 即使 alpha=1.0 也应兜底
        regime_baselines=_REGIME_BASE_RANGES,
    )

    for k in ("global_position_mult", "ls_ratio_cap", "long_bias", "short_bias",
              "long_threshold_mult", "short_threshold_mult"):
        assert abs(result[k] - _REGIME_BASE_RANGES[k]) < 1e-9, (
            f"R5 兜底失败：{k}={result[k]:.4f}，预期 baseline={_REGIME_BASE_RANGES[k]:.4f}"
        )
