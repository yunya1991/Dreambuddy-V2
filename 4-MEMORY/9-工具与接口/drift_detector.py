"""TB1 PSI 漂移检测器 — SPEC-L0-AGENT-TRAIN-BASE v0.1 §1

三重漂移检测：PSI（总体稳定性指数）+ KS 检验 + 分层告警开关。

硬约束（H8）：阈值硬编码，无 env override 路径，禁止运行时调整。
依赖：numpy + scipy.stats（KS 检验）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
from scipy import stats

# ---------------------------------------------------------------------------
# H8 硬编码阈值（禁止 env override / 运行期调整）
# ---------------------------------------------------------------------------
PSI_STABLE: float = 0.1  # psi < 0.1 → stable
PSI_MINOR_DRIFT: float = 0.25  # 0.1 <= psi < 0.25 → minor_drift; >= 0.25 → severe_drift
KS_ALPHA: float = 0.01  # KS 检验显著性水平

# 浮点边界 epsilon（经验 VM-1792148857896：防 psi==0.1/0.25 边界浮点坑）
_EPSILON: float = 1e-9

# PSI 分箱默认值
_PSI_BINS: int = 10


# ---------------------------------------------------------------------------
# PSI 计算
# ---------------------------------------------------------------------------
def compute_psi(
    expected: Sequence[float],
    actual: Sequence[float],
    bins: int = _PSI_BINS,
) -> float:
    """计算 PSI（Population Stability Index）。

    expected: 基线分布样本；actual: 当前分布样本。
    分箱基于 expected 的分位数边界，比例加平滑项兜底防除零。
    """
    expected_arr = np.asarray(expected, dtype=float)
    actual_arr = np.asarray(actual, dtype=float)
    if expected_arr.size == 0 or actual_arr.size == 0:
        raise ValueError("compute_psi: expected/actual 不能为空")

    # 基于 expected 分位数分箱（等频）
    quantiles = np.linspace(0.0, 1.0, bins + 1)
    edges = np.unique(np.quantile(expected_arr, quantiles))
    if edges.size < 2:
        # 常量基线：退化为单箱比较均值偏移
        edges = np.array([edges[0], edges[0] + 1.0])

    expected_counts = np.histogram(expected_arr, bins=edges)[0]
    actual_counts = np.histogram(actual_arr, bins=edges)[0]

    expected_ratio = (expected_counts + 1e-6) / (expected_arr.size + 1e-6 * edges.size)
    actual_ratio = (actual_counts + 1e-6) / (actual_arr.size + 1e-6 * edges.size)

    psi = float(np.sum((actual_ratio - expected_ratio) * np.log(actual_ratio / expected_ratio)))
    return max(psi, 0.0)


def ks_test_drift(
    expected: Sequence[float],
    actual: Sequence[float],
    alpha: float = KS_ALPHA,
) -> Tuple[bool, float]:
    """KS 双样本检验。返回 (是否检出漂移, p_value)。"""
    ks_stat, p_value = stats.ks_2samp(
        np.asarray(expected, dtype=float),
        np.asarray(actual, dtype=float),
    )
    return bool(p_value < alpha), float(p_value)


# ---------------------------------------------------------------------------
# 三档分类
# ---------------------------------------------------------------------------
def classify_drift(psi_value: float) -> str:
    """PSI 三档分类（H8 阈值硬编码）。

    - psi < 0.1            → "stable"
    - 0.1 <= psi < 0.25    → "minor_drift"
    - psi >= 0.25          → "severe_drift"

    边界加 epsilon 防浮点坑（VM-1792148857896）：
    距阈值 <1e-9 的值归入更低一档（如 0.099999999 → stable），
    阈值本身（0.1/0.25）严格归入更高一档。
    """
    if psi_value <= PSI_STABLE - _EPSILON:
        return "stable"
    if psi_value <= PSI_MINOR_DRIFT - _EPSILON:
        return "minor_drift"
    return "severe_drift"


def classify_drift_triple(
    psi_value: float,
    ks_drifted: bool,
    _principal: Optional[str] = None,
) -> str:
    """PSI + KS 三重融合判定（SPEC §1.4 RED 8）。

    规则：KS 检出漂移时，在 PSI 档位基础上升级一档：
      stable + KS drifted     → "minor_drift"
      minor_drift + KS drifted → "severe_drift"
      severe_drift + KS drifted → "severe_drift"（已最高档）
    """
    level = classify_drift(psi_value)
    if not ks_drifted:
        return level
    if level == "stable":
        return "minor_drift"
    return "severe_drift"


# ---------------------------------------------------------------------------
# 分层告警开关（fail-closed，告警型非执行型）
# ---------------------------------------------------------------------------
KILL_SWITCH_TIERS: Tuple[str, ...] = (
    "reduce_position_50%",
    "pause_new",
    "halt_all",
)

_TIER_INDEX: Dict[str, int] = {name: idx for idx, name in enumerate(KILL_SWITCH_TIERS)}


@dataclass
class DriftKillSwitchState:
    """drift_kill_switch 状态（fail-closed：异常时按最高档处理）。"""

    current_tier: Optional[str] = None
    alert_log: List[Dict] = field(default_factory=list)

    def escalate(self, drift_level: str, trace_id: str = "") -> Dict:
        """按漂移等级升级开关档位，返回本次动作记录。

        - stable      → Level 1 log_alert（不升级档位）
        - minor_drift → Level 1 log_alert + 升至第 1 档
        - severe_drift → Level 2 kill_switch + 升至第 2 档（pause_new）
        - 未知等级    → fail-closed，直接 halt_all
        """
        if drift_level == "stable":
            action = {
                "level": 1,
                "action": "log_alert",
                "tier": self.current_tier,
                "trace_id": trace_id,
            }
            self.alert_log.append(action)
            return action

        if drift_level == "minor_drift":
            target = KILL_SWITCH_TIERS[0]
        elif drift_level == "severe_drift":
            target = KILL_SWITCH_TIERS[1]
        else:
            # fail-closed：未知等级按最高档处理
            target = KILL_SWITCH_TIERS[-1]

        # 只升不降
        if self.current_tier is None or _TIER_INDEX[target] > _TIER_INDEX[self.current_tier]:
            self.current_tier = target

        action = {
            "level": 2,
            "action": "kill_switch",
            "tier": self.current_tier,
            "trace_id": trace_id,
        }
        self.alert_log.append(action)
        return action


def drift_kill_switch(
    psi_value_or_level: Union[float, str],
    state: Optional[DriftKillSwitchState] = None,
    trace_id: str = "",
    context: Optional[Dict] = None,
    _principal: Optional[str] = None,
) -> Dict:
    """Fail-closed 分层 Kill Switch，兼容两种调用形态（SPEC §1.4 RED 9）：

    1) 便捷形态（psi 数值 + 有状态阶梯）：
       drift_kill_switch(0.3, state) → {"psi_value":…, "drift_level":…, "kill_switch": {level, action, tier}}
    2) SPEC 形态（等级字符串 + 上下文，无状态）：
       drift_kill_switch("severe_drift", context={"reason": "…", "trace_id": "t1"})
       → {"action": "kill_switch", "level": 2, "tiers": [...], "reason": …, "trace_id": …}
    """
    if isinstance(psi_value_or_level, str):
        drift_level = psi_value_or_level
        ctx = context or {}
        if drift_level == "stable":
            return {"action": "no_op", "level": 0}
        if drift_level == "minor_drift":
            return {
                "action": "log_alert",
                "level": 1,
                "reason": ctx.get("reason"),
                "trace_id": ctx.get("trace_id", trace_id),
            }
        return {
            "action": "kill_switch",
            "level": 2,
            "tiers": list(KILL_SWITCH_TIERS),
            "reason": ctx.get("reason"),
            "trace_id": ctx.get("trace_id", trace_id),
        }

    if state is None:
        state = DriftKillSwitchState()
    drift_level = classify_drift(psi_value_or_level)
    action = state.escalate(drift_level, trace_id=trace_id)
    return {
        "psi_value": psi_value_or_level,
        "drift_level": drift_level,
        "kill_switch": action,
    }
