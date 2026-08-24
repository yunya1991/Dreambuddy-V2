"""QualityGate — 在 18-quality.QualityChecker 之上加 enforce 开关。

责任（Spec§D2 质量门§2）：
 1. 复用 18-数据获取中心/data_center/monitoring/quality.py 的 4 类检查
    （EMPTY_RESULT / CONTRACT_INVALID / DUPLICATE_DETECTED / TIMESTAMP_FRESHNESS）
 2. enforce_hard_block=True → issues 非空直接抛 QualityGateFailed，阻止 Bronze→Silver
 3. enforce_hard_block=False → 旁路模式，只 report 不抛（T-G1 旁路等价用）
 4. FAIL 时异常 traceback_str 填完整当前栈，6 层向上也可追溯
"""
from __future__ import annotations

import traceback
from datetime import timedelta
from typing import Iterable, Optional

# 兼容：DataRecord 也走 18-contract
from data_center.core.contract import DataRecord  # type: ignore

# 复用 18-quality 的代码（conftest 已把 18/data_center 加进 sys.path）
from data_center.monitoring.quality import (  # type: ignore
    QualityChecker,
    QualityIssue,
    QualityIssueCode,
)

from data_cleaning.contract import CleaningTrace
from data_cleaning.errors import QualityGateFailed

__all__ = ["QualityGate", "QualityIssue", "QualityIssueCode"]


class QualityGate:
    """Silver 出口质量门。复用 18-数据获取中心质量检查 API。"""

    def __init__(
        self,
        *,
        enforce_hard_block: bool = True,
        freshness_threshold: timedelta = timedelta(hours=48),
        allow_empty_degraded_sources: Optional[Iterable[str]] = None,
    ) -> None:
        self.enforce_hard_block = enforce_hard_block
        self._checker = QualityChecker(
            freshness_threshold=freshness_threshold,
            allow_empty_degraded_sources=allow_empty_degraded_sources,
        )

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def validate(
        self,
        records: list[DataRecord],
        *,
        source: str = "",
        category: str = "",
        is_degraded: bool = False,
        trace: Optional[CleaningTrace] = None,
    ) -> tuple[bool, list[QualityIssue]]:
        """执行质量检查。

        Returns:
            (gate_pass, issues) — enforce=False 时始终返回
        Raises:
            QualityGateFailed — enforce=True 且 issues 非空时抛出
        """
        issues: list[QualityIssue] = self._checker.check_all(
            list(records) if records is not None else [],
            source=source,
            category=category,
            is_degraded=bool(is_degraded),
        )
        gate_pass = len(issues) == 0

        # trace 打点
        if trace is not None:
            from data_cleaning.contract import CleanAction
            trace.append(CleanAction(
                step="QualityGate",
                input_rows=len(records),
                output_rows=len(records),
                blocked_count=0 if gate_pass else len(records),
                note=(
                    f"pass={gate_pass} issues={len(issues)} "
                    f"codes={sorted({i.code.value for i in issues})}"
                ),
            ))

        if gate_pass:
            return True, issues

        # FAIL：enforce 时抛异常，携带完整 traceback_str
        if self.enforce_hard_block:
            tb_str = traceback.format_exc(limit=6)  # 6 层：若当前没栈，用 format_stack
            if not tb_str or tb_str == "NoneType: None\n":
                tb_str = "".join(traceback.format_stack(limit=6))
            raise QualityGateFailed(
                code=issues[0].code,  # 首个主因
                message=(
                    f"QualityGate FAIL · {len(issues)} 个issues · 主因: "
                    f"{issues[0].code} | {issues[0].message}"
                ),
                issues=issues,
                traceback_str=tb_str,
            )
        return False, issues
