"""ASIL 六种触发源扫描 + 冷却时间 + 合并策略。

SPEC v0.2 §1.3：六种触发源、冷却时间表、同类型合并。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# SPEC v0.2 §1.3 冷却时间（秒）
# ---------------------------------------------------------------------------
TRIGGER_COOLDOWN: Dict[str, float] = {
    "low_confidence_memory": 48 * 3600,  # 48h
    "gap_router": 72 * 3600,  # 72h
    "active_reflection": 24 * 3600,  # 24h
    "verdict_feedback": 0,  # 即时触发（轻量）
    "psi_drift": 24 * 3600,  # 24h
    "psi_severe_drift": 72 * 3600,  # 72h
}


@dataclass
class PipelineTrigger:
    """Pipeline 触发事件。"""

    type: str
    source: str
    evidence: Dict = field(default_factory=dict)
    psi_value: Optional[float] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "type": self.type,
            "source": self.source,
            "evidence": self.evidence,
            "psi_value": self.psi_value,
            "timestamp": self.timestamp,
        }


class TriggerScanner:
    """ASIL 触发扫描器 — 六种触发源 + 冷却 + 合并。"""

    def __init__(self, cooldown: Optional[Dict[str, float]] = None):
        self.cooldown = cooldown or TRIGGER_COOLDOWN
        self._last_trigger: Dict[str, float] = {}  # type → last trigger timestamp
        self._freq_count: Dict[str, int] = {}  # type → today's count

    # ------------------------------------------------------------------
    # 冷却检查
    # ------------------------------------------------------------------
    def _in_cooldown(self, trigger_type: str) -> bool:
        last = self._last_trigger.get(trigger_type, 0)
        cd = self.cooldown.get(trigger_type, 24 * 3600)
        return (time.time() - last) < cd

    def _record_trigger(self, trigger_type: str) -> None:
        self._last_trigger[trigger_type] = time.time()
        self._freq_count[trigger_type] = self._freq_count.get(trigger_type, 0) + 1

    # ------------------------------------------------------------------
    # 触发扫描入口 — Phase 1 不接真实外部系统，用 stub 数据
    # ------------------------------------------------------------------
    def scan(
        self,
        c_level_ratio: float = 0.67,
        open_gaps: int = 5,
        psi_value: float = 0.05,
    ) -> List[PipelineTrigger]:
        """扫描六种触发源。

        Phase 1 stub：不接真实认知库/capability_gaps.jsonl，
        参数传入模拟值用于验证管道跑通。
        """
        triggers: List[PipelineTrigger] = []

        # ① 低置信记忆
        if c_level_ratio > 0.6 and not self._in_cooldown("low_confidence_memory"):
            triggers.append(
                PipelineTrigger(
                    type="low_confidence_memory",
                    source="C级记忆扫描",
                    evidence={"ratio": c_level_ratio, "threshold": 0.6},
                )
            )
            self._record_trigger("low_confidence_memory")

        # ② E6 需求单
        if open_gaps >= 1 and not self._in_cooldown("gap_router"):
            triggers.append(
                PipelineTrigger(
                    type="gap_router",
                    source=f"capability_gaps.jsonl open={open_gaps}",
                    evidence={"n_open": open_gaps},
                )
            )
            self._record_trigger("gap_router")

        # ③ PSI 漂移
        if psi_value > 0.25 and not self._in_cooldown("psi_severe_drift"):
            triggers.append(
                PipelineTrigger(
                    type="psi_severe_drift",
                    source=f"PSI={psi_value:.3f}",
                    evidence={"psi": psi_value},
                    psi_value=psi_value,
                )
            )
            self._record_trigger("psi_severe_drift")
        elif psi_value > 0.1 and not self._in_cooldown("psi_drift"):
            triggers.append(
                PipelineTrigger(
                    type="psi_drift",
                    source=f"PSI={psi_value:.3f}",
                    evidence={"psi": psi_value},
                    psi_value=psi_value,
                )
            )
            self._record_trigger("psi_drift")

        return triggers

    # ------------------------------------------------------------------
    # Phase 1 主动反思 stub
    # ------------------------------------------------------------------
    def scan_active_reflection(self, n_fail_sessions: int = 3) -> List[PipelineTrigger]:
        """主动反思触发 — 每日定时扫描失败 session。"""
        if self._in_cooldown("active_reflection"):
            return []
        if n_fail_sessions == 0:
            return []
        self._record_trigger("active_reflection")
        return [
            PipelineTrigger(
                type="active_reflection",
                source=f"前一天 {n_fail_sessions} 个失败 session",
                evidence={"n_fail": n_fail_sessions},
            )
        ]

    def scan_verdict_feedback(self, n_new_candidates: int = 1) -> List[PipelineTrigger]:
        """实验 verdict 反馈触发 — 轻量，只跑 Step⑦。"""
        if n_new_candidates <= 0:
            return []
        # 无冷却（verdict_feedback 冷却时间 = 0）
        self._record_trigger("verdict_feedback")
        return [
            PipelineTrigger(
                type="verdict_feedback",
                source=f"{n_new_candidates} 个新 candidate",
                evidence={"n_new": n_new_candidates},
            )
        ]

    # ------------------------------------------------------------------
    # 频率审计（M-ASIL-4b）
    # ------------------------------------------------------------------
    def frequency_audit(self) -> Dict[str, int]:
        return dict(self._freq_count)

    def reset_daily(self) -> None:
        self._freq_count.clear()
