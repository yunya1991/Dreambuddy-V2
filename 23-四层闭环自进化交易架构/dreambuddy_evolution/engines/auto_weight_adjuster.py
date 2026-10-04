"""
AutoWeightAdjuster — 自进化权重自动调整 (T13, SPEC §5.3)

基于案例库胜率统计，自动升降级策略基因权重:

  win_rate >= 0.65 且 sample_count >= 10 → weight *= 1.1 (升级)
  win_rate < 0.40 → weight *= 0.9 (降级)
  其他 → 不调整

边界:
  weight 上限 2.0
  weight 下限 0.1

HC: 开关关断时不调整 weight
HC: FAIL-OPEN 异常不调整

持久化:
  内存中实时调整，定期持久化到 library.json
"""
from __future__ import annotations

import logging
from typing import Any

from dreambuddy_evolution.agi_config import is_enabled

logger = logging.getLogger(__name__)


class AutoWeightAdjuster:
    """自进化权重自动调整器 (T13, SPEC §5.3)。"""

    WEIGHT_UPGRADE_THRESHOLD = 0.65  # win_rate >= 0.65
    WEIGHT_DOWNGRADE_THRESHOLD = 0.40  # win_rate < 0.40
    MIN_SAMPLE_FOR_ADJUST = 10  # 最小样本数

    WEIGHT_UPGRADE_FACTOR = 1.1  # 升级因子
    WEIGHT_DOWNGRADE_FACTOR = 0.9  # 降级因子
    WEIGHT_CEILING = 2.0  # 上限
    WEIGHT_FLOOR = 0.1  # 下限

    def adjust(
        self,
        case_library: Any | None,
        gene_library: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """
        根据案例库胜率调整策略基因权重。

        P2-2: 支持两种 gene_library 格式：
          1. 完整 library dict（load_gene_library 返回值，含 'combinations' key）
          2. 扁平 dict {gene_id: {weight, pattern, event_type, ...}}（向后兼容）

        Args:
            case_library: EventCaseLibrary 实例
            gene_library: 基因库 dict

        Returns:
            调整后的 gene_library（内存中，原地修改完整 library dict）
        """
        if not is_enabled("enable_contradiction_driven_layer"):
            return dict(gene_library) if isinstance(gene_library, dict) else {}
        if not is_enabled("enable_auto_weight_adjustment"):
            return dict(gene_library) if isinstance(gene_library, dict) else {}

        # HC: FAIL-OPEN
        try:
            if not isinstance(gene_library, dict):
                return {}
            if case_library is None:
                return dict(gene_library) if isinstance(gene_library, dict) else {}

            # P2-2: 检测完整 library dict 格式（含 combinations key）
            if "combinations" in gene_library:
                return self._adjust_library_dict(case_library, gene_library)

            # 原有扁平 dict 格式 {gene_id: {weight, pattern, event_type}}
            return self._adjust_flat_dict(case_library, gene_library)
        except Exception as e:
            logger.warning("AutoWeightAdjuster FAIL-OPEN: %s", e, exc_info=False)
            return dict(gene_library) if isinstance(gene_library, dict) else {}

    def _adjust_library_dict(
        self,
        case_library: Any,
        library: dict[str, Any],
    ) -> dict[str, Any]:
        """P2-2: 调整完整 library dict 中 combinations 的 meta.weight（原地修改）。"""
        combinations = library.get("combinations", []) or []
        for combo in combinations:
            if not isinstance(combo, dict):
                continue
            meta = combo.get("meta")
            if not isinstance(meta, dict) or "weight" not in meta:
                continue
            pattern = meta.get("pattern")
            event_type = meta.get("event_type")
            if not pattern:
                continue

            stats = case_library.get_pattern_winrate(pattern=pattern, event_type=event_type)
            sample_count = stats.get("sample_count", 0)
            win_rate = stats.get("win_rate", 0.0)

            if sample_count < self.MIN_SAMPLE_FOR_ADJUST:
                continue

            current_weight = float(meta["weight"])
            new_weight = self._compute_new_weight(
                current_weight, win_rate, sample_count, combo.get("combo_id", ""),
            )
            meta["weight"] = round(new_weight, 4)

        return library

    def _adjust_flat_dict(
        self,
        case_library: Any,
        gene_library: dict[str, Any],
    ) -> dict[str, Any]:
        """原有扁平 dict 格式调整逻辑（向后兼容）。"""
        result = dict(gene_library)
        for gene_id, gene_data in result.items():
            if not isinstance(gene_data, dict):
                continue
            if "weight" not in gene_data:
                continue

            pattern = gene_data.get("pattern")
            event_type = gene_data.get("event_type")
            if not pattern:
                continue

            stats = case_library.get_pattern_winrate(pattern=pattern, event_type=event_type)
            sample_count = stats.get("sample_count", 0)
            win_rate = stats.get("win_rate", 0.0)

            if sample_count < self.MIN_SAMPLE_FOR_ADJUST:
                continue

            current_weight = float(gene_data["weight"])
            new_weight = self._compute_new_weight(
                current_weight, win_rate, sample_count, gene_id,
            )
            gene_data["weight"] = round(new_weight, 4)

        return result

    def _compute_new_weight(
        self,
        current_weight: float,
        win_rate: float,
        sample_count: int,
        gene_id: str,
    ) -> float:
        """计算新权重（公共逻辑，避免重复代码）。"""
        new_weight = current_weight
        if win_rate >= self.WEIGHT_UPGRADE_THRESHOLD:
            new_weight = current_weight * self.WEIGHT_UPGRADE_FACTOR
            logger.info(
                "[AutoWeight] %s 升级: %.3f → %.3f (win_rate=%.2f, n=%d)",
                gene_id, current_weight, new_weight, win_rate, sample_count,
            )
        elif win_rate < self.WEIGHT_DOWNGRADE_THRESHOLD:
            new_weight = current_weight * self.WEIGHT_DOWNGRADE_FACTOR
            logger.info(
                "[AutoWeight] %s 降级: %.3f → %.3f (win_rate=%.2f, n=%d)",
                gene_id, current_weight, new_weight, win_rate, sample_count,
            )
        return max(self.WEIGHT_FLOOR, min(self.WEIGHT_CEILING, new_weight))
