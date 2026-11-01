# -*- coding: utf-8 -*-
"""
metrics.py — 灰度观测指标（P1-5）
==================================
职责（PLAN P1-5 / SPEC §17）：
- 受理量：快照时间窗内的申请数
- 状态分布 / 判定分布 / 分类分布 / 积压（queued+running）
- 成功率：succeeded / (succeeded+failed)（取消不计入分母）
- 耗时：created_at → decided_at（报告判定时间）
- 执行统计：Runner 逐次执行结果（进程内计数，多实例需接外部指标系统）

边界：
- 快照按 list_requests 上限 1000 行统计（P4 SLO 看板改 SQL 聚合）
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Callable

from storage.repo import EvalRepo, zulu

from core.gateway import CATEGORIES

VERDICT_KEYS = ("PASS", "BLOCK", "INCONCLUSIVE", "none")
STATUS_KEYS = ("queued", "running", "succeeded", "failed", "cancelled")

SNAPSHOT_LIMIT = 1000


class Metrics:
    """评测观测指标：repo 推导快照 + Runner 进程内执行统计。"""

    def __init__(
        self,
        repo: EvalRepo,
        shadow: bool | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repo = repo
        self._shadow = shadow
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        self._runs_total = 0
        self._runs_succeeded = 0
        self._runs_failed = 0
        self._runs_cancelled = 0
        self._attempts_total = 0
        self._elapsed_ms_total = 0

    def record_run(self, outcome: Any, elapsed_ms: int) -> None:
        """记录一次 Runner 执行结果（status ∈ succeeded/failed/cancelled）。"""
        with self._lock:
            self._runs_total += 1
            self._attempts_total += max(0, int(outcome.attempts))
            self._elapsed_ms_total += max(0, int(elapsed_ms))
            if outcome.status == "succeeded":
                self._runs_succeeded += 1
            elif outcome.status == "failed":
                self._runs_failed += 1
            elif outcome.status == "cancelled":
                self._runs_cancelled += 1

    def snapshot(
        self,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        limit: int = SNAPSHOT_LIMIT,
    ) -> dict[str, Any]:
        rows = self._repo.list_requests(from_dt=from_dt, to_dt=to_dt, limit=limit)

        by_status = dict.fromkeys(STATUS_KEYS, 0)
        by_verdict = dict.fromkeys(VERDICT_KEYS, 0)
        by_category = dict.fromkeys(CATEGORIES, 0)
        latencies: list[int] = []

        for row in rows:
            status = row.get("status") or "queued"
            by_status[status] = by_status.get(status, 0) + 1
            verdict = row.get("verdict") or "none"
            by_verdict[verdict] = by_verdict.get(verdict, 0) + 1
            category = row.get("category") or "unknown"
            by_category[category] = by_category.get(category, 0) + 1
            created, decided = row.get("created_at"), row.get("decided_at")
            if isinstance(created, datetime) and isinstance(decided, datetime):
                latencies.append(max(0, int((decided - created).total_seconds() * 1000)))

        finished = by_status["succeeded"] + by_status["failed"]
        success_rate = round(by_status["succeeded"] / finished, 4) if finished else None

        with self._lock:
            runs = {
                "total": self._runs_total,
                "succeeded": self._runs_succeeded,
                "failed": self._runs_failed,
                "cancelled": self._runs_cancelled,
                "attempts": self._attempts_total,
                "avg_ms": (
                    round(self._elapsed_ms_total / self._runs_total) if self._runs_total else None
                ),
            }

        return {
            "accepted": len(rows),
            "by_status": by_status,
            "by_verdict": by_verdict,
            "by_category": by_category,
            "backlog": by_status["queued"] + by_status["running"],
            "success_rate": success_rate,
            "latency_ms": {
                "avg": round(sum(latencies) / len(latencies)) if latencies else None,
                "max": max(latencies) if latencies else None,
                "samples": len(latencies),
            },
            "runs": runs,
            "gate_shadow": self._shadow,
            "generated_at": zulu(self._clock()),
        }
