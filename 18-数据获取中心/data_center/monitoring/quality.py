"""quality — DataRecord 数据质量检查。

检查项：
  EMPTY_RESULT      — 空列表且无正当降级理由
  CONTRACT_INVALID  — DataRecord.validate() 抛 ContractError
  DUPLICATE_DETECTED— 同批次 dedupe_key 重复
  TIMESTAMP_FRESHNESS — 最老记录超过 freshness_threshold
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Iterable, Optional

from data_center.core.contract import DataRecord, validate_record
from data_center.core.errors import ContractError
from data_center.storage.cache import dedupe_key as _canonical_dedupe_key


class QualityIssueCode(str, Enum):
    EMPTY_RESULT = "EMPTY_RESULT"
    CONTRACT_INVALID = "CONTRACT_INVALID"
    DUPLICATE_DETECTED = "DUPLICATE_DETECTED"
    TIMESTAMP_FRESHNESS = "TIMESTAMP_FRESHNESS"


@dataclass
class QualityIssue:
    code: QualityIssueCode
    message: str
    source: str = ""
    category: str = ""
    # 关联字段（如重复 key、违规字段名等）
    extra: dict = field(default_factory=dict)
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class QualityChecker:
    """对一批 DataRecord 做质量检查，返回问题列表。"""

    def __init__(
        self,
        *,
        freshness_threshold: timedelta = timedelta(hours=48),
        allow_empty_degraded_sources: Optional[Iterable[str]] = None,
    ) -> None:
        """
        Args:
            freshness_threshold: 最老记录距当前超过此阈值 → FRESHNESS issue
            allow_empty_degraded_sources: 这些 source 空列表不算问题（明确降级）
        """
        self.freshness_threshold = freshness_threshold
        self._degraded_ok = set(allow_empty_degraded_sources or ())

    # ------------------------------------------------------------------
    # 全量检查
    # ------------------------------------------------------------------
    def check_all(
        self,
        records: list[DataRecord],
        *,
        source: str = "",
        category: str = "",
        is_degraded: bool = False,
    ) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        issues.extend(self._check_empty(records, source=source, category=category, is_degraded=is_degraded))
        issues.extend(self._check_contract(records, source=source, category=category))
        issues.extend(self._check_duplicate(records, source=source, category=category))
        issues.extend(self._check_freshness(records, source=source, category=category))
        return issues

    # ------------------------------------------------------------------
    # 单项检查
    # ------------------------------------------------------------------
    def _check_empty(
        self,
        records: list[DataRecord],
        *,
        source: str,
        category: str,
        is_degraded: bool,
    ) -> list[QualityIssue]:
        if records:
            return []
        if is_degraded or source in self._degraded_ok:
            return []
        return [QualityIssue(
            code=QualityIssueCode.EMPTY_RESULT,
            message=f"返回空列表：source={source} category={category}",
            source=source,
            category=category,
        )]

    def _check_contract(
        self,
        records: list[DataRecord],
        *,
        source: str,
        category: str,
    ) -> list[QualityIssue]:
        issues: list[QualityIssue] = []
        for i, rec in enumerate(records):
            try:
                validate_record(rec)
            except ContractError as e:
                issues.append(QualityIssue(
                    code=QualityIssueCode.CONTRACT_INVALID,
                    message=f"records[{i}] 契约异常: {e}",
                    source=source,
                    category=category,
                    extra={
                        "index": i,
                        "contract_error": str(e),
                        "sub_category": rec.sub_category,
                    },
                ))
            except Exception as e:  # noqa: BLE001 — 防御性
                issues.append(QualityIssue(
                    code=QualityIssueCode.CONTRACT_INVALID,
                    message=f"records[{i}] validate() 未预期异常: {type(e).__name__}: {e}",
                    source=source,
                    category=category,
                    extra={"index": i, "error_type": type(e).__name__},
                ))
        return issues

    def _check_duplicate(
        self,
        records: list[DataRecord],
        *,
        source: str,
        category: str,
    ) -> list[QualityIssue]:
        seen: dict[str, list[int]] = {}
        for i, rec in enumerate(records):
            k = _canonical_dedupe_key(rec)
            seen.setdefault(k, []).append(i)

        issues: list[QualityIssue] = []
        for k, idxs in seen.items():
            if len(idxs) > 1:
                issues.append(QualityIssue(
                    code=QualityIssueCode.DUPLICATE_DETECTED,
                    message=f"同批次发现 {len(idxs)} 条重复（key={k}），indices={idxs}",
                    source=source,
                    category=category,
                    extra={"dedupe_key": k, "duplicate_indices": idxs},
                ))
        return issues

    def _check_freshness(
        self,
        records: list[DataRecord],
        *,
        source: str,
        category: str,
    ) -> list[QualityIssue]:
        if not records:
            return []
        now = datetime.now(timezone.utc)
        oldest: Optional[datetime] = None
        for rec in records:
            try:
                if isinstance(rec.timestamp, datetime):
                    ts = rec.timestamp
                else:
                    ts = datetime.fromisoformat(str(rec.timestamp).replace("Z", "+00:00"))
            except Exception:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if oldest is None or ts < oldest:
                oldest = ts

        if oldest is None:
            return []
        age = now - oldest
        if age > self.freshness_threshold:
            return [QualityIssue(
                code=QualityIssueCode.TIMESTAMP_FRESHNESS,
                message=(
                    f"最老记录距当前 {age}，超过阈值 {self.freshness_threshold}"
                ),
                source=source,
                category=category,
                extra={
                    "oldest_ts": oldest.isoformat(),
                    "age_seconds": age.total_seconds(),
                    "threshold_seconds": self.freshness_threshold.total_seconds(),
                },
            )]
        return []
