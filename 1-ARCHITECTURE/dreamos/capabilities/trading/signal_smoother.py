"""
基本面信号平滑器 — 跨周期信号平滑与异常值过滤

对 F 链节点（F1-F5）输出的 score 做时间维度平滑：
    1. MAD 鲁棒限幅 — 过滤突发噪声（API 抖动、数据源异常）
    2. EWMA 指数平滑 — 降低单点信号的随机波动
    3. 置信度调整 — 平滑后偏离原始值越大，置信度衰减越多

设计:
    - 有状态：维护各节点 score 的历史序列
    - 单例：全局共享一个实例，跨周期累积
    - 安全：历史不足时返回原始值，不影响首次运行
    - 回测兼容：回测时每个 K 线调用 smooth()，自动累积历史
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

from dreamos.capabilities.trading.stats_utils import (
    ExponentialSmoother,
    robust_clip,
    mad_outlier_score,
)

logger = logging.getLogger(__name__)


class FundamentalSignalSmoother:
    """基本面信号平滑器（单例）

    维护 F1-F5 各节点的 score 历史，提供：
        - smooth_score(): 对原始 score 做鲁棒限幅 + EWMA 平滑
        - smooth_confidence(): 根据平滑偏离度调整置信度

    用法:
        smoother = get_smoother()
        smoothed_score, adj_conf = smoother.smooth("F2", raw_score, raw_conf)
    """

    # F 链节点列表
    F_NODES = ("F1", "F2", "F3", "F4", "F5")

    # 各节点的 EWMA 平滑系数
    # alpha 越大越响应新数据（弱平滑），越小越平滑（强平滑）
    # 基本面信号本就低频，过强平滑会导致滞后，采用弱平滑
    NODE_ALPHA = {
        "F1": 0.6,   # 新闻情绪：快速响应
        "F2": 0.5,   # 资金流：弱平滑
        "F3": 0.5,   # 估值：弱平滑
        "F4": 0.5,   # 链上：弱平滑
        "F5": 0.55,  # 宏观：弱平滑
    }

    def __init__(self):
        # 各节点的 EWMA 平滑器
        self._smoothers: Dict[str, ExponentialSmoother] = {}
        # 各节点的 score 历史（用于 MAD 异常检测）
        self._histories: Dict[str, list] = {}
        self._init_nodes()

    def _init_nodes(self) -> None:
        for node_id in self.F_NODES:
            alpha = self.NODE_ALPHA.get(node_id, 0.3)
            self._smoothers[node_id] = ExponentialSmoother(alpha=alpha)
            self._histories[node_id] = []

    def smooth_score(self, node_id: str, raw_score: float) -> float:
        """对 F 节点 score 做平滑处理

        步骤:
            1. MAD 鲁棒限幅 — 裁剪极端异常值
            2. EWMA 平滑 — 指数加权移动平均

        Args:
            node_id: 节点 ID（F1-F5）
            raw_score: 原始 score（通常在 [-1, 1] 范围）

        Returns:
            平滑后的 score
        """
        if node_id not in self._smoothers:
            return raw_score

        history = self._histories[node_id]

        # Step 1: MAD 鲁棒限幅（历史不足时跳过）
        clipped = robust_clip(raw_score, history, z_limit=3.5)

        # Step 2: EWMA 平滑
        smoothed = self._smoothers[node_id].update(clipped)

        # 记录历史（用限幅后的值，避免异常值污染历史）
        history.append(clipped)
        if len(history) > 100:
            history[:] = history[-100:]

        return smoothed

    def smooth_confidence(
        self, node_id: str, raw_confidence: float, raw_score: float, smoothed_score: float
    ) -> float:
        """根据平滑偏离度调整置信度

        平滑后 score 与原始值偏离越大，说明原始信号越可能是噪声，
        置信度应适当衰减。

        Args:
            node_id: 节点 ID
            raw_confidence: 原始置信度
            raw_score: 原始 score
            smoothed_score: 平滑后 score

        Returns:
            调整后的置信度
        """
        history = self._histories.get(node_id, [])

        # 异常分数 [0, 1]，越高越异常
        anomaly = mad_outlier_score(raw_score, history)

        # 平滑偏离度：原始与平滑的差异
        deviation = abs(raw_score - smoothed_score)

        # 置信度衰减因子
        # anomaly 高 → 衰减多；deviation 大 → 衰减多
        decay = 1.0 - 0.3 * anomaly - 0.2 * min(1.0, deviation / 0.5)
        decay = max(0.5, decay)  # 最低保留 50% 置信度

        return raw_confidence * decay

    def smooth(
        self, node_id: str, raw_score: float, raw_confidence: float = 0.5
    ) -> Tuple[float, float]:
        """一站式平滑：score + confidence

        Args:
            node_id: 节点 ID
            raw_score: 原始 score
            raw_confidence: 原始置信度

        Returns:
            (smoothed_score, adjusted_confidence)
        """
        smoothed = self.smooth_score(node_id, raw_score)
        adjusted = self.smooth_confidence(node_id, raw_confidence, raw_score, smoothed)
        return smoothed, adjusted

    def reset(self) -> None:
        """重置所有平滑器状态"""
        for node_id in self.F_NODES:
            self._smoothers[node_id].reset()
            self._histories[node_id] = []
        logger.info("信号平滑器已重置")

    def get_stats(self) -> Dict[str, Dict]:
        """获取各节点平滑状态"""
        stats = {}
        for node_id in self.F_NODES:
            es = self._smoothers[node_id]
            stats[node_id] = {
                "current_ewma": round(es.value, 4),
                "sample_count": es._count,
                "history_size": len(self._histories[node_id]),
                "alpha": es.alpha,
            }
        return stats


# ── 单例 ──
_smoother_instance: Optional[FundamentalSignalSmoother] = None


def get_smoother() -> FundamentalSignalSmoother:
    """获取全局信号平滑器单例"""
    global _smoother_instance
    if _smoother_instance is None:
        _smoother_instance = FundamentalSignalSmoother()
    return _smoother_instance


def reset_smoother() -> None:
    """重置全局平滑器（回测开始前调用）"""
    global _smoother_instance
    if _smoother_instance is not None:
        _smoother_instance.reset()
    else:
        _smoother_instance = FundamentalSignalSmoother()
