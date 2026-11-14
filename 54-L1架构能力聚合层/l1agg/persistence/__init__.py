# -*- coding: utf-8 -*-
"""延续性统计分析模块（T0）。

对外只暴露确定性统计能力，不做预测：
    from l1agg.persistence import build_profile
    profile = build_profile(db_path, "BTC")

结构与职责：
    constants.py  常量与异常
    _stats.py     纯 stdlib 统计原语
    metrics.py    A1–A7 单指标
    profile.py    聚合画像 + 质量门禁 + 文本模板
    report.py     报告入口
"""

from .constants import CAVEAT, HURST_CONFIDENT_N, HURST_MAX_CHUNK, KIND, MIN_N, PersistenceError
from .metrics import (
    ar1_halflife,
    hurst_rs,
    ic_decay,
    run_length_stats,
    transition_matrix,
    trend_slope,
    variance_ratio,
)
from .profile import PersistenceProfile, build_profile

__all__ = [
    "CAVEAT",
    "KIND",
    "HURST_CONFIDENT_N",
    "HURST_MAX_CHUNK",
    "MIN_N",
    "PersistenceError",
    "PersistenceProfile",
    "build_profile",
    "hurst_rs",
    "variance_ratio",
    "ar1_halflife",
    "run_length_stats",
    "transition_matrix",
    "trend_slope",
    "ic_decay",
]
