"""战略层历史数据回补脚本。

回补 FRED 宏观序列和 yfinance 价格数据到 records 表，
使 IC 检验有足够的历史样本（≥250 交易日）。

用法：
    python backfill_historical_data.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent.parent
_DC = _REPO / "18-数据获取中心"
_DB = _DC / "data_center.db"

if str(_DC) not in sys.path:
    sys.path.insert(0, str(_DC))

# 加载 .env
from dotenv import load_dotenv  # noqa: E402
load_dotenv(_DC / "config" / ".env")

from fredapi import Fred  # noqa: E402
from data_center.collectors._base import BaseCollector  # noqa: E402
from data_center.core.contract import DataRecord, validate_record  # noqa: E402
from data_center.storage.sink_sqlite import SqliteSink  # noqa: E402

FRED_SERIES = (
    "FEDFUNDS",     # 联邦基金利率（日度）
    "CPIAUCSL",     # CPI（月度）
    "INDPRO",       # 工业产出（月度）
    "M2SL",         # M2（月度）
    "WALCL",        # 联储总资产（周度）
    "T10Y2YM",      # 10Y-2Y利差（日度）
    "PPIACO",       # PPI（月度）
)

YOY_SERIES = {"CPIAUCSL", "INDPRO", "M2SL", "PPIACO"}

YF_SYMBOLS = ("^VIX", "BTC-USD", "SPY", "GLD")

START_DATE = "2023-01-01"


def _fred_records(series_id: str, series: pd.Series) -> list[DataRecord]:
    """将 FRED 序列拆为每日记录（月度数据每月一条）。"""
    records = []
    for idx, val in series.items():
        if pd.isna(val):
            continue
        date_str = str(idx.date() if hasattr(idx, "date") else idx)
        if date_str < START_DATE:
            continue
        metrics = {"value": round(float(val), 6), "date": date_str}
        # 计算 YoY%
        if series_id in YOY_SERIES:
            try:
                year_ago = idx - pd.DateOffset(months=12)
                pos = series.index.get_indexer([year_ago], method="nearest")[0]
                year_ago_val = float(series.iloc[pos])
                if year_ago_val != 0:
                    metrics["yoy_pct"] = round(
                        (float(val) - year_ago_val) / abs(year_ago_val) * 100, 4)
            except Exception:
                pass
        rec = DataRecord(
            source="fred",
            category="macro",
            sub_category=series_id,  # 与 latest 路由同 sub_category，按 date 去重
            timestamp=datetime.fromisoformat(f"{date_str}T00:00:00").astimezone().isoformat(),
            metrics=metrics,
            events=[],
            timeseries=[{"date": date_str, "value": float(val)}],
            raw={"series_id": series_id, "date": date_str, "value": float(val)},
        )
        validate_record(rec)
        records.append(rec)
    return records


def _yf_records(symbol: str, df: pd.DataFrame) -> list[DataRecord]:
    """将 yfinance 日线拆为每日记录。"""
    records = []
    # 处理 MultiIndex columns
    if hasattr(df.columns, "levels") and len(df.columns.levels) > 1:
        close_col = [c for c in df.columns if c[0] == "Close"]
        if close_col:
            closes = df[close_col[0]]
        else:
            closes = df["Close"]
    else:
        closes = df["Close"]

    for idx, val in closes.items():
        if pd.isna(val):
            continue
        date_str = str(idx.date() if hasattr(idx, "date") else idx)
        if date_str < START_DATE:
            continue
        rec = DataRecord(
            source="yfinance",
            category="finance",
            sub_category=symbol,
            timestamp=datetime.fromisoformat(f"{date_str}T00:00:00").astimezone().isoformat(),
            metrics={"value": round(float(val), 6), "date": date_str},
            events=[],
            timeseries=[{"date": date_str, "value": float(val)}],
            raw={"symbol": symbol, "date": date_str, "close": float(val)},
        )
        validate_record(rec)
        records.append(rec)
    return records


def main() -> None:
    sink = SqliteSink(str(_DB))
    fred_key = os.environ.get("FRED_API_KEY", "")
    if not fred_key:
        print("[ERR] FRED_API_KEY not found")
        return
    fred = Fred(api_key=fred_key)

    total_inserted = 0

    # ── FRED ──
    for series_id in FRED_SERIES:
        try:
            print(f"[FRED] fetching {series_id} ...")
            s = fred.get_series(series_id, observation_start=START_DATE)
            s = s.dropna()
            recs = _fred_records(series_id, s)
            n = sink.write(recs)
            total_inserted += n
            print(f"[FRED] {series_id}: {len(recs)} records, inserted {n}")
        except Exception as e:
            print(f"[FRED] {series_id} ERROR: {e}")

    # ── yfinance ──
    import yfinance as yf
    for symbol in YF_SYMBOLS:
        try:
            print(f"[YF] fetching {symbol} ...")
            df = yf.download(symbol, start=START_DATE, progress=False, auto_adjust=True)
            if df.empty:
                print(f"[YF] {symbol}: empty")
                continue
            recs = _yf_records(symbol, df)
            n = sink.write(recs)
            total_inserted += n
            print(f"[YF] {symbol}: {len(recs)} records, inserted {n}")
        except Exception as e:
            print(f"[YF] {symbol} ERROR: {e}")

    print(f"\n[DONE] total inserted: {total_inserted}")


if __name__ == "__main__":
    main()
