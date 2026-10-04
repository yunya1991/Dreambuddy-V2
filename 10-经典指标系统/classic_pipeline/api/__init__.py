"""classic_pipeline.api — API 兼容层。

承接单体路由的核心计算签名，委托给 classic_pipeline 各模块。
路由的 I/O（请求解析、事件系统、缓存、响应格式化）保留在单体中。
"""
from classic_pipeline.api.universe_adapter import (
    compute_btc_corr,
    compute_beta,
    compute_corr,
    kmeans_cluster,
    ari_nmi,
)
from classic_pipeline.api.three_screen_adapter import (
    compute_three_screen_signal,
    compute_5m_confirm_gate,
    compute_daily_direction,
)
from classic_pipeline.api.quant_adapter import (
    compute_quant_signal,
    compute_signal_confidence,
    compute_strategy_weight,
    compute_strategy_perf,
    vote_signals,
    risk_check,
)

__all__ = [
    "compute_btc_corr", "compute_beta", "compute_corr", "kmeans_cluster", "ari_nmi",
    "compute_three_screen_signal", "compute_5m_confirm_gate", "compute_daily_direction",
    "compute_quant_signal", "compute_signal_confidence", "compute_strategy_weight",
    "compute_strategy_perf", "vote_signals", "risk_check",
]
