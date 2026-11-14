# -*- coding: utf-8 -*-
"""E 组统计关系能力编排（能力层，D-E03/E05/E06/E07/E08/E10/E11）。

分工：能力层只做「取数后编排 + 门禁 + 信封 + 一句话」，所有统计量一律调用
`l1agg.methods.run`（方法层唯一 SSoT），不在此重算任何口径。

门禁口径（TECHNICAL_DESIGN §0.3 / METHOD_LIBRARY §15）：
  - 季节性强结论需 ≥5 年（60 个月），不足只作描述并标 `seasonality_depth_lt_5y`；
  - 同期相关 n≥60、领先滞后 n≥120、状态转移 n≥100、条件 IC 每桶非重叠 n≥250；
  - 回撤画像只需价格，n≥250；任何不足都返回 `status=partial` 且统计字段保留原始门禁块。
"""

from __future__ import annotations

import datetime as _dt
import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..methods import run as run_method
from .envelope import (
    STATUS_EMPTY,
    STATUS_GOOD,
    STATUS_PARTIAL,
    build,
    quality_for,
    unavailable,
)

INTENT_SEASONALITY = "seasonality_query"
INTENT_CORRELATION = "correlation_query"
INTENT_STATE = "state_transition"
INTENT_CONDITIONAL = "conditional_return"
INTENT_DRAWDOWN = "drawdown_query"

MIN_DRAWDOWN = 250
MIN_SEASONALITY = 60
MIN_STATE = 100
MIN_CORR = 60
MIN_CCF = 120
MIN_CONDITIONAL = 250
MONTHS_FOR_SEASONALITY = 60
CAVEAT = "历史统计，不代表未来"


# ---------------- 通用工具 ----------------


def _floats(values: Sequence[Any]) -> List[float]:
    out: List[float] = []
    for v in values:
        if v is None:
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def _returns(prices: Sequence[float]) -> List[float]:
    return [prices[i] / prices[i - 1] - 1.0 for i in range(1, len(prices)) if prices[i - 1]]


def _parse_dates(values: Optional[Sequence[Any]]) -> List[_dt.date]:
    if not values:
        return []
    out: List[_dt.date] = []
    for v in values:
        if isinstance(v, _dt.datetime):
            out.append(v.date())
        elif isinstance(v, _dt.date):
            out.append(v)
        elif isinstance(v, (int, float)):
            out.append(_dt.datetime.fromtimestamp(float(v), _dt.timezone.utc).date())
        else:
            text = str(v)[:10]
            try:
                out.append(_dt.date.fromisoformat(text))
            except ValueError:
                return []
    return out


def _span(dates: Sequence[_dt.date]) -> Optional[List[str]]:
    if not dates:
        return None
    return [dates[0].isoformat(), dates[-1].isoformat()]


def _call(method_id: str, data: Any, **params: Any) -> Dict[str, Any]:
    """调方法层；任何输入/门禁问题收敛为结构化块，不抛给 L1。"""
    try:
        env = run_method(method_id, data, **params)
    except ValueError as exc:
        return {
            "gate": "insufficient_history",
            "reason": str(exc),
            "result": None,
            "method": method_id,
        }
    if env.get("gate") != "ok":
        return {"gate": env.get("gate"), "result": None, "method": method_id}
    return {"gate": "ok", "result": env["result"], "method": method_id}


def _months_span(dates: Sequence[_dt.date]) -> int:
    if not dates:
        return 0
    return (dates[-1].year - dates[0].year) * 12 + (dates[-1].month - dates[0].month) + 1


def _degrade(quality_block: Dict[str, Any], reason: str) -> Dict[str, Any]:
    if quality_block["status"] == STATUS_EMPTY:
        return quality_block
    updated = dict(quality_block)
    updated["status"] = STATUS_PARTIAL
    updated["degraded_reason"] = reason
    return updated


# ---------------- D-E10 回撤画像 ----------------


