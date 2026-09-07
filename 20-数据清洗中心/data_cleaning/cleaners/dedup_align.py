"""T2 · DedupAlignCleaner：去重 + 时间戳对齐 + 重采样 ffill(limit=5) + 长间隙线性 + fail-open=50。

支持两类数据模式（自动识别 + 可手动覆盖）：

A. TIME_SERIES（finance/chain/同 asset 同 metric 多时间点 → 默认）
   行为：按 (timestamp, asset, key) 去重 → resample mean+ffill → ffill → linear → fillna(50)
   适用：OHLCV、稳定币市值日频、持仓量/资金费率等时序列

B. FLAT_HETEROGENEOUS（news/macro/按 sub_category 或 asset 语义拆分的一行/一指标记录）
   判定：
     · category="news"（DataCleaningPipeline 自动注入）；或
     · 含有 "sub_category" 列 且 行数≤1000 且 每 (sub_category, asset) 只出现 ≤2 条（避免错判）
   行为：
     · 不 resample（不合并不同 sub_category 的语义），只按主键 (timestamp, sub_category, asset) 去重
     · 不对缺失数值列做 ffill / linear / fillna(50) 的跨记录插值（跨 sub_category 无意义）
     · 数值列仅对本记录内部 NaN → fail-open_50 兜底（不互相污染）
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
from data_cleaning.contract import CleanAction, CleaningTrace


class DedupAlignCleaner:
    """责任链：先消除主键重复，再按目标频率对齐resample，按 B7 ffill(limit=N) 兜底。

    NEWS（异质）模式下自动退化为：(timestamp, sub_category, asset) dedup + 逐记录 fillna(50)，
    不做跨 sub_category resample/ffill/linear（语义独立，禁止互相污染）。
    """

    # FLAT 模式每 (sub_category, asset) 去重后重复行数阈值；低于此值走 FLAT 模式避免误 resample
    _FLAT_MODE_REPEAT_THRESHOLD = 3

    def __init__(
        self,
        *,
        target_freq: str = "1h",
        dedup_subset: Optional[list[str]] = None,       # None → 自动选 [timestamp, asset, key]
        ffill_limit: int = 5,
        timestamp_col: str = "timestamp",
        asset_col: str = "asset",
        key_col: str = "key",
        sub_category_col: str = "sub_category",
        fail_open_value: float = 50.0,
        category: Optional[str] = None,                 # Dispatcher 注入 category（news/macro/finance/chain）
    ) -> None:
        self.target_freq = target_freq
        self._dedup_subset = dedup_subset
        self.ffill_limit = ffill_limit
        self.timestamp_col = timestamp_col
        self.asset_col = asset_col
        self.key_col = key_col
        self.sub_category_col = sub_category_col
        self.fail_open_value = fail_open_value
        self.category = category  # "news" 时强制异质模式

    # ------------------------------------------------------------------
    # 对外：clean(df, trace) → (df, CleanAction)
    # ------------------------------------------------------------------
    def clean(self, df: pd.DataFrame, trace: CleaningTrace, **ctx: object) -> tuple[pd.DataFrame, CleanAction]:
        input_rows = len(df)
        clipped = 0
        imputed = 0
        note_parts: list[str] = []

        out = df.copy()
        if out.empty:
            return self._emit(out, trace, input_rows, clipped, imputed, note_parts, "empty_ds")

        category = self.category or (ctx.get("category") if isinstance(ctx, dict) else None) or None
        is_flat = self._detect_flat_heterogeneous(out, category)

        # --- ① 去重 ---
        if is_flat:
            dedup_cols = self._resolve_flat_dedup_cols(out)
        else:
            dedup_cols = self._resolve_ts_dedup_cols(out)
        if dedup_cols:
            before = len(out)
            out = out.drop_duplicates(subset=dedup_cols, keep="first").reset_index(drop=True)
            clipped += before - len(out)
            if before - len(out):
                note_parts.append(f"dedup_drop={before - len(out)}")

        if is_flat:
            # --- ②-FLAT：不 resample / 不跨行 ffill，仅逐行数值 NaN → fillna(50) ---
            if self.timestamp_col in out.columns:
                out[self.timestamp_col] = pd.to_datetime(out[self.timestamp_col])
            numeric_cols = out.select_dtypes(include=[np.number]).columns.tolist()
            if numeric_cols:
                mask = out[numeric_cols].isna()
                if mask.any().any():
                    count_fb50 = int(mask.sum().sum())
                    out[numeric_cols] = out[numeric_cols].fillna(self.fail_open_value)
                    imputed += count_fb50
                    note_parts.append(f"flat_fail-open_50={count_fb50}")
            mode_note = "FLAT(news/macro heterogeneous per-subcategory no-resample)"
            return self._emit(out, trace, input_rows, clipped, imputed, note_parts, mode_note)

        # --- ②-TIMESERIES · 时间戳索引对齐 ---
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
        return self._emit(
            out, trace, input_rows, clipped, imputed, note_parts,
            f"TIMESERIES resample({self.target_freq})",
        )

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    def _emit(
        self,
        out: pd.DataFrame,
        trace: CleaningTrace,
        input_rows: int,
        clipped: int,
        imputed: int,
        note_parts: list[str],
        mode: str,
    ) -> tuple[pd.DataFrame, CleanAction]:
        note = f"mode={mode}"
        if note_parts:
            note += "; " + "; ".join(note_parts)
        action = CleanAction(
            step="DedupAlignCleaner",
            input_rows=input_rows,
            output_rows=len(out),
            clipped_count=clipped,
            imputed_count=imputed,
            note=note,
        )
        trace.append(action)
        return out, action

    def _detect_flat_heterogeneous(self, df: pd.DataFrame, category) -> bool:
        # 1) 显式 category == "news" → 按异质
        if isinstance(category, str) and category.lower() == "news":
            return True
        # 2) 显式 dedup_subset 被用户给了 → 尊重用户配置，走 TS 模式（由 caller 控制）
        if self._dedup_subset:
            return False
        # 3) 有 sub_category 列：按 (sub_category, asset) 重复次数 ≤3 → FLAT（避免和时序列混）
        if self.sub_category_col in df.columns:
            group_cols = [c for c in (self.sub_category_col, self.asset_col) if c in df.columns]
            if group_cols:
                counts = df.groupby(group_cols).size()
                # 所有组重复次数 <= _FLAT_MODE_REPEAT_THRESHOLD 且 唯一 sub_category 数 ≥2（≥2条语义独立）
                if len(counts) >= 2 and (counts <= self._FLAT_MODE_REPEAT_THRESHOLD).all():
                    return True
        return False

    def _resolve_ts_dedup_cols(self, df: pd.DataFrame) -> list[str]:
        if self._dedup_subset:
            return [c for c in self._dedup_subset if c in df.columns]
        candidates = [self.timestamp_col, self.asset_col, self.key_col]
        return [c for c in candidates if c in df.columns]

    def _resolve_flat_dedup_cols(self, df: pd.DataFrame) -> list[str]:
        if self._dedup_subset:
            return [c for c in self._dedup_subset if c in df.columns]
        # 异质记录去重主键：(timestamp, sub_category, asset) 三元组；sub_category 不存在时 fallback
        candidates = [
            self.timestamp_col,
            self.sub_category_col,
            self.asset_col,
            self.key_col,
        ]
        cols = [c for c in candidates if c in df.columns]
        if not cols:
            return []
        return cols

