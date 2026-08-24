"""T5 · UnitNormalizer：非USD×汇率 / %→/100 / 换手率%→ratio。"""
from __future__ import annotations

from typing import Iterable, Mapping

import pandas as pd
from data_cleaning.contract import CleanAction, CleaningTrace


class UnitNormalizer:
    def __init__(
        self,
        *,
        fx_rates: Mapping[str, float] | None = None,       # 如 {"EUR":1.10}（1 EUR = X USD）
        price_columns: Iterable[str] = (),                 # 需按币种换算的列（后缀识别币种）
        percent_columns: Iterable[str] = (),               # 需 /100 的百分数字段
        turnover_columns: Iterable[str] = (),              # 换手率 %→ratio（同%，但单独分类便于审计）
    ) -> None:
        self.fx = dict(fx_rates or {"EUR": 1.10, "JPY": 0.0067, "GBP": 1.27})
        self.price_cols = list(price_columns)
        self.pct_cols = list(percent_columns)
        self.turn_cols = list(turnover_columns)

    # ------------------------------------------------------------------
    def clean(self, df: pd.DataFrame, trace: CleaningTrace, **_: object) -> tuple[pd.DataFrame, CleanAction]:
        input_rows = len(df)
        clipped = 0
        imputed = 0
        note_parts: list[str] = []
        out = df.copy()

        # T5-1：price 按后缀币种 → USD
        for col in self.price_cols:
            if col not in out.columns:
                continue
            # 后缀识别：_eur / _jpy / _gbp（大小写不敏感）
            suffix = col.lower().rsplit("_", 1)[-1] if "_" in col else ""
            rate: float | None = None
            for curr, fx in self.fx.items():
                if curr.lower() == suffix:
                    rate = fx
                    break
            if rate is None:
                continue
            original_sum = float(out[col].sum())
            out[col] = out[col] * rate
            new_sum = float(out[col].sum())
            note_parts.append(f"fx({col})×{rate}:{original_sum:.2f}→{new_sum:.2f}USD")

        # T5-2：百分比 → /100
        for col in self.pct_cols:
            if col not in out.columns:
                continue
            out[col] = out[col] / 100.0
            note_parts.append(f"%→ratio({col})")

        # T5-3：换手率 → /100
        for col in self.turn_cols:
            if col not in out.columns:
                continue
            out[col] = out[col] / 100.0
            note_parts.append(f"turnover%→ratio({col})")

        action = CleanAction(
            step="UnitNormalizer",
            input_rows=input_rows,
            output_rows=len(out),
            clipped_count=clipped,
            imputed_count=imputed,
            note="; ".join(note_parts) or "no_conversion_needed",
        )
        trace.append(action)
        return out, action
