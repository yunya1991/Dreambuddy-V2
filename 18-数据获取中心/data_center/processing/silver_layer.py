"""SilverLayerCleaner — 奖章架构 Silver 层清洗。

Spec: docs/superpowers/specs/2026-09-21-washout-detector-design.md §6.3

清洗链路:
  1. 去重: (timestamp, symbol) 唯一
  2. 3σ 异常值过滤
  3. IQR 异常值过滤
  4. 动态 ATR 异常值过滤

project_memory 硬约束:
  - Bronze 层保留原始采集结果
  - Silver 层进行去重、三级异常值过滤（3σ→IQR→动态ATR）
  - 异常数据仅保留在 Bronze 层用于审计

FAIL-OPEN 铁律: 异常 → 保留原始数据不阻塞
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def dedup_by_timestamp_symbol(df: pd.DataFrame) -> pd.DataFrame:
    """(timestamp, symbol) 组合去重，保留第一条。

    Args:
        df: 含 timestamp 和 symbol 列的 DataFrame

    Returns:
        去重后的 DataFrame
    """
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()
    if "timestamp" not in df.columns or "symbol" not in df.columns:
        return df
    return df.drop_duplicates(
        subset=["timestamp", "symbol"], keep="first"
    ).reset_index(drop=True)


def filter_3sigma(df: pd.DataFrame, field: str) -> pd.DataFrame:
    """3σ 异常值过滤: |value - mean| > 3σ 的记录被过滤。

    Args:
        df: 含数值列的 DataFrame
        field: 要过滤的数值列名

    Returns:
        过滤异常值后的 DataFrame
    """
    if df is None or df.empty or field not in df.columns:
        return df if df is not None else pd.DataFrame()
    if len(df) < 2:
        return df
    try:
        values = df[field].astype(float)
        mean = values.mean()
        std = values.std()
        if pd.isna(std) or std == 0:
            return df
        mask = (values - mean).abs() <= 3 * std
        return df[mask].reset_index(drop=True)
    except Exception as e:
        logger.debug("filter_3sigma FAIL-OPEN: %s", e)
        return df


def filter_iqr(df: pd.DataFrame, field: str) -> pd.DataFrame:
    """IQR 异常值过滤: 超出 [Q1-1.5*IQR, Q3+1.5*IQR] 的记录被过滤。

    Args:
        df: 含数值列的 DataFrame
        field: 要过滤的数值列名

    Returns:
        过滤异常值后的 DataFrame
    """
    if df is None or df.empty or field not in df.columns:
        return df if df is not None else pd.DataFrame()
    if len(df) < 4:
        return df
    try:
        values = df[field].astype(float)
        q1 = values.quantile(0.25)
        q3 = values.quantile(0.75)
        iqr = q3 - q1
        if pd.isna(iqr) or iqr == 0:
            return df
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        mask = (values >= lower) & (values <= upper)
        return df[mask].reset_index(drop=True)
    except Exception as e:
        logger.debug("filter_iqr FAIL-OPEN: %s", e)
        return df


def filter_dynamic_atr(
    df: pd.DataFrame,
    field: str,
    window: int = 14,
    k: float = 3.0,
) -> pd.DataFrame:
    """动态 ATR 异常值过滤: |value - prev| > k*ATR 的记录被过滤。

    使用 True Range（相邻值差的绝对值）的滚动均值作为 ATR。
    当当前变化幅度超过 k 倍 ATR 时，判定为异常。

    Args:
        df: 含数值列的 DataFrame
        field: 要过滤的数值列名
        window: ATR 滚动窗口大小
        k: ATR 倍数阈值

    Returns:
        过滤异常值后的 DataFrame
    """
    if df is None or df.empty or field not in df.columns:
        return df if df is not None else pd.DataFrame()
    if len(df) < window + 1:
        return df
    try:
        values = df[field].astype(float)
        # True Range: 相邻值的绝对差
        tr = values.diff().abs()
        # 滚动 ATR (简单移动平均)
        atr = tr.rolling(window=window, min_periods=1).mean()
        # 异常判定: TR > k * ATR
        # 正常: TR <= k * ATR，或 ATR=0 (初始平稳期)，或 NaN (第一条)
        mask = (tr <= k * atr) | (atr == 0) | atr.isna()
        return df[mask].reset_index(drop=True)
    except Exception as e:
        logger.debug("filter_dynamic_atr FAIL-OPEN: %s", e)
        return df


class SilverLayerCleaner:
    """奖章架构 Silver 层清洗器。

    完整清洗链路: 去重 → 3σ → IQR → 动态 ATR
    """

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self._window: int = int(self.config.get("atr_window", 14))
        self._k: float = float(self.config.get("atr_k", 3.0))

    def clean(
        self,
        df: pd.DataFrame,
        value_field: str = "cvd_value",
    ) -> pd.DataFrame:
        """完整清洗链路。

        Args:
            df: Bronze 层原始数据
            value_field: 要清洗的数值列名

        Returns:
            Silver 层清洗后数据
        """
        if df is None or df.empty:
            return df if df is not None else pd.DataFrame()
        result = df.copy()
        # 1. 去重
        result = dedup_by_timestamp_symbol(result)
        # 2. 3σ 过滤
        result = filter_3sigma(result, value_field)
        # 3. IQR 过滤
        result = filter_iqr(result, value_field)
        # 4. 动态 ATR 过滤
        result = filter_dynamic_atr(
            result, value_field, window=self._window, k=self._k
        )
        return result
