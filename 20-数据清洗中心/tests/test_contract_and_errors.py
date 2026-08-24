"""T1 · Contract + Errors 单测（RED → GREEN TDD）。"""
from __future__ import annotations

from datetime import datetime

import pandas as pd


# ---------------------------------------------------------------------------
# T1-1 / T1-2 / T1-3 · Contract 三个 dataclass 字段齐全 & 基础构造
# ---------------------------------------------------------------------------
class TestContractTypesExist:
    def test_t1_1_silver_record_fields_exist(self) -> None:
        """SilverRecord = bronze_id + df + trace + gate_passed + quality_report."""
        from data_cleaning.contract import SilverRecord  # RED: 导入会失败

        df = pd.DataFrame({"close": [1.0, 2.0]})
        trace = object()  # CleaningTrace 稍后测
        rec = SilverRecord(
            bronze_id="bronze-abc-123",
            df=df,
            trace=trace,
            gate_passed=True,
            quality_report=[],
        )
        assert rec.bronze_id == "bronze-abc-123"
        assert rec.df is df
        assert rec.trace is trace
        assert rec.gate_passed is True
        assert rec.quality_report == []

    def test_t1_1_cleaned_df_schema_tag(self) -> None:
        """CleanedDF 携带 schema_tag 便于 Pandera 校验定位。"""
        from data_cleaning.contract import CleanedDF

        df = pd.DataFrame({"ts": [1, 2], "price": [10.0, 20.0]})
        cdf = CleanedDF(df=df, schema_tag="ohlcv_v1")
        assert cdf.schema_tag == "ohlcv_v1"
        assert len(cdf.df) == 2

    def test_t1_1_cleaning_trace_and_action(self) -> None:
        """CleaningTrace 存 CleanAction 列表，每个 Action 含 clipped/imputed 计数。"""
        from data_cleaning.contract import CleaningAction, CleaningTrace

        a1 = CleaningAction(
            step="Outlier3LFilter",
            input_rows=1000,
            output_rows=1000,
            clipped_count=7,
            imputed_count=0,
            note="3σ 标记 5；IQR clip 2",
        )
        a2 = CleaningAction(
            step="MissingImputer",
            input_rows=1000,
            output_rows=1000,
            clipped_count=0,
            imputed_count=12,
            note="ffill(5) 11 + linear 1",
        )
        trace = CleaningTrace(actions=[a1, a2], started_at=datetime.now(), finished_at=datetime.now())
        assert trace.total_clipped == 7
        assert trace.total_imputed == 12
        assert len(trace.actions) == 2
        assert trace.actions[0].step == "Outlier3LFilter"


# ---------------------------------------------------------------------------
# T1-2 · Errors 继承层次：CleaningError(Base) → QualityGateFailed(带 code)
# ---------------------------------------------------------------------------
class TestErrorHierarchy:
    def test_t1_2_cleaning_error_is_exception(self) -> None:
        from data_cleaning.errors import CleaningError

        assert issubclass(CleaningError, Exception)
        try:
            raise CleaningError("x", traceback_str="stack-lines")
        except CleaningError as e:
            assert e.message == "x"
            assert "stack-lines" in (e.traceback_str or "")

    def test_t1_2_quality_gate_failed_is_cleaning_error(self) -> None:
        from data_center.monitoring.quality import QualityIssueCode
        from data_cleaning.errors import CleaningError, QualityGateFailed

        assert issubclass(QualityGateFailed, CleaningError)
        try:
            raise QualityGateFailed(
                message="stale > 15min",
                code=QualityIssueCode.TIMESTAMP_FRESHNESS,
                issues=[{"code": "TIMESTAMP_FRESHNESS"}],
            )
        except CleaningError as e:
            assert isinstance(e, QualityGateFailed)
            assert e.code == QualityIssueCode.TIMESTAMP_FRESHNESS
            assert len(e.issues) == 1


# ---------------------------------------------------------------------------
# T1-3 · __init__.py 对外导出字节等价（调用方 import 一次拿齐）
# ---------------------------------------------------------------------------
class TestPackageExports:
    def test_t1_3_init_exports_all_public_symbols(self) -> None:
        """__init__.py 必须直接导出：Contract三类型 + Errors二类型。"""
        import data_cleaning

        for name in ("SilverRecord", "CleanedDF", "CleaningTrace",
                     "CleaningAction", "CleaningError", "QualityGateFailed"):
            assert hasattr(data_cleaning, name), f"缺少导出: {name}"
