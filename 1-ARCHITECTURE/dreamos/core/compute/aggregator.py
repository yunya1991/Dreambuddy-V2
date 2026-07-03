"""
DreamOS C层 — 结果聚合器

职责:
    1. 聚合多个节点的执行结果
    2. 计算最终决策方向 (LONG/SHORT/HOLD)
    3. 计算最终置信度
    4. 加权融合各节点贡献

聚合策略:
    - 方向投票: 各节点方向投票，多数胜出
    - 置信度加权: 高置信度节点权重更大
    - 方向分歧大 → HOLD（不确定）
    - 必须节点缺失 → 置信度大打折扣
"""

from __future__ import annotations

from typing import Dict, List, Optional, Any
from collections import Counter

from dreamos.shared.state import State, NodeResult, NodeStatus

from .types import ExecutionReport, NodeExecutionRecord


class Aggregator:
    """结果聚合器

    用法:
        agg = Aggregator()
        report = agg.aggregate(state, node_ids=["A0", "A1", "A2", "A3"])
        print(report.final_action)       # "LONG"
        print(report.final_confidence)   # 0.72
    """

    # 方向权重：不同节点对最终方向的贡献权重
    DEFAULT_NODE_WEIGHTS: Dict[str, float] = {
        "A0": 1.0,   # 矛盾论
        "A1": 1.0,   # 趋势分析
        "A2": 1.2,   # 量价分析
        "A3": 1.5,   # 综合决策
        "A4": 2.0,   # 风控
        "C1": 0.8,   # 短线信号
        "C2": 0.8,   # 突破检测
        "F1": 0.9,   # 新闻分析
        "F2": 0.9,   # 资金流
        "F3": 0.7,   # 链上数据
    }

    # 置信度阈值
    CONFIDENCE_HOLD_THRESHOLD = 0.4      # 低于此值 → HOLD
    DIRECTION_DISAGREEMENT_THRESHOLD = 0.3  # 方向分歧 > 30% → HOLD

    def __init__(self, node_weights: Optional[Dict[str, float]] = None):
        self._weights = node_weights or dict(self.DEFAULT_NODE_WEIGHTS)

    def aggregate(self, state: State,
                  node_ids: Optional[List[str]] = None,
                  report: Optional[ExecutionReport] = None) -> ExecutionReport:
        """聚合结果

        Args:
            state: 全局状态
            node_ids: 参与聚合的节点 ID（None=全部）
            report: 已有的执行报告（可选）

        Returns:
            ExecutionReport: 包含聚合结果的报告
        """
        if report is None:
            report = ExecutionReport()

        ids = node_ids or list(state.results.keys())
        results: List[NodeResult] = [state.results[i] for i in ids if i in state.results]

        if not results:
            report.final_action = "HOLD"
            report.final_confidence = 0.0
            return report

        # ── 方向投票（加权） ─────────────────────────
        direction_scores: Dict[str, float] = {"LONG": 0.0, "SHORT": 0.0, "HOLD": 0.0, "NEUTRAL": 0.0}
        total_weight = 0.0

        for r in results:
            if not r.success or r.direction is None:
                continue
            weight = self._weights.get(r.node_id, 1.0) * r.confidence
            direction_scores[r.direction] = direction_scores.get(r.direction, 0.0) + weight
            total_weight += weight

        # 归一化
        if total_weight > 0:
            direction_scores = {k: v / total_weight for k, v in direction_scores.items()}
        report.final_direction_scores = direction_scores

        # ── 确定最终方向 ─────────────────────────────
        # 去掉 NEUTRAL 后看 LONG vs SHORT
        long_score = direction_scores.get("LONG", 0.0)
        short_score = direction_scores.get("SHORT", 0.0)

        if long_score > short_score and long_score > self.CONFIDENCE_HOLD_THRESHOLD:
            final_direction = "LONG"
        elif short_score > long_score and short_score > self.CONFIDENCE_HOLD_THRESHOLD:
            final_direction = "SHORT"
        else:
            final_direction = "HOLD"

        # 方向分歧检查
        non_neutral = long_score + short_score
        if non_neutral > 0:
            disagreement = 1.0 - abs(long_score - short_score) / non_neutral
            if disagreement > 1.0 - self.DIRECTION_DISAGREEMENT_THRESHOLD:
                final_direction = "HOLD"

        report.final_action = final_direction

        # ── 计算最终置信度 ───────────────────────────
        successful = [r for r in results if r.success and r.confidence > 0]
        if successful:
            # 加权平均置信度
            weighted_sum = sum(r.confidence * self._weights.get(r.node_id, 1.0) for r in successful)
            weight_sum = sum(self._weights.get(r.node_id, 1.0) for r in successful)
            report.final_confidence = round(weighted_sum / weight_sum if weight_sum > 0 else 0.0, 3)
        else:
            report.final_confidence = 0.0

        # 如果方向是 HOLD，置信度打折
        if final_direction == "HOLD":
            report.final_confidence *= 0.6

        return report

    def update_state(self, state: State, report: ExecutionReport) -> State:
        """将聚合结果写入 State"""
        state.final_action = report.final_action
        state.final_confidence = report.final_confidence
        return state
