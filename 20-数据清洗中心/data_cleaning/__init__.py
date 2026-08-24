"""20-数据清洗中心 · 对外统一入口。

调用方（18-dispatcher H1）仅需：
    from data_cleaning import CleaningPipeline
    _pipe = CleaningPipeline.default_with_gate(enforce_hard_block=True)
    silver_result = _pipe.run_or_fallback(record)

P1 打通：Silver → DAL 写入
    from data_cleaning import DalSink
    DalSink().write_silver(silver_record, source=..., category=..., sub_category=...)
"""
from data_cleaning.contract import (
    CleanAction,
    CleanedDF,
    CleaningAction,
    CleaningTrace,
    SilverRecord,
)
from data_cleaning.dal_sink import DalSink
from data_cleaning.errors import CleaningError, QualityGateFailed

__all__ = [
    # Contracts
    "SilverRecord",
    "CleanedDF",
    "CleaningTrace",
    "CleanAction",
    "CleaningAction",
    # DalSink
    "DalSink",
    # Errors
    "CleaningError",
    "QualityGateFailed",
]
