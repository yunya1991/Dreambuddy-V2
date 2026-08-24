"""T4 · MissingImputer：三级兜底（时序 / 宏观 / 事件 → 中性50）。

T4-1  时序 ffill(5)：5 个以内连续空被前值填满
T4-2  时序连续 >5 空 → linear 插值
T4-3  整列全空 → 全列 50（B5 fail-open）
T4-4  宏观：linear → 拖尾 → 50
T4-5  事件：发生=1 / 未发生=0
T4-6  事件：未知（NaN）→ 0.5 中性
"""
from __future__ import annotations

import numpy as np
import pandas as pd


class TestMissingImputer:
    # T4-1
    def test_t4_1_timeseries_ffill_5(self) -> None:
        from data_cleaning.cleaners.missing_imputer import MissingImputer
        from data_cleaning.contract import CleaningTrace

        df = pd.DataFrame({
            "timestamp": pd.date_range("2026-08-01 10:00", periods=7, freq="1h"),
            "close": [10.0, np.nan, np.nan, np.nan, np.nan, np.nan, 20.0],  # 5 个空
            "category": ["timeseries"] * 7,
        })
        imp = MissingImputer(ffill_limit=5, fail_open_value=50.0)
        out, action = imp.clean(df, CleaningTrace())
        close = out["close"].tolist()
        # 1~5 行（index 1~5）被 ffill
        assert close[1] == 10.0 and close[5] == 10.0
        assert close[6] == 20.0
        assert action.imputed_count == 5

    # T4-2 时序连续 >5 空 → ffill(5) 填前5个空 → 剩余空用 linear 插值
    #       (index 1~5=6个位置？实际 df index 0=10有值；index1~8空；index9=30有值。长间隙=8空)
    def test_t4_2_timeseries_long_gap_linear_interp(self) -> None:
        from data_cleaning.cleaners.missing_imputer import MissingImputer
        from data_cleaning.contract import CleaningTrace

        df = pd.DataFrame({
            "timestamp": pd.date_range("2026-08-01 10:00", periods=10, freq="1h"),
            "close": [10.0] + [np.nan] * 8 + [30.0],  # >5 个空
            "category": ["timeseries"] * 10,
        })
        imp = MissingImputer(ffill_limit=5, fail_open_value=50.0)
        out, _ = imp.clean(df, CleaningTrace())
        close = out["close"]
        # ffill(5) 填了 index1~5 → 它们=10（前向）
        assert close.iloc[1] == 10.0 and close.iloc[5] == 10.0
        # index6~8 超出了 ffill_limit=5 → 走 linear，index6 位置≈ (10+30)中间偏左
        # （线性插值在 [0=10, 9=30] 之间 → index6 = 10 + (6/9)*(20) = 23.33 附近）
        assert 15.0 <= close.iloc[6] <= 28.0, f"linear 超出预期: {close.tolist()}"
        assert 15.0 <= close.iloc[7] <= 29.0
        assert not close.isna().any()

    # T4-3
    def test_t4_3_all_nan_fallback_50(self) -> None:
        from data_cleaning.cleaners.missing_imputer import MissingImputer
        from data_cleaning.contract import CleaningTrace

        df = pd.DataFrame({
            "timestamp": pd.date_range("2026-08-01", periods=4, freq="1h"),
            "close": [np.nan] * 4,
            "volume": [np.nan] * 4,
            "category": ["timeseries"] * 4,
        })
        imp = MissingImputer(fail_open_value=50.0)
        out, _ = imp.clean(df, CleaningTrace())
        assert (out["close"] == 50.0).all()
        assert (out["volume"] == 50.0).all()

    # T4-4
    def test_t4_4_macro_linear_then_stable_then_50(self) -> None:
        from data_cleaning.cleaners.missing_imputer import MissingImputer
        from data_cleaning.contract import CleaningTrace

        ts = pd.date_range("2026-08-01", periods=15, freq="1h")
        # 前后 3 个已知，中间 >10 个空（比 limit 大很多）
        values = [2.0, 2.0, 2.0] + [np.nan] * 9 + [2.0, 2.0, 2.0]
        df = pd.DataFrame({
            "timestamp": ts,
            "m2_growth": values,
            "category": ["macro"] * 15,
        })
        imp = MissingImputer(fail_open_value=50.0)
        out, _ = imp.clean(df, CleaningTrace())
        # macro 用线性：稳定期不变，中间被线性插
        assert out["m2_growth"].iloc[0] == 2.0
        assert out["m2_growth"].iloc[-1] == 2.0
        assert not out["m2_growth"].isna().any()

    # T4-5
    def test_t4_5_event_occurred_1_not_occurred_0(self) -> None:
        from data_cleaning.cleaners.missing_imputer import MissingImputer
        from data_cleaning.contract import CleaningTrace

        df = pd.DataFrame({
            "timestamp": pd.date_range("2026-08-01", periods=3, freq="1h"),
            "fomc_hike": [True, False, True],
            "category": ["events"] * 3,
        })
        imp = MissingImputer()
        out, _ = imp.clean(df, CleaningTrace())
        # bool → int: True=1, False=0
        assert out["fomc_hike"].tolist() == [1, 0, 1]

    # T4-6
    def test_t4_6_event_unknown_nan_to_half(self) -> None:
        from data_cleaning.cleaners.missing_imputer import MissingImputer
        from data_cleaning.contract import CleaningTrace

        df = pd.DataFrame({
            "timestamp": pd.date_range("2026-08-01", periods=4, freq="1h"),
            "fomc_hike": [True, np.nan, np.nan, False],
            "category": ["events"] * 4,
        })
        imp = MissingImputer()
        out, _ = imp.clean(df, CleaningTrace())
        vals = out["fomc_hike"].tolist()
        assert vals[0] == 1
        assert vals[1] == 0.5 and vals[2] == 0.5, "事件未知应为0.5中性"
        assert vals[3] == 0
