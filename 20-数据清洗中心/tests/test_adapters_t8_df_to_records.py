"""T8 · DF→Record Adapters（Spec§C4 Adapters 双向 6 条）。

方向：CleanedDF（经过 cleaners 清洗后的 DataFrame）→ [DataRecord]。
  T8-1  timeseries 4行 → 1个 DataRecord.timeseries（timestamp+close+volume 恢复）
  T8-2  macro 1行 → metrics 扁平（asset、M2NS、M2SL 还原）
  T8-3  events 多行 → 单个 DataRecord.events
  T8-4  空 DF → 空 list（不抛）
  T8-5  回写 DataRecord.source/category/sub_category 保持输入一致（非空）
  T8-6  timestamp 列恢复为 ISO 字符串（DataRecord.timeseries 内）
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
from data_center.core.contract import DataRecord  # type: ignore


def _iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


class TestDFToRecords:
    # T8-1 timeseries df → timeseries list[dict]
    def test_t8_1_timeseries_df_to_record_timeseries(self) -> None:
        from data_cleaning.adapters import cleaned_df_to_records, records_to_cleaned_df
        # 先 records→df 再 df→records，往返等价
        ts_base = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        rows = [ts_base - timedelta(hours=i) for i in (3, 2, 1, 0)]
        src = DataRecord(
            source="yfinance", category="finance", sub_category="ohlcv",
            timestamp=_iso(ts_base),
            metrics={"asset": "BTC", "pair": "BTC-USD"},
            events=[],
            timeseries=pd.DataFrame({
                "timestamp": [_iso(t) for t in rows],
                "close": [100.0, 101.0, 102.0, 103.0],
                "volume": [10, 20, 30, 40],
            }).to_dict(orient="records"),
            raw={},
        )
        cleaned = records_to_cleaned_df([src])
        # 经过清洁（此处没改内容，空跑 round-trip 测试）
        out_records = cleaned_df_to_records(
            cleaned.df, source="yfinance", category="finance", sub_category="ohlcv",
            asset_col="asset",
        )
        assert len(out_records) >= 1
        r = out_records[0]
        assert len(r.timeseries) == 4
        # close 还原
        closes = sorted([row["close"] for row in r.timeseries])
        assert closes == [100.0, 101.0, 102.0, 103.0]

    # T8-2 macro 1行 → metrics 扁平
    def test_t8_2_macro_df_to_metrics_flat(self) -> None:
        from data_cleaning.adapters import cleaned_df_to_records

        ts = datetime.now(timezone.utc)
        df = pd.DataFrame([{
            "timestamp": _iso(ts),
            "asset": "USA",
            "M2NS": 21.5, "M2SL": 21.4,
        }])
        records = cleaned_df_to_records(
            df, source="fred", category="macro", sub_category="m2",
            asset_col="asset",
        )
        assert len(records) == 1
        r = records[0]
        assert r.category == "macro"
        assert r.metrics["asset"] == "USA"
        assert float(r.metrics["M2NS"]) == 21.5
        assert float(r.metrics["M2SL"]) == 21.4

    # T8-3 events 多行 → DataRecord.events
    def test_t8_3_events_df_to_record_events(self) -> None:
        from data_cleaning.adapters import cleaned_df_to_records

        ts = datetime.now(timezone.utc)
        df = pd.DataFrame([
            {"timestamp": _iso(ts - timedelta(minutes=2)),
             "title": "加息", "importance": 5, "asset": "MKT"},
            {"timestamp": _iso(ts - timedelta(minutes=1)),
             "title": "ETF流入", "importance": 3, "asset": "MKT"},
        ])
        records = cleaned_df_to_records(
            df, source="rsshub", category="news", sub_category="economy",
            asset_col="asset",
        )
        assert len(records) == 1
        r = records[0]
        assert len(r.events) == 2
        assert r.events[0]["title"] == "加息"

    # T8-4 空DF → 空 records
    def test_t8_4_empty_df_empty_records(self) -> None:
        from data_cleaning.adapters import cleaned_df_to_records

        records = cleaned_df_to_records(
            pd.DataFrame(), source="x", category="finance", sub_category="ohlcv",
        )
        assert records == []

    # T8-5 source/category/sub_category 回写保持
    def test_t8_5_preserve_meta(self) -> None:
        from data_cleaning.adapters import cleaned_df_to_records

        ts = datetime.now(timezone.utc)
        df = pd.DataFrame([{"timestamp": _iso(ts), "asset": "A"}])
        [r] = cleaned_df_to_records(
            df, source="MY_SRC", category="chain", sub_category="whale",
            asset_col="asset",
        )
        assert r.source == "MY_SRC"
        assert r.category == "chain"
        assert r.sub_category == "whale"

    # T8-6 timeseries 里 timestamp 列保留 ISO str
    def test_t8_6_timestamp_iso_str_in_timeseries(self) -> None:
        from data_cleaning.adapters import cleaned_df_to_records

        ts = datetime.now(timezone.utc)
        df = pd.DataFrame({
            "timestamp": pd.to_datetime([_iso(ts)]),  # 传入 pd.Timestamp
            "close": [100.0],
            "asset": ["BTC"],
        })
        [r] = cleaned_df_to_records(
            df, source="y", category="finance", sub_category="ohlcv",
            asset_col="asset",
        )
        assert len(r.timeseries) == 1
        ts_str = r.timeseries[0]["timestamp"]
        # 必须字符串 ISO 格式
        assert isinstance(ts_str, str), f"timestamp 应为 str: {type(ts_str)}"
        assert "T" in ts_str or ts_str.endswith("Z") or "+" in ts_str
