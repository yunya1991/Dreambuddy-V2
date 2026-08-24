"""RegistryAdapter — 适配已有 FeatureRegistry 模块"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from feature_hub.adapters.base_adapter import BaseAdapter


class RegistryAdapter(BaseAdapter):
    """适配已注册到 FeatureRegistry 的模块"""

    def __init__(self, module_name: str, **kwargs) -> None:
        self._module_name = module_name
        self._kwargs = kwargs

    def compute(
        self,
        df: pd.DataFrame,
        ref_df: Optional[pd.DataFrame] = None,
        macro_df: Optional[pd.DataFrame] = None,
        symbol: str = "",
    ) -> pd.DataFrame:
        from feature_hub.hub.feature_registry import FeatureRegistry

        features, _ = FeatureRegistry.compute_all(
            df=df,
            ref_df=ref_df,
            macro_df=macro_df,
            symbol=symbol,
            enabled=[self._module_name],
        )
        return features
