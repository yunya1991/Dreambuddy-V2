#!/usr/bin/env python3
"""
易经参数插值模块 (Yijing Param Interpolator)

职责：
  将易经 risk_score / value_score 映射为 V15 参数微调倍数(tp_mult / holding_mult / size_mult)。
  纯函数，无状态，无副作用，可独立测试。

设计原则：
  - 在 Phase B+ 子形态倍数基础上叠加，不覆盖
  - 总幅度受限 ±25%（subregime_mult × yijing_mult 的乘积 clamp 到 [0.75, 1.25]）
  - 不碰参数空间边界（日常 5-7 天只更新插值，60 天才重算参数空间）

映射逻辑（risk 0=安全 1=高危，value 0=低价值 1=高价值）：
  risk 低 + value 高 → 放宽 TP + 延长持仓 + 加仓（趋势友好，让利润跑）
  risk 高 + value 低 → 收紧 TP + 缩短持仓 + 减仓（危险，快速离场）
  risk 高 + value 高 → 持仓不变 + 收紧 TP（有价值但风险高，见好就收）
  risk 低 + value 低 → 持仓不变 + 略加仓（安全但价值不明确，小仓位试探）
  中性 → 不调整

用法：
  from yijing_param_interpolator import interpolate_params
  mults = interpolate_params(risk_score=0.3, value_score=0.8)
  # → {"tp_mult": 1.05, "holding_mult": 1.10, "size_mult": 1.05}
"""
from typing import Dict


# 幅度限制：subregime × yijing 总乘积不超过此范围
_MIN_TOTAL_MULT = 0.75
_MAX_TOTAL_MULT = 1.25

# 单项 yijing 倍数范围
_YIJING_TP_RANGE = (0.90, 1.08)
_YIJING_HOLDING_RANGE = (0.85, 1.15)
_YIJING_SIZE_RANGE = (0.85, 1.10)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _lerp(t: float, lo: float, hi: float) -> float:
    """线性插值：t=0→lo, t=1→hi"""
    return lo + (hi - lo) * _clamp(t, 0.0, 1.0)


def interpolate_params(
    risk_score: float,
    value_score: float,
    subregime_mults: Dict[str, float] = None,
) -> Dict[str, float]:
    """risk/value → 参数微调倍数

    Args:
        risk_score: 风险评分 0-1（0=安全，1=高危）
        value_score: 价值评分 0-1（0=低价值，1=高价值）
        subregime_mults: Phase B+ 子形态倍数（含 tp_mult/holding_mult），
                        若提供则 yijing 倍数与之相乘并 clamp

    Returns:
        dict: tp_mult / holding_mult / size_mult（最终应用倍数）
    """
    # ── 计算 yijing 独立倍数 ──
    # 核心思路：
    #   value 高 + risk 低 → 放宽（趋势友好）
    #   value 低 + risk 高 → 收紧（危险）
    #   用 (value - risk) 作为"净价值"驱动因子，范围 [-1, 1]
    net_value = value_score - risk_score  # [-1, 1]

    # 中性区：|net_value| < 0.12 时不调整 TP（避免 risk≈value 时的无效收紧）
    _NEUTRAL_THRESHOLD = 0.12

    # tp_mult: 净价值明显>0 放宽止盈（让利润跑），明显<0 收紧（快速离场）
    if abs(net_value) < _NEUTRAL_THRESHOLD:
        yijing_tp = 1.0
    else:
        yijing_tp = _lerp((net_value + 1) / 2, _YIJING_TP_RANGE[0], _YIJING_TP_RANGE[1])
    # risk 高时额外收紧 TP（不管 value 如何）
    if risk_score > 0.6:
        yijing_tp *= (1.0 - (risk_score - 0.6) * 0.25)  # risk 0.6→1.0 时额外 ×0.9

    # holding_mult: 中性区不调整，明显偏离才调整
    if abs(net_value) < _NEUTRAL_THRESHOLD:
        yijing_holding = 1.0
    else:
        yijing_holding = _lerp((net_value + 1) / 2, _YIJING_HOLDING_RANGE[0], _YIJING_HOLDING_RANGE[1])

    # size_mult: value 高加仓，risk 高减仓
    yijing_size = _lerp(value_score, _YIJING_SIZE_RANGE[0], _YIJING_SIZE_RANGE[1])
    if risk_score > 0.6:
        yijing_size *= (1.0 - (risk_score - 0.6) * 0.30)

    yijing_tp = round(yijing_tp, 4)
    yijing_holding = round(yijing_holding, 4)
    yijing_size = round(yijing_size, 4)

    # ── 与子形态倍数叠加 ──
    if subregime_mults:
        sr_tp = subregime_mults.get("tp_mult", 1.0)
        sr_holding = subregime_mults.get("holding_mult", 1.0)
        sr_size = subregime_mults.get("size_mult", 1.0)

        final_tp = _clamp(sr_tp * yijing_tp, _MIN_TOTAL_MULT, _MAX_TOTAL_MULT)
        final_holding = _clamp(sr_holding * yijing_holding, _MIN_TOTAL_MULT, _MAX_TOTAL_MULT)
        final_size = _clamp(sr_size * yijing_size, _MIN_TOTAL_MULT, _MAX_TOTAL_MULT)
    else:
        final_tp = _clamp(yijing_tp, _MIN_TOTAL_MULT, _MAX_TOTAL_MULT)
        final_holding = _clamp(yijing_holding, _MIN_TOTAL_MULT, _MAX_TOTAL_MULT)
        final_size = _clamp(yijing_size, _MIN_TOTAL_MULT, _MAX_TOTAL_MULT)

    return {
        "tp_mult": round(final_tp, 4),
        "holding_mult": round(final_holding, 4),
        "size_mult": round(final_size, 4),
        "yijing_tp": yijing_tp,
        "yijing_holding": yijing_holding,
        "yijing_size": yijing_size,
    }


def classify_risk_value(risk_score: float, value_score: float) -> str:
    """风险-价值象限分类（用于日志和分析）

    Returns:
        "TREND_FRIENDLY"   - risk低+value高（趋势友好，放宽）
        "DANGER"           - risk高+value低（危险，收紧）
        "HIGH_VALUE_RISK"  - risk高+value高（有价值但风险高，见好就收）
        "LOW_VALUE_SAFE"   - risk低+value低（安全但价值不明确，试探）
        "NEUTRAL"          - 中性
    """
    risk_high = risk_score > 0.55
    risk_low = risk_score < 0.45
    value_high = value_score > 0.55
    value_low = value_score < 0.45

    if risk_low and value_high:
        return "TREND_FRIENDLY"
    if risk_high and value_low:
        return "DANGER"
    if risk_high and value_high:
        return "HIGH_VALUE_RISK"
    if risk_low and value_low:
        return "LOW_VALUE_SAFE"
    return "NEUTRAL"
