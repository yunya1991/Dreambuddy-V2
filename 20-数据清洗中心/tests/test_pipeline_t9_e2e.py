"""T9 · Pipeline 全链路 + fail-open（Spec§C3/C6）。

入口：DataCleaningPipeline(records) → SilverRecord。
  路径：records→DF → DedupAlign → Outlier3L → MissingImputer → UnitNormalizer → Gate → (SilverRecord 或 fail-open)

T9-1 全链路端到端：records=[BTC ohlcv] → SilverRecord.gate_passed=True + df无NaN无重复
T9-2 注入 2 个 NaN → imputed_count > 0 → Gate仍通过
T9-3 注入 IQR 尾部异常值 → clipped_count > 0 → Gate仍通过
T9-4 注入脏 batch（全空 records）→ Gate FAIL → enforce=True 时抛 QualityGateFailed，fail_open=True 时返回 gate_passed=False 但不抛
T9-5 注入中间 cleaner 抛 Exception → fail_open=True 返回 gate_passed=False + 原始DF作为兜底；fail_open=False 抛
T9-6 trace.actions 覆盖 4 个 Cleaner + QualityGate（共5段痕迹），顺序正确
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from data_center.core.contract import DataRecord  # type: ignore


def _iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _ohlcv_btc(ts_shift_min: int = 5, with_hours: int = 6) -> DataRecord:
    ts = datetime.now(timezone.utc) - timedelta(minutes=ts_shift_min)
    rows = pd.date_range(ts - timedelta(hours=with_hours - 1), periods=with_hours, freq="1h")
    values_close = [100.0 + i for i in range(with_hours)]
    volume = [10 * (i + 1) for i in range(with_hours)]
    return DataRecord(
        source="yfinance", category="finance", sub_category="ohlcv",
        timestamp=_iso(ts),
        metrics={"asset": "BTC", "pair": "BTC-USD"},
        events=[],
        timeseries=pd.DataFrame({
            "timestamp": [_iso(t) for t in rows],
            "close": values_close,
            "volume": volume,
        }).to_dict(orient="records"),
        raw={},
    )


class TestPipeline:
    # T9-1 全链路：空脏=全通过
    def test_t9_1_e2e_clean_btc_ohlcv(self) -> None:
        from data_cleaning.pipeline import DataCleaningPipeline

        pipe = DataCleaningPipeline(
            enforce_hard_block=True,
            freshness_threshold=timedelta(days=365),  # 保证测试数据新鲜度不拦
            fail_open=False,
        )
        silver = pipe.clean([_ohlcv_btc()], source="yfinance", category="finance")
        assert silver.gate_passed is True
        assert len(silver.df) >= 6
        # 无 NaN（cleaner 已处理）
        assert silver.df["close"].isna().sum() == 0
        # Trace 长度：Adapter→4个Cleaner→Gate（至少6段痕迹中含"cleaner"类步骤）
        steps = {a.step for a in silver.trace.actions}
        assert "DedupAlignCleaner" in steps

    # T9-2 注入 2 NaN → MissingImputer 工作，Gate仍通过
    def test_t9_2_inject_two_nan_imputed_ok(self) -> None:
        from data_cleaning.pipeline import DataCleaningPipeline

        rec = _ohlcv_btc()
        # 把 timeseries 的第 1/3 行 close 改成 NaN
        rec.timeseries[1]["close"] = None
        rec.timeseries[3]["close"] = None
        pipe = DataCleaningPipeline(
            enforce_hard_block=True,
            freshness_threshold=timedelta(days=365),
            fail_open=False,
        )
        silver = pipe.clean([rec], source="yfinance", category="finance")
        assert silver.gate_passed is True
        # 注入的两个 NaN 已被 ffill/linear 填，无 NaN
        assert silver.df["close"].isna().sum() == 0
        # trace 内所有 Cleaner imputed 合计 >= 2（DedupAlign 先跑 ffill 再 MissingImputer 兜底，二选一都算）
        total_imputed = silver.trace.total_imputed
        assert total_imputed >= 2, f"总插补计数应≥2: {total_imputed}"
        # 至少有一个 Cleaner 贡献了 imputed（DedupAlign 或 MissingImputer）
        imputed_steps = [(a.step, a.imputed_count) for a in silver.trace.actions if a.imputed_count > 0]
        assert len(imputed_steps) >= 1, f"NaN未被任何步骤处理: trace={[a.note for a in silver.trace.actions]}"

    # T9-3 IQR 尾部异常值 → Outlier3L clip
    def test_t9_3_inject_outlier_clipped_then_pass(self) -> None:
        from data_cleaning.pipeline import DataCleaningPipeline

        rec = _ohlcv_btc(with_hours=40)  # 多点才够 IQR 统计
        # 注入 3 个极端尾部点
        rec.timeseries[10]["close"] = 10_000.0
        rec.timeseries[20]["close"] = -5_000.0
        rec.timeseries[30]["close"] = 50_000.0
        pipe = DataCleaningPipeline(
            enforce_hard_block=True,
            freshness_threshold=timedelta(days=365),
            fail_open=False,
        )
        silver = pipe.clean([rec], source="yfinance", category="finance")
        assert silver.gate_passed is True
        clips = [a.clipped_count for a in silver.trace.actions if a.step == "Outlier3LFilter"]
        assert clips and clips[0] >= 1, f"异常值没被裁剪: clips={clips}"
        # 最大值应被 IQR clip 限制到 < 5000
        assert silver.df["close"].max() < 5000

    # T9-4 全空 records：enforce=True 抛异常；fail_open=True 不抛但 gate_passed=False
    def test_t9_4_empty_records_gate_fail(self) -> None:
        from data_cleaning.errors import QualityGateFailed
        from data_cleaning.pipeline import DataCleaningPipeline

        pipe_hard = DataCleaningPipeline(
            enforce_hard_block=True,
            freshness_threshold=timedelta(days=365),
            fail_open=False,
        )
        with pytest.raises(QualityGateFailed):
            pipe_hard.clean([], source="yfinance", category="finance")

        # 软模式（enforce=True 但 fail_open=True 兜底 gate 拦截也兜底 = 不抛）
        pipe_soft = DataCleaningPipeline(
            enforce_hard_block=True,
            freshness_threshold=timedelta(days=365),
            fail_open=True,
        )
        silver = pipe_soft.clean([], source="yfinance", category="finance")
        assert silver.gate_passed is False
        # df 是兜底空DF，不应是 None
        assert silver.df is not None

    # T9-5 中间 cleaner 抛 Exception：fail_open 兜底；否则抛
    def test_t9_5_middle_cleaner_exception_fail_open(self) -> None:
        # 通过 monkey-patch DedupAlignCleaner.clean 强制抛
        from data_cleaning.cleaners.dedup_align import DedupAlignCleaner
        from data_cleaning.pipeline import DataCleaningPipeline
        orig = DedupAlignCleaner.clean

        def boom(self, df, trace, **kw):  # noqa: D401
            raise RuntimeError("oops, dedup broken")

        DedupAlignCleaner.clean = boom
        try:
            pipe = DataCleaningPipeline(
                enforce_hard_block=True,
                freshness_threshold=timedelta(days=365),
                fail_open=False,
            )
            with pytest.raises(RuntimeError):
                pipe.clean([_ohlcv_btc()], source="yfinance", category="finance")

            # fail_open=True → 不抛，gate_passed=False，df有行数兜底
            pipe_fs = DataCleaningPipeline(
                enforce_hard_block=True,
                freshness_threshold=timedelta(days=365),
                fail_open=True,
            )
            silver = pipe_fs.clean([_ohlcv_btc()], source="yfinance", category="finance")
            assert silver.gate_passed is False
            # 至少能把 records_to_cleaned_df 的 df 兜底给出来
            assert len(silver.df) >= 1
        finally:
            DedupAlignCleaner.clean = orig  # type: ignore[assignment]

    # T9-6 trace 全步骤：5段（DedupAlign / Outlier3L / MissingImputer / UnitNormalizer / QualityGate）
    def test_t9_6_trace_actions_full_choreography(self) -> None:
        from data_cleaning.pipeline import DataCleaningPipeline

        pipe = DataCleaningPipeline(
            enforce_hard_block=True,
            freshness_threshold=timedelta(days=365),
            fail_open=False,
        )
        silver = pipe.clean([_ohlcv_btc()], source="yfinance", category="finance")
        steps = [a.step for a in silver.trace.actions]
        # 含 4 Cleaner + QualityGate
        for must in ["DedupAlignCleaner", "Outlier3LFilter", "MissingImputer",
                      "UnitNormalizer", "QualityGate"]:
            assert must in steps, f"缺失 {must} 步骤: {steps}"
        # 顺序：Cleaner 在 Gate 前
        assert steps.index("QualityGate") > steps.index("UnitNormalizer")
