"""T2 · DedupAlignCleaner：去重 + 时间戳对齐 + 重采样 ffill(limit=5) + 长间隙线性 + fail-open=50。"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
from data_cleaning.contract import CleanAction, CleaningTrace


class DedupAlignCleaner:
    """责任链：先消除主键重复，再按目标频率对齐resample，按 B7 ffill(limit=N) 兜底。"""

    def __init__(
        self,
        *,
        target_freq: str = "1h",
        dedup_subset: Optional[list[str]] = None,       # None → 自动选 [timestamp, asset, key]
        ffill_limit: int = 5,
        timestamp_col: str = "timestamp",
        asset_col: str = "asset",
        key_col: str = "key",
        fail_open_value: float = 50.0,
    ) -> None:
        self.target_freq = target_freq
        self._dedup_subset = dedup_subset
        self.ffill_limit = ffill_limit
        self.timestamp_col = timestamp_col
        self.asset_col = asset_col
        self.key_col = key_col
        self.fail_open_value = fail_open_value

    # ------------------------------------------------------------------
    # 对外：clean(df, trace) → (df, CleanAction)
    # ------------------------------------------------------------------
    def clean(self, df: pd.DataFrame, trace: CleaningTrace, **_: object) -> tuple[pd.DataFrame, CleanAction]:
        input_rows = len(df)
        clipped = 0
        imputed = 0
        note_parts: list[str] = []

        out = df.copy()

        # --- ① 去重 ---
        subset = self._resolve_dedup_cols(out)
        if subset:
            before = len(out)
            out = out.drop_duplicates(subset=subset, keep="first").reset_index(drop=True)
            clipped += before - len(out)
            if before - len(out):
                note_parts.append(f"dedup_drop={before - len(out)}")

        # --- ② 时间戳索引对齐 ---
        if self.timestamp_col in out.columns:
            out[self.timestamp_col] = pd.to_datetime(out[self.timestamp_col])
            out = out.set_index(self.timestamp_col).sort_index()

            # resample 到目标频率（数值列取 mean，非数值 ffill）
            numeric_cols = out.select_dtypes(include=[np.number]).columns.tolist()
            non_numeric_cols = [c for c in out.columns if c not in numeric_cols]
            resampler = out.resample(self.target_freq)
            if numeric_cols:
                resampled_num = resampler[numeric_cols].mean()
            else:
                resampled_num = pd.DataFrame(index=resampler.asfreq().index)
            resampled_nonnum = (
                resampler[non_numeric_cols].ffill()
                if non_numeric_cols else pd.DataFrame(index=resampled_num.index)
            )
            out = resampled_num.join(resampled_nonnum, how="left")
            # 保证完整时间网格（丢失的小时条目生成 NaN 行，供后续 ffill/linear/fallback50 责任链节点处理）
            out = out.asfreq(self.target_freq)

            # --- ③ ffill(limit=5) ---
            before_na = out[numeric_cols].isna().sum().sum() if numeric_cols else 0
            if numeric_cols:
                out[numeric_cols] = out[numeric_cols].ffill(limit=self.ffill_limit)
            after_ffill = out[numeric_cols].isna().sum().sum() if numeric_cols else 0
            filled_by_ffill = int(before_na - after_ffill)
            imputed += filled_by_ffill
            if filled_by_ffill:
                note_parts.append(f"ffill(limit={self.ffill_limit})={filled_by_ffill}")

            # --- ④ 超过 ffill 仍空 → 线性插值 ---
            if numeric_cols:
                before_interp = out[numeric_cols].isna().sum().sum()
                out[numeric_cols] = out[numeric_cols].interpolate(method="linear", limit_direction="both")
                after_interp = out[numeric_cols].isna().sum().sum()
                filled_by_interp = int(before_interp - after_interp)
                imputed += filled_by_interp
                if filled_by_interp:
                    note_parts.append(f"linear_interp={filled_by_interp}")

                # --- ⑤ 仍空 → fail-open 中性50（B5兜底） ---
                mask = out[numeric_cols].isna()
                if mask.any().any():
                    count_fb50 = int(mask.sum().sum())
                    out[numeric_cols] = out[numeric_cols].fillna(self.fail_open_value)
                    imputed += count_fb50
                    note_parts.append(f"fail-open_50={count_fb50}")

            out = out.reset_index()  # timestamp 回到列

        action = CleanAction(
            step="DedupAlignCleaner",
            input_rows=input_rows,
            output_rows=len(out),
            clipped_count=clipped,
            imputed_count=imputed,
            note="; ".join(note_parts) if note_parts else f"resample({self.target_freq})",
        )
        trace.append(action)
        return out, action

    # ------------------------------------------------------------------
    def _resolve_dedup_cols(self, df: pd.DataFrame) -> list[str]:
        if self._dedup_subset:
            return [c for c in self._dedup_subset if c in df.columns]
        candidates = [self.timestamp_col, self.asset_col, self.key_col]
        return [c for c in candidates if c in df.columns]
