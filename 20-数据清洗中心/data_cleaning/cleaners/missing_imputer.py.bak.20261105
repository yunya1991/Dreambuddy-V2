"""T4 · MissingImputer：三级兜底（时序 ffill→linear→50 / 宏观 linear→拖尾→50 / 事件 1/0/0.5）。"""
from __future__ import annotations

import numpy as np
import pandas as pd
from data_cleaning.contract import CleanAction, CleaningTrace


class MissingImputer:
    def __init__(
        self,
        *,
        ffill_limit: int = 5,             # B7
        fail_open_value: float = 50.0,    # B5
        category_col: str = "category",
    ) -> None:
        self.ffill_limit = ffill_limit
        self.fail_open = fail_open_value
        self.cat_col = category_col

    # ------------------------------------------------------------------
    def clean(self, df: pd.DataFrame, trace: CleaningTrace, **_: object) -> tuple[pd.DataFrame, CleanAction]:
        input_rows = len(df)
        imputed = 0
        note_parts: list[str] = []
        out = df.copy()

        category = "timeseries"
        if self.cat_col in out.columns and len(out) > 0:
            vals = out[self.cat_col].dropna().unique().tolist()
            category = vals[0] if vals else "timeseries"

        numeric_cols = out.select_dtypes(include=[np.number]).columns.tolist()
        # 事件布尔列：object/bool 列也要转 1/0/0.5
        bool_cols = [c for c in out.columns if c != self.cat_col
                     and (out[c].dtype == bool or out[c].dtype == object)]

        # ================================================================
        # 事件分支 (events) → 先处理 bool/object 列
        # ================================================================
        if category == "events":
            for c in bool_cols:
                before = out[c].copy()
                uniq = before.dropna().unique().tolist()
                is_bool_like = all(isinstance(v, (bool, np.bool_)) or
                                   (isinstance(v, (int, float, np.number)) and v in (0, 1))
                                   for v in uniq) if uniq else False
                if is_bool_like:
                    # True/False → 1/0；NaN → 0.5（T4-5 / T4-6）
                    def _map(x: object) -> float:
                        if x is None or (isinstance(x, float) and np.isnan(x)):
                            return 0.5
                        if isinstance(x, (bool, np.bool_)):
                            return 1.0 if x else 0.0
                        return 1.0 if float(x) == 1.0 else 0.0
                    out[c] = before.apply(_map).astype(float)
                    imputed += int((before.isna() & out[c].notna()).sum())
                    note_parts.append(f"event_bool_0.5neutral({c})")
                numeric_cols.append(c) if c not in numeric_cols else None

        # ================================================================
        # 数值列：分支 = timeseries / macro
        # ================================================================
        if numeric_cols:
            before_nan = int(out[numeric_cols].isna().sum().sum())
            if before_nan == 0:
                pass
            elif category == "timeseries":
                # ① ffill(limit=5) → ② linear → ③ fail-open=50（T4-1/T4-2/T4-3）
                out[numeric_cols] = out[numeric_cols].ffill(limit=self.ffill_limit)
                out[numeric_cols] = out[numeric_cols].interpolate(method="linear", limit_direction="both")
                out[numeric_cols] = out[numeric_cols].fillna(self.fail_open)
            elif category == "macro":
                # ① linear → ② ffill（稳定期拖尾）→ fail-open（T4-4）
                out[numeric_cols] = out[numeric_cols].interpolate(method="linear", limit_direction="both")
                out[numeric_cols] = out[numeric_cols].ffill().bfill()
                out[numeric_cols] = out[numeric_cols].fillna(self.fail_open)
            else:
                out[numeric_cols] = out[numeric_cols].ffill(limit=self.ffill_limit).interpolate(limit_direction="both").fillna(self.fail_open)

            after_nan = int(out[numeric_cols].isna().sum().sum())
            filled = before_nan - after_nan
            imputed += filled
            if after_nan > 0:
                # 极端情况：再加一次 50 兜底（不应发生但 fail-safe）
                out[numeric_cols] = out[numeric_cols].fillna(self.fail_open)
                imputed += after_nan
            note_parts.append(f"{category}_filled={filled}")

        # 整列全空 fail-open 双保险（T4-3）
        for c in numeric_cols:
            if c in out.columns and out[c].isna().any():
                cnt = int(out[c].isna().sum())
                out[c] = out[c].fillna(self.fail_open)
                imputed += cnt
                note_parts.append(f"fallback50({c}={cnt})")

        action = CleanAction(
            step="MissingImputer",
            input_rows=input_rows,
            output_rows=len(out),
            imputed_count=imputed,
            note="; ".join(note_parts) or "no_missing",
        )
        trace.append(action)
        return out, action
