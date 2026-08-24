"""SklearnStyleAdapter — 包装 sklearn-style create_features(X) 类"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from feature_hub.adapters.base_adapter import BaseAdapter


class SklearnStyleAdapter(BaseAdapter):
    """适配有 create_features(df) 方法的类（如 TrendFeatureEngineer）"""

    def __init__(self, fe_cls: type, **kwargs: Any) -> None:
        self._fe_cls = fe_cls
        self._kwargs = kwargs
        self._instance = fe_cls(**kwargs)

    def compute(
        self,
        df: pd.DataFrame,
        ref_df: Optional[pd.DataFrame] = None,
        macro_df: Optional[pd.DataFrame] = None,
        symbol: str = "",
    ) -> pd.DataFrame:
        # 1) 输入防御：确保所有 OHLCV 列都是 pd.Series（而非 ndarray）
        #    有些环境（如系统 talib vs shim talib）返回值类型不一致，
        #    create_features 内常直接 df["close"].pct_change()，必须 Series。
        safe_df = pd.DataFrame(
            {col: s if isinstance(s, pd.Series) else pd.Series(s, index=df.index)
             for col, s in df.items()},
            index=df.index,
        )

        # 2) 调用 create_features，去掉 label 列（如果有）
        result = self._instance.create_features(safe_df)

        # 3) 输出防御：确保每一列都是 ndarray 或 pd.Series 的数值列；
        #    若某列是 list/tuple，转成 Series，避免 concat/add_prefix 异常。
        out = pd.DataFrame(index=safe_df.index)
        label_cols: list[str] = []
        for col in result.columns:
            v = result[col]
            if col.startswith("label_"):
                label_cols.append(col)
                continue
            if isinstance(v, np.ndarray):
                out[col] = v if len(v) == len(out.index) else pd.Series(dtype=float)
            elif isinstance(v, pd.Series):
                out[col] = v.values if len(v) == len(out.index) else pd.Series(dtype=float)
            else:
                out[col] = pd.Series(v, index=out.index, dtype=float)
        return out
