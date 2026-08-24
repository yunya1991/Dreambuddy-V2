"""Adapters: DataRecord ←双向→ CleanedDF。

设计（Spec§C4）：
  · records_to_cleaned_df(records) → 把若干 DataRecord 按三类（timeseries/metrics/events）
    规范化并 concat 为统一 DataFrame（加 asset 列、timestamp 统一）。
  · cleaned_df_to_records(df) → 把清洗后 DataFrame 还原为 DataRecord。
  · 统一：CleanedDF = DataFrame + 其来源 SilverRecord 指针。
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, List
from uuid import uuid4

import pandas as pd
from data_center.core.contract import DataRecord  # type: ignore

from data_cleaning.contract import AdapterMeta, CleanedDF

__all__ = ["records_to_cleaned_df", "cleaned_df_to_records"]


# ---------------------------------------------------------------------------
# T7 · Record → DF
# ---------------------------------------------------------------------------
def records_to_cleaned_df(records: Iterable[DataRecord]) -> CleanedDF:
    """标准化 DataRecord 列表 → CleanedDF。

    规则：
      1. 每条 DataRecord 转换为一个 DataFrame 片段，加 asset 列（metrics["asset"] → ""）。
      2. 合并片段：同一列多的先上，缺失列补 NaN。
      3. 返回 CleanedDF(records=[SilverRecord...], df=df)。
    """
    records = list(records)
    if not records:
        return CleanedDF(records=[], df=pd.DataFrame(), primary_key_count=0)

    silver_records: list[AdapterMeta] = []
    dfs: List[pd.DataFrame] = []
    for rec in records:
        # 1) 确定 asset：metrics 里有就拿，否则空串或 fallback
        asset = (rec.metrics.get("asset") if isinstance(rec.metrics, dict) else None) or ""
        fetched_at = rec.timestamp  # ISO str

        # 2) 根据 payload 决定片段
        if rec.category in ("finance", "chain") and rec.timeseries:
            frag = pd.DataFrame(rec.timeseries)
        elif rec.category == "news" and rec.events:
            frag = pd.DataFrame(rec.events)
        else:
            # macro 或 fallback：metrics 扁平 → 1行
            row = dict(rec.metrics) if isinstance(rec.metrics, dict) else {}
            row.setdefault("fetched_at", fetched_at)
            frag = pd.DataFrame([row])

        frag["asset"] = asset
        frag["fetched_at"] = fetched_at
        frag["source"] = rec.source
        frag["sub_category"] = rec.sub_category

        # timestamp 统一：有则用，否则 fallback fetched_at
        if "timestamp" not in frag.columns:
            frag["timestamp"] = fetched_at

        # 类型化 timestamp 列（但保留原始语义，DF 内可为 object/str）
        dfs.append(frag)
        # AdapterMeta：记录原始 DataRecord 引用信息（Pipeline 出口再映射到 SilverRecord）
        sr = AdapterMeta(
            source=rec.source, category=rec.category, sub_category=rec.sub_category,
            asset=str(asset),
            fetched_at=fetched_at,
            data={
                "timeseries": rec.timeseries,
                "metrics": rec.metrics,
                "events": rec.events,
            },
            schema_version=getattr(rec, "schema_version", "1.0"),
            record_id=str(uuid4()),
        )
        silver_records.append(sr)

    df = pd.concat(dfs, ignore_index=True, sort=False) if dfs else pd.DataFrame()
    # primary_key：(source, category, sub_category, asset, timestamp)
    pk_cols = [c for c in ("source", "category", "sub_category", "asset", "timestamp")
               if c in df.columns]
    pk_count = len(df.drop_duplicates(subset=pk_cols)) if pk_cols else len(df)
    return CleanedDF(records=silver_records, df=df, primary_key_count=pk_count)


# ---------------------------------------------------------------------------
# T8 · DF → Record
# ---------------------------------------------------------------------------
def cleaned_df_to_records(
    df: pd.DataFrame,
    *,
    source: str,
    category: str,
    sub_category: str,
    asset_col: str = "asset",
    timestamp_col: str = "timestamp",
) -> list[DataRecord]:
    """把 CleanedDF.df（按 asset 分组）→ 多个 DataRecord，每组 1 个。

    规则：
      · category="news" → events（多行）
      · category="finance/chain" + 有多行且有 close/volume 等 → timeseries
      · 否则（macro、1行、无时序列）→ metrics 扁平
      · timestamp 列还原为 ISO str
    """
    if df is None or df.empty:
        return []

    # 归一 timestamp 列 → ISO str（pandas.Timestamp / datetime / str → 字符串）
    work = df.copy()
    if timestamp_col in work.columns:
        work[timestamp_col] = work[timestamp_col].apply(_to_iso_str)
    # asset 列可能有 NaN（resample/ffill 引入），统一成空串避免分组空
    if asset_col in work.columns:
        work[asset_col] = work[asset_col].where(work[asset_col].notna(), "").astype(str)

    records: list[DataRecord] = []
    assets = work[asset_col].unique() if asset_col in work.columns else [""]
    for asset in assets:
        grp = work[work[asset_col] == asset] if asset_col in work.columns else work
        grp_cols = set(grp.columns)
        grp = grp.reset_index(drop=True)

        metrics_cols = {
            c for c in grp_cols
            if c not in {"timestamp", "source", "sub_category", "fetched_at", asset_col}
            and c not in {"title", "importance"}  # event 字段除外
        }
        if category == "news":
            # events 流
            ev_cols = [c for c in ("timestamp", "title", "importance") if c in grp_cols]
            events = grp[ev_cols].to_dict(orient="records")
            metrics = {asset_col: asset}
            if metrics_cols:
                sample = grp.iloc[0]
                for c in metrics_cols & set(sample.index):
                    metrics[c] = sample[c]
            records.append(DataRecord(
                source=source, category=category, sub_category=sub_category,
                timestamp=_first_iso(grp, timestamp_col),
                metrics=metrics, events=events, timeseries=[], raw={},
            ))
        elif category in ("finance", "chain") and {
            "timestamp", "close", "volume", "open", "high", "low",
        } & grp_cols >= {"timestamp", "close"}:
            # 时序类（OHLCV）：timeseries = timestamp + 其余数值列
            ts_cols = [timestamp_col] + sorted(metrics_cols)
            timeseries = grp[ts_cols].rename(
                columns={timestamp_col: "timestamp"},
            ).to_dict(orient="records")
            metrics = {asset_col: asset}
            # 把分组内首行的其他扁平字段塞进 metrics （如 pair）
            first = grp.iloc[0]
            for c in metrics_cols:
                if c not in {"close", "open", "high", "low", "volume"}:
                    v = first[c]
                    if not _is_nan(v):
                        metrics[c] = v
            records.append(DataRecord(
                source=source, category=category, sub_category=sub_category,
                timestamp=_first_iso(grp, timestamp_col),
                metrics=metrics, events=[], timeseries=timeseries, raw={},
            ))
        else:
            # macro/默认：按行扁平化 metrics（通常1行）
            for _, row in grp.iterrows():
                metrics = {asset_col: asset}
                for c in metrics_cols:
                    v = row[c]
                    if _is_nan(v):
                        continue
                    if isinstance(v, (int, float, str, bool)):
                        metrics[c] = v
                    else:
                        metrics[c] = str(v)
                records.append(DataRecord(
                    source=source, category=category, sub_category=sub_category,
                    timestamp=_to_iso_str(row[timestamp_col]) if timestamp_col in grp_cols
                    else datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                    metrics=metrics, events=[], timeseries=[], raw={},
                ))
    return records


# ---------------------------------------------------------------------------
# 内部小工具
# ---------------------------------------------------------------------------
def _to_iso_str(v) -> str:
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime().strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(v, str):
        return v
    return str(v)


def _first_iso(df: pd.DataFrame, ts_col: str) -> str:
    if ts_col not in df.columns or df.empty:
        return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    return _to_iso_str(df.iloc[0][ts_col])


def _is_nan(v) -> bool:
    try:
        return pd.isna(v)
    except Exception:  # noqa: BLE001
        return False
