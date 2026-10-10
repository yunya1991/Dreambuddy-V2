"""ReverseDerivationBacktest — 逆向推导回测验证。

P3: 模拟交易场景，对比启用/不启用逆向推导（因子权重调整）的胜率。

市场模型:
  - 3 个维度 C1/C2/C3，各自预测 long/short
  - C1 是噪声维度（预测准确率 ~40%，持续错）
  - C2/C3 是准确维度（预测准确率 ~70%）
  - 决策 = 加权投票（权重默认 1.0）
  - 逆向推导: 亏损交易后识别错误维度，降权其因子权重 (×0.9)

预期: 启用逆向推导后，噪声维度 C1 权重降低，决策更依赖 C2/C3，胜率提升。
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from reverse_deriver import ReverseDeriver

logger = logging.getLogger(__name__)


class ReverseDerivationBacktest:
    """逆向推导回测模拟器."""

    DIMS = ["C1", "C2", "C3"]

    def __init__(self, rng: np.random.RandomState | None = None) -> None:
        self._rng = rng or np.random.RandomState(0)
        self._deriver = ReverseDeriver()

    def run(self, enable_reverse: bool, n_trades: int = 200,
            warmup: int = 20) -> dict[str, Any]:
        """运行回测.

        Args:
            enable_reverse: 是否启用逆向推导（因子权重调整）
            n_trades: 总交易数
            warmup: 预热期（不启用逆向推导，积累初始样本）

        Returns:
            {win_rate, total_trades, wins, losses, final_weights}
        """
        weights = {d: 1.0 for d in self.DIMS}
        wins = 0
        losses = 0

        for i in range(n_trades):
            # 生成真实方向
            real_direction = "long" if self._rng.rand() > 0.5 else "short"

            # 各维度预测
            predictions = {}
            for dim in self.DIMS:
                acc = 0.40 if dim == "C1" else 0.70  # C1 噪声，C2/C3 准确
                predictions[dim] = (
                    real_direction if self._rng.rand() < acc
                    else ("short" if real_direction == "long" else "long")
                )

            # 加权投票决策
            long_score = sum(weights[d] for d, p in predictions.items() if p == "long")
            short_score = sum(weights[d] for d, p in predictions.items() if p == "short")
            action = "long" if long_score >= short_score else "short"

            # 结算
            is_win = action == real_direction
            if is_win:
                wins += 1
            else:
                losses += 1

            # 逆向推导（仅亏损交易 + 预热期后）
            if enable_reverse and not is_win and i >= warmup:
                snapshot = {
                    "symbol": "BACKTEST",
                    "dimension_predictions": predictions,
                    "dimension_factors": {d: {"f": 1.0} for d in self.DIMS},
                }
                outcome = {"real_direction": real_direction, "real_outcome": "SL"}
                derive_result = self._deriver.derive(snapshot, outcome)

                # 降权错误维度
                for dim in derive_result.wrong_dimensions:
                    weights[dim] = max(0.1, weights[dim] * 0.9)

        total = wins + losses
        return {
            "win_rate": wins / total if total > 0 else 0.0,
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "final_weights": weights,
        }
