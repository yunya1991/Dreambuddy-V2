"""影子模式自动晋升管理器。

需求：影子模式运行到一定阶段/阈值后自动开启（晋升到 live 模式）。

状态机：shadow ↔ live，带滞回（晋升阈值 + 降级阈值 + 最短驻留时间）。

晋升条件（全部满足，且当前为 shadow）：
- 训练样本数 >= min_samples
- AUC >= promote_auc_threshold
- ECE <= promote_ece_threshold
- PSI <= promote_psi_threshold
- shadow 驻留时间 >= min_shadow_dwell_seconds

降级条件（任一满足，且当前为 live，且 live 驻留 >= min_live_dwell_seconds）：
- AUC < demote_auc_threshold（比 promote 低 → 滞回）
- ECE > demote_ece_threshold（比 promote 高 → 滞回）
- PSI > demote_psi_threshold（比 promote 高 → 滞回）

设计依据（来自经验 VM-100018222）：
- 进入/退出使用不同阈值形成滞回，避免边界抖动
- 最短驻留时间防止频繁切换
- 状态推进单点写入（evaluate 是唯一修改 state 的入口）
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AutoPromotionConfig:
    """自动晋升配置。"""
    # 晋升阈值（进入 live 模式）
    min_samples: int = 50
    promote_auc_threshold: float = 0.70
    promote_ece_threshold: float = 0.15
    promote_psi_threshold: float = 0.10
    # 降级阈值（退回 shadow 模式，比晋升阈值宽松 → 滞回）
    demote_auc_threshold: float = 0.55
    demote_ece_threshold: float = 0.25
    demote_psi_threshold: float = 0.20
    # 最短驻留时间（秒）
    min_shadow_dwell_seconds: float = 300.0  # shadow 至少 5 分钟
    min_live_dwell_seconds: float = 600.0    # live 至少 10 分钟
    # 是否启用自动晋升
    enabled: bool = True


@dataclass
class PromotionDecision:
    """一次 evaluate 的决策结果。"""
    promoted: bool = False
    demoted: bool = False
    reason: str = ""  # 不晋升/不降级的原因
    metrics: Dict[str, float] = field(default_factory=dict)


class AutoPromotionManager:
    """影子模式自动晋升状态机。"""

    STATE_SHADOW = "shadow"
    STATE_LIVE = "live"

    def __init__(self, config: Optional[AutoPromotionConfig] = None):
        self._config = config or AutoPromotionConfig()
        self._state = self.STATE_SHADOW
        self._state_entered_at: float = time.time()
        self._metrics_history: List[Dict[str, Any]] = []
        self._event_log: List[Dict[str, Any]] = []

    @property
    def config(self) -> AutoPromotionConfig:
        return self._config

    def is_shadow_mode(self) -> bool:
        return self._state == self.STATE_SHADOW

    def is_live_mode(self) -> bool:
        return self._state == self.STATE_LIVE

    def current_state(self) -> str:
        return self._state

    def dwell_time(self) -> float:
        """当前状态已驻留时间（秒）。"""
        return time.time() - self._state_entered_at

    def evaluate(
        self,
        sample_count: int,
        auc: float,
        ece: float,
        psi: float,
    ) -> PromotionDecision:
        """评估是否需要晋升或降级。

        这是唯一修改状态的入口（单点写入）。
        """
        metrics = {
            "sample_count": float(sample_count),
            "auc": float(auc),
            "ece": float(ece),
            "psi": float(psi),
            "ts": time.time(),
            "state": self._state,
        }
        self._metrics_history.append(metrics)

        if not self._config.enabled:
            return PromotionDecision(metrics=metrics)

        if self._state == self.STATE_SHADOW:
            return self._try_promote(sample_count, auc, ece, psi, metrics)
        else:
            return self._try_demote(auc, ece, psi, metrics)

    def _try_promote(
        self,
        sample_count: int,
        auc: float,
        ece: float,
        psi: float,
        metrics: Dict[str, Any],
    ) -> PromotionDecision:
        cfg = self._config

        # 最短驻留时间检查（最先检查，避免无意义计算）
        if self.dwell_time() < cfg.min_shadow_dwell_seconds:
            return PromotionDecision(reason="min_shadow_dwell_not_met", metrics=metrics)

        # 样本数
        if sample_count < cfg.min_samples:
            return PromotionDecision(reason="insufficient_samples", metrics=metrics)

        # AUC
        if auc < cfg.promote_auc_threshold:
            return PromotionDecision(reason="auc_below_promote_threshold", metrics=metrics)

        # ECE
        if ece > cfg.promote_ece_threshold:
            return PromotionDecision(reason="ece_above_promote_threshold", metrics=metrics)

        # PSI
        if psi > cfg.promote_psi_threshold:
            return PromotionDecision(reason="psi_above_promote_threshold", metrics=metrics)

        # 全部满足 → 晋升
        self._transition_to(self.STATE_LIVE, reason="all_promote_conditions_met")
        return PromotionDecision(promoted=True, reason="promoted", metrics=metrics)

    def _try_demote(
        self,
        auc: float,
        ece: float,
        psi: float,
        metrics: Dict[str, Any],
    ) -> PromotionDecision:
        cfg = self._config

        # 最短驻留时间检查
        if self.dwell_time() < cfg.min_live_dwell_seconds:
            return PromotionDecision(reason="min_live_dwell_not_met", metrics=metrics)

        # 任一降级条件满足 → 降级
        if auc < cfg.demote_auc_threshold:
            self._transition_to(self.STATE_SHADOW, reason="auc_below_demote_threshold")
            return PromotionDecision(demoted=True, reason="demoted_auc", metrics=metrics)

        if ece > cfg.demote_ece_threshold:
            self._transition_to(self.STATE_SHADOW, reason="ece_above_demote_threshold")
            return PromotionDecision(demoted=True, reason="demoted_ece", metrics=metrics)

        if psi > cfg.demote_psi_threshold:
            self._transition_to(self.STATE_SHADOW, reason="psi_above_demote_threshold")
            return PromotionDecision(demoted=True, reason="demoted_psi", metrics=metrics)

        return PromotionDecision(reason="no_demote_condition_met", metrics=metrics)

    def _transition_to(self, new_state: str, reason: str) -> None:
        """状态切换（单点写入）。"""
        old_state = self._state
        self._state = new_state
        self._state_entered_at = time.time()
        self._event_log.append({
            "event": "promoted" if new_state == self.STATE_LIVE else "demoted",
            "from": old_state,
            "to": new_state,
            "reason": reason,
            "ts": time.time(),
        })

    def force_live(self) -> None:
        """强制切换到 live 模式（手动覆盖）。"""
        self._transition_to(self.STATE_LIVE, reason="forced_live")

    def force_shadow(self) -> None:
        """强制切换到 shadow 模式（手动覆盖）。"""
        self._transition_to(self.STATE_SHADOW, reason="forced_shadow")

    def metrics_history(self) -> List[Dict[str, Any]]:
        return list(self._metrics_history)

    def event_log(self) -> List[Dict[str, Any]]:
        return list(self._event_log)
