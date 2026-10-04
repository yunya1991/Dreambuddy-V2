"""GoldLayerValidator — 奖章架构 Gold 层 Schema 验证。

Spec: docs/superpowers/specs/2026-09-21-washout-detector-design.md §6.3

Gold 层:
  - cvd_clean 表: 通过 Schema 验证
  - ofi_clean 表: 通过 Schema 验证
  - long_short_ratio_clean 表: 通过 Schema 验证

project_memory 硬约束:
  - Gold 层为进入数据访问层的可用干净数据并进行 Schema 验证
  - 所有数据入库前必须经过 Silver 层清洗
  - quality.py 从监控报警升级为硬门禁拦截，异常数据仅保留 Bronze 层
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


# ============================================================
# Washout 数据表 Schema 定义
# ============================================================
WASHOUT_SCHEMAS: dict[str, dict] = {
    "cvd_clean": {
        "required_fields": [
            "timestamp", "symbol", "cvd_value", "buy_volume", "sell_volume",
        ],
        "numeric_fields": ["cvd_value", "buy_volume", "sell_volume"],
    },
    "ofi_clean": {
        "required_fields": [
            "timestamp", "symbol", "bid_volume", "ask_volume", "ofi_value",
        ],
        "numeric_fields": ["bid_volume", "ask_volume", "ofi_value"],
    },
    "long_short_ratio_clean": {
        "required_fields": ["timestamp", "symbol", "long_ratio", "short_ratio"],
        "numeric_fields": ["long_ratio", "short_ratio"],
    },
}


def validate_schema(df: pd.DataFrame, table_type: str) -> bool:
    """Gold 层 Schema 验证。

    Args:
        df: Silver 层清洗后的 DataFrame
        table_type: 表类型（cvd_clean/ofi_clean/long_short_ratio_clean）

    Returns:
        True = 通过 Schema 验证；False = 拦截
    """
    if table_type not in WASHOUT_SCHEMAS:
        logger.debug("validate_schema: unknown table_type %s", table_type)
        return False
    if df is None or df.empty:
        return False

    schema = WASHOUT_SCHEMAS[table_type]
    required = schema["required_fields"]
    numeric = schema["numeric_fields"]

    # 1. 检查必需字段存在
    for f in required:
        if f not in df.columns:
            return False

    # 2. 检查数值字段类型（可转 float）
    for f in numeric:
        if f not in df.columns:
            return False
        try:
            pd.to_numeric(df[f])
        except (ValueError, TypeError):
            return False

    return True


class GoldLayerValidator:
    """奖章架构 Gold 层验证器。"""

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    def validate(self, df: pd.DataFrame, table_type: str) -> bool:
        """验证 DataFrame 是否符合 Gold 层 Schema。

        Args:
            df: Silver 层清洗后的 DataFrame
            table_type: 表类型

        Returns:
            True = 通过验证；False = 拦截
        """
        return validate_schema(df, table_type)
