"""Three Screen API 兼容层。

承接单体 three_screen 路由的核心计算签名，委托给 classic_pipeline.signals.three_screen。
路由的 I/O（请求解析、事件系统、缓存、响应格式化）保留在单体中。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

from classic_pipeline.signals.three_screen import confirm_gate, daily_direction, compute


def compute_three_screen_signal(
    df_5m: Optional[pd.DataFrame],
    df_daily: Optional[pd.DataFrame],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """计算三屏信号。

    委托给 classic_pipeline.signals.three_screen.compute。

    Args:
        df_5m: 5m OHLCV DataFrame
        df_daily: 日线 OHLCV DataFrame
        config: 配置

    Returns:
        {direction, confidence, strategy, reject_reason, details}
    """
    return compute(df_5m, df_daily, config)


def compute_5m_confirm_gate(
    df_5m: pd.DataFrame,
    carry_side: str,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """5m 信号确认门。

    委托给 classic_pipeline.signals.three_screen.confirm_gate。
    """
    return confirm_gate(df_5m, carry_side, config)


def compute_daily_direction(
    df_daily: pd.DataFrame,
    config: Optional[Dict[str, Any]] = None,
) -> str:
    """日线方向判断。"""
    return daily_direction(df_daily, config)
