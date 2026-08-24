"""Adapter 基类 — 统一 compute 接口"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd


class BaseAdapter(ABC):
    """所有 Adapter 的抽象基类"""

    @abstractmethod
    def compute(
        self,
        df: pd.DataFrame,
        ref_df: Optional[pd.DataFrame] = None,
        macro_df: Optional[pd.DataFrame] = None,
        symbol: str = "",
    ) -> pd.DataFrame:
        """统一计算接口"""
        ...
