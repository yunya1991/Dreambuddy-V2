"""L2 Silver 层异常体系：严格分层（与§七.1 L1/L2/L3一致）。

- CleaningError：热路径用「带6层栈」+ fail-open 兜底，不抛到交易端（§七.1 L1铁则）
- QualityGateFailed：携带 IssueCode（便于监控告警聚合）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from data_center.monitoring.quality import QualityIssueCode


class CleaningError(Exception):
    """Silver 层异常基类（L1 fail-open 时捕获、落指标、不抛）。"""

    def __init__(
        self,
        message: str,
        *,
        traceback_str: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.traceback_str = traceback_str            # L1 必带：traceback.format_exc(limit=6)
        self.extra = extra or {}                       # 自由字段（模块名/行号/资产等）


@dataclass
class QualityGateFailed(CleaningError):
    """QualityGate 硬拦截失败：携带 4 类 IssueCode + 完整 issues 列表（用于告警）。"""
    code: "QualityIssueCode | None" = None
    issues: list[Any] = field(default_factory=list)

    def __init__(
        self,
        *,
        message: str,
        code: "QualityIssueCode | None" = None,
        issues: list[Any] | None = None,
        traceback_str: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        CleaningError.__init__(self, message, traceback_str=traceback_str, extra=extra)
        self.code = code
        self.issues = issues or []
