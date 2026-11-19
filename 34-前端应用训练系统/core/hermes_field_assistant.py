# -*- coding: utf-8 -*-
"""P0-D3C: Hermes 场外助手（C 层例外通道）。

职责:
  - 接收 DSH 交接信封，在预算内尝试救援；
  - 只返回候选结果/证据/能力缺口，不修改 Ticket、不写 receipt；
  - 超预算、异常、非法结果一律升级人工。

依据: SPEC-P0-D3C §2。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

from core.hermes_handoff import (
    DEFAULT_COOLDOWN_S,
    HandoffEnvelope,
    HandoffLedger,
    decide_handoff,
)

RESCUE_STATUSES = frozenset({"resolved", "partial", "needs_dsh_retry", "needs_human", "rejected"})


@dataclass(frozen=True)
class RescueBudget:
    max_attempts: int = 1
    timeout_s: float = 300.0
    max_cost_usd: float = 0.5


@dataclass
class RescueResult:
    status: str
    summary: str = ""
    evidence_refs: Tuple[str, ...] = ()
    capability_gap: Optional[Dict[str, Any]] = None
    cost_usd: float = 0.0
    duration_ms: int = 0
    trace_id: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "evidence_refs": list(self.evidence_refs),
            "capability_gap": self.capability_gap,
            "cost_usd": self.cost_usd,
            "duration_ms": self.duration_ms,
            "trace_id": self.trace_id,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Optional["RescueResult"]:
        if not isinstance(data, dict):
            return None
        status = str(data.get("status") or "")
        if status not in RESCUE_STATUSES:
            return None
        refs = data.get("evidence_refs") or ()
        if isinstance(refs, str):
            refs = (refs,)
        return cls(
            status=status,
            summary=str(data.get("summary") or ""),
            evidence_refs=tuple(str(r) for r in refs),
            capability_gap=(
                data.get("capability_gap") if isinstance(data.get("capability_gap"), dict) else None
            ),
            cost_usd=float(data.get("cost_usd") or 0.0),
            duration_ms=int(data.get("duration_ms") or 0),
            trace_id=str(data.get("trace_id") or ""),
            error=str(data.get("error")) if data.get("error") else None,
        )


class FieldAssistant:
    """有界救援器：runner 是注入的 Hermes 执行适配器。"""

    def __init__(
        self,
        runner: Callable[[HandoffEnvelope], Any],
        ledger: Optional[HandoffLedger] = None,
        budget: Optional[RescueBudget] = None,
        clock: Optional[Callable[[], float]] = None,
        escalator: Optional[Callable[[HandoffEnvelope, RescueResult], None]] = None,
        cooldown_s: float = DEFAULT_COOLDOWN_S,
    ) -> None:
        self._runner = runner
        self._ledger = ledger if isinstance(ledger, HandoffLedger) else HandoffLedger()
        self._budget = budget if isinstance(budget, RescueBudget) else RescueBudget()
        self._clock = clock or time.monotonic
        self._escalator = escalator
        self._cooldown_s = cooldown_s

    def _escalate(self, envelope: HandoffEnvelope, result: RescueResult) -> None:
        if self._escalator is None:
            return
        try:
            self._escalator(envelope, result)
        except Exception:
            pass

    def rescue(self, envelope: Any) -> RescueResult:
        start = self._clock()
        if not isinstance(envelope, HandoffEnvelope):
            return RescueResult(status="rejected", summary="invalid_envelope")

        decision = decide_handoff(envelope, self._ledger, now=start, cooldown_s=self._cooldown_s)
        if not decision.allowed:
            return RescueResult(
                status="rejected", summary=decision.reason, trace_id=envelope.trace_id
            )

        self._ledger.append(envelope, now=start)
        total_cost = 0.0
        last_error: Optional[str] = None
        attempts = max(1, int(self._budget.max_attempts))

        for _ in range(attempts):
            try:
                raw = self._runner(envelope)
            except Exception as exc:  # FAIL-OPEN：异常不外抛
                last_error = f"{type(exc).__name__}:{exc}"
                continue

            result = raw if isinstance(raw, RescueResult) else RescueResult.from_dict(raw)
            if result is None:
                last_error = "invalid_result"
                continue

            total_cost += float(result.cost_usd or 0.0)
            if total_cost > float(self._budget.max_cost_usd):
                failed = RescueResult(
                    status="needs_human",
                    summary="rescue budget exceeded",
                    evidence_refs=result.evidence_refs,
                    capability_gap=result.capability_gap,
                    cost_usd=total_cost,
                    trace_id=envelope.trace_id,
                    error="budget_exceeded",
                )
                self._escalate(envelope, failed)
                return failed

            elapsed = self._clock() - start
            if self._budget.timeout_s > 0 and elapsed > self._budget.timeout_s:
                failed = RescueResult(
                    status="needs_human",
                    summary="rescue timeout",
                    evidence_refs=result.evidence_refs,
                    capability_gap=result.capability_gap,
                    cost_usd=total_cost,
                    duration_ms=int(elapsed * 1000),
                    trace_id=envelope.trace_id,
                    error="timeout",
                )
                self._escalate(envelope, failed)
                return failed

            if not result.trace_id:
                result.trace_id = envelope.trace_id
            result.cost_usd = total_cost
            result.duration_ms = int(elapsed * 1000)
            return result

        failed = RescueResult(
            status="needs_human",
            summary="rescue exhausted",
            cost_usd=total_cost,
            duration_ms=int((self._clock() - start) * 1000),
            trace_id=envelope.trace_id,
            error=last_error or "unknown",
        )
        self._escalate(envelope, failed)
        return failed
