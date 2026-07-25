"""三屏趋势系统 — 技术面 + 基本面撮合

第二重趋势一致性检查：
- 趋势方向以技术面为主
- 基本面影响置信度调整
- 矛盾存在时：方向不变，置信度按矛盾程度扣减
"""

from typing import Dict

try:
    from .config import (
        FUNDAMENTAL_WEIGHT,
        MAX_CONFLICT_DEDUCTION,
        TECHNICAL_WEIGHT,
    )
except ImportError:
    from config import (
        FUNDAMENTAL_WEIGHT,
        MAX_CONFLICT_DEDUCTION,
        TECHNICAL_WEIGHT,
    )


def _core_direction(d: str) -> str:
    """提取核心方向（去除 REVERSAL_ 前缀）"""
    if not d:
        return "NEUTRAL"
    if d.startswith("REVERSAL_"):
        return "BULL" if d == "REVERSAL_BULL" else "BEAR"
    return d


def fuse_technical_fundamental(technical_result: Dict, fundamental_result: Dict) -> Dict:
    """
    技术面 + 基本面撮合

    融合规则：
    - 方向一致 → 加权平均（技术60% + 基本面40%）
    - 基本面中性 → 直接用技术面置信度
    - 方向矛盾 → 取较低值，按矛盾程度最大扣减 MAX_CONFLICT_DEDUCTION

    核心原则：趋势方向以技术面为主，基本面影响置信度调整。

    参数:
        technical_result: {"direction": str, "confidence": float}
        fundamental_result: {"direction": str, "confidence": float}

    返回:
        {
            "technical": {"direction", "confidence"},
            "fundamental": {"direction", "confidence"},
            "consistent": bool,
            "final_direction": str,
            "final_confidence": float,
            "weights": {"technical": float, "fundamental": float},
            "conflict_level": float (0-100),
        }
    """
    tech_dir = technical_result.get("direction", "NEUTRAL")
    tech_conf = technical_result.get("confidence", 0)
    fund_dir = fundamental_result.get("direction", "NEUTRAL")
    fund_conf = fundamental_result.get("confidence", 0)

    tech_core = _core_direction(tech_dir)
    fund_core = _core_direction(fund_dir)

    consistent = tech_core == fund_core and tech_core != "NEUTRAL"

    final_direction = tech_dir if tech_dir != "NEUTRAL" else fund_dir

    conflict_level = 0.0

    if consistent:
        final_confidence = round(tech_conf * TECHNICAL_WEIGHT + fund_conf * FUNDAMENTAL_WEIGHT, 1)
    elif fund_core == "NEUTRAL":
        final_confidence = tech_conf
    else:
        base_conf = min(tech_conf, fund_conf)
        conflict_level = (tech_conf / 100) * (fund_conf / 100)
        deduction = conflict_level * MAX_CONFLICT_DEDUCTION * 100
        final_confidence = round(max(0, base_conf - deduction), 1)

    return {
        "technical": {
            "direction": tech_dir,
            "confidence": tech_conf,
        },
        "fundamental": {
            "direction": fund_dir,
            "confidence": fund_conf,
        },
        "consistent": consistent,
        "final_direction": final_direction,
        "final_confidence": final_confidence,
        "weights": {"technical": TECHNICAL_WEIGHT, "fundamental": FUNDAMENTAL_WEIGHT},
        "conflict_level": round(conflict_level * 100, 1) if not consistent else 0,
    }
