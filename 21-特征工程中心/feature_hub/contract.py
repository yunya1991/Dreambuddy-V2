"""FeatureHub 数据契约 — FeatureVector / FeatureSpec / LineageRecord"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import pandas as pd


@dataclass
class FeatureVector:
    """特征向量 — FeaturePipeline 的最终输出"""
    df: pd.DataFrame
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FeatureSpec:
    """特征模块规格 — 注册时的元信息"""
    name: str
    version: str
    enabled_sets: List[str] = field(default_factory=list)
    input_cols: List[str] = field(default_factory=list)
    output_cols: List[str] = field(default_factory=list)


@dataclass
class LineageRecord:
    """血缘记录 — 单步清洗/特征变换的审计日志"""
    timestamp: str
    module: str
    input_cols: List[str] = field(default_factory=list)
    output_cols: List[str] = field(default_factory=list)
    dropped_cols: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "module": self.module,
            "input_cols": list(self.input_cols),
            "output_cols": list(self.output_cols),
            "dropped_cols": list(self.dropped_cols),
            "reasons": list(self.reasons),
        }