def drawdown(
    prices: Sequence[Any],
    *,
    symbol: str = "",
    dates: Optional[Sequence[Any]] = None,
    now_ts: Optional[int] = None,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    px = _floats(prices)
    ds = _parse_dates(dates)
    if len(px) < 2:
        return unavailable(
            capability="D-E10",
            intent=INTENT_DRAWDOWN,
            reason="价格样本不足 2 点",
            trace_id=trace_id,
        )
    profile = _call("D20", px)
    duration = _call("D21", px)
    if profile["gate"] != "ok" or duration["gate"] != "ok":
        return unavailable(
            capability="D-E10", intent=INTENT_DRAWDOWN, reason="回撤画像计算失败", trace_id=trace_id
        )
    mdd = profile["result"]
    dur = duration["result"]
    peak = max(px)
    peak_index = px.index(peak)
    peak_date = ds[peak_index].isoformat() if len(ds) == len(px) else None
    last = px[-1]
    current_dd = round(1.0 - last / peak, 6) if peak else None
    q = quality_for(
        len(px),
        min_n=MIN_DRAWDOWN,
        span=_span(ds),
        sources=["market.candles"],
        align_method="utc_daily_close",
        timezone="UTC",
    )
    if q["status"] != STATUS_GOOD:
        note = "样本不足 250 点，回撤仅为短窗口描述"
    else:
        note = "样本充足"
    head = f"{symbol or '标的'} " if symbol else ""
    peak_txt = f"（高点 {peak_date}）" if peak_date else ""
    answer = (
        f"{head}当前价 {last:.2f}，自历史高点 {peak:.2f}{peak_txt} 回撤 {current_dd * 100:.2f}%；"
        f"区间最大回撤 {mdd['mdd'] * 100:.2f}%（峰→谷 {mdd['trough_index'] - mdd['peak_index']} 天），"
        f"当前回撤已持续 {dur['duration_days']} 天，"
        f"{'已收复前高' if dur['recovered'] else '尚未收复前高'}。{note}，n={len(px)}。{CAVEAT}。"
    )
    return build(
        capability="D-E10",
        intent=INTENT_DRAWDOWN,
        answer=answer,
        data={
            "capabilities": {
                "D-E10": {
                    "gate": "ok",
                    "methods": ["D20", "D21", "F09", "F10"],
                    "mdd": mdd["mdd"],
                    "peak_index": mdd["peak_index"],
                    "trough_index": mdd["trough_index"],
                    "peak_date": peak_date,
                    "current_drawdown": current_dd,
                    "duration_days": dur["duration_days"],
                    "recovery_days": dur["recovery_days"],
                    "recovered": dur["recovered"],
                }
            },
            "params": {"min_n": MIN_DRAWDOWN, "window_days": len(px)},
            "symbol": symbol or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-E03 季节性 / 日历效应 ----------------


def seasonality(
    prices: Sequence[Any],
    *,
    dates: Optional[Sequence[Any]] = None,
    symbol: str = "",
    is_returns: bool = False,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    values = _floats(prices)
    ds = _parse_dates(dates)
    if not is_returns:
        values = _returns(values)
        ds = ds[1:] if ds else ds
    if not ds:
        return unavailable(
            capability="D-E03",
            intent=INTENT_SEASONALITY,
            reason="缺少日期轴，无法做日历分组",
            trace_id=trace_id,
        )
    n = min(len(values), len(ds))
    values, ds = values[:n], ds[:n]
    if n < MIN_SEASONALITY:
        return unavailable(
            capability="D-E03",
            intent=INTENT_SEASONALITY,
            reason=f"样本 {n} 天 < {MIN_SEASONALITY} 天",
            trace_id=trace_id,
        )

    data = {"returns": values, "dates": [d.isoformat() for d in ds]}
    month = _call("C01", data)
    win = _call("C02", data)
    weekday = _call("C05", data)
    strength = _call("C13", data)
    consistency = _call("C14", data)
    dom = _call("C07", data)
    failed = [name for name, block in (("C01", month), ("C05", weekday)) if block["gate"] != "ok"]
    if failed:
        return unavailable(
            capability="D-E03",
            intent=INTENT_SEASONALITY,
            reason=f"方法门禁未通过: {failed}",
            trace_id=trace_id,
        )

    table = month["result"]["table"]
    best = max(table, key=lambda row: row["mean"])
    worst = min(table, key=lambda row: row["mean"])
    wd_table = weekday["result"]["table"]
    wd_best = max(wd_table, key=lambda row: row["mean"])
    months = _months_span(ds)
    q = quality_for(
        n,
        min_n=MIN_SEASONALITY,
        span=_span(ds),
        sources=["market.candles"],
        align_method="utc_daily_close",
        timezone="UTC",
    )
    caveat_depth = ""
    if months < MONTHS_FOR_SEASONALITY:
        q = _degrade(q, "seasonality_depth_lt_5y")
        caveat_depth = (
            f"注意：样本仅覆盖 {months} 个月，未达月份效应 5 年门槛，下述结论只作描述、不构成规律。"
        )
    answer = (
        f"{symbol + ' ' if symbol else ''}按月看：最强月 {best['month']} 月"
        f"均值 {best['mean'] * 100:.3f}%（n={best['n']}），最弱月 {worst['month']} 月"
        f"均值 {worst['mean'] * 100:.3f}%（n={worst['n']}）；"
        f"星期维度最强 {wd_best['label']} 均值 {wd_best['mean'] * 100:.3f}%、"
        f"胜率 {wd_best['win_rate'] * 100:.1f}%（n={wd_best['n']}）；"
        f"季节强度 {strength['result']['strength'] if strength['gate'] == 'ok' else None}。"
        f"{caveat_depth}样本 n={n}（{q['span'][0]}~{q['span'][1]}）。{CAVEAT}。"
    )
    return build(
        capability="D-E03",
        intent=INTENT_SEASONALITY,
        answer=answer,
        data={
            "capabilities": {
                "D-E03": {
                    "gate": "ok",
                    "methods": ["C01", "C02", "C05", "C07", "C13", "C14"],
                    "month_table": table,
                    "month_win_rate": win["result"] if win["gate"] == "ok" else None,
                    "weekday_table": wd_table,
                    "seasonal_strength": strength["result"] if strength["gate"] == "ok" else None,
                    "month_consistency": (
                        consistency["result"] if consistency["gate"] == "ok" else None
                    ),
                    "day_of_month": dom["result"] if dom["gate"] == "ok" else None,
                    "best_month": best["month"],
                    "worst_month": worst["month"],
                    "months_covered": months,
                }
            },
            "params": {"min_n": MIN_SEASONALITY, "months_for_conclusion": MONTHS_FOR_SEASONALITY},
            "symbol": symbol or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-E07 状态转移 ----------------


def state_transition(
    prices: Sequence[Any],
    *,
    k: int = 4,
    symbol: str = "",
    dates: Optional[Sequence[Any]] = None,
    is_returns: bool = False,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    values = _floats(prices)
    if not is_returns:
        values = _returns(values)
    if len(values) < MIN_STATE:
        return unavailable(
            capability="D-E07",
            intent=INTENT_STATE,
            reason=f"样本 {len(values)} < {MIN_STATE}",
            trace_id=trace_id,
        )
    bins = _call("B02", values, k=k)
    if bins["gate"] != "ok":
        return unavailable(
            capability="D-E07", intent=INTENT_STATE, reason="分箱失败", trace_id=trace_id
        )
    edges = bins["result"]["edges"]
    inner = edges[1:-1]
    states = [f"q{sum(1 for e in inner if v > e)}" for v in values]

    trans = _call("B07", {"states": states})
    stationary = _call("B08", {"states": states})
    dwell = _call("B09", {"states": states})
    if trans["gate"] != "ok" or stationary["gate"] != "ok":
        return unavailable(
            capability="D-E07", intent=INTENT_STATE, reason="转移矩阵计算失败", trace_id=trace_id
        )
    order = trans["result"]["states"]
    matrix = trans["result"]["matrix"]
    stat = stationary["result"]["stationary"]
    dwell_vals = dwell["result"]["dwell"] if dwell["gate"] == "ok" else [None] * len(order)
    idx = sorted(range(len(order)), key=lambda i: order[i])
    order = [order[i] for i in idx]
    matrix = [[matrix[i][j] for j in idx] for i in idx]
    stat = [stat[i] for i in idx]
    dwell_vals = [dwell_vals[i] for i in idx]
    dwell_txt = "、".join(
        f"{s} {d if d is not None else '∞'} 步" for s, d in zip(order, dwell_vals, strict=False)
    )
    q = quality_for(
        len(values),
        min_n=MIN_STATE,
        span=_span(_parse_dates(dates)),
        sources=["market.candles"],
        align_method="utc_daily_close",
        timezone="UTC",
    )
    hotspots = sorted(zip(order, stat, strict=False), key=lambda item: item[1], reverse=True)
    answer = (
        f"{symbol + ' ' if symbol else ''}按日收益 {k} 分位状态（{order[0]}~{order[-1]}）："
        f"稳态分布占比最高为 {hotspots[0][0]}（{hotspots[0][1] * 100:.1f}%）；"
        f"平均停留 {dwell_txt}。样本 n={len(values)}。{CAVEAT}。"
    )
    return build(
        capability="D-E07",
        intent=INTENT_STATE,
        answer=answer,
        data={
            "capabilities": {
                "D-E07": {
                    "gate": "ok",
                    "methods": ["B02", "B07", "B08", "B09"],
                    "states": order,
                    "edges": edges,
                    "transition_matrix": matrix,
                    "stationary": stat,
                    "dwell": dwell_vals,
                }
            },
            "params": {"min_n": MIN_STATE, "k": k},
            "symbol": symbol or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-E05 / D-E06 / D-E11 相关与领先滞后 ----------------


def _matrix_correlation(
    series: Mapping[str, Sequence[Any]],
    *,
    dates: Optional[Sequence[Any]],
    k: int,
    base: str,
    trace_id: Optional[str],
) -> Dict[str, Any]:
    if not isinstance(series, Mapping) or len(series) < 2:
        return unavailable(
            capability="D-E05",
            intent=INTENT_CORRELATION,
            reason="多资产相关矩阵至少 2 个资产",
            trace_id=trace_id,
        )
    names = sorted(series)
    try:
        raw = {name: list(series[name]) for name in names}
    except TypeError:
        return unavailable(
            capability="D-E05",
            intent=INTENT_CORRELATION,
            reason="多资产序列必须是可迭代数值序列",
            trace_id=trace_id,
        )
    raw_n = min((len(values) for values in raw.values()), default=0)
    ds = _parse_dates(dates)
    if dates and (len(ds) != len(dates) or len(ds) < raw_n):
        return unavailable(
            capability="D-E05",
            intent=INTENT_CORRELATION,
            reason="共享日期轴无效或短于对齐序列",
            trace_id=trace_id,
        )

    aligned = {name: [] for name in names}
    aligned_dates: List[_dt.date] = []
    for i in range(raw_n):
        try:
            row = [float(raw[name][i]) for name in names]
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(value) for value in row):
            continue
        for name, value in zip(names, row, strict=False):
            aligned[name].append(value)
        if ds:
            aligned_dates.append(ds[i])
    n = len(aligned_dates) if ds else len(next(iter(aligned.values())))
    if n < MIN_CORR:
        return unavailable(
            capability="D-E05",
            intent=INTENT_CORRELATION,
            reason=f"对齐点 {n} < {MIN_CORR}",
            trace_id=trace_id,
        )

    panel = {"series": aligned}
    matrix = _call("M05", panel)
    ranking = _call("M06", panel, k=k, base=base)
    average = _call("M07", panel)
    if any(block["gate"] != "ok" for block in (matrix, ranking, average)):
        return unavailable(
            capability="D-E05",
            intent=INTENT_CORRELATION,
            reason="相关矩阵 TopK 计算失败",
            trace_id=trace_id,
        )

    ranked = ranking["result"]
    pairs = [dict(pair, p_adj=pair["q"]) for pair in ranked["pairs"]]
    topk = pairs[: len(ranked["topk"])]
    as_of = aligned_dates[-1].isoformat() if aligned_dates else None
    relationship = {
        "type": "contemporaneous",
        "lag": 0,
        "window": n,
        "h": None,
        "n": n,
        "as_of": as_of,
        "align_method": "utc_daily_close",
        "timezone": "UTC",
        "search_space": {"pairs": ranked["fdr"]["m"], "lag": [0], "window": [n], "h": []},
        "pairs": pairs,
        "topk": topk,
        "fdr": ranked["fdr"],
    }
    span = _span(aligned_dates) if aligned_dates else None
    missing_rate = round(1.0 - n / raw_n, 6) if raw_n else 1.0
    q = quality_for(
        n,
        min_n=MIN_CORR,
        span=span,
        sources=["market.candles"],
        missing_rate=missing_rate,
        align_method="utc_daily_close",
        timezone="UTC",
    )
    leaders = "、".join(f"{p['a']}–{p['b']}(ρ={p['r']:+.3f})" for p in topk)
    scope = f"（基准 {base}）" if base else ""
    answer = (
        f"同期联动 TopK{scope}：{leaders}；平均 |ρ|={average['result']['avg_abs_r']:.3f}"
        f"（{len(names)} 个资产，window={n}，as_of={as_of or '未提供'}，对齐 n={n}）。{CAVEAT}。"
    )
    return build(
        capability="D-E05",
        intent=INTENT_CORRELATION,
        answer=answer,
        data={
            "capabilities": {
                "D-E05": {
                    "gate": "ok",
                    "methods": ["M05", "M06", "M07"],
                    "matrix": matrix["result"],
                    "average_correlation": average["result"],
                    "relationship_topk": relationship,
                }
            },
            "params": {"min_n": MIN_CORR, "k": int(k), "base": base or None},
            "assets": names,
        },
        quality_block=q,
        trace_id=trace_id,
    )


def correlation(
    x: Optional[Sequence[Any]] = None,
    y: Optional[Sequence[Any]] = None,
    *,
    series: Optional[Mapping[str, Sequence[Any]]] = None,
    dates: Optional[Sequence[Any]] = None,
    k: int = 5,
    base: str = "",
    x_name: str = "x",
    y_name: str = "y",
    window: int = 90,
    max_lag: int = 10,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    if series is not None:
        return _matrix_correlation(series, dates=dates, k=k, base=base, trace_id=trace_id)
    if x is None or y is None:
        return unavailable(
            capability="D-E05",
            intent=INTENT_CORRELATION,
            reason="需要双序列 x/y 或多资产 series",
            trace_id=trace_id,
        )
    xv, yv = _floats(x), _floats(y)
    n = min(len(xv), len(yv))
    if n < MIN_CORR:
        return unavailable(
            capability="D-E05",
            intent=INTENT_CORRELATION,
            reason=f"对齐点 {n} < {MIN_CORR}",
            trace_id=trace_id,
        )
    xv, yv = xv[:n], yv[:n]
    pair = {"x": xv, "y": yv}

    pearson = _call("M01", pair)
    spearman = _call("M02", pair)
    kendall = _call("M03", pair)
    rolling = _call("M04", pair, window=min(window, n))
    move = _call("M23", pair)
    stability = _call("M24", pair, window=min(30, n))
    change = _call("M25", pair, window=min(30, n))
    if pearson["gate"] != "ok" or move["gate"] != "ok":
        return unavailable(
            capability="D-E05", intent=INTENT_CORRELATION, reason="相关计算失败", trace_id=trace_id
        )

    blocks: Dict[str, Any] = {
        "D-E05": {
            "gate": "ok",
            "methods": ["M01", "M02", "M03", "M04", "M23"],
            "pearson": pearson["result"],
            "spearman": spearman["result"] if spearman["gate"] == "ok" else None,
            "kendall": kendall["result"] if kendall["gate"] == "ok" else None,
            "rolling": rolling["result"] if rolling["gate"] == "ok" else None,
            "same_direction": move["result"],
        },
        "D-E11": {
            "gate": (
                "ok"
                if (stability["gate"] == "ok" and change["gate"] == "ok")
                else "insufficient_history"
            ),
            "methods": ["M23", "M24", "M25"],
            "stability": stability["result"] if stability["gate"] == "ok" else None,
            "breakpoints": change["result"]["breakpoints"] if change["gate"] == "ok" else None,
        },
    }
    ccf_note = ""
    if n >= MIN_CCF:
        ccf = _call("T03", pair, max_lag=max_lag)
        best = _call("T04", pair, max_lag=max_lag)
        if ccf["gate"] == "ok" and best["gate"] == "ok":
            blocks["D-E06"] = {
                "gate": "ok",
                "methods": ["T03", "T04"],
                "ccf": ccf["result"]["ccf"],
                "best_lag": best["result"]["lag"],
                "best_ccf": best["result"]["ccf"],
            }
            lag = best["result"]["lag"]
            ccf_note = (
                f"领先滞后：最优 lag={lag}（CCF={best['result']['ccf']}），"
                f"{'正 lag 表示 ' + x_name + ' 领先' if lag > 0 else ('负 lag 表示 ' + y_name + ' 领先' if lag < 0 else '同期同步')}。"
            )
    else:
        blocks["D-E06"] = {
            "gate": "insufficient_history",
            "methods": ["T03", "T04"],
            "reason": f"n={n} < {MIN_CCF}",
            "result": None,
        }

    q = quality_for(
        n,
        min_n=MIN_CORR,
        sources=["market.candles"],
        align_method="utc_daily_close",
        timezone="UTC",
    )
    r = pearson["result"]
    answer = (
        f"{x_name} 与 {y_name}：Pearson ρ={r['r']}（p={r['p']}，95%CI {r['ci95']}），"
        f"Spearman ρ={spearman['result']['r'] if spearman['gate'] == 'ok' else None}，"
        f"同向率 {move['result']['ratio'] * 100:.1f}%；"
        f"相关稳定性 {stability['result']['stability'] if stability['gate'] == 'ok' else None}，"
        f"突变点 {len(blocks['D-E11']['breakpoints'] or [])} 个。{ccf_note}"
        f"对齐 n={n}。{CAVEAT}。"
    )
    return build(
        capability="D-E05",
        intent=INTENT_CORRELATION,
        answer=answer,
        data={
            "capabilities": blocks,
            "params": {
                "min_n": MIN_CORR,
                "min_ccf_n": MIN_CCF,
                "window": window,
                "max_lag": max_lag,
            },
            "pair": [x_name, y_name],
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-E02 分位 → 前瞻收益 ----------------


def percentile_forward(
    prices: Sequence[Any],
    *,
    dates: Optional[Sequence[Any]] = None,
    symbol: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    from ..persistence.profile import conditional_distribution

    px = _floats(prices)
    ds = _parse_dates(dates)
    if dates and len(ds) != len(px):
        return unavailable(
            capability="D-E02",
            intent="metric_percentile",
            reason="日期轴与价格长度不一致",
            trace_id=trace_id,
        )
    a8 = conditional_distribution(px, ds if dates else None)
    result = a8.get("result")
    if not result:
        return unavailable(
            capability="D-E02",
            intent="metric_percentile",
            reason=str(a8.get("degraded_reason") or "条件分布样本不足"),
            trace_id=trace_id,
        )
    current = result["by_horizon"][0]
    if not current.get("effective_n"):
        return unavailable(
            capability="D-E02",
            intent="metric_percentile",
            reason="当前波动分位桶无有效前瞻样本",
            trace_id=trace_id,
        )

    n = result["sample_n"]
    offset = len(px) - n
    span = _span(ds[offset:]) if len(ds) == len(px) else None
    q = quality_for(
        n,
        min_n=MIN_CONDITIONAL,
        span=span,
        sources=["market.candles"],
        align_method=result["align_method"],
        timezone="UTC",
    )
    notes = []
    if a8["buckets"] != a8["requested_buckets"]:
        notes.append("4 桶非重叠样本不足，降为 2 桶")
    if a8["gate"] != "ok":
        notes.append("每桶非重叠样本仍未达 250，仅作描述")
    if a8.get("degraded_reason"):
        q = _degrade(q, a8["degraded_reason"])
    note = f"{'；'.join(notes)}。" if notes else ""
    head = f"{symbol} " if symbol else ""
    answer = (
        f"{head}截至 {result['as_of']}，滚动波动率处于 {result['current_percentile']:.1f}% 分位；"
        f"历史同状态后 1 日均值 {current['mean'] * 100:+.2f}%、"
        f"中位 {current['median'] * 100:+.2f}%、80% 历史区间 "
        f"[{current['p10'] * 100:+.2f}%, {current['p90'] * 100:+.2f}%]、"
        f"上涨 {current['win_rate'] * 100:.1f}%（{a8['buckets']} 桶，"
        f"有效 n={current['effective_n']}，非重叠 n={current['nonoverlap_n']}）。"
        f"{note}{CAVEAT}。"
    )
    return build(
        capability="D-E02",
        intent="metric_percentile",
        answer=answer,
        data={
            "capabilities": {
                "D-E02": {
                    "gate": a8["gate"],
                    "methods": ["I30", "R02"],
                    "conditional_distribution": a8,
                }
            },
            "params": {
                "min_n": MIN_CONDITIONAL,
                "h": 1,
                "min_bucket_nonoverlap_n": a8["min_bucket_nonoverlap_n"],
            },
            "symbol": symbol or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-E08 条件 IC / 分箱单调性 ----------------


def conditional_ic(
    factor: Sequence[Any],
    forward: Sequence[Any],
    *,
    k: int = 5,
    name: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    f, t = _floats(factor), _floats(forward)
    n = min(len(f), len(t))
    if n < MIN_CONDITIONAL:
        return unavailable(
            capability="D-E08",
            intent=INTENT_CONDITIONAL,
            reason=f"对齐点 {n} < {MIN_CONDITIONAL}（每桶非重叠门禁）",
            trace_id=trace_id,
        )
    pair = {"factor": f[:n], "target": t[:n]}
    mono = _call("B11", pair, k=k)
    ic = _call("B13", pair)
    rank_ic = _call("B14", pair)
    if ic["gate"] != "ok" or mono["gate"] != "ok":
        return unavailable(
            capability="D-E08",
            intent=INTENT_CONDITIONAL,
            reason="IC/分箱计算失败",
            trace_id=trace_id,
        )
    q = quality_for(
        n,
        min_n=MIN_CONDITIONAL,
        sources=["market.candles"],
        align_method="forward_returns",
        timezone="UTC",
    )
    answer = (
        f"{name + ' ' if name else ''}因子对前瞻收益：IC={ic['result']['ic']}"
        f"（p={ic['result']['p']}），RankIC="
        f"{rank_ic['result']['rank_ic'] if rank_ic['gate'] == 'ok' else None}，"
        f"分箱单调性 {mono['result']['monotonic']}（ρ_bin={mono['result']['rho_bin']}）。"
        f"对齐 n={n}。{CAVEAT}。"
    )
    return build(
        capability="D-E08",
        intent=INTENT_CONDITIONAL,
        answer=answer,
        data={
            "capabilities": {
                "D-E08": {
                    "gate": "ok",
                    "methods": ["B11", "B13", "B14"],
                    "monotonic": mono["result"]["monotonic"],
                    "bin_means": mono["result"]["bin_means"],
                    "ic": ic["result"],
                    "rank_ic": rank_ic["result"] if rank_ic["gate"] == "ok" else None,
                }
            },
            "params": {"min_n": MIN_CONDITIONAL, "k": k},
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- 统一调度（能力 ID → executor） ----------------

_EXECUTORS = {
    "D-E02": percentile_forward,
    "D-E03": seasonality,
    "D-E05": correlation,
    "D-E06": correlation,
    "D-E07": state_transition,
    "D-E08": conditional_ic,
    "D-E10": drawdown,
    "D-E11": correlation,
}


def run_capability(capability_id: str, **kwargs: Any) -> Dict[str, Any]:
    """按能力 ID 调度；未知能力直接抛 KeyError（注册表校验在 manifest 层）。"""
    if capability_id not in _EXECUTORS:
        raise KeyError(f"unregistered capability: {capability_id}")
    return _EXECUTORS[capability_id](**kwargs)


def supported() -> Tuple[str, ...]:
    return tuple(sorted(_EXECUTORS))
