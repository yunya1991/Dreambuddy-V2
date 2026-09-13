"""
ContradictionShiftAccumulator — 量变积累 + 质变检测（修正算法）
理论文档: 三维度矛盾论理论框架.md §9

v3.0 修正: 比较 old_primary 的当前力量 vs new_primary 的当前力量
（v2.0 错误地比较 new 当前力量 vs old 初始力量）

质变判定规则:
  质变 = 矛盾力量排序变化 AND (波动率制度转换 OR 相关性结构断裂 OR 市场形态转换)
  仅排序变化（无结构性断裂）= 量变，不触发质变流程
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ContradictionSnapshot:
    """单个时刻的矛盾矩阵快照."""
    timestamp: float
    contradictions: list[dict]  # [{dimension, timeframe, direction, normalized_strength, ...}]

    def get_primary(self) -> dict | None:
        """获取当前力量最强的矛盾."""
        if not self.contradictions:
            return None
        return max(self.contradictions, key=lambda c: c.get("normalized_strength", 0.0))

    def find_by_key(self, dimension: str, timeframe: str) -> dict | None:
        """按维度×周期查找矛盾."""
        for c in self.contradictions:
            if c.get("dimension") == dimension and c.get("timeframe") == timeframe:
                return c
        return None


class ContradictionShiftAccumulator:
    """
    跟踪矛盾力量变化，检测主要矛盾转移.

    量变: 矛盾力量数值变化，排序不变 → 不触发质变
    质变: 排序变化 + 结构性断裂 → 触发质变流程
    """

    def __init__(self, persistence: int = 14, dominance_gap: float = 0.15):
        """
        Args:
            persistence: 连续 persistence 次评估中排序变化才考虑质变
            dominance_gap: 新矛盾当前力量 - 旧矛盾当前力量 > dominance_gap 才算超越
        """
        self._persistence = persistence
        self._dominance_gap = dominance_gap
        self._history: list[ContradictionSnapshot] = []

    def record(self, contradictions: list[dict]):
        """记录当前时刻的矛盾矩阵."""
        snapshot = ContradictionSnapshot(
            timestamp=time.time(),
            contradictions=contradictions,
        )
        self._history.append(snapshot)

        # 限制历史长度
        max_history = self._persistence * 3
        if len(self._history) > max_history:
            self._history = self._history[-max_history:]

    def detect_shift(self,
                     structural_break: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """
        检测主要矛盾是否发生转移（修正算法）.

        条件（全部满足才判定质变）:
        1. 连续 persistence 次评估中，新矛盾当前力量 > 旧矛盾当前力量
        2. 新矛盾当前力量 - 旧矛盾当前力量 > dominance_gap
        3. 新矛盾方向与旧矛盾方向不同
        4. 至少一项结构性断裂检测为 True（质变条件）

        Args:
            structural_break: StructuralBreakDetector.detect_all() 的结果

        Returns:
            {
                "shifted_from": {dimension, timeframe, direction, strength},
                "shifted_to": {dimension, timeframe, direction, strength},
                "new_direction": str,
                "structural_break_type": str | None,
            }
            None if 未检测到质变.
        """
        if len(self._history) < self._persistence:
            return None

        recent = self._history[-self._persistence:]
        init_snapshot = recent[0]
        init_primary = init_snapshot.get_primary()
        if init_primary is None:
            return None

        init_dim = init_primary.get("dimension", "")
        init_tf = init_primary.get("timeframe", "")
        init_dir = init_primary.get("direction", "neutral")

        # 追踪旧主矛盾的当前力量（不是初始力量）
        consecutive_count = 0
        best_new_primary = None
        best_old_current = None

        for snapshot in recent[1:]:
            # 找旧主矛盾在当前时刻的力量
            old_current = snapshot.find_by_key(init_dim, init_tf)
            if old_current is None:
                continue

            old_current_strength = old_current.get("normalized_strength", 0.0)

            # 找当前力量最强的矛盾
            current_primary = snapshot.get_primary()
            if current_primary is None:
                continue

            current_dim = current_primary.get("dimension", "")
            current_tf = current_primary.get("timeframe", "")
            current_strength = current_primary.get("normalized_strength", 0.0)
            current_dir = current_primary.get("direction", "neutral")

            # 检查是否有新矛盾超越旧矛盾（比较的都是当前力量）
            is_new_primary = (current_dim != init_dim or current_tf != init_tf)
            gap = current_strength - old_current_strength

            if is_new_primary and gap > self._dominance_gap and current_dir != init_dir:
                consecutive_count += 1
                best_new_primary = current_primary
                best_old_current = old_current
            else:
                consecutive_count = 0  # 重置

        # 需要连续 persistence-1 次（因为初始不算）都满足
        if consecutive_count < self._persistence - 1:
            return None

        # 检查结构性断裂条件
        has_structural_break = False
        break_type = None
        if structural_break is not None:
            for break_name in ["volatility_regime_shift", "correlation_break", "market_form_shift"]:
                break_result = structural_break.get(break_name)
                if break_result is not None and break_result.get("detected", False):
                    has_structural_break = True
                    break_type = break_name
                    break

        if not has_structural_break:
            # 排序变化但无结构性断裂 = 量变，不是质变
            return None

        return {
            "shifted_from": {
                "dimension": init_dim,
                "timeframe": init_tf,
                "direction": init_dir,
                "strength": best_old_current.get("normalized_strength", 0.0) if best_old_current else 0.0,
            },
            "shifted_to": {
                "dimension": best_new_primary.get("dimension", ""),
                "timeframe": best_new_primary.get("timeframe", ""),
                "direction": best_new_primary.get("direction", "neutral"),
                "strength": best_new_primary.get("normalized_strength", 0.0),
            },
            "new_direction": best_new_primary.get("direction", "neutral"),
            "structural_break_type": break_type,
        }

    def get_accumulation_status(self) -> dict[str, Any]:
        """获取当前量变积累状态（不检测质变）."""
        if len(self._history) < 2:
            return {"status": "insufficient_data", "samples": len(self._history)}

        latest = self._history[-1]
        first = self._history[0]
        latest_primary = latest.get_primary()
        first_primary = first.get_primary()

        if latest_primary is None or first_primary is None:
            return {"status": "no_primary", "samples": len(self._history)}

        return {
            "status": "accumulating",
            "samples": len(self._history),
            "initial_primary": {
                "dimension": first_primary.get("dimension"),
                "timeframe": first_primary.get("timeframe"),
                "strength": first_primary.get("normalized_strength"),
            },
            "current_primary": {
                "dimension": latest_primary.get("dimension"),
                "timeframe": latest_primary.get("timeframe"),
                "strength": latest_primary.get("normalized_strength"),
            },
            "persistence_required": self._persistence,
            "persistence_met": len(self._history) >= self._persistence,
        }
