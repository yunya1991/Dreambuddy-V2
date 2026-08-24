"""T2 · DedupAlignCleaner：去重 + 时间戳对齐 + 重采样 ffill(limit=5)。

覆盖边例（6条）：
  T2-1  重复行按 [timestamp, asset, key] 正确消除
  T2-2  resample 到目标频率后时间戳对齐
  T2-3  ffill limit=5 连续空只填充5个，第6个空不填
  T2-4  连续 >5 空 → 线性插值兜底 → 仍空 → 中性 50（B5/B7）
  T2-5  极端全列全空 → 整列填充 50（fail-open 中性）
  T2-6  三类 DataRecord（metrics / timeseries / events）分别跑，不崩
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


class TestDedupAlign:
    # ------------------------------------------------------------------
    # T2-1 重复行消除（两个不同小时：保证 dedup 后两个条目不会被 resample 合并）
    # ------------------------------------------------------------------
    def test_t2_1_deduplicate_by_timestamp_asset_key(self) -> None:
        from data_cleaning.cleaners.dedup_align import DedupAlignCleaner
        from data_cleaning.contract import CleaningTrace

        df = pd.DataFrame({
            "timestamp": pd.to_datetime(
                ["2026-08-01 10:00"] * 3 + ["2026-08-01 11:00"]   # 不同小时桶，去重后应剩2行
            ),
            "asset": ["BTC", "BTC", "BTC", "BTC"],
            "key": ["close", "close", "close", "close"],
            "value": [100.0, 101.0, 102.0, 103.0],   # 重复3行，保留第一行
        })
        trace = CleaningTrace()
        cleaner = DedupAlignCleaner(target_freq="1h")
        out, action = cleaner.clean(df, trace)
        assert len(out) == 2, f"去重后应有2行，实得{len(out)}"
        # 重复的3行里第一行（100.0）被保留
        assert out["value"].iloc[0] == 100.0

    # ------------------------------------------------------------------
    # T2-2 时间戳 resample 对齐
    # ------------------------------------------------------------------
    def test_t2_2_resample_to_hourly_frequency(self) -> None:
        from data_cleaning.cleaners.dedup_align import DedupAlignCleaner
        from data_cleaning.contract import CleaningTrace

        idx = pd.to_datetime([
            "2026-08-01 10:05", "2026-08-01 10:35",
            "2026-08-01 11:10", "2026-08-01 12:05",
        ])
        df = pd.DataFrame({"close": [1.0, 2.0, 3.0, 4.0]}, index=idx)
        df["timestamp"] = df.index
        trace = CleaningTrace()
        cleaner = DedupAlignCleaner(target_freq="1h", timestamp_col="timestamp")
        out, _ = cleaner.clean(df, trace)
        # 结果索引应落在整小时
        assert all(t.minute == 0 for t in pd.to_datetime(out["timestamp"])), \
            f"resample 未对齐整小时: {out['timestamp'].tolist()}"

    # ------------------------------------------------------------------
    # T2-3 ffill(limit=5)：前5个空被ffill；第6个空不被ffill（但会被后续 linear 插值=Spec§B7）
    #   → 断言通过 CleanAction.imputed_count 精确看 ffill 本身填了 5 个
    # ------------------------------------------------------------------
    def test_t2_3_ffill_limit_5(self) -> None:
        from data_cleaning.cleaners.dedup_align import DedupAlignCleaner
        from data_cleaning.contract import CleaningTrace

        idx = pd.date_range("2026-08-01 10:00", periods=8, freq="1h")
        df = pd.DataFrame({
            "timestamp": idx,
            "close": [1.0, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, 8.0],
            # 行0:1.0，行1~6共7个空，行7:8.0
            # ffill(limit=5) 只能填 行1~5（5个），行6仍空（被 linear 填）
        })
        trace = CleaningTrace()
        cleaner = DedupAlignCleaner(target_freq="1h", ffill_limit=5, timestamp_col="timestamp")
        out, _ = cleaner.clean(df, trace)
        # 通过 trace 审计：第一段 DedupAlignCleaner 的 imputed 注记应含 ffill(limit=5)=5
        action = trace.actions[0]
        assert "ffill(limit=5)=5" in action.note, f"ffill计数≠5: {action.note}"
        # 行1~5 被 ffill 到 1.0（正确）
        close = out["close"].tolist()
        assert close[1] == 1.0 and close[5] == 1.0, f"ffill填充错: {close}"
        # 行6: 被 linear 插值填充（1 和 8 之间）→ 不能再是 1.0（否则是 ffill 超限）
        assert close[6] != 1.0, f"ffill超出limit: {close}"
        # 行7: 8.0 正确
        assert close[7] == 8.0

    # ------------------------------------------------------------------
    # T2-4 连续 >5 空 → 线性插值 → 仍空 → 中性50
    # ------------------------------------------------------------------
    def test_t2_4_long_gap_linear_interp_then_fallback50(self) -> None:
        from data_cleaning.cleaners.dedup_align import DedupAlignCleaner
        from data_cleaning.contract import CleaningTrace

        idx = pd.date_range("2026-08-01 10:00", periods=10, freq="1h")
        vals = [10.0] + [np.nan] * 8 + [20.0]  # 中间8个空 >5
        df = pd.DataFrame({"timestamp": idx, "close": vals})
        trace = CleaningTrace()
        cleaner = DedupAlignCleaner(
            target_freq="1h", ffill_limit=5, timestamp_col="timestamp",
            fail_open_value=50.0,
        )
        out, _ = cleaner.clean(df, trace)
        close = out["close"]
        # 线性插值后 不应有 nan
        assert not close.isna().any(), f"长间隙后仍有nan: {close.tolist()}"
        # 第1行~第8行插值区间应该在 10~20 之间（不会落到 50）
        assert 10.0 <= close.iloc[4] <= 20.0

    # ------------------------------------------------------------------
    # T2-5 整列全空 → fail-open 中性50（B5 兜底）
    # ------------------------------------------------------------------
    def test_t2_5_whole_column_nan_fallback_to_50(self) -> None:
        from data_cleaning.cleaners.dedup_align import DedupAlignCleaner
        from data_cleaning.contract import CleaningTrace

        idx = pd.date_range("2026-08-01", periods=4, freq="1h")
        df = pd.DataFrame({
            "timestamp": idx,
            "close": [np.nan] * 4,
            "volume": [np.nan] * 4,
        })
        trace = CleaningTrace()
        cleaner = DedupAlignCleaner(target_freq="1h", timestamp_col="timestamp",
                                    fail_open_value=50.0)
        out, _ = cleaner.clean(df, trace)
        assert (out["close"] == 50.0).all()
        assert (out["volume"] == 50.0).all()

    # ------------------------------------------------------------------
    # T2-6 三类 category 模拟（直接传 DF 都能跑）
    # ------------------------------------------------------------------
    @pytest.mark.parametrize("kind", ["metrics", "timeseries", "events"])
    def test_t2_6_three_categories_run_crash_free(self, kind: str) -> None:
        from data_cleaning.cleaners.dedup_align import DedupAlignCleaner
        from data_cleaning.contract import CleaningTrace

        if kind == "metrics":
            df = pd.DataFrame({
                "timestamp": pd.date_range("2026-08-01", periods=3, freq="1h"),
                "key": ["M2", "M2", "M2"],
                "value": [1.0, 1.1, 1.2],
                "asset": ["USA", "USA", "USA"],
            })
        elif kind == "timeseries":
            df = pd.DataFrame({
                "timestamp": pd.date_range("2026-08-01 10:00", periods=3, freq="1h"),
                "open": [1, 2, 3], "high": [1, 2, 3], "low": [1, 2, 3],
                "close": [1, 2, 3], "volume": [1, 2, 3],
                "asset": ["BTC", "BTC", "BTC"],
            })
        else:  # events
            df = pd.DataFrame({
                "timestamp": pd.date_range("2026-08-01", periods=3, freq="1h"),
                "event_type": ["FOMC", "FOMC", "CPI"],
                "impact": [0.9, 0.9, 0.8],
                "occurred": [True, True, False],
            })
        cleaner = DedupAlignCleaner(target_freq="1h", timestamp_col="timestamp")
        out, action = cleaner.clean(df, CleaningTrace())
        assert len(out) > 0
        assert action.step == "DedupAlignCleaner"
