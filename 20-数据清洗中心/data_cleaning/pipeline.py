"""DataCleaningPipeline — Silver 层入口（Spec§C3 全链路编排）。

顺序（Spec§C3）：
  1. Adapters.records_to_cleaned_df → (df, meta, primary_key_count)
  2. DedupAlignCleaner
  3. Outlier3LFilter
  4. MissingImputer
  5. UnitNormalizer
  6. cleaned_df_to_records → [DataRecord]
  7. QualityGate.validate(enforce 或 fail-open 兜底)
  8. 出口：SilverRecord（gate_passed + quality_report + trace）

fail-open（Spec§C6）：
  · 中间 cleaner 抛异常 → 记录 trace，跳过后续 cleaner，直接把当前 DF 兜底进入 Gate（enforce=False）
  · Gate enforce=True 抛 QualityGateFailed 时，如果 fail_open=True → catch 后返回 gate_passed=False 的 SilverRecord。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Iterable, Optional

import pandas as pd
from data_center.core.contract import DataRecord  # type: ignore

from data_cleaning.adapters import cleaned_df_to_records, records_to_cleaned_df
from data_cleaning.cleaners.dedup_align import DedupAlignCleaner
from data_cleaning.cleaners.missing_imputer import MissingImputer
from data_cleaning.cleaners.outlier_filter import Outlier3LFilter
from data_cleaning.cleaners.unit_normalizer import UnitNormalizer
from data_cleaning.contract import CleanAction, CleanedDF, CleaningTrace, SilverRecord
from data_cleaning.errors import QualityGateFailed
from data_cleaning.gate.quality_gate import QualityGate, QualityIssue

__all__ = ["DataCleaningPipeline", "PipelineConfig"]


@dataclass
class PipelineConfig:
    """可配置参数（Spec§C3.3）。"""
    target_freq: str = "1h"
    ffill_limit: int = 5
    z_threshold: float = 3.0
    iqr_coef: float = 1.5
    atr_k: float = 3.0
    enforce_hard_block: bool = True
    freshness_threshold: timedelta = field(default_factory=lambda: timedelta(hours=48))
    allow_empty_degraded_sources: tuple = ()
    # timestamp 列名（Cleaners 默认"timestamp"，可传"event_ts"等）
    timestamp_col: str = "timestamp"
    # fail-open 开关：任意异常兜底为 gate_passed=False SilverRecord（不向上抛）
    fail_open: bool = False
    # unit 规范化：是否启用汇率/百分比转换（默认关，保持字段语义不变）
    enable_unit_normalize: bool = True


class DataCleaningPipeline:
    """Silver 层总入口：对外唯一调用 API。"""

    def __init__(self, config: Optional[PipelineConfig] = None, **kwargs) -> None:
        if config is None:
            config = PipelineConfig(**kwargs)
        else:
            # kwargs 覆盖 config 字段（方便用在测试中）
            for k, v in kwargs.items():
                if hasattr(config, k):
                    setattr(config, k, v)
        self.cfg = config
        self._build()

    def _build(self) -> None:
        cfg = self.cfg
        self.dedup = DedupAlignCleaner(
            target_freq=cfg.target_freq,
            ffill_limit=cfg.ffill_limit,
            timestamp_col=cfg.timestamp_col,
        )
        self.outlier = Outlier3LFilter(
            z_threshold=cfg.z_threshold,
            iqr_coef=cfg.iqr_coef,
            default_atr_k=cfg.atr_k,
        )
        self.missing = MissingImputer(
            ffill_limit=cfg.ffill_limit,
        )
        self.unit = UnitNormalizer()
        self.gate = QualityGate(
            enforce_hard_block=cfg.enforce_hard_block,
            freshness_threshold=cfg.freshness_threshold,
            allow_empty_degraded_sources=cfg.allow_empty_degraded_sources,
        )

    # ------------------------------------------------------------------
    # 主 API
    # ------------------------------------------------------------------
    def clean(
        self,
        records: Iterable[DataRecord],
        *,
        source: str = "",
        category: str = "",
        sub_category: str = "",
        is_degraded: bool = False,
    ) -> SilverRecord:
        """执行整条清洗链 → SilverRecord 出口。"""
        records = list(records) if not isinstance(records, list) else records
        trace = CleaningTrace()
        cleaned: CleanedDF = records_to_cleaned_df(records)
        df = cleaned.df.copy() if not cleaned.df.empty else cleaned.df
        issues: list[QualityIssue] = []
        gate_passed = True

        # ---------- Cleaner 链（fail-open: 任意异常→记 trace, 保持原 df, 进 Gate）
        try:
            df = self._run_cleaner(self.dedup, df, trace, asset=_extract_first_asset(cleaned))
            df = self._run_cleaner(self.outlier, df, trace, asset=_extract_first_asset(cleaned))
            df = self._run_cleaner(self.missing, df, trace)
            if self.cfg.enable_unit_normalize:
                df = self._run_cleaner(self.unit, df, trace)
        except Exception as exc:  # noqa: BLE001
            trace.append(CleanAction(
                step="FAIL-OPEN-CATCH",
                input_rows=len(df), output_rows=len(df),
                note=f"{type(exc).__name__}: {exc}",
            ))
            if not self.cfg.fail_open:
                raise
            # fail-open: 直接把当前 df 兜底送出；不跑 Gate 流程（因为已经异常了，再送正常 Gate 可能 PASS，语义错）
            gate_passed = False
            issues = []
            trace.append(CleanAction(
                step="FAIL-OPEN(cleaner-exc)",
                input_rows=len(df), output_rows=len(df),
                note=f"{type(exc).__name__}: {exc}",
            ))
            trace.finished_at = pd.Timestamp.utcnow().to_pydatetime()
            return SilverRecord(
                bronze_id=_mk_bronze_id(records, source, category),
                df=df,
                trace=trace,
                gate_passed=False,
                quality_report=[],
            )

        # ---------- 还原成 [DataRecord]，再送 Gate
        records_out = cleaned_df_to_records(
            df,
            source=source or _source_fallback(records, cleaned),
            category=category or _category_fallback(records, cleaned),
            sub_category=sub_category or _sub_fallback(records, cleaned),
            asset_col="asset",
            timestamp_col=self.cfg.timestamp_col,
        ) if not df.empty else list(records)

        try:
            _gate_pass, issues = self.gate.validate(
                records_out if self.cfg.enforce_hard_block else records,
                source=source,
                category=category,
                is_degraded=is_degraded,
                trace=trace,
            )
            gate_passed = _gate_pass
        except QualityGateFailed as exc:
            if self.cfg.fail_open:
                gate_passed = False
                issues = exc.issues
                trace.append(CleanAction(
                    step="QualityGateFailed(catch-fail-open)",
                    input_rows=0, output_rows=0,
                    note=f"code={exc.code}, msg={exc.message}",
                ))
            else:
                raise

        trace.finished_at = trace.finished_at or pd.Timestamp.utcnow().to_pydatetime()
        return SilverRecord(
            bronze_id=_mk_bronze_id(records, source, category),
            df=df,
            trace=trace,
            gate_passed=gate_passed,
            quality_report=issues,
            schema_tag=cleaned.schema_tag,
        )

    # ------------------------------------------------------------------
    def _run_cleaner(self, cleaner, df: pd.DataFrame, trace: CleaningTrace, **kw) -> pd.DataFrame:
        if df is None or df.empty:
            trace.append(CleanAction(
                step=type(cleaner).__name__,
                input_rows=0, output_rows=0,
                note="empty_df_skip",
            ))
            return df
        out, _action = cleaner.clean(df, trace, **kw)
        return out


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _extract_first_asset(cleaned: CleanedDF) -> str:
    if cleaned.records and hasattr(cleaned.records[0], "asset"):
        return cleaned.records[0].asset or ""
    if "asset" in cleaned.df.columns and len(cleaned.df):
        v = cleaned.df["asset"].iloc[0]
        return str(v) if not pd.isna(v) else ""
    return ""


def _source_fallback(orig_records, cleaned: CleanedDF) -> str:
    if orig_records:
        return getattr(orig_records[0], "source", "")
    if cleaned.records and hasattr(cleaned.records[0], "source"):
        return cleaned.records[0].source
    return ""


def _category_fallback(orig_records, cleaned: CleanedDF) -> str:
    if orig_records:
        return getattr(orig_records[0], "category", "")
    if cleaned.records and hasattr(cleaned.records[0], "category"):
        return cleaned.records[0].category
    return ""


def _sub_fallback(orig_records, cleaned: CleanedDF) -> str:
    if orig_records:
        return getattr(orig_records[0], "sub_category", "")
    if cleaned.records and hasattr(cleaned.records[0], "sub_category"):
        return cleaned.records[0].sub_category
    return ""


def _mk_bronze_id(records, source: str, category: str) -> str:
    if records and hasattr(records[0], "timestamp"):
        return f"brz-{source or 'unk'}-{category or 'unk'}-{records[0].timestamp}"
    return f"brz-{source or 'unk'}-{category or 'unk'}"
