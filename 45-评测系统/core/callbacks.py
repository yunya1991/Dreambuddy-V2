# -*- coding: utf-8 -*-
"""
callbacks.py — 判定回调路由：只受理不拦截（P1-3）
===================================================
职责（PLAN P1-3 / SPEC §13.3）：
- 影子模式（gate.shadow=true）：判定只记录 would-dispatch，绝不触发下游回调
- 实盘模式（gate.shadow=false）：调用真实回调并留审计记录
- 回调异常 fail-soft：记录原因，不影响评测结果

边界：
- 拦截执行体（部署卡点/L0 卡点）属 P3；本层只负责"是否放行回调"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DispatchRecord:
    """一次回调路由的审计记录。"""

    eval_id: str
    verdict: str
    mode: str  # shadow / live
    dispatched: bool
    target: str | None
    reason: str | None
    at: datetime


class CallbackDispatcher(Protocol):
    def dispatch(self, eval_id: str, verdict: str, report: dict[str, Any]) -> DispatchRecord: ...


class ShadowDispatcher:  # noqa: D101 — 语义见模块文档
    def __init__(
        self,
        audit: list[DispatchRecord] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._audit = audit if audit is not None else []
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def audit(self) -> list[DispatchRecord]:
        return self._audit

    def dispatch(self, eval_id: str, verdict: str, report: dict[str, Any]) -> DispatchRecord:
        record = DispatchRecord(
            eval_id=eval_id,
            verdict=verdict,
            mode="shadow",
            dispatched=False,
            target=None,
            reason="gate.shadow=true：只记录 would-dispatch，不触发下游回调（P1-3）",
            at=self._clock(),
        )
        self._audit.append(record)
        logger.info("shadow would-dispatch eval_id=%s verdict=%s（不回调，P1-3）", eval_id, verdict)
        return record


class RecordingDispatcher:
    """实盘分发：调用真实回调，异常 fail-soft 并记录原因。"""

    def __init__(
        self,
        callback: Callable[[dict[str, Any]], Any],
        audit: list[DispatchRecord] | None = None,
        clock: Callable[[], datetime] | None = None,
        target: str = "callback",
    ) -> None:
        self._callback = callback
        self._audit = audit if audit is not None else []
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._target = target

    @property
    def audit(self) -> list[DispatchRecord]:
        return self._audit

    def dispatch(self, eval_id: str, verdict: str, report: dict[str, Any]) -> DispatchRecord:
        payload = {"eval_id": eval_id, "verdict": verdict, "report": report}
        dispatched = True
        reason: str | None = None
        try:
            self._callback(payload)
        except Exception as exc:  # noqa: BLE001 — 下游异常不得影响评测结果
            dispatched = False
            reason = f"callback_error: {exc}"
            logger.warning("判定回调失败（fail-soft）eval_id=%s: %s", eval_id, exc)
        record = DispatchRecord(
            eval_id=eval_id,
            verdict=verdict,
            mode="live",
            dispatched=dispatched,
            target=self._target,
            reason=reason,
            at=self._clock(),
        )
        self._audit.append(record)
        if dispatched:
            logger.info("verdict dispatched eval_id=%s verdict=%s", eval_id, verdict)
        return record


def build_dispatcher(
    shadow: bool,
    callback: Callable[[dict[str, Any]], Any],
    audit: list[DispatchRecord] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> CallbackDispatcher:
    """按 gate.shadow 路由：影子只记录，实盘才回调（P1-3 开关唯一出口）。"""
    if shadow:
        return ShadowDispatcher(audit=audit, clock=clock)
    return RecordingDispatcher(callback=callback, audit=audit, clock=clock)
