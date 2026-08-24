"""LineageTracker — 特征血缘追踪

注册模块的输入→输出列映射，verify_closed() 检测断链（L3 Fail-Fast）。
"""
from __future__ import annotations

import logging
from typing import List

from feature_hub.contract import LineageRecord

logger = logging.getLogger(__name__)


class LineageTracker:
    """特征血缘追踪器"""

    def __init__(self) -> None:
        self._records: List[LineageRecord] = []
        self._available_cols: set[str] = set()

    def add(
        self,
        module: str,
        input_cols: List[str],
        output_cols: List[str],
        timestamp: str = "",
    ) -> None:
        """注册一个模块的输入→输出映射"""
        from datetime import datetime
        ts = timestamp or datetime.now().isoformat()
        rec = LineageRecord(
            timestamp=ts,
            module=module,
            input_cols=list(input_cols),
            output_cols=list(output_cols),
        )
        self._records.append(rec)
        # 输出列加入可用集合
        self._available_cols.update(output_cols)

    def verify_closed(self) -> None:
        """验证无断链：每个模块的输入列必须在之前某模块的输出列中

        第一个模块的输入列豁免（原始输入）。
        """
        produced: set[str] = set()
        for i, rec in enumerate(self._records):
            if i > 0:
                missing = set(rec.input_cols) - produced
                if missing:
                    raise RuntimeError(
                        f"Lineage broken: module '{rec.module}' "
                        f"requires input cols {missing} "
                        f"not produced by any preceding module"
                    )
            produced.update(rec.output_cols)

    @property
    def records(self) -> List[LineageRecord]:
        return list(self._records)
