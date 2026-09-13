"""
Phase 1.2: ESS 自适应 EMA 更新器
SPEC-AGI升级蓝图.md §4.1.2

核心：
  - EMA 衰减：近期样本权重更高，旧样本影响指数衰减
  - 高CS交易获得完整步长，不衰减
  - 冷启动阈值降至10样本（HC-AGI-02）
"""
from __future__ import annotations


class ESSAdaptiveUpdater:
    """ESS 自适应更新器 — EMA衰减 + 动态步长.

    ema_alpha: EMA 平滑系数，越大则近期样本权重越高（默认0.3）
    """

    COLD_START_THRESHOLD = 10  # HC-AGI-02: 冷启动阈值降至10样本

    def __init__(self, ema_alpha: float = 0.3) -> None:
        self.ema_alpha: float = float(ema_alpha)
        self._ema_delta: float = 0.0  # EMA 平滑后的有效 delta
        self._trade_count: int = 0

    def update(self, ess_delta: float, cs: float) -> float:
        """记录一笔交易的 ess_delta，返回 EMA 平滑后的有效 delta.

        EMA 公式: ema = alpha * new + (1-alpha) * old
        高CS(≥0.9)交易: 不衰减，直接用原始 delta
        低CS交易: 经 EMA 衰减
        """
        self._trade_count += 1
        # 高CS交易获得完整步长，不参与EMA衰减
        if cs >= 0.9:
            self._ema_delta = float(ess_delta)
            return self._ema_delta
        # 低/中CS交易: EMA 平滑
        self._ema_delta = self.ema_alpha * float(ess_delta) + (1.0 - self.ema_alpha) * self._ema_delta
        return self._ema_delta

    def effective_delta(self, ess_delta: float, cs: float) -> float:
        """计算给定 (ess_delta, cs) 的有效 delta（不更新内部状态）.

        用于查询：高CS返回原始delta，低CS返回EMA衰减后的值.
        """
        if cs >= 0.9:
            return float(ess_delta)
        # 模拟一次EMA更新（不修改内部状态）
        return self.ema_alpha * float(ess_delta) + (1.0 - self.ema_alpha) * self._ema_delta

    @property
    def trade_count(self) -> int:
        return self._trade_count

    def is_cold_start(self) -> bool:
        """冷启动判断：交易数 < COLD_START_THRESHOLD."""
        return self._trade_count < self.COLD_START_THRESHOLD
