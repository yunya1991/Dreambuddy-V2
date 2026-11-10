"""ASIL Kill Switch 链 — 复用 4-MEMORY drift_detector。

SPEC v0.2 §6.1 L0-L4 分层。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class KillSwitchAction:
    """Kill Switch 动作。"""

    level: str  # L0 / L1 / L2 / L3 / L4
    action: str  # no_op / reduce_position / pause_new / halt_all
    reason: str = ""


class KillSwitchMonitor:
    """ASIL Kill Switch 监控器 — 分层 Fail-closed。"""

    def __init__(self):
        self.current_level = "L0"
        self._continuous_fail_days = 0

    def check(
        self,
        drift_level: str,
        oracle_confidence: float,
        pnl_sharpe: Optional[float] = None,
        consecutive_falsified: int = 0,
        daily_loss_pct: float = 0.0,
    ) -> KillSwitchAction:
        """按 SPEC §6.1 分层规则检查。"""
        # L4 Halt
        if daily_loss_pct >= 0.02 and drift_level == "severe_drift" and consecutive_falsified >= 3:
            self.current_level = "L4"
            return KillSwitchAction("L4", "halt_all", "日亏2%+严重漂移+3次falsified")

        # L3 Pause
        if self._continuous_fail_days >= 3 and (pnl_sharpe is not None and pnl_sharpe < 0.5):
            self.current_level = "L3"
            return KillSwitchAction("L3", "pause_new", "连续3天L2+Sharpe<0.5")

        # L2 Reduce
        if drift_level == "severe_drift":
            self.current_level = "L2"
            return KillSwitchAction("L2", "reduce_position", "severe_drift")

        # L1 Warning
        if drift_level == "minor_drift" or oracle_confidence < 0.5:
            self.current_level = "L1"
            return KillSwitchAction("L1", "no_op", "minor_drift or oracle_low")

        # L0 Normal
        self.current_level = "L0"
        return KillSwitchAction("L0", "no_op", "stable")
