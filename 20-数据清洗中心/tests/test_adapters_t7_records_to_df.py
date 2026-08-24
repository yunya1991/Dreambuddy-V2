"""T7 · Record→DF Adapters（Spec§C4 Adapters）。

方向：[DataRecord] → CleanedDF + SilverRecord + DataFrame（每类 category 各一条）。
覆盖：
  T7-1  timeseries ohlcv → DataFrame 多行（timestamp+close+volume）
  T7-2  macro metrics 扁平 → DataFrame 单行（fetched_at / asset / M2NS）
  T7-3  news events 流 → DataFrame 多行（event_ts / title / importance）
  T7-4  timeseries records 多资产拼接 → asset 列完整
  T7-5  空 record → 空 DataFrame 仍返回（不抛）
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
from data_center.core.contract import DataRecord  # type: ignore


def _iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _ohlcv_record(asset: str) -> DataRecord:
    ts = datetime.now(timezone.utc) - timedelta(minutes=5)
    rows = pd.date_range(ts - timedelta(hours=3), periods=4, freq="1h")
    df = pd.DataFrame({
        "timestamp": [_iso(t) for t in rows],
        "close": [100.0, 101.0, 102.0, 103.0],
        "volume": [10, 20, 30, 40],
    })
    return DataRecord(
        source="yfinance", category="finance", sub_category="ohlcv",
        timestamp=_iso(ts),
        metrics={"asset": asset, "pair": f"{asset}-USD"},
        events=[], timeseries=df.to_dict(orient="records"),
        raw={},
    )


def _macro_record() -> DataRecord:
    ts = datetime.now(timezone.utc) - timedelta(hours=24)
    return DataRecord(
        source="fred", category="macro", sub_category="m2",
        timestamp=_iso(ts),
        metrics={"asset": "USA", "M2NS": 21.5, "M2SL": 21.4},
        events=[], timeseries=[], raw={},
    )


def _news_record() -> DataRecord:
    ts = datetime.now(timezone.utc) - timedelta(minutes=30)
    events = [
        {"timestamp": _iso(ts - timedelta(minutes=2)), "title": "美联储加息25bp", "importance": 5},
        {"timestamp": _iso(ts - timedelta(minutes=1)), "title": "BTC现货ETF净流入", "importance": 3},
    ]
    return DataRecord(
        source="rsshub", category="news", sub_category="economy",
        timestamp=_iso(ts),
        metrics={"asset": "MKT"},
        events=events, timeseries=[], raw={},
    )


class TestRecordsToDF:
    # T7-1 timeseries → DataFrame 多行
    def test_t7_1_timeseries_to_df_multi_row(self) -> None:
        from data_cleaning.adapters import records_to_cleaned_df

        records = [_ohlcv_record("BTC")]
        cleaned = records_to_cleaned_df(records)
        assert isinstance(cleaned.df, pd.DataFrame)
        assert len(cleaned.df) == 4, f"ohlcv 4行：{len(cleaned.df)}"
        # 列包含 timestamp + close + volume + asset（asset 应被注入）
        for col in ["timestamp", "close", "volume", "asset"]:
            assert col in cleaned.df.columns, f"缺失列 {col}: {cleaned.df.columns.tolist()}"
        assert cleaned.df["asset"].iloc[0] == "BTC"
        # SilverRecord 列表非空
        assert len(cleaned.records) == 1
        # primary_key 去重=4
        assert cleaned.primary_key_count == 4

    # T7-2 macro 扁平 → 1 行
    def test_t7_2_metrics_to_df_single_row(self) -> None:
        from data_cleaning.adapters import records_to_cleaned_df

        records = [_macro_record()]
        cleaned = records_to_cleaned_df(records)
        assert len(cleaned.df) == 1
        for col in ["timestamp", "asset", "M2NS", "M2SL"]:
            assert col in cleaned.df.columns, f"缺失列 {col}"
        assert cleaned.df["asset"].iloc[0] == "USA"
        assert float(cleaned.df["M2NS"].iloc[0]) == 21.5

    # T7-3 events news → DataFrame 多行
    def test_t7_3_events_to_df_multi_row(self) -> None:
        from data_cleaning.adapters import records_to_cleaned_df

        records = [_news_record()]
        cleaned = records_to_cleaned_df(records)
        assert len(cleaned.df) == 2
        for col in ["timestamp", "title", "importance", "asset"]:
            assert col in cleaned.df.columns, f"缺失列 {col}"
        assert cleaned.df["title"].tolist() == ["美联储加息25bp", "BTC现货ETF净流入"]

    # T7-4 多资产拼接
    def test_t7_4_multi_asset_concat(self) -> None:
        from data_cleaning.adapters import records_to_cleaned_df

        records = [_ohlcv_record("BTC"), _ohlcv_record("ETH")]
        cleaned = records_to_cleaned_df(records)
        assert len(cleaned.df) == 4 + 4
        assets = set(cleaned.df["asset"].unique())
        assert assets == {"BTC", "ETH"}, f"资产错: {assets}"

    # T7-5 空 records → 空DF 不抛
    def test_t7_5_empty_records_empty_df(self) -> None:
        from data_cleaning.adapters import records_to_cleaned_df

        cleaned = records_to_cleaned_df([])
        assert len(cleaned.df) == 0
        assert len(cleaned.records) == 0
        assert cleaned.primary_key_count == 0
