"""ablation_gate.py — E2 前置：决策级准入 gate 最小实现（SPEC v0.5 §4 E2 / P0#2）。

全仓 grep 无 ablation gate 实现（v0.4 评审结论），本模块按要求**新建**：
  - 不复制 45 评测系统的 backtest 统计内核，只做**决策级准入封装**
  - 双判据：过拟合（IS→OOS 退化）+ 稳定性（切片一致）
  - 附加硬约束：最小样本 + 「不优于基线即丢弃」

阈值权属 45-评测系统（SPEC v0.4）。下列默认值为本地护栏，**不是**可优化目标；
调用方可显式传参覆盖，但 48 域不得为出涌现指标而放宽（VM-1793798309647）。

无评估器（未接入 45/11 域 config 级回测）时如实返回 evaluator_missing，
不伪造指标——由 run_e2 发 E6 需求单。

FAIL-OPEN：异常不外抛，降级为 admitted=False + reason。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# 本地护栏（阈值定义权属 45-评测系统，此处仅决策级准入封装）
DEFAULT_MIN_TRADES = 10
DEFAULT_MAX_OVERFIT_DEGRADATION = 0.5  # IS→OOS 相对退化上限
DEFAULT_MIN_SLICE_WIN_RATIO = 0.6  # 切片非负比例下限
DEFAULT_MIN_SLICES = 3
DEFAULT_METRIC_KEY = "total_pnl_pct"
_EPS = 1e-9


def evaluate(
    is_metrics: Optional[Dict[str, Any]],
    oos_metrics: Optional[Dict[str, Any]],
    slice_metrics: Optional[Sequence[float]] = None,
    baseline_oos: Optional[Dict[str, Any]] = None,
    metric_key: str = DEFAULT_METRIC_KEY,
    min_trades: int = DEFAULT_MIN_TRADES,
    max_overfit_degradation: float = DEFAULT_MAX_OVERFIT_DEGRADATION,
    min_slice_win_ratio: float = DEFAULT_MIN_SLICE_WIN_RATIO,
    min_slices: int = DEFAULT_MIN_SLICES,
) -> Dict[str, Any]:
    """决策级准入判定。

    Args:
        is_metrics: 样本内指标（含 metric_key 与 n_trades）
        oos_metrics: 样本外指标
        slice_metrics: 分片/regime 窗口指标序列（稳定性判据必需）
        baseline_oos: 人工基线 OOS 指标（不优于基线即拒）

    Returns:
        {admitted, status, reasons, is_oos_degradation, stability_win_ratio, n_trades}
    """
    try:
        if is_metrics is None or oos_metrics is None:
            return {
                "admitted": False,
                "status": "evaluator_missing",
                "reasons": ["evaluator_missing: 无 config 级回测评估器，未做任何指标判定"],
                "is_oos_degradation": None,
                "stability_win_ratio": None,
                "n_trades": None,
            }

        reasons: List[str] = []
        is_val = float(is_metrics.get(metric_key, 0.0))
        oos_val = float(oos_metrics.get(metric_key, 0.0))
        n_trades = int(oos_metrics.get("n_trades", 0) or 0)
        degradation = (is_val - oos_val) / max(abs(is_val), _EPS)

        # 判据 1：过拟合（样本外相对退化超阈）
        if degradation > max_overfit_degradation:
            reasons.append(f"overfit_degradation={degradation:.3f} > {max_overfit_degradation}")

        # 判据 2：稳定性（切片一致；缺失即不可准入）
        stability_win_ratio = None
        if slice_metrics is None or len(slice_metrics) < min_slices:
            reasons.append("stability_unavailable: 分片指标不足，双判据不可同时成立")
        else:
            vals = [float(x) for x in slice_metrics]
            stability_win_ratio = sum(1 for x in vals if x >= 0) / len(vals)
            if stability_win_ratio < min_slice_win_ratio:
                reasons.append(
                    f"stability_win_ratio={stability_win_ratio:.3f} < {min_slice_win_ratio}"
                )

        # 附加：最小样本
        if n_trades < min_trades:
            reasons.append(f"insufficient_sample: n_trades={n_trades} < {min_trades}")

        # 附加：不优于基线即丢弃
        if baseline_oos is not None:
            base_val = float(baseline_oos.get(metric_key, 0.0))
            if oos_val <= base_val:
                reasons.append(
                    f"not_better_than_baseline: oos={oos_val:.4f} <= baseline={base_val:.4f}"
                )

        return {
            "admitted": not reasons,
            "status": "ok",
            "reasons": reasons,
            "is_oos_degradation": degradation,
            "stability_win_ratio": stability_win_ratio,
            "n_trades": n_trades,
        }
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("ablation gate FAIL-OPEN: %s", exc)
        return {
            "admitted": False,
            "status": "error",
            "reasons": [f"gate_error: {exc}"],
            "is_oos_degradation": None,
            "stability_win_ratio": None,
            "n_trades": None,
        }
