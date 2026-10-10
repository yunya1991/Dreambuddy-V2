"""ParameterReverseOptimizer — 策略参数逆向优化器。

P2 §5.3: 止损/止盈/超时参数的逆向优化
  - 若多次"方向对但被扫损"（CS≥0.7 & SL）→ 放宽止损
  - 若多次"方向对但超时" → 延长持仓时间

类比反向传播：参数调整幅度 = 错误模式频次 × 步长，有边界约束。
"""
from __future__ import annotations

import logging
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)


class ParameterReverseOptimizer:
    """基于交易模式的参数逆向优化器.

    跟踪两类可优化模式:
      1. 假失败 (CS≥0.7 & SL): 方向对但被扫损 → 放宽止损
      2. 超时 (CS≥0.7 & TIMEOUT): 方向对但超时 → 延长持仓

    冷启动保护: 样本 < threshold 时不调整。
    边界约束: stop_loss_mult ∈ [1.0, max_stop_loss_mult],
             timeout_mult ∈ [1.0, max_timeout_mult]。
    """

    FALSE_FAILURE_CS_THRESHOLD = 0.7

    def __init__(
        self,
        false_failure_threshold: int = 5,
        timeout_threshold: int = 5,
        max_stop_loss_mult: float = 2.0,
        max_timeout_mult: float = 3.0,
        step: float = 0.1,
        window_size: int = 100,
    ) -> None:
        self._false_failure_threshold = false_failure_threshold
        self._timeout_threshold = timeout_threshold
        self._max_stop_loss_mult = max_stop_loss_mult
        self._max_timeout_mult = max_timeout_mult
        self._step = step
        self._trades: deque[dict[str, Any]] = deque(maxlen=window_size)

    def record_trade(self, trade: dict[str, Any]) -> None:
        """记录一笔交易用于模式统计.

        Args:
            trade: {cs: float, outcome: str, symbol: str}
        """
        self._trades.append(trade)

    def optimize(self) -> dict[str, float]:
        """基于累积交易模式输出参数调整.

        Returns:
            {stop_loss_mult, timeout_mult, tp_mult}
            乘数 = 1.0 表示不调整。
        """
        false_failures = 0
        timeouts = 0
        for t in self._trades:
            cs = float(t.get("cs", 0.0))
            outcome = str(t.get("outcome", "")).upper()
            if cs >= self.FALSE_FAILURE_CS_THRESHOLD:
                if outcome == "SL":
                    false_failures += 1
                elif outcome == "TIMEOUT":
                    timeouts += 1

        # 假失败 → 放宽止损
        if false_failures >= self._false_failure_threshold:
            excess = false_failures - self._false_failure_threshold + 1
            stop_loss_mult = min(
                self._max_stop_loss_mult,
                1.0 + excess * self._step,
            )
        else:
            stop_loss_mult = 1.0

        # 超时 → 延长持仓
        if timeouts >= self._timeout_threshold:
            excess = timeouts - self._timeout_threshold + 1
            timeout_mult = min(
                self._max_timeout_mult,
                1.0 + excess * self._step,
            )
        else:
            timeout_mult = 1.0

        return {
            "stop_loss_mult": round(stop_loss_mult, 4),
            "timeout_mult": round(timeout_mult, 4),
            "tp_mult": 1.0,  # 止盈暂不逆向调整
        }

    def reset(self) -> None:
        """清空交易记录。"""
        self._trades.clear()
