"""金融环境四层对齐器（SPEC-EMERGENCE-FINANCIAL-ENV §7.1，P2-A）。

`align(events, sentiment, regime, form, horizon, prices=...) -> DataFrame`
  索引：(symbol, date)
  列  ：E_* / S_* / M_* / P_* + forward_ret_{1,3,5,10,20}d + label + in_event_window

对齐纪律（硬约束，改动前先读 SPEC §7.1）：
  1. 事件按 `available_at` 落到**第一个可交易时点**：crypto → 下一小时；
     美股 / A 股 → 下一交易日（保守，不假设盘中可成交）。
  2. 所有特征 `available_at ≤ date`，标签只从 `date+1` 起算；
     `audit_lookahead()` 是硬门禁，违规数必须为 0（否则数据作废）。
  3. 事件窗口 `[date−1, date+1]` 的样本标 `in_event_window=True`，回测可选剔除。

本模块只做对齐，不做统计检验（检验在 `financial_env_validate.py`）。
"""

from __future__ import annotations

from datetime import date as _date
from datetime import timedelta
from typing import Any, Sequence

import numpy as np
import pandas as pd

FORWARD_HORIZONS = (1, 3, 5, 10, 20)
BUCKET_CODE = {"low": 0.0, "normal": 1.0, "elevated": 2.0, "crisis": 3.0}
DIRECTION_SIGN = {"bullish": 1.0, "bearish": -1.0, "neutral": 0.0}
EVENT_WINDOW_DAYS = 1

_E_COLS = ("E_has_event", "E_event_count", "E_surprise", "E_direction")


def _frame(obj: Any) -> pd.DataFrame:
    if obj is None:
        return pd.DataFrame()
    if isinstance(obj, pd.DataFrame):
        return obj.copy()
    if isinstance(obj, dict):
        return pd.DataFrame([obj])
    return pd.DataFrame(list(obj))


def _ts(series: Any) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce")


