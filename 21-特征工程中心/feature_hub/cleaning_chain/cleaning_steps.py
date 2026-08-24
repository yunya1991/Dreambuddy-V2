"""标准特征清洗链 — 4 步各自的 Step 类

① InfNaNImpute    : +/-inf→median, NaN→ffill(3)→median, 全列缺失→50
② RobustScalerIQR : (X-median)/IQR, IQR=0 恒等不除零
③ VIFDropper      : VIF>10 从高到低剔除, 样本<1000 自动跳过
④ IVDropper       : IV<0.02 剔除, 无标签 y 自动跳过
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class InfNaNImpute:
    """① Inf/NaN 兜底"""

    def fit_transform(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        for col in out.columns:
            s = out[col]
            # +/-inf → NaN
            s = s.replace([np.inf, -np.inf], np.nan)
            # NaN → ffill(3) → median → 50
            s = s.ffill(limit=3)
            med = s.median()
            if pd.isna(med):
                s = s.fillna(50.0)
            else:
                s = s.fillna(med)
            out[col] = s
        return out


class RobustScalerIQR:
    """② RobustScaler (X-median)/IQR, IQR=0 恒等"""

    def fit_transform(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        for col in out.columns:
            s = out[col]
            med = s.median()
            q1 = s.quantile(0.25)
            q3 = s.quantile(0.75)
            iqr = q3 - q1
            if iqr == 0 or pd.isna(iqr):
                # IQR=0 → 恒等，不缩放
                continue
            out[col] = (s - med) / iqr
        return out


class VIFDropper:
    """③ VIF 去共线（VIF>10 从高到低剔除）"""

    def __init__(
        self,
        threshold: float = 10.0,
        skip_if: Optional[Callable[[pd.DataFrame], bool]] = None,
    ) -> None:
        self.threshold = threshold
        self.skip_if = skip_if
        self.dropped_cols: list[str] = []

    def _compute_vif(self, df: pd.DataFrame) -> dict[str, float]:
        cols = list(df.columns)
        if len(cols) < 2:
            return dict.fromkeys(cols, 1.0)
        vif = {}
        X = df.values.astype(float)
        for i, col in enumerate(cols):
            others = np.delete(X, i, axis=1)
            if others.shape[1] == 0:
                vif[col] = 1.0
                continue
            try:
                # OLS: regress X[:,i] on others
                ones = np.ones((X.shape[0], 1))
                A = np.hstack([others, ones])
                coef, *_ = np.linalg.lstsq(A, X[:, i], rcond=None)
                fitted = A @ coef
                ss_res = np.sum((X[:, i] - fitted) ** 2)
                ss_tot = np.sum((X[:, i] - X[:, i].mean()) ** 2)
                r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
                r2 = min(max(r2, 0.0), 0.9999)  # clamp
                vif[col] = 1.0 / (1.0 - r2)
            except Exception:
                vif[col] = 1.0
        return vif

    def fit_transform(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.skip_if and self.skip_if(df):
            logger.info("VIFDropper: skipped (skip_if returned True)")
            return df

        out = df.copy()
        self.dropped_cols = []
        while True:
            vif = self._compute_vif(out)
            max_col = max(vif, key=vif.get)
            max_val = vif[max_col]
            if max_val <= self.threshold:
                break
            out = out.drop(columns=[max_col])
            self.dropped_cols.append(max_col)
            if len(out.columns) < 2:
                break
        if self.dropped_cols:
            logger.info(
                "VIFDropper: dropped %d cols (VIF>%s): %s",
                len(self.dropped_cols), self.threshold, self.dropped_cols,
            )
        return out


class IVDropper:
    """④ IV 筛选（IV<0.02 剔除）"""

    def __init__(
        self,
        threshold: float = 0.02,
        n_bins: int = 10,
        skip_if: Optional[Callable[[object], bool]] = None,
    ) -> None:
        self.threshold = threshold
        self.n_bins = n_bins
        self.skip_if = skip_if
        self.dropped_cols: list[str] = []

    def _compute_iv(self, s: pd.Series, y: np.ndarray) -> float:
        # 分箱
        try:
            binned = pd.qcut(s, q=self.n_bins, duplicates="drop")
        except Exception:
            binned = pd.cut(s, bins=self.n_bins)
        df_tmp = pd.DataFrame({"bin": binned, "y": y})
        total_good = max(df_tmp["y"].sum(), 1e-10)
        total_bad = max(len(df_tmp) - df_tmp["y"].sum(), 1e-10)
        iv = 0.0
        for _, group in df_tmp.groupby("bin", observed=False):
            good = max(group["y"].sum(), 1e-10)
            bad = max(len(group) - group["y"].sum(), 1e-10)
            p_good = good / total_good
            p_bad = bad / total_bad
            woe = np.log(p_good / p_bad)
            iv += (p_good - p_bad) * woe
        return abs(iv)

    def fit_transform(self, df: pd.DataFrame, y: Optional[np.ndarray] = None) -> pd.DataFrame:
        if y is None or (self.skip_if and self.skip_if(y)):
            logger.info("IVDropper: skipped (no label or skip_if=True)")
            return df

        y_arr = np.asarray(y).astype(float)
        out = df.copy()
        self.dropped_cols = []
        ivs = {}
        for col in out.columns:
            try:
                ivs[col] = self._compute_iv(out[col], y_arr)
            except Exception:
                ivs[col] = 1.0  # 出错保留

        for col, iv in sorted(ivs.items(), key=lambda x: x[1]):
            if iv < self.threshold:
                out = out.drop(columns=[col])
                self.dropped_cols.append(col)
        if self.dropped_cols:
            logger.info(
                "IVDropper: dropped %d cols (IV<%s): %s",
                len(self.dropped_cols), self.threshold, self.dropped_cols,
            )
        return out
