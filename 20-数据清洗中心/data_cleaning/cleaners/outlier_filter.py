"""T3 · Outlier3LFilter：三级异常过滤（①3σ 粗筛(仅标记) → ②IQR×1.5 中筛 clip → ③14-ATR×k 精筛 clip/事件命中保留）。"""
from __future__ import annotations

from typing import Iterable, Mapping

import numpy as np
import pandas as pd
from data_cleaning.contract import CleanAction, CleaningTrace


class Outlier3LFilter:
    def __init__(
        self,
        *,
        z_threshold: float = 3.0,                    # B1
        iqr_coef: float = 1.5,                       # B2 (宏观 1.3× 走查)
        category_iqr_coef: Mapping[str, float] | None = None,  # 如 {"macro": 1.3}
        default_atr_k: float = 3.0,                  # B3
        asset_atr_k_map: Mapping[str, float] | None = None,    # 如 {"XAU": 2.5, "COIN": 2.8}
        atr_period: int = 14,                        # Wilder 14
        price_col: str = "close",
    ) -> None:
        self.z = z_threshold
        self.iqr_coef_default = iqr_coef
        self.iqr_coef_by_cat = dict(category_iqr_coef or {})
        self.atr_k_default = default_atr_k
        self.atr_k_by_asset = dict(asset_atr_k_map or {})
        self.atr_period = atr_period
        self.price_col = price_col

    # ------------------------------------------------------------------
    def clean(
        self,
        df: pd.DataFrame,
        trace: CleaningTrace,
        *,
        asset: str = "",
        category: str = "",
        event_hits: Iterable[int] | None = None,  # 被巨鲸/新闻事件命中的行号（命中则ATR异常保留原值）
        **_: object,
    ) -> tuple[pd.DataFrame, CleanAction]:
        input_rows = len(df)
        note_parts: list[str] = []
        clipped = 0

        out = df.copy()
        event_rows = set(event_hits or [])

        # 仅对数值列操作
        numeric_cols = out.select_dtypes(include=[np.number]).columns.tolist()
        if not numeric_cols:
            act = CleanAction(step="Outlier3LFilter", input_rows=input_rows,
                              output_rows=len(out), note="no_numeric_cols")
            trace.append(act)
            return out, act

        # ================================================================
        # ① 粗筛：|Z|>3.0 仅标记（不裁剪，不丢原始信号原则）
        # ================================================================
        z_marked = 0
        for col in numeric_cols:
            series = out[col].dropna()
            if len(series) < 2:
                continue
            mu = series.mean()
            sigma = series.std()
            if sigma == 0 or np.isnan(sigma):
                continue
            z_vals = (out[col] - mu).abs() / sigma
            count = int(((z_vals > self.z) & (~out[col].isna())).sum())
            z_marked += count
        if z_marked:
            note_parts.append(f"3σ_marked_only_no_clip={z_marked}")

        # ================================================================
        # ② 中筛：IQR × coef → clip 到边界（事件期保留）
        # ================================================================
        iqr_coef = self.iqr_coef_by_cat.get(category, self.iqr_coef_default)
        iqr_clip_total = 0
        for col in numeric_cols:
            series = out[col].dropna()
            if len(series) < 4:
                continue
            q1 = series.quantile(0.25)
            q3 = series.quantile(0.75)
            iqr = q3 - q1
            if iqr == 0:
                continue  # 常值列不除零不抛
            lower = q1 - iqr_coef * iqr
            upper = q3 + iqr_coef * iqr
            # 对非事件行 clip，事件行保留
            row_mask = out.index.isin([i for i in out.index if i not in event_rows]) if event_rows else slice(None)
            before = out[col].copy()
            if isinstance(row_mask, slice):
                out.loc[:, col] = out[col].clip(lower=lower, upper=upper)
            else:
                out.loc[row_mask, col] = out.loc[row_mask, col].clip(lower=lower, upper=upper)
            diffs = (out[col] - before).abs().fillna(0)
            col_clip = int((diffs > 1e-12).sum())
            iqr_clip_total += col_clip
        clipped += iqr_clip_total
        if iqr_clip_total:
            note_parts.append(f"IQR×{iqr_coef}_clip={iqr_clip_total}")

        # ================================================================
        # ③ 精筛：14-ATR × k
        # ================================================================
        atr_k = self.atr_k_by_asset.get(asset, self.atr_k_default)
        atr_clip = 0
        if self.price_col in out.columns and len(out) >= self.atr_period:
            price = pd.to_numeric(out[self.price_col], errors="coerce").astype(float)
            atr_series = self._wilder_atr(price, period=self.atr_period)
            threshold = atr_k * atr_series
            price.diff().abs()
            # 超阈值 & 不在事件命中行 → clip 到 ± threshold（与上一行方向一致）
            if not threshold.isna().all():
                prev_price = price.shift(1)
                direction = np.sign(price - prev_price)
                prev_price + direction * threshold.fillna(0)
                # 对非事件行做 clip 限制
                for i, idx in enumerate(out.index):
                    if i < 1 or idx in event_rows:
                        continue
                    thr = threshold.iloc[i]
                    if np.isnan(thr) or thr == 0:
                        continue
                    cur = out.loc[idx, self.price_col]
                    prev = out.iloc[i - 1][self.price_col]
                    if np.isnan(cur) or np.isnan(prev):
                        continue
                    if abs(cur - prev) > thr:
                        out.loc[idx, self.price_col] = prev + np.sign(cur - prev) * thr
                        atr_clip += 1
        clipped += atr_clip
        if atr_clip or True:
            note_parts.append(f"ATR{self.atr_period}×k={atr_k}_clip={atr_clip}_eventHit={len(event_rows)}")

        action = CleanAction(
            step="Outlier3LFilter",
            input_rows=input_rows,
            output_rows=len(out),
            clipped_count=clipped,
            imputed_count=z_marked,  # 把 3σ 标记数写到 imputed（借用计数槽做审计），真实 impute=0
            note="; ".join(note_parts),
        )
        trace.append(action)
        return out, action

    # ------------------------------------------------------------------
    @staticmethod
    def _wilder_atr(price: pd.Series, period: int) -> pd.Series:
        """Wilder 平滑 ATR：仅用 close 的 abs diff 近似（缺少 high/low 时的降级）。"""
        tr = price.diff().abs()
        atr = tr.rolling(window=period, min_periods=period).mean()
        # Wilder's smoothing（一步近似：足够用于粗筛阈值）
        for i in range(period + 1, len(atr)):
            if pd.notna(atr.iloc[i - 1]):
                atr.iloc[i] = (atr.iloc[i - 1] * (period - 1) + (tr.iloc[i] if pd.notna(tr.iloc[i]) else 0)) / period
        return atr