def next_tradable_date(available_at: Any, asset_class: str = "crypto") -> _date | None:
    """事件可得时点 → 第一个可交易日期（保守取整，不做盘中假设）。"""
    ts = pd.to_datetime(available_at, utc=True, errors="coerce")
    if pd.isna(ts):
        return None
    ts = pd.Timestamp(ts)
    if asset_class == "crypto":
        return (ts.floor("h") + pd.Timedelta(hours=1)).date()
    d = ts.date() + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _norm_symbol(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "symbol" not in out.columns:
        out["symbol"] = ""
    out["symbol"] = out["symbol"].fillna("").astype(str)
    return out


def _split_market(long: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """→ (named 行, market 行)，market 行按 date 广播。"""
    if long.empty or "symbol" not in long.columns:
        return long, long.iloc[0:0]
    market = long[long["symbol"].eq("")]
    named = long[~long["symbol"].eq("")]
    return named, market


def _fill_from_market(df: pd.DataFrame, market: pd.DataFrame, cols: Sequence[str]) -> pd.DataFrame:
    """用市场级行（symbol 为空）按 date 广播补齐 named 行的 NaN。

    市场级信号（FOMC / CPI / 大盘形态）对宇宙内所有标的成立，
    但不能覆盖标的自身的同层信号，所以只补 NaN（`fillna` 而非 `where`）。
    """
    cols = [c for c in cols if c in df.columns]
    if market.empty or df.empty or not cols:
        return df
    mk = market.drop_duplicates(subset=["date"], keep="last").set_index("date")[cols]
    for c in cols:
        df[c] = df[c].fillna(df["date"].map(mk[c]))
    return df


def _events_long(events: Any, asset_class: str) -> pd.DataFrame:
    ev = _frame(events)
    if ev.empty:
        return pd.DataFrame(columns=["symbol", "date", *_E_COLS])
    ev = _norm_symbol(ev)
    if "available_at" not in ev.columns:
        if "event_time" not in ev.columns:
            return pd.DataFrame(columns=["symbol", "date", *_E_COLS])
        ev["available_at"] = ev["event_time"]
    ev["date"] = [next_tradable_date(v, asset_class) for v in ev["available_at"]]
    ev = ev.dropna(subset=["date"])
    if ev.empty:
        return pd.DataFrame(columns=["symbol", "date", *_E_COLS])
    ev["surprise"] = pd.to_numeric(
        ev["surprise"] if "surprise" in ev.columns else pd.Series(0.0, index=ev.index),
        errors="coerce",
    ).fillna(0.0)
    direction = ev.get("direction", pd.Series("neutral", index=ev.index))
    ev["dir_sign"] = direction.astype(str).str.lower().map(DIRECTION_SIGN).fillna(0.0)
    agg = ev.groupby(["symbol", "date"], as_index=False).agg(
        event_count=("dir_sign", "size"),
        surprise_sum=("surprise", "sum"),
        dir_sum=("dir_sign", "sum"),
    )
    agg["E_event_count"] = agg["event_count"].astype(float)
    agg["E_has_event"] = 1.0
    agg["E_surprise"] = agg["surprise_sum"] / agg["event_count"]
    agg["E_direction"] = agg["dir_sum"] / agg["event_count"]
    return agg[["symbol", "date", *_E_COLS]]


def _event_windows(events: Any, asset_class: str) -> tuple[set[_date], set[tuple[str, _date]]]:
    """→ (市场级事件日窗口, 品种级 (symbol, date) 窗口)。"""
    ev = _frame(events)
    if ev.empty:
        return set(), set()
    ev = _norm_symbol(ev)
    if "available_at" not in ev.columns:
        if "event_time" not in ev.columns:
            return set(), set()
        ev["available_at"] = ev["event_time"]
    dates = [next_tradable_date(v, asset_class) for v in ev["available_at"]]
    span = range(-EVENT_WINDOW_DAYS, EVENT_WINDOW_DAYS + 1)
    market_days: set[_date] = set()
    per_symbol: set[tuple[str, _date]] = set()
    for sym, d in zip(ev["symbol"], dates, strict=True):
        if d is None:
            continue
        if not sym:
            market_days.update(d + timedelta(days=k) for k in span)
        else:
            per_symbol.update((sym, d + timedelta(days=k)) for k in span)
    return market_days, per_symbol


def _sentiment_long(sentiment: Any) -> pd.DataFrame:
    s = _frame(sentiment)
    cols = ["symbol", "date", "S_score", "S_available_at"]
    if s.empty:
        return pd.DataFrame(columns=cols)
    s = _norm_symbol(s)
    col = next((c for c in ("date", "event_time", "published_at", "as_of") if c in s.columns), None)
    score = next((c for c in ("S_score", "score", "s1", "sentiment") if c in s.columns), None)
    if col is None or score is None:
        return pd.DataFrame(columns=cols)
    s["date"] = _ts(s[col]).dt.date
    s["S_score"] = pd.to_numeric(s[score], errors="coerce")
    s["S_available_at"] = _ts(s.get("available_at", s[col]))
    s = s.dropna(subset=["date"])
    agg = s.groupby(["symbol", "date"], as_index=False).agg(
        S_score=("S_score", "mean"), S_available_at=("S_available_at", "max")
    )
    return agg


def _regime_long(regime: Any) -> pd.DataFrame:
    r = _frame(regime)
    if r.empty:
        return pd.DataFrame()
    col = next((c for c in ("as_of", "date", "datetime") if c in r.columns), None)
    if col is None:
        return pd.DataFrame()
    r["date"] = _ts(r[col]).dt.date
    out = pd.DataFrame({"date": r["date"]})
    vix = r.get("vix")
    if isinstance(vix, pd.Series) and vix.map(lambda v: isinstance(v, dict)).any():
        out["M_vix_level"] = vix.map(
            lambda v: (v or {}).get("level") if isinstance(v, dict) else None
        )
        out["M_slope"] = vix.map(lambda v: (v or {}).get("slope") if isinstance(v, dict) else None)
        out["M_vvix"] = vix.map(lambda v: (v or {}).get("vvix") if isinstance(v, dict) else None)
        out["M_vix_bucket_code"] = vix.map(
            lambda v: BUCKET_CODE.get((v or {}).get("bucket")) if isinstance(v, dict) else None
        )
    else:
        for key, name in (
            ("vix_level", "M_vix_level"),
            ("vix_slope", "M_slope"),
            ("vvix", "M_vvix"),
        ):
            if key in r.columns:
                out[name] = pd.to_numeric(r[key], errors="coerce")
        if "vix_bucket" in r.columns:
            out["M_vix_bucket_code"] = r["vix_bucket"].map(BUCKET_CODE)
    if "label" in r.columns:
        out["M_label"] = r["label"].astype(str)
    fng = r.get("crypto_fng")
    if isinstance(fng, pd.Series) and fng.map(lambda v: isinstance(v, dict)).any():
        out["M_fng"] = fng.map(lambda v: (v or {}).get("value") if isinstance(v, dict) else None)
    elif "fng" in r.columns:
        out["M_fng"] = pd.to_numeric(r["fng"], errors="coerce")
    return out.dropna(subset=["date"]).drop_duplicates(subset=["date"], keep="last")


def _form_long(form: Any) -> pd.DataFrame:
    f = _frame(form)
    if f.empty:
        return f
    if isinstance(f.index, pd.MultiIndex):
        f = f.reset_index()
    f = _norm_symbol(f)
    if "date" not in f.columns:
        return pd.DataFrame()
    f["date"] = _ts(f["date"]).dt.date
    numeric = [
        c for c in f.columns if c not in ("symbol", "date") and pd.api.types.is_numeric_dtype(f[c])
    ]
    if not numeric:
        return pd.DataFrame()
    out = f[["symbol", "date"] + numeric].copy()
    out.columns = ["symbol", "date"] + [f"P_{c}" for c in numeric]
    return out


def _prices_long(prices: Any) -> pd.DataFrame:
    if prices is None:
        return pd.DataFrame(columns=["symbol", "date", "close"])
    p = _frame(prices)
    if p.empty:
        return pd.DataFrame(columns=["symbol", "date", "close"])
    if isinstance(p.index, pd.MultiIndex):
        p = p.reset_index()
    p = _norm_symbol(p)
    col = next((c for c in ("date", "datetime", "timestamp") if c in p.columns), None)
    if col is None:
        raise ValueError("prices 需要 date（或 datetime/timestamp）列")
    if "close" not in p.columns:
        raise ValueError("prices 需要 close 列")
    p["date"] = _ts(p[col]).dt.date
    out = p[["symbol", "date", "close"]].dropna(subset=["date", "close"])
    return out.drop_duplicates(subset=["symbol", "date"]).sort_values(["symbol", "date"])


def align(
    events: Any,
    sentiment: Any,
    regime: Any,
    form: Any,
    horizon: int | Sequence[int] = 5,
    prices: pd.DataFrame | None = None,
    asset_class: str = "crypto",
) -> pd.DataFrame:
    """四层对齐。`horizon` 只标记主评估期，列始终给全部 FORWARD_HORIZONS。

    `label` 取主评估期的收益符号（`horizon` 为列表时取第一个）。
    """
    empty_cols = [*_E_COLS, "S_score", "M_label", "in_event_window", "label", "feat_as_of"]
    ev_long = _events_long(events, asset_class)
    sent = _sentiment_long(sentiment)
    reg = _regime_long(regime)
    frm = _form_long(form)
    px = _prices_long(prices)

    ev_named, ev_market = _split_market(ev_long)
    sent_named, sent_market = _split_market(sent)
    frm_named, frm_market = _split_market(frm)

    if not px.empty:
        base = px[["symbol", "date"]]
    else:
        pool = [d for d in (sent_named, frm_named, ev_named) if not d.empty]
        if not pool:
            pool = [d for d in (sent, frm, ev_long) if not d.empty]
        if not pool:
            out = pd.DataFrame(columns=empty_cols)
            out.index = pd.MultiIndex.from_arrays([[], []], names=["symbol", "date"])
            out.attrs["lookahead_violations"] = []
            return out
        base = pd.concat([d[["symbol", "date"]] for d in pool])

    base = base.drop_duplicates(subset=["symbol", "date"]).sort_values(["symbol", "date"])
    df = base.reset_index(drop=True)

    # E 层：品种级事件优先，市场级事件按 date 广播到全宇宙，其余补 0
    if not ev_named.empty:
        df = df.merge(ev_named, on=["symbol", "date"], how="left")
    for c in _E_COLS:
        if c not in df.columns:
            df[c] = np.nan
    df = _fill_from_market(df, ev_market, _E_COLS)
    for c in _E_COLS:
        df[c] = df[c].fillna(0.0)

    # S 层：品种级情绪优先，市场级情绪广播
    if not sent_named.empty:
        df = df.merge(sent_named, on=["symbol", "date"], how="left")
    if "S_score" not in df.columns:
        df["S_score"] = np.nan
    if "S_available_at" not in df.columns:
        df["S_available_at"] = pd.NaT
    df = _fill_from_market(df, sent_market, ["S_score", "S_available_at"])

    # M 层：天然市场级，按 date 合并
    if not reg.empty:
        df = df.merge(reg, on="date", how="left")

    # P 层：品种级形态优先，市场级形态（大盘）广播
    if not frm_named.empty:
        df = df.merge(frm_named, on=["symbol", "date"], how="left")
    p_cols = [c for c in frm.columns if c.startswith("P_")]
    for c in p_cols:
        if c not in df.columns:
            df[c] = np.nan
    df = _fill_from_market(df, frm_market, p_cols)

    h_main = int(horizon) if isinstance(horizon, int) else int(list(horizon)[0])
    if not px.empty:
        px = px.sort_values(["symbol", "date"]).copy()
        for h in FORWARD_HORIZONS:
            px[f"forward_ret_{h}d"] = px.groupby("symbol")["close"].shift(-h) / px["close"] - 1
        ret_cols = [f"forward_ret_{h}d" for h in FORWARD_HORIZONS]
        df = df.merge(px[["symbol", "date", *ret_cols]], on=["symbol", "date"], how="left")
        df["label"] = np.sign(df[f"forward_ret_{h_main}d"]).where(
            df[f"forward_ret_{h_main}d"].notna()
        )
    else:
        for h in FORWARD_HORIZONS:
            df[f"forward_ret_{h}d"] = np.nan
        df["label"] = np.nan

    # 特征可得时点：取各层最大可得时刻；日频层按当日 23:59
    avail = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns, UTC]")
    if "S_available_at" in df.columns:
        avail = pd.to_datetime(df["S_available_at"], utc=True, errors="coerce")
    has_daily = ("M_label" in df.columns) or any(c.startswith("P_") for c in df.columns)
    if has_daily:
        day_end = pd.to_datetime(df["date"].astype(str), utc=True) + pd.Timedelta(
            hours=23, minutes=59
        )
        avail = avail.where(avail.notna() & (avail > day_end), day_end)
    df["feat_as_of"] = avail
    df = df.drop(columns=["S_available_at"], errors="ignore")

    market_days, per_symbol = _event_windows(events, asset_class)
    df["in_event_window"] = [
        ((sym, d) in per_symbol) or (d in market_days)
        for sym, d in zip(df["symbol"], df["date"], strict=True)
    ]

    df = df.set_index(["symbol", "date"]).sort_index()
    violations = audit_lookahead(df)
    df.attrs["lookahead_violations"] = violations
    df.attrs["horizon"] = int(horizon) if isinstance(horizon, int) else list(horizon)
    return df


def audit_lookahead(df: pd.DataFrame) -> list[dict]:
    """前视审计：`feat_as_of` 的日期必须 ≤ 样本 date。返回违规清单（应为空）。"""
    if df.empty or "feat_as_of" not in df.columns:
        return []
    dates = pd.to_datetime(pd.Series(df.index.get_level_values("date"), index=df.index))
    feat = pd.to_datetime(df["feat_as_of"], utc=True, errors="coerce").dt.tz_localize(None)
    bad = feat.notna() & (feat > dates + pd.Timedelta(hours=23, minutes=59))
    return [
        {"symbol": sym, "date": str(d)}
        for sym, d in zip(df.index.get_level_values("symbol")[bad], dates[bad], strict=True)
    ]
