"""ReverseDeriver — 金融逆向推导引擎。

从交易结果反推哪个矛盾维度判断错，类比神经网络反向传播：
- forward: 矛盾系统 + 矛盾Transformer → 预测
- loss: CS 一致性得分 + PnL
- backward: ReverseDeriver → per_dimension_error
- SGD: ESS/gmax/因子权重更新

借鉴 33-REA 的 Evidence-First：每条逆向结论带 confidence + known_gaps。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ReverseDeriveResult:
    """逆向推导结果。"""
    per_dimension_correctness: dict[str, bool] = field(default_factory=dict)
    per_dimension_cs: dict[str, float] = field(default_factory=dict)
    wrong_dimensions: list[str] = field(default_factory=list)
    root_cause: str = ""
    root_cause_type: str = "unknown"  # factor_error / weight_error / data_error / unknown
    confidence: float = 0.0
    known_gaps: list[str] = field(default_factory=list)
    optimization_action: str = "no_adjustment"


class ReverseDeriver:
    """逆向推导器：从交易结果反推哪个矛盾维度判断错。

    四步法：
    1. 对比每个矛盾维度的预测方向 vs 实际方向
    2. 定位主要矛盾的判断是否正确
    3. 根因分类（factor_error / weight_error / data_error）
    4. 输出 optimization_action
    """

    VALID_DIRECTIONS = {"long", "short", "wait"}

    def derive(self, snapshot: dict[str, Any], outcome: dict[str, Any]) -> ReverseDeriveResult:
        """执行逆向推导。

        Args:
            snapshot: 开仓快照，须含 dimension_predictions: {C1: "long", C2: "short", ...}
            outcome: 交易结果，须含 real_direction: "long"/"short"

        Returns:
            ReverseDeriveResult（FAIL-OPEN：输入不完整时返回 neutral）
        """
        try:
            dim_predictions = snapshot.get("dimension_predictions")
            real_direction = outcome.get("real_direction")

            # FAIL-OPEN：缺少必要数据
            if not dim_predictions or not real_direction:
                return self._neutral_result(snapshot, outcome,
                    "缺少 dimension_predictions 或 real_direction")

            real_direction = str(real_direction).lower()
            if real_direction not in self.VALID_DIRECTIONS:
                return self._neutral_result(snapshot, outcome,
                    f"无效 real_direction: {real_direction}")

            # Step 1: 每维度正确性
            per_dim_correctness: dict[str, bool] = {}
            per_dim_cs: dict[str, float] = {}
            for dim, pred_dir in dim_predictions.items():
                pred_dir = str(pred_dir).lower()
                correct = self._direction_match(pred_dir, real_direction)
                per_dim_correctness[dim] = correct
                per_dim_cs[dim] = 1.0 if correct else -1.0

            wrong_dims = [d for d, c in per_dim_correctness.items() if not c]

            # Step 2-3: 根因分析
            root_cause, root_cause_type = self._analyze_root_cause(
                per_dim_correctness, snapshot, outcome)

            # Step 4: 优化动作
            optimization_action = self._recommend_action(
                wrong_dims, root_cause_type, outcome)

            # 置信度：正确维度占比
            total = len(per_dim_correctness)
            correct_count = sum(per_dim_correctness.values())
            confidence = round(correct_count / total, 3) if total > 0 else 0.0

            known_gaps = [
                "维度预测方向来自 PrimaryContradictionIdentifier 输入 paths",
                "因子值缺失时无法区分 factor_error 与 data_error",
                "动态调用/条件分支的维度判断可能不准确",
            ]

            return ReverseDeriveResult(
                per_dimension_correctness=per_dim_correctness,
                per_dimension_cs=per_dim_cs,
                wrong_dimensions=wrong_dims,
                root_cause=root_cause,
                root_cause_type=root_cause_type,
                confidence=confidence,
                known_gaps=known_gaps,
                optimization_action=optimization_action,
            )
        except Exception as e:
            logger.warning("[FO] ReverseDeriver fail: %s", e)
            return self._neutral_result(snapshot, outcome, str(e))

    # ------------------------------------------------------------------
    def _direction_match(self, pred: str, real: str) -> bool:
        """预测方向与实际方向是否一致（wait 始终算不匹配）。"""
        if pred not in self.VALID_DIRECTIONS or real not in self.VALID_DIRECTIONS:
            return False
        if pred == "wait" or real == "wait":
            return False
        return pred == real

    def _analyze_root_cause(self, per_dim_correctness: dict[str, bool],
                             snapshot: dict, outcome: dict) -> tuple[str, str]:
        """根因分类。"""
        wrong_dims = [d for d, c in per_dim_correctness.items() if not c]
        total = len(per_dim_correctness)

        if not wrong_dims:
            return "所有维度判断正确", "unknown"

        wrong_ratio = len(wrong_dims) / total if total > 0 else 0

        # 多数维度判断错 → 可能是权重问题（主导维度权重不足）
        if wrong_ratio >= 0.5:
            return (f"多数维度({len(wrong_dims)}/{total})判断错误，"
                    f"可能是维度权重分配不当", "weight_error")

        # 少数维度判断错 → 可能是该维度因子计算问题
        if wrong_ratio < 0.5:
            return (f"少数维度({','.join(wrong_dims)})判断错误，"
                    f"可能是因子计算或数据源问题", "factor_error")

        return "判断错误原因待查", "unknown"

    def _recommend_action(self, wrong_dims: list[str], root_cause_type: str,
                          outcome: dict) -> str:
        """建议优化动作。"""
        if not wrong_dims:
            return "no_adjustment"

        real_outcome = str(outcome.get("real_outcome", "")).upper()

        # 亏损且有错误维度 → 降权
        if real_outcome == "SL":
            if root_cause_type == "weight_error":
                return f"降低错误维度权重: {wrong_dims}"
            if root_cause_type == "factor_error":
                return f"审计错误维度因子: {wrong_dims}"
            return f"检查维度: {wrong_dims}"

        # 盈利但有错误维度 → 假成功，谨慎处理
        if real_outcome == "TP":
            return f"记录假成功案例(维度错但盈利): {wrong_dims}"

        return f"监控维度: {wrong_dims}"

    def _neutral_result(self, snapshot: dict, outcome: dict,
                        reason: str) -> ReverseDeriveResult:
        """FAIL-OPEN 中性结果。"""
        return ReverseDeriveResult(
            per_dimension_correctness={},
            per_dimension_cs={},
            wrong_dimensions=[],
            root_cause=f"reverse_derive_failed: {reason}",
            root_cause_type="unknown",
            confidence=0.0,
            known_gaps=[f"逆向推导失败: {reason}"],
            optimization_action="no_adjustment",
        )
