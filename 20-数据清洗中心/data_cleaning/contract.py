"""L2 Silver 层契约：记录清洗的输入/输出/痕迹，便于审计与追溯。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd


@dataclass(slots=True)
class CleanAction:
    """某一步清洗算子的执行痕迹，便于脏数据事后复盘。"""
    step: str                           # 算子名（如 DedupAlign / Outlier3LFilter）
    input_rows: int                     # 进入该算子的行数
    output_rows: int                    # 离开该算子的行数
    clipped_count: int = 0              # 被裁剪/标记的异常值单元格数
    imputed_count: int = 0              # 被插补的缺失值单元格数
    blocked_count: int = 0              # QualityGate 拒绝的行数
    note: str = ""                      # 自由备注（例："3σ 标记5；IQR clip2"）


@dataclass(slots=True)
class CleaningTrace:
    """整条 CleaningPipeline 的执行记录。"""
    actions: list[CleanAction] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: datetime | None = None

    @property
    def total_clipped(self) -> int:
        return sum(a.clipped_count for a in self.actions)

    @property
    def total_imputed(self) -> int:
        return sum(a.imputed_count for a in self.actions)

    def append(self, action: CleanAction) -> None:
        self.actions.append(action)


@dataclass(slots=True)
class CleanedDF:
    """清洗完成后的 DataFrame，携带 schema 标签（供 Gold/Pandera 校验定位）。"""
    df: pd.DataFrame
    schema_tag: str = ""                # 如 "ohlcv_v1" / "macro_m2_v1"
    records: list = field(default_factory=list)  # 适配器元数据（每源 record 一条元信息）
    primary_key_count: int = 0          # (src,cat,sub,asset,timestamp) 去重计数


@dataclass(slots=True)
class AdapterMeta:
    """Adapter 元信息：records_to_cleaned_df 在 records 里放它。

    与 SilverRecord 的区别：SilverRecord 是 pipeline 出口产物（带 trace/gate/bronze_id）；
    AdapterMeta 仅承载“原始 DataRecord 的引用元数据”。
    """
    source: str
    category: str
    sub_category: str
    asset: str
    fetched_at: str                     # ISO str
    record_id: str = ""
    schema_version: str = "1.0"
    data: dict = field(default_factory=dict)


@dataclass(slots=True)
class SilverRecord:
    """Silver 层最终产物：DF + 痕迹 + QualityGate 结果 + Bronze 关联。

    - gate_passed=True  → 允许写 19-DAL（Gold 就绪）
    - gate_passed=False → 仅写 Bronze 审计 + 告警，不入库
    """
    bronze_id: str                      # 关联 Bronze DataRecord 的 id（审计回查）
    df: pd.DataFrame                    # 清洗后的 DataFrame（CleanedDF.df 提取）
    trace: CleaningTrace                # 全链路清洗痕迹
    gate_passed: bool                   # QualityGate 是否通过
    quality_report: list[Any] = field(default_factory=list)  # QualityIssue 列表
    schema_tag: str = ""                # 透传 CleanedDF.schema_tag


# 命名别名：对外文档与测试文件使用 "CleaningAction"（更语义），内部 slots 用短名。
CleaningAction = CleanAction
__all__ = [
    "CleanAction",
    "CleaningAction",
    "CleanedDF",
    "CleaningTrace",
    "SilverRecord",
    "AdapterMeta",
]
