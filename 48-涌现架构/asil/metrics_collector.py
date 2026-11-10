"""ASIL 指标收集器 — M-ASIL-0a/0b/1/2/3/4a/4b/4c。

SPEC v0.2 §7.1。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class MetricsCollector:
    """Phase 1 指标收集器。"""

    total_pipelines: int = 0
    valid_pipelines: int = 0  # M-ASIL-0b: 至少产出 1 个非空 BuildPlan
    completed_pipelines: int = 0  # M-ASIL-0a: 跑完 8 步
    verify_writebacks: int = 0  # M-ASIL-1
    distill_count: int = 0  # M-ASIL-2
    recall_hits_after_distill: int = 0
    kill_switch_events: int = 0  # M-ASIL-4a
    trigger_freq: Dict[str, int] = field(default_factory=dict)  # M-ASIL-4b
    llm_tokens_used: int = 0  # M-ASIL-4c

    def record_pipeline_start(self) -> None:
        self.total_pipelines += 1

    def record_pipeline_valid(self) -> None:
        self.valid_pipelines += 1

    def record_pipeline_complete(self) -> None:
        self.completed_pipelines += 1

    def record_verify_writeback(self) -> None:
        self.verify_writebacks += 1

    def record_distill(self) -> None:
        self.distill_count += 1

    def record_kill_switch(self) -> None:
        self.kill_switch_events += 1

    def record_trigger(self, trigger_type: str) -> None:
        self.trigger_freq[trigger_type] = self.trigger_freq.get(trigger_type, 0) + 1

    def record_llm(self, tokens: int) -> None:
        self.llm_tokens_used += tokens

    # ------------------------------------------------------------------
    # 计算指标
    # ------------------------------------------------------------------
    @property
    def completion_rate(self) -> float:
        return self.completed_pipelines / max(self.total_pipelines, 1)

    @property
    def valid_completion_rate(self) -> float:
        """M-ASIL-0b 硬指标。"""
        return self.valid_pipelines / max(self.total_pipelines, 1)

    @property
    def verify_writeback_rate(self) -> float:
        return self.verify_writebacks / max(self.completed_pipelines, 1)

    @property
    def distill_effectiveness(self) -> float:
        """M-ASIL-2。"""
        return self.recall_hits_after_distill / max(self.distill_count, 1)

    @property
    def kill_switch_freq(self) -> float:
        """M-ASIL-4a。"""
        return self.kill_switch_events  # 每日

    def snapshot(self) -> Dict:
        return {
            "total_pipelines": self.total_pipelines,
            "valid_pipelines": self.valid_pipelines,
            "completed_pipelines": self.completed_pipelines,
            "completion_rate": round(self.completion_rate, 3),
            "valid_completion_rate": round(self.valid_completion_rate, 3),
            "verify_writebacks": self.verify_writebacks,
            "verify_writeback_rate": round(self.verify_writeback_rate, 3),
            "distill_count": self.distill_count,
            "distill_effectiveness": round(self.distill_effectiveness, 3),
            "kill_switch_events": self.kill_switch_events,
            "trigger_freq": dict(self.trigger_freq),
            "llm_tokens_used": self.llm_tokens_used,
        }
