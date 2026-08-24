"""StandardCleaningChain — 按 B8 顺序串联 4 步清洗

顺序：① InfNaNImpute → ② RobustScalerIQR → ③ VIFDropper → ④ IVDropper
L1 fail-open：任一步异常 → Raw 透传 + log.warning（永不阻塞）
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

import numpy as np
import pandas as pd

from feature_hub.cleaning_chain.cleaning_steps import (
    InfNaNImpute,
    IVDropper,
    RobustScalerIQR,
    VIFDropper,
)

logger = logging.getLogger(__name__)


class StandardCleaningChain:
    """标准特征清洗链"""

    def __init__(
        self,
        vif_threshold: float = 10.0,
        iv_threshold: float = 0.02,
        vif_skip_if: Optional[Callable[[pd.DataFrame], bool]] = None,
        iv_skip_if: Optional[Callable[[object], bool]] = None,
    ) -> None:
        self.steps = [
            ("InfNaNImpute", InfNaNImpute()),
            ("RobustScalerIQR", RobustScalerIQR()),
            ("VIFDropper", VIFDropper(
                threshold=vif_threshold,
                skip_if=vif_skip_if or (lambda X: len(X) < 1000),
            )),
            ("IVDropper", IVDropper(
                threshold=iv_threshold,
                skip_if=iv_skip_if or (lambda y: y is None),
            )),
        ]

    def fit_transform(
        self,
        df: pd.DataFrame,
        y: Optional[np.ndarray] = None,
    ) -> pd.DataFrame:
        """执行 4 步清洗，L1 fail-open 永不抛异常"""
        out = df
        for name, step in self.steps:
            try:
                if name == "IVDropper":
                    out = step.fit_transform(out, y=y)
                else:
                    out = step.fit_transform(out)
            except Exception as exc:
                logger.warning(
                    "[FeatureHub] cleaning step '%s' failed: %s — "
                    "returning raw features (fail-open)", name, exc,
                )
                return out
        return out
