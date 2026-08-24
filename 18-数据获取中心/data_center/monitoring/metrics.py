"""metrics — InvocationMetric 调用统计与 MetricsStore 存储。

无外部依赖，仅用标准库 dataclasses / threading / collections。
"""
from __future__ import annotations

import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


_ALLOWED_STATUS = frozenset({"ok", "error"})


@dataclass
class InvocationMetric:
    """一次 DataCenter.fetch() 调用的统计项。"""

    invocation_id: str
    ts: datetime  # 调用发生时间（UTC timezone-aware）
    source: str
    category: str
    status: str  # "ok" | "error"
    duration_ms: float
    records_count: int
    error_type: Optional[str]
    error_msg: Optional[str]

    def __post_init__(self) -> None:
        if self.status not in _ALLOWED_STATUS:
            raise ValueError(
                f"InvocationMetric.status must be one of {sorted(_ALLOWED_STATUS)}, "
                f"got {self.status!r}"
            )
        if self.duration_ms < 0:
            raise ValueError("duration_ms 不能为负")
        if self.records_count < 0:
            raise ValueError("records_count 不能为负")
        if self.ts.tzinfo is None:
            self.ts = self.ts.replace(tzinfo=timezone.utc)

    @staticmethod
    def new_ok(
        *,
        source: str,
        category: str,
        duration_ms: float,
        records_count: int,
    ) -> "InvocationMetric":
        return InvocationMetric(
            invocation_id=str(uuid.uuid4()),
            ts=datetime.now(timezone.utc),
            source=source,
            category=category,
            status="ok",
            duration_ms=duration_ms,
            records_count=records_count,
            error_type=None,
            error_msg=None,
        )

    @staticmethod
    def new_error(
        *,
        source: str,
        category: str,
        duration_ms: float,
        exc: BaseException,
    ) -> "InvocationMetric":
        return InvocationMetric(
            invocation_id=str(uuid.uuid4()),
            ts=datetime.now(timezone.utc),
            source=source,
            category=category,
            status="error",
            duration_ms=duration_ms,
            records_count=0,
            error_type=type(exc).__name__,
            error_msg=str(exc)[:500],
        )


_METRIC_SUMMARY = dict[str, Any]


class MetricsStore:
    """线程安全的内存调用统计存储。

    设计原则：
    - record() 追加，永不删除（可由外部定期 dump 并 reset）
    - query() 支持 source/category/time_window 过滤
    - summary() 按 (source, category) 聚合
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: list[InvocationMetric] = []

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    def record(self, metric: InvocationMetric) -> None:
        if not isinstance(metric, InvocationMetric):
            raise TypeError("record() 需要 InvocationMetric")
        with self._lock:
            self._records.append(metric)

    def reset(self) -> None:
        """清空所有记录（测试辅助）。"""
        with self._lock:
            self._records.clear()

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def query(
        self,
        *,
        source: Optional[str] = None,
        category: Optional[str] = None,
        window_sec: Optional[float] = None,
    ) -> list[InvocationMetric]:
        cutoff_ts: Optional[datetime] = None
        if window_sec is not None:
            cutoff_ts = datetime.now(timezone.utc).timestamp() - window_sec

        with self._lock:
            snap = list(self._records)

        result: list[InvocationMetric] = []
        for m in snap:
            if source is not None and m.source != source:
                continue
            if category is not None and m.category != category:
                continue
            if cutoff_ts is not None and m.ts.timestamp() < cutoff_ts:
                continue
            result.append(m)
        return result

    # ------------------------------------------------------------------
    # 聚合
    # ------------------------------------------------------------------
    def summary(
        self,
        *,
        window_sec: Optional[float] = None,
    ) -> dict[tuple[str, str], _METRIC_SUMMARY]:
        """按 (source, category) 聚合，返回每个 bucket 的统计。"""
        records = self.query(window_sec=window_sec)
        buckets: dict[tuple[str, str], list[InvocationMetric]] = defaultdict(list)
        for m in records:
            buckets[(m.source, m.category)].append(m)

        out: dict[tuple[str, str], _METRIC_SUMMARY] = {}
        for key, items in buckets.items():
            total = len(items)
            ok = sum(1 for x in items if x.status == "ok")
            errs = total - ok
            avg = sum(x.duration_ms for x in items) / total if total else 0.0
            total_records = sum(x.records_count for x in items)
            out[key] = {
                "total": total,
                "ok_count": ok,
                "error_count": errs,
                "avg_duration_ms": round(avg, 3),
                "total_records": total_records,
            }
        return out
