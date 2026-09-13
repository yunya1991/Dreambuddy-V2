"""
ElasticConstraintResolver — 弹性约束解析器
理论文档: 三维度矛盾论理论框架.md §7

核心区别 vs 传统金融 MTA:
  - 传统 MTA: 高周期优先 = 刚性 veto（Weekly 看跌 → Daily 禁止做多）
  - 弹性约束: 力量更强的矛盾约束力量较弱的矛盾，但允许偏离
    偏离越大，回弹力越强（弹簧模型，非墙壁模型）

数学模型:
  T_max = base_limit × (S_primary / (S_primary + S_minor))
  偏离度 Δp = |short_direction_strength - long_direction_strength|
  position_mult = floor + (1 - floor) × sigmoid(1 - Δp/T_max)
  当 Δp > T_max 时，position_mult 急剧下降（弹簧压缩到极限）

参数理论边界:
  base_limit ∈ [0.05, 0.20]  不超过历史最大反弹幅度
  floor ∈ [0.10, 0.30]       最低仓位比例
  bonus ∈ [0.00, 0.10]       方向对齐时的仓位加成
"""
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class ElasticConstraintResolver:
    """
    弹性约束解析器: 当短期矛盾方向与长期矛盾相反时，
    允许短期偏离但设置反弹上限 T_max.

    使用 sigmoid 衰减（非线性）而非线性衰减，
    因为市场偏离是弹簧式的——偏离越大，回弹力越强.
    """

    def __init__(self,
                 base_limit: float = 0.12,
                 floor: float = 0.20,
                 bonus: float = 0.05,
                 steepness: float = 3.0):
        """
        Args:
            base_limit: 基础反弹上限（理论边界 [0.05, 0.20]）
            floor: 最低仓位比例（理论边界 [0.10, 0.30]）
            bonus: 方向对齐时的仓位加成（理论边界 [0.00, 0.10]）
            steepness: sigmoid 陡度（越大弹簧越硬）
        """
        # 参数边界检查
        self._base_limit = max(0.05, min(0.20, base_limit))
        self._floor = max(0.10, min(0.30, floor))
        self._bonus = max(0.00, min(0.10, bonus))
        self._steepness = max(1.0, min(10.0, steepness))

    def resolve(self,
                primary: dict[str, Any] | None,
                secondary: dict[str, Any] | None,
                base_position: float = 1.0,
                primary_tf: str = "medium",
                secondary_tf: str = "medium") -> dict[str, Any]:
        """
        解析弹性约束，返回调整后的仓位倍数.

        Args:
            primary: 主矛盾 {direction, strength}
            secondary: 次矛盾 {direction, strength}
            base_position: 基础仓位（默认 1.0）
            primary_tf: 主矛盾时间框架 "short"|"medium"|"long"
            secondary_tf: 次矛盾时间框架

        Returns:
            {
                "position_mult": float,      # 调整后仓位倍数
                "t_max": float,               # 弹性约束反弹上限
                "deviation": float,           # 短期偏离度
                "constraint_active": bool,    # 弹性约束是否激活
                "aligned": bool,              # 矛盾方向是否对齐
                "rebound_risk": float,        # 回弹风险 [0,1]
            }
        """
        # 默认结果（无约束）
        default_result = {
            "position_mult": base_position,
            "t_max": 0.0,
            "deviation": 0.0,
            "constraint_active": False,
            "aligned": True,
            "rebound_risk": 0.0,
        }

        if primary is None or secondary is None:
            return default_result

        try:
            p_dir = str(primary.get("direction", "neutral")).lower()
            p_strength = max(0.0, min(1.0, float(primary.get("strength", 0.0))))
            s_dir = str(secondary.get("direction", "neutral")).lower()
            s_strength = max(0.0, min(1.0, float(secondary.get("strength", 0.0))))
        except (TypeError, ValueError):
            return default_result

        # 方向对齐 → 无约束 + 加成
        if p_dir == s_dir or p_dir == "neutral" or s_dir == "neutral":
            mult = base_position * (1.0 + self._bonus * min(p_strength, s_strength))
            return {
                "position_mult": max(self._floor, mult),
                "t_max": 0.0,
                "deviation": 0.0,
                "constraint_active": False,
                "aligned": True,
                "rebound_risk": 0.0,
            }

        # 方向相反 → 弹性约束激活
        # §20 分层弹性约束：
        # 判据2：力量差大时力量驱动；力量接近时层级驱动（长期约束短期）
        total_strength = p_strength + s_strength
        if total_strength < 1e-6:
            return default_result

        TIER_WEIGHT = {"short": 0.2, "medium": 0.3, "long": 0.5}
        DOMINANCE_GAP = 0.15

        strength_gap = abs(p_strength - s_strength)

        if strength_gap >= DOMINANCE_GAP:
            # 力量驱动: 纯力量比 (现有逻辑)
            t_max = self._base_limit * (p_strength / total_strength)
        else:
            # 层级驱动: 长期约束短期 → T_max 增大
            tier_bonus = TIER_WEIGHT.get(primary_tf, 0.3) / max(TIER_WEIGHT.get(secondary_tf, 0.2), 1e-6)
            t_max = self._base_limit * (p_strength / total_strength) * tier_bonus
            # clip 防止 T_max 超界
            t_max = min(t_max, self._base_limit * 2.0)

        # 偏离度: 次矛盾方向上的力量（偏离主矛盾的程度）
        deviation = s_strength

        # Sigmoid 衰减: 偏离越大，仓位越小
        # ratio = deviation / t_max，ratio > 1 时急剧衰减
        if t_max > 1e-6:
            ratio = deviation / t_max
        else:
            ratio = float('inf')

        # sigmoid(1 - ratio): ratio=0 → 1.0（满仓），ratio=1 → 0.5，ratio→∞ → 0.0
        sigmoid_val = 1.0 / (1.0 + math.exp(self._steepness * (ratio - 1.0)))

        # 仓位倍数: floor + (1 - floor) × sigmoid
        position_mult = self._floor + (1.0 - self._floor) * sigmoid_val

        # 回弹风险: 偏离接近或超过 T_max 时风险升高
        rebound_risk = max(0.0, min(1.0, ratio / 2.0))

        return {
            "position_mult": max(self._floor, position_mult),
            "t_max": round(t_max, 6),
            "deviation": round(deviation, 6),
            "constraint_active": True,
            "aligned": False,
            "rebound_risk": round(rebound_risk, 6),
        }

    def check_rebound_threshold(self, primary: dict | None,
                                secondary: dict | None,
                                current_price: float,
                                reference_price: float) -> dict[str, Any]:
        """
        检查短期矛盾是否已达到反弹阈值（量变即将引发质变）.

        Args:
            primary/secondary: 主/次矛盾
            current_price: 当前价格
            reference_price: 参考价格（主矛盾方向的价格基准）

        Returns:
            {
                "exceeded_threshold": bool,
                "rebound_ratio": float,  # 已反弹幅度 / T_max
                "force_align": bool,    # 是否需要强制对齐
            }
        """
        if primary is None or secondary is None:
            return {"exceeded_threshold": False, "rebound_ratio": 0.0, "force_align": False}

        try:
            p_strength = max(0.0, min(1.0, float(primary.get("strength", 0.0))))
            s_strength = max(0.0, min(1.0, float(secondary.get("strength", 0.0))))
        except (TypeError, ValueError):
            return {"exceeded_threshold": False, "rebound_ratio": 0.0, "force_align": False}

        total_strength = p_strength + s_strength
        if total_strength < 1e-6:
            return {"exceeded_threshold": False, "rebound_ratio": 0.0, "force_align": False}

        t_max = self._base_limit * (p_strength / total_strength)

        if reference_price == 0 or t_max <= 0:
            return {"exceeded_threshold": False, "rebound_ratio": 0.0, "force_align": False}

        price_change = abs(current_price - reference_price) / reference_price
        rebound_ratio = price_change / t_max

        return {
            "exceeded_threshold": rebound_ratio >= 1.0,
            "rebound_ratio": round(rebound_ratio, 6),
            "force_align": rebound_ratio >= 1.5,  # 超过 1.5× T_max 强制对齐
        }
