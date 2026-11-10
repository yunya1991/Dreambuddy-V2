"""ASIL 指标收集器 — M-ASIL-0a/0b/1/2/3/4a/4b/4c。

SPEC v0.2 §7.1。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .recall_stats import RecallStatsProvider


@dataclass
class MetricsCollector:
    """Phase 1 指标收集器。"""

    total_pipelines: int = 0
    valid_pipelines: int = 0  # M-ASIL-0b: 至少产出 1 个非空 BuildPlan
    completed_pipelines: int = 0  # M-ASIL-0a: 跑完 8 步
    verify_writebacks: int = 0  # M-ASIL-1
    distill_count: int = 0  # M-ASIL-2
    distill_timestamps: List[float] = field(default_factory=list)
    kill_switch_events: int = 0  # M-ASIL-4a
    trigger_freq: Dict[str, int] = field(default_factory=dict)  # M-ASIL-4b
    llm_tokens_used: int = 0  # M-ASIL-4c
    writeback_fallbacks: int = 0  # 认知库不可用时的本地镜像次数
    recall_provider: Optional[Any] = field(default=None, repr=False, compare=False)
    _last_distill_effect: Dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def record_pipeline_start(self) -> None:
        self.total_pipelines += 1

    def record_pipeline_valid(self) -> None:
        self.valid_pipelines += 1

    def record_pipeline_complete(self) -> None:
        self.completed_pipelines += 1

    def record_verify_writeback(self) -> None:
        self.verify_writebacks += 1

    def record_writeback_fallback(self) -> None:
        self.writeback_fallbacks += 1

    def record_distill(self, ts: Optional[float] = None) -> None:
        self.distill_count += 1
        self.distill_timestamps.append(time.time() if ts is None else float(ts))

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

    def _provider(self) -> Any:
        if self.recall_provider is None:
            self.recall_provider = RecallStatsProvider()
        return self.recall_provider

    @property
    def distill_effectiveness(self) -> float:
        """M-ASIL-2：蒸馏后 recall 命中率相对蒸馏前的提升（真实 recall stats）。

        无蒸馏记录或无足够前后窗口数据时返回 0.0。
        """
        if not self.distill_timestamps:
            return 0.0
        provider = self._provider()
        deltas: List[float] = []
        for ts in self.distill_timestamps:
            try:
                eff = provider.effectiveness(ts)
            except Exception:  # FAIL-OPEN：统计不可用不阻塞主流程
                continue
            self._last_distill_effect = eff
            if eff.get("sufficient"):
                deltas.append(float(eff["delta"]))
        return sum(deltas) / len(deltas) if deltas else 0.0

    @property
    def distill_effectiveness_detail(self) -> Dict[str, Any]:
        """最近一次蒸馏的前后窗口明细（便于审计）。"""
        return dict(self._last_distill_effect)

    @property
    def kill_switch_freq(self) -> float:
        """M-ASIL-4a。"""
        return self.kill_switch_events  # 每日

    def snapshot(self) -> Dict:
        effectiveness = self.distill_effectiveness
        try:
            recall_stats = self._provider().summary()
        except Exception:  # FAIL-OPEN：统计不可用不影响主流程
            recall_stats = {"source": None, "n_recalls": 0, "hit_rate": 0.0}
        return {
            "total_pipelines": self.total_pipelines,
            "valid_pipelines": self.valid_pipelines,
            "completed_pipelines": self.completed_pipelines,
            "completion_rate": round(self.completion_rate, 3),
            "valid_completion_rate": round(self.valid_completion_rate, 3),
            "verify_writebacks": self.verify_writebacks,
            "verify_writeback_rate": round(self.verify_writeback_rate, 3),
            "writeback_fallbacks": self.writeback_fallbacks,
            "distill_count": self.distill_count,
            "distill_effectiveness": round(effectiveness, 3),
            "distill_effectiveness_detail": self.distill_effectiveness_detail,
            "recall_stats": recall_stats,
            "kill_switch_events": self.kill_switch_events,
            "trigger_freq": dict(self.trigger_freq),
            "llm_tokens_used": self.llm_tokens_used,
        }
