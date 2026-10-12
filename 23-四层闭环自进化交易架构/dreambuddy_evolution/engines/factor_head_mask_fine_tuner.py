"""FactorHeadMaskFineTuner — 矛盾Transformer factor_head_mask 微调器。

SPEC §5.4: 用逆向推导的标注数据（哪个维度该赢）微调 factor_head_mask，
降低错误维度的 head 权重，提升正确维度的相对影响力。

类比反向传播中对错误梯度方向的参数更新：
- wrong_dim → 该维度 head 权重 ×0.8 降权
- correct_dim → 不变（避免过度调整）
- 边界约束 [0.1, 1.0]
- FAIL-OPEN：无效输入返回原 mask

生产接线（P2-1b）: engines/reverse_cognitive_bridge.record_evidence(wrong_dims)
→ gene_data/factor_head_mask_override.json →
core/exogenous_data_bridge.build_factor_head_mask 应用 log(m) 负偏置
（cross_attention additive bias 语义：0.0=无影响，负值=抑制）。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class FactorHeadMaskFineTuner:
    """factor_head_mask 微调器：基于逆向推导结果调整维度 head 权重。"""

    DOWNGRADE_MULT = 0.8  # 错误维度降权 20%
    MIN_WEIGHT = 0.1
    MAX_WEIGHT = 1.0

    def adjust(self, current_mask: Any, wrong_dimensions: list[str]) -> Any:
        """根据错误维度调整 factor_head_mask。

        Args:
            current_mask: {维度: 权重} 字典，如 {"C1": 1.0, "C2": 0.8}
            wrong_dimensions: 逆向推导判定的错误维度列表

        Returns:
            调整后的 mask 字典；无效输入时 FAIL-OPEN 返回原 mask
        """
        try:
            if not isinstance(current_mask, dict) or not current_mask:
                return current_mask

            wrong_set = set(wrong_dimensions or [])
            if not wrong_set:
                return dict(current_mask)

            adjusted: dict[str, float] = {}
            for dim, weight in current_mask.items():
                try:
                    w = float(weight)
                except (TypeError, ValueError):
                    adjusted[dim] = weight
                    continue

                if dim in wrong_set:
                    w = w * self.DOWNGRADE_MULT

                # 边界约束
                w = max(self.MIN_WEIGHT, min(self.MAX_WEIGHT, w))
                adjusted[dim] = round(w, 6)

            return adjusted
        except Exception as e:
            logger.warning("[FO] FactorHeadMaskFineTuner.adjust fail: %s", e)
            return current_mask
