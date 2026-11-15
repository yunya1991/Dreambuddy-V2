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

import bisect
import datetime as _dt
import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..methods import REGISTRY
from ..methods import run as run_method

# 复用方法层唯一的 EMA 实现（禁止在能力层另写一套），只为产出整条平滑曲线。
from ..methods.technical import _ema_series
from .envelope import (
    STATUS_EMPTY,
    STATUS_GOOD,
    STATUS_PARTIAL,
    build,
    quality_for,
    unavailable,
)
from .visual import build_visual

INTENT_SEASONALITY = "seasonality_query"
INTENT_CORRELATION = "correlation_query"
INTENT_STATE = "state_transition"
INTENT_CONDITIONAL = "conditional_return"
INTENT_CONDITIONAL_DISTRIBUTION = "conditional_distribution"
INTENT_DRAWDOWN = "drawdown_query"
INTENT_CROSS = "cross_check"
INTENT_SIGNIFICANCE = "significance_query"
INTENT_PERCENTILE = "metric_percentile"
INTENT_EVENT = "event_study"
INTENT_METRIC_SERIES = "metric_series"
INTENT_TREND = "trend_query"
INTENT_CHANGE_POINT = "change_point_query"

MIN_DRAWDOWN = 250
MIN_ALIGNMENT = 30
MIN_SEASONALITY = 60
MIN_STATE = 100
MIN_CORR = 60
MIN_CCF = 120
MIN_CONDITIONAL = 250
MIN_SIGNIFICANCE = 250
MIN_CROWDING = 60
MIN_EVENT_STUDY = 250
MIN_CHANGE_POINT = 60
MIN_SEASONAL_ADJUSTMENT_SPAN_DAYS = 1095
EVENT_GATE = 30
MIN_COUNT = 3
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


def _paired_rows(
    left: Sequence[Any], right: Sequence[Any]
) -> Tuple[List[int], List[float], List[float]]:
    """按原始位置做 paired complete-case，并保留行号供日期轴同步过滤。"""
    indices: List[int] = []
    left_out: List[float] = []
    right_out: List[float] = []
    for index, (left_value, right_value) in enumerate(zip(left, right, strict=False)):
        try:
            x = float(left_value)
            y = float(right_value)
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(x) and math.isfinite(y)):
            continue
        indices.append(index)
        left_out.append(x)
        right_out.append(y)
    return indices, left_out, right_out


def _paired_floats(left: Sequence[Any], right: Sequence[Any]) -> Tuple[List[float], List[float]]:
    _, left_out, right_out = _paired_rows(left, right)
    return left_out, right_out


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


def _call_soft(method_id: str, data: Any, **params: Any) -> Dict[str, Any]:
    """方法层硬门禁不足时仍取小样本结果，`gate=degraded` 交由能力层披露降级。

    仅对 `insufficient_samples` 生效（其余门禁失败仍原样返回），计算方法不变，
    仍复用方法层登记的同一个函数，不在此重算口径。
    """
    out = _call(method_id, data, **params)
    if out["gate"] != "insufficient_samples":
        return out
    spec = REGISTRY.get(method_id)
    if spec is None or spec.func is None:
        return out
    try:
        result = spec.func(data, **params)
    except ValueError:
        return out
    return {"gate": "degraded", "result": result, "method": method_id}


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


MAX_DRAWDOWN_PATH_POINTS = 500


def _drawdown_path(
    prices: Sequence[float], dates: Sequence[_dt.date], cap: int = MAX_DRAWDOWN_PATH_POINTS
) -> List[Dict[str, Any]]:
    """逐点回撤路径：`1 - p / running_max`（正数幅度），与 D20 的 mdd 同口径（谷点即 mdd）。

    等距抽稀到 `cap` 点，首尾必保留；前端只渲染，不做任何差分或再采样。
    """
    running_peak: Optional[float] = None
    points: List[Dict[str, Any]] = []
    for i, price in enumerate(prices):
        running_peak = price if running_peak is None or price > running_peak else running_peak
        dd = round(1.0 - price / running_peak, 6) if running_peak else None
        points.append({"date": dates[i].isoformat() if i < len(dates) else None, "drawdown": dd})
    if len(points) <= cap:
        return points
    step = (len(points) - 1) / (cap - 1)
    keep = sorted({round(i * step) for i in range(cap)})
    worst_i = max(
        range(len(points)),
        key=lambda i: (points[i]["drawdown"] is not None, points[i]["drawdown"] or 0.0),
    )
    if worst_i not in keep:
        # 抽稀必须保留最大回撤点，否则 min(path) 不再等于 -mdd
        slot = min(range(1, len(keep) - 1), key=lambda j: abs(keep[j] - worst_i))
        keep[slot] = worst_i
        keep = sorted(set(keep))
    return [points[i] for i in keep]


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
    trough_index = int(mdd["trough_index"])
    peak_to_trough_days = trough_index - int(mdd["peak_index"])
    trough_price = px[trough_index] if 0 <= trough_index < len(px) else None
    drawdown_path = _drawdown_path(px, ds)
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
    payload = {
        "capabilities": {
            "D-E10": {
                "gate": "ok",
                "methods": ["D20", "D21"],
                "mdd": mdd["mdd"],
                "peak_index": mdd["peak_index"],
                "trough_index": mdd["trough_index"],
                "peak_date": peak_date,
                "peak_price": peak,
                "trough_price": trough_price,
                "peak_to_trough_days": peak_to_trough_days,
                "current_drawdown": current_dd,
                "duration_days": dur["duration_days"],
                "recovery_days": dur["recovery_days"],
                "recovered": dur["recovered"],
                "drawdown_path": drawdown_path,
            }
        },
        "params": {"min_n": MIN_DRAWDOWN, "window_days": len(px)},
        "symbol": symbol or None,
    }
    return build(
        capability="D-E10",
        intent=INTENT_DRAWDOWN,
        answer=answer,
        data=payload,
        quality_block=q,
        trace_id=trace_id,
        visual=build_visual(capability="D-E10", data=payload, quality_block=q),
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
    counts = _call("C03", data)
    ranking = _call("C04", data)
    weekday = _call("C05", data)
    dom = _call("C07", data)
    quarter = _call("C09", data)
    half_year = _call("C12", data)
    strength = _call("C13", data)
    consistency = _call("C14", data)
    transition = _call("C15", data)
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
                    "methods": [
                        "C01",
                        "C02",
                        "C03",
                        "C04",
                        "C05",
                        "C07",
                        "C09",
                        "C12",
                        "C13",
                        "C14",
                        "C15",
                    ],
                    "month_table": table,
                    "month_win_rate": win["result"] if win["gate"] == "ok" else None,
                    "month_counts": counts["result"] if counts["gate"] == "ok" else None,
                    "month_ranking": ranking["result"] if ranking["gate"] == "ok" else None,
                    "weekday_table": wd_table,
                    "day_of_month": dom["result"] if dom["gate"] == "ok" else None,
                    "quarter_effect": quarter["result"] if quarter["gate"] == "ok" else None,
                    "half_year": half_year["result"] if half_year["gate"] == "ok" else None,
                    "seasonal_strength": strength["result"] if strength["gate"] == "ok" else None,
                    "month_consistency": (
                        consistency["result"] if consistency["gate"] == "ok" else None
                    ),
                    "month_transition": (
                        transition["result"] if transition["gate"] == "ok" else None
                    ),
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

    crosstab = _call("B06", {"row": states[:-1], "col": states[1:]})
    trans = _call("B07", {"states": states})
    stationary = _call("B08", {"states": states})
    dwell = _call("B09", {"states": states})
    if crosstab["gate"] != "ok" or trans["gate"] != "ok" or stationary["gate"] != "ok":
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
                    "methods": ["B02", "B06", "B07", "B08", "B09"],
                    "states": order,
                    "edges": edges,
                    "crosstab": crosstab["result"],
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
    capability_id: str,
    intent: str,
    trace_id: Optional[str],
) -> Dict[str, Any]:
    if not isinstance(series, Mapping) or len(series) < 2:
        return unavailable(
            capability=capability_id,
            intent=intent,
            reason="多资产相关矩阵至少 2 个资产",
            trace_id=trace_id,
        )
    names = sorted(series)
    try:
        raw = {name: list(series[name]) for name in names}
    except TypeError:
        return unavailable(
            capability=capability_id,
            intent=intent,
            reason="多资产序列必须是可迭代数值序列",
            trace_id=trace_id,
        )
    raw_n = min((len(values) for values in raw.values()), default=0)
    ds = _parse_dates(dates)
    if dates and (len(ds) != len(dates) or len(ds) < raw_n):
        return unavailable(
            capability=capability_id,
            intent=intent,
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
            capability=capability_id,
            intent=intent,
            reason=f"对齐点 {n} < {MIN_CORR}",
            trace_id=trace_id,
        )

    panel = {"series": aligned}
    matrix = _call("M05", panel)
    ranking = _call("M06", panel, k=k, base=base)
    average = _call("M07", panel)
    if any(block["gate"] != "ok" for block in (matrix, ranking, average)):
        return unavailable(
            capability=capability_id,
            intent=intent,
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
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "capabilities": {
                capability_id: {
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
    capability_id: str = "D-E05",
    intent: str = INTENT_CORRELATION,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    if series is not None:
        return _matrix_correlation(
            series,
            dates=dates,
            k=k,
            base=base,
            capability_id=capability_id,
            intent=intent,
            trace_id=trace_id,
        )
    if x is None or y is None:
        return unavailable(
            capability=capability_id,
            intent=intent,
            reason="需要双序列 x/y 或多资产 series",
            trace_id=trace_id,
        )
    if dates is not None and (len(dates) < len(x) or len(dates) < len(y)):
        return unavailable(
            capability=capability_id,
            intent=intent,
            reason="日期轴短于双序列，无法保持逐行对齐",
            trace_id=trace_id,
        )
    indices, xv, yv = _paired_rows(x, y)
    n = len(xv)
    if n < MIN_CORR:
        return unavailable(
            capability=capability_id,
            intent=intent,
            reason=f"对齐点 {n} < {MIN_CORR}",
            trace_id=trace_id,
        )
    aligned_dates = [dates[i] for i in indices] if dates is not None else None
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
            capability=capability_id, intent=intent, reason="相关计算失败", trace_id=trace_id
        )

    cycle = (
        _call("C18", {"a": xv, "b": yv, "dates": aligned_dates})
        if aligned_dates is not None
        else None
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
                if (
                    stability["gate"] == "ok"
                    and change["gate"] == "ok"
                    and (cycle is None or cycle["gate"] == "ok")
                )
                else "insufficient_history"
            ),
            "methods": ["M23", "M24", "M25"] + (["C18"] if cycle is not None else []),
            "stability": stability["result"] if stability["gate"] == "ok" else None,
            "breakpoints": change["result"]["breakpoints"] if change["gate"] == "ok" else None,
            "cycle_alignment": cycle["result"] if cycle and cycle["gate"] == "ok" else None,
        },
    }
    ccf_note = ""
    if n >= MIN_CCF:
        legacy_ccf = _call("T03", pair, max_lag=max_lag)
        legacy_best = _call("T04", pair, max_lag=max_lag)
        ccf = _call("M11", pair, max_lag=max_lag)
        best = _call("M12", pair, max_lag=max_lag)
        if all(block["gate"] == "ok" for block in (legacy_ccf, legacy_best, ccf, best)):
            family = ccf["result"]
            optimum = best["result"]
            best_index = family["lags"].index(optimum["lag"])
            best_significant = bool(family["significant"][best_index])
            blocks["D-E06"] = {
                "gate": "ok",
                "methods": ["T03", "T04", "M11", "M12"],
                "lags": family["lags"],
                # 兼容字段改由 M11/M12 提供；T03/T04 原始结果保留在 legacy。
                "ccf": family["r"],
                "r": family["r"],
                "p": family["p"],
                "q": family["q"],
                "p_adj": family["q"],
                "significant": family["significant"],
                "n_by_lag": family["n_by_lag"],
                "best_lag": optimum["lag"],
                "best_ccf": optimum["r"],
                "best_p": optimum["p"],
                "best_q": optimum["q"],
                "best_p_adj": optimum["q"],
                "best_significant": best_significant,
                "search_space": {
                    "pairs": 1,
                    "lag": family["lags"],
                    "window": [n],
                    "h": [],
                    "tests": len(family["lags"]),
                },
                "fdr": {
                    "method": "BH-FDR",
                    "alpha": 0.05,
                    "m": len(family["lags"]),
                },
                "legacy": {
                    "ccf": legacy_ccf["result"],
                    "best": legacy_best["result"],
                },
            }
            lag = optimum["lag"]
            ccf_note = (
                f"领先滞后：最优 lag={lag}（CCF={optimum['r']}，"
                f"BH-FDR q={optimum['q']}，"
                f"{'校正后显著' if best_significant else '校正后不显著'}），"
                f"{'正 lag 表示 ' + x_name + ' 领先' if lag > 0 else ('负 lag 表示 ' + y_name + ' 领先' if lag < 0 else '同期同步')}。"
            )
    else:
        blocks["D-E06"] = {
            "gate": "insufficient_history",
            "methods": ["T03", "T04", "M11", "M12"],
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
        capability=capability_id,
        intent=intent,
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


# ---------------- D-E01 条件收益 ----------------


def conditional_return(
    factor: Sequence[Any],
    prices: Sequence[Any],
    *,
    k: int = 5,
    name: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    if len(factor) != len(prices):
        return unavailable(
            capability="D-E01",
            intent=INTENT_CONDITIONAL,
            reason="因子与价格长度不一致",
            trace_id=trace_id,
        )
    px = _floats(prices)
    if len(px) != len(prices) or not all(math.isfinite(value) for value in px):
        return unavailable(
            capability="D-E01",
            intent=INTENT_CONDITIONAL,
            reason="价格包含无效值，无法在原轴计算前瞻收益",
            trace_id=trace_id,
        )

    from ..align import forward_returns

    forward = forward_returns(px, 1)
    f, target = _paired_floats(factor, forward)
    n = len(f)
    if n < MIN_CONDITIONAL:
        return unavailable(
            capability="D-E01",
            intent=INTENT_CONDITIONAL,
            reason=f"有效因子与前瞻收益对齐点 {n} < {MIN_CONDITIONAL}",
            trace_id=trace_id,
        )

    bins = _call("B02", f, k=k)
    if bins["gate"] != "ok":
        return unavailable(
            capability="D-E01",
            intent=INTENT_CONDITIONAL,
            reason="因子分位分箱失败",
            trace_id=trace_id,
        )
    inner = bins["result"]["edges"][1:-1]
    states = [f"q{min(bisect.bisect_right(inner, value), k - 1)}" for value in f]
    conditional = _call("B05", {"state": states, "target": target})
    price_returns = _call("F01", px)
    baseline = _call("H01", target)
    if any(block["gate"] != "ok" for block in (conditional, price_returns, baseline)):
        return unavailable(
            capability="D-E01",
            intent=INTENT_CONDITIONAL,
            reason="条件收益计算失败",
            trace_id=trace_id,
        )

    table = conditional["result"]["table"]
    bottom, top = table[0], table[-1]
    returns_summary = {key: price_returns["result"][key] for key in ("mean", "std", "n")}
    q = quality_for(
        n,
        min_n=MIN_CONDITIONAL,
        sources=["market.candles"],
        align_method="forward_returns",
        timezone="UTC",
    )
    answer = (
        f"{name + ' ' if name else ''}按因子 {k} 等分分位：最低组 {bottom['state']} "
        f"后 1 日均值 {bottom['mean'] * 100:+.3f}%（n={bottom['n']}），"
        f"最高组 {top['state']} 后 1 日均值 {top['mean'] * 100:+.3f}%（n={top['n']}）；"
        f"全样本前瞻收益单样本检验 p={baseline['result']['p']}。"
        f"对齐 n={n}。{CAVEAT}。"
    )
    return build(
        capability="D-E01",
        intent=INTENT_CONDITIONAL,
        answer=answer,
        data={
            "capabilities": {
                "D-E01": {
                    "gate": "ok",
                    "methods": ["B02", "B05", "F01", "H01"],
                    "horizon": 1,
                    "bins": bins["result"],
                    "conditional": conditional["result"],
                    "price_returns": returns_summary,
                    "baseline_t": baseline["result"],
                }
            },
            "params": {"min_n": MIN_CONDITIONAL, "k": k, "h": 1},
            "name": name or None,
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


# ---------------- D-E14 相关状态条件分布 ----------------


def conditional_distribution(
    factor: Sequence[Any],
    prices: Sequence[Any],
    *,
    dates: Optional[Sequence[Any]] = None,
    release_ts: Optional[Sequence[Any]] = None,
    as_of: Any = None,
    horizons: Sequence[int] = (1, 2),
    buckets: int = 4,
    window: int = MIN_CONDITIONAL,
    min_bucket_n: int = MIN_CONDITIONAL,
    name: str = "相关状态",
    symbol: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """一维相关状态经 R02 PIT 分桶，输出 h=1/2 前瞻分布与共享桶内统计。"""
    if len(factor) != len(prices):
        return unavailable(
            capability="D-E14",
            intent=INTENT_CONDITIONAL_DISTRIBUTION,
            reason="相关状态与价格长度不一致",
            trace_id=trace_id,
        )
    fx, px = _floats(factor), _floats(prices)
    if (
        len(fx) != len(factor)
        or len(px) != len(prices)
        or not all(math.isfinite(value) for value in fx + px)
    ):
        return unavailable(
            capability="D-E14",
            intent=INTENT_CONDITIONAL_DISTRIBUTION,
            reason="相关状态或价格包含无效值",
            trace_id=trace_id,
        )
    if len(px) < MIN_CONDITIONAL:
        return unavailable(
            capability="D-E14",
            intent=INTENT_CONDITIONAL_DISTRIBUTION,
            reason=f"对齐样本 {len(px)} < {MIN_CONDITIONAL}",
            trace_id=trace_id,
        )
    try:
        hs = tuple(sorted({int(h) for h in horizons}))
        requested_buckets = int(buckets)
        window = int(window)
        min_bucket_n = int(min_bucket_n)
    except (TypeError, ValueError):
        return unavailable(
            capability="D-E14",
            intent=INTENT_CONDITIONAL_DISTRIBUTION,
            reason="horizons/buckets/window 参数无效",
            trace_id=trace_id,
        )
    if not hs or min(hs) < 1 or requested_buckets < 2 or window < 2 or min_bucket_n < 1:
        return unavailable(
            capability="D-E14",
            intent=INTENT_CONDITIONAL_DISTRIBUTION,
            reason="horizons 须为正整数，buckets/window/min_bucket_n 超出有效范围",
            trace_id=trace_id,
        )
    n = len(px)
    timestamps = list(dates) if dates else list(range(n))
    ds = _parse_dates(dates)
    if len(timestamps) != n or (dates and len(ds) != n):
        return unavailable(
            capability="D-E14",
            intent=INTENT_CONDITIONAL_DISTRIBUTION,
            reason="日期轴与相关状态/价格长度不一致或日期无效",
            trace_id=trace_id,
        )
    if release_ts is not None and len(release_ts) != n:
        return unavailable(
            capability="D-E14",
            intent=INTENT_CONDITIONAL_DISTRIBUTION,
            reason="release_ts 与相关状态/价格长度不一致",
            trace_id=trace_id,
        )

    payload: Dict[str, Any] = {
        "indicator": fx,
        "price": px,
        "timestamps": timestamps,
        "align_method": "prealigned",
    }
    if release_ts is not None:
        payload["release_ts"] = list(release_ts)

    def evaluate(k: int) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "buckets": k,
            "horizons": hs,
            "label": name or "相关状态",
            "pit": True,
            "window": window,
            "include_states": True,
        }
        if as_of is not None:
            params["as_of"] = as_of
        return _call("R02", payload, **params)

    def primary_passed(result: Dict[str, Any]) -> bool:
        rows = result["by_horizon"][0]["by_bucket"]
        return bool(rows) and all(row["nonoverlap_n"] >= min_bucket_n for row in rows)

    chosen = evaluate(requested_buckets)
    if chosen["result"] is None:
        return unavailable(
            capability="D-E14",
            intent=INTENT_CONDITIONAL_DISTRIBUTION,
            reason=str(chosen.get("reason") or chosen["gate"]),
            trace_id=trace_id,
        )
    degraded_reason: Optional[str] = None
    if not primary_passed(chosen["result"]):
        if requested_buckets <= 2:
            return unavailable(
                capability="D-E14",
                intent=INTENT_CONDITIONAL_DISTRIBUTION,
                reason=f"主期限每桶非重叠样本不足 {min_bucket_n}",
                trace_id=trace_id,
            )
        fallback = evaluate(2)
        if fallback["result"] is None or not primary_passed(fallback["result"]):
            return unavailable(
                capability="D-E14",
                intent=INTENT_CONDITIONAL_DISTRIBUTION,
                reason=f"降为 2 桶后主期限每桶非重叠样本仍不足 {min_bucket_n}",
                trace_id=trace_id,
            )
        chosen = fallback
        degraded_reason = "bucket_nonoverlap_lt_250"

    result = chosen["result"]
    states = result.get("states")
    visible_n = int(result["sample_n"])
    if not isinstance(states, list) or len(states) != visible_n:
        return unavailable(
            capability="D-E14",
            intent=INTENT_CONDITIONAL_DISTRIBUTION,
            reason="R02 未返回等长 PIT 桶标签",
            trace_id=trace_id,
        )

    from ..align import forward_returns

    rows: List[Dict[str, Any]] = []
    weak_horizons: List[int] = []
    for distribution in result["by_horizon"]:
        h = int(distribution["h"])
        if any(row["nonoverlap_n"] < min_bucket_n for row in distribution["by_bucket"]):
            weak_horizons.append(h)
        forward = forward_returns(px[:visible_n], h)
        labels: List[int] = []
        target: List[float] = []
        for state, value in zip(states, forward, strict=False):
            if state is None or value is None:
                continue
            labels.append(int(state))
            target.append(float(value))
        pair = {"state": labels, "target": target}
        percentiles = _call("B10", pair)
        monotonic = _call(
            "R08",
            pair,
            k=len(distribution["by_bucket"]),
            label=name or "相关状态",
            prebinned=True,
        )
        conditional = expression = None
        required = [percentiles, monotonic]
        if h == 1:
            conditional = _call("B05", pair)
            expression = _call("R01", pair, h=h, state=str(result["bucket"]))
            required.extend([conditional, expression])
        if any(block["gate"] != "ok" or block["result"] is None for block in required):
            return unavailable(
                capability="D-E14",
                intent=INTENT_CONDITIONAL_DISTRIBUTION,
                reason=f"h={h} 条件分位或单调性计算失败",
                trace_id=trace_id,
            )
        rows.append(
            {
                "h": h,
                "gate": "degraded" if h in weak_horizons else "ok",
                "distribution": distribution,
                "conditional": conditional["result"] if conditional else None,
                "percentiles": percentiles["result"],
                "expression": expression["result"] if expression else None,
                "monotonic": monotonic["result"],
            }
        )

    if weak_horizons:
        degraded_reason = "bucket_nonoverlap_lt_250"
    q = quality_for(
        visible_n,
        min_n=MIN_CONDITIONAL,
        span=_span(ds[:visible_n]) if ds else None,
        sources=["market.candles", "mm_metrics"],
        align_method=result["align_method"],
        timezone="UTC",
    )
    if degraded_reason:
        q = _degrade(q, degraded_reason)

    main_row = next((row for row in rows if row["h"] == 1), rows[0])
    main = main_row["distribution"]
    if not main.get("effective_n") or any(
        main.get(key) is None for key in ("mean", "median", "p10", "p90", "win_rate")
    ):
        return unavailable(
            capability="D-E14",
            intent=INTENT_CONDITIONAL_DISTRIBUTION,
            reason="当前相关状态桶无有效前瞻分布",
            trace_id=trace_id,
        )
    notes: List[str] = []
    actual_buckets = len(result["by_horizon"][0]["by_bucket"])
    if actual_buckets != requested_buckets:
        notes.append(f"降级：{requested_buckets} 桶非重叠样本不足，降为 {actual_buckets} 桶")
    if weak_horizons:
        weak_text = "、".join(f"h={h}" for h in weak_horizons)
        notes.append(f"降级：{weak_text} 每桶非重叠样本不足，仅作描述")
    note = f"{'；'.join(notes)}。" if notes else ""
    head = f"{symbol} " if symbol else ""
    answer = (
        f"{head}截至 {result['as_of']}，{name or '相关状态'}处于 "
        f"{result['current_percentile']:.1f}% 分位；历史同状态后 {main['h']} 日均值 "
        f"{main['mean'] * 100:+.2f}%、中位 {main['median'] * 100:+.2f}%、80% 历史区间 "
        f"[{main['p10'] * 100:+.2f}%, {main['p90'] * 100:+.2f}%]、"
        f"上涨 {main['win_rate'] * 100:.1f}%（{actual_buckets} 桶，"
        f"有效 n={main['effective_n']}，非重叠 n={main['nonoverlap_n']}）。"
        f"{main_row['monotonic']['phrase']}{note}{CAVEAT}。"
    )
    public_result = {key: value for key, value in result.items() if key != "states"}
    return build(
        capability="D-E14",
        intent=INTENT_CONDITIONAL_DISTRIBUTION,
        answer=answer,
        data={
            "capabilities": {
                "D-E14": {
                    "gate": "insufficient_samples" if degraded_reason else "ok",
                    "methods": ["B05", "B10", "R01", "R02", "R08"],
                    "state_name": name or "相关状态",
                    "pit": True,
                    "as_of": result["as_of"],
                    "requested_buckets": requested_buckets,
                    "buckets": actual_buckets,
                    "min_bucket_nonoverlap_n": min_bucket_n,
                    "degraded_reason": degraded_reason,
                    "weak_horizons": weak_horizons,
                    "conditional_distribution": public_result,
                    "by_horizon": rows,
                }
            },
            "params": {
                "min_n": MIN_CONDITIONAL,
                "horizons": list(hs),
                "window": window,
                "min_bucket_nonoverlap_n": min_bucket_n,
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
    f, t = _paired_floats(factor, forward)
    n = len(f)
    if n < MIN_CONDITIONAL:
        return unavailable(
            capability="D-E08",
            intent=INTENT_CONDITIONAL,
            reason=f"对齐点 {n} < {MIN_CONDITIONAL}（条件 IC 总样本门禁）",
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


# ---------------- D-E12 时空对齐切片 ----------------


def alignment_slice(
    series: Mapping[str, Sequence[Any]],
    *,
    dates: Optional[Sequence[Any]] = None,
    start: Optional[Any] = None,
    end: Optional[Any] = None,
    window: Optional[int] = None,
    max_stale_days: int = 3,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"series": series}
    if dates is not None:
        payload["dates"] = dates
    aligned = _call(
        "R18",
        payload,
        start=start,
        end=end,
        window=window,
        max_stale_days=max_stale_days,
    )
    if aligned["gate"] != "ok":
        reason = (
            f"时空对齐样本不足 {MIN_ALIGNMENT} 点"
            if aligned["gate"] == "insufficient_samples"
            else aligned.get("reason", "时空对齐切片计算失败")
        )
        return unavailable(
            capability="D-E12",
            intent=INTENT_CROSS,
            reason=reason,
            sources=["market.candles"],
            trace_id=trace_id,
        )

    result = aligned["result"]
    sample_n = min((row["n_obs"] for row in result["window_rows"]), default=0)
    span = result["window"].split("~")
    q = quality_for(
        sample_n,
        min_n=MIN_ALIGNMENT,
        span=span,
        sources=["market.candles"],
        align_method=result["align_method"],
        timezone=result["timezone"],
    )
    answer = (
        f"{len(result['assets'])} 个资产完成 UTC 日收盘对齐，窗口 {result['window']}，"
        f"最小有效观测样本 n={sample_n}，stale 上限 {result['max_stale_days']} 天。{CAVEAT}。"
    )
    payload = {
        "capabilities": {
            "D-E12": {
                "gate": "ok",
                "methods": ["R18"],
                **result,
            }
        },
        "params": {
            "min_n": MIN_ALIGNMENT,
            "start": start,
            "end": end,
            "window": window,
            "max_stale_days": max_stale_days,
        },
    }
    return build(
        capability="D-E12",
        intent=INTENT_CROSS,
        answer=answer,
        data=payload,
        quality_block=q,
        trace_id=trace_id,
        visual=build_visual(capability="D-E12", data=payload, quality_block=q),
    )


# ---------------- D-G22 HAC 显著性（Newey-West / Deflated Sharpe） ----------------


def hac_significance(
    series: Sequence[Any],
    *,
    n_trials: int = 1,
    name: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """h>1 重叠前瞻收益的显著性推断出口：Q06 HAC t + Q07 Deflated Sharpe。

    能力层只做门禁与信封，统计口径全部来自方法层（`l1agg.methods.run`），不在此重算。
    `n_trials` 为多重试验次数；默认 1 表示不做多重试验折扣。
    """
    values = _floats(series)
    n = len(values)
    if n < MIN_SIGNIFICANCE:
        return unavailable(
            capability="D-G22",
            intent=INTENT_SIGNIFICANCE,
            reason=f"对齐点 {n} < {MIN_SIGNIFICANCE}（显著性推断样本门禁）",
            trace_id=trace_id,
        )
    payload = {"series": values}
    nw = _call("Q06", payload)
    if nw["gate"] != "ok":
        return unavailable(
            capability="D-G22",
            intent=INTENT_SIGNIFICANCE,
            reason="Newey-West 计算失败：序列退化或样本不足",
            trace_id=trace_id,
        )
    dsr = _call("Q07", payload, n_trials=n_trials)
    dsr_result = dsr["result"] if dsr["gate"] == "ok" else None
    q = quality_for(
        n,
        min_n=MIN_SIGNIFICANCE,
        sources=["market.candles"],
        align_method="hac_newey_west",
        timezone="UTC",
    )
    prefix = f"{name} " if name else ""
    t_nw = nw["result"]["t_nw"]
    if dsr_result is None:
        q = _degrade(q, "dsr_unavailable")
        answer = (
            f"{prefix}均值显著性：Newey-West t={t_nw}"
            f"（se={nw['result']['se']}，Bartlett 核 lag={nw['result']['lag']}，n={n}）。"
            f"DSR 降级：收益序列退化（标准差为 0），不输出 Deflated Sharpe。"
            f"h>1 的重叠向前收益按 HAC 口径推断。{CAVEAT}。"
        )
    else:
        answer = (
            f"{prefix}均值显著性：Newey-West t={t_nw}"
            f"（se={nw['result']['se']}，Bartlett 核 lag={nw['result']['lag']}，n={n}）；"
            f"Deflated Sharpe={dsr_result['dsr']}（试验次数 {dsr_result['n_trials']}，"
            f"sr0={dsr_result['sr0']}）。"
            f"h>1 的重叠向前收益按 HAC 口径推断，不作独立样本解释。{CAVEAT}。"
        )
    return build(
        capability="D-G22",
        intent=INTENT_SIGNIFICANCE,
        answer=answer,
        data={
            "capabilities": {
                "D-G22": {
                    "gate": "ok",
                    "methods": ["Q06", "Q07"],
                    "newey_west": nw["result"],
                    "deflated_sharpe": dsr_result,
                }
            },
            "params": {"min_n": MIN_SIGNIFICANCE, "n_trials": int(n_trials)},
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-A14 拥挤度（F26 + A 分位法 level） ----------------

LEVEL_METHOD = "A_quantile"
LEVEL_QUANTILES = (0.2, 0.6, 0.8)


def crowding(
    series: Mapping[str, Any],
    *,
    dates: Optional[Sequence[Any]] = None,
    symbol: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """拥挤度合成：F26 固定权重分 + A 分位法四档（极低/低/偏高/高）。

    阈值一律取分值历史分布的 p20/p60/p80，禁止使用固定等宽档位；样本不足或
    分值分布退化时方法层返回 `level=None`，此处降级为 partial 并保留原因。
    """
    panel = {
        str(name): _floats(values)
        for name, values in (series or {}).items()
        if isinstance(values, Sequence) and not isinstance(values, str)
    }
    panel = {name: values for name, values in panel.items() if values}
    if not panel:
        return unavailable(
            capability="D-A14",
            intent=INTENT_PERCENTILE,
            reason="缺少拥挤度指标序列（资金费率/多空比/未平仓）",
            trace_id=trace_id,
        )
    n = min(len(values) for values in panel.values())
    if n < MIN_CROWDING:
        return unavailable(
            capability="D-A14",
            intent=INTENT_PERCENTILE,
            reason=f"指标对齐点 {n} < {MIN_CROWDING}（拥挤度样本门禁）",
            trace_id=trace_id,
        )
    ds = _parse_dates(dates)
    method_dates = [d.isoformat() for d in ds[-n:]] if ds else None
    f26 = _call("F26", panel, dates=method_dates)
    if f26["gate"] != "ok":
        return unavailable(
            capability="D-A14",
            intent=INTENT_PERCENTILE,
            reason="拥挤度合成计算失败",
            trace_id=trace_id,
        )
    result = f26["result"]
    span = _span(ds[-n:]) if ds else None
    q = quality_for(
        n,
        min_n=MIN_CROWDING,
        span=span,
        sources=["19-DAL mm_metrics"],
        align_method="series_native",
        timezone="UTC",
    )
    head = f"{symbol or '标的'} " if symbol else ""
    if result["level"] is None:
        q = _degrade(q, result["level_status"])
        reason_txt = {
            "insufficient_sample": "样本不足",
            "degenerate_distribution": "分值分布退化",
        }.get(result["level_status"], "分布不足")
        answer = (
            f"{head}拥挤度合成 score {result['score']}（权重 "
            f"{'/'.join(str(w) for w in result['weights'])}），但{reason_txt}，"
            f"等级与分位阈值降级不出（level_status={result['level_status']}，"
            f"window={result['window']}，n={n}，as_of={result['as_of']}）。{CAVEAT}。"
        )
    else:
        thresholds = result["thresholds"]
        answer = (
            f"{head}拥挤度合成 score {result['score']}（权重 "
            f"{'/'.join(str(w) for w in result['weights'])}），处于分值历史 "
            f"{result['percentile']:.1f}% 分位，等级「{result['level']}」"
            f"（A 分位法 p20/p60/p80={thresholds['p20']}/{thresholds['p60']}/"
            f"{thresholds['p80']}，window={result['window']}，n={n}，"
            f"as_of={result['as_of']}）。{CAVEAT}。"
        )
    return build(
        capability="D-A14",
        intent=INTENT_PERCENTILE,
        answer=answer,
        data={
            "capabilities": {"D-A14": {"gate": "ok", "methods": ["F26"], **result}},
            "params": {
                "min_n": MIN_CROWDING,
                "level_method": LEVEL_METHOD,
                "level_quantiles": list(LEVEL_QUANTILES),
                "window": result["window"],
                "as_of": result["as_of"],
                "pit": False,
            },
            "symbol": symbol or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-E04 事件研究窗 ----------------


def _date_one(value: Any) -> Optional[_dt.date]:
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _dt.datetime.fromtimestamp(float(value), _dt.timezone.utc).date()
    try:
        return _dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _event_index_map(price_dates: Sequence[_dt.date], events: Sequence[Any]) -> List[int]:
    """事件日期 → 价格轴下标：取首个不早于事件日的交易日（盘后事件也落到下一交易日）。"""
    out: List[int] = []
    for raw in events:
        value = raw
        if isinstance(raw, Mapping):
            value = raw.get("event_time", raw.get("date", raw.get("ts")))
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            index = int(value)
            if 0 <= index < len(price_dates):
                out.append(index)
            continue
        event_date = _date_one(value)
        if event_date is None or not price_dates:
            continue
        pos = bisect.bisect_left(price_dates, event_date)
        if pos < len(price_dates):
            out.append(pos)
    return sorted(set(out))


def event_study(
    prices: Sequence[Any],
    *,
    events: Optional[Sequence[Any]] = None,
    dates: Optional[Sequence[Any]] = None,
    k: int = 5,
    event_type: str = "",
    symbol: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """事件研究窗：事件日对齐到价格轴后，用 F19 事件窗收益 + F23 事件后分布 + F21 CAR。"""
    px = _floats(prices)
    if len(px) < MIN_EVENT_STUDY:
        return unavailable(
            capability="D-E04",
            intent=INTENT_EVENT,
            reason=f"价格样本 {len(px)} < {MIN_EVENT_STUDY}（事件研究样本门禁）",
            trace_id=trace_id,
        )
    if not events:
        return unavailable(
            capability="D-E04",
            intent=INTENT_EVENT,
            reason="缺少事件日期（mm_events 为空或未提供 events）",
            trace_id=trace_id,
        )
    ds = _parse_dates(dates)
    price_dates = ds[-len(px) :] if ds else []
    if ds and len(ds) < len(px):
        return unavailable(
            capability="D-E04",
            intent=INTENT_EVENT,
            reason="价格与日期轴长度不一致，无法把事件对齐到价格轴",
            trace_id=trace_id,
        )
    indices = _event_index_map(price_dates, events)
    if not indices:
        return unavailable(
            capability="D-E04",
            intent=INTENT_EVENT,
            reason="事件日期无法映射到价格轴（需提供 dates 或整数下标）",
            trace_id=trace_id,
        )
    window = max(1, int(k))
    payload = {"prices": px, "events": indices}
    f19 = _call_soft("F19", payload, k=window)
    f23 = _call_soft("F23", payload, k=window)
    if f19["result"] is None or f23["result"] is None:
        return unavailable(
            capability="D-E04",
            intent=INTENT_EVENT,
            reason="事件窗收益计算失败",
            trace_id=trace_id,
        )
    returns = _returns(px)
    f21 = _call("F21", returns, window=window) if returns else {"gate": "empty", "result": None}
    cars = f19["result"]
    post = f23["result"]
    n_events = int(cars["n_events"])
    if n_events <= 0:
        return unavailable(
            capability="D-E04",
            intent=INTENT_EVENT,
            reason="事件日无有效事件窗（全部越界或被截断）",
            trace_id=trace_id,
        )
    q = quality_for(
        len(px),
        min_n=MIN_EVENT_STUDY,
        span=_span(price_dates) if price_dates else None,
        sources=["market.candles", "mm_events"],
        align_method="event_to_next_trading_day",
        timezone="UTC",
    )
    if n_events < EVENT_GATE:
        q = _degrade(q, "events_lt_30")
    label = event_type or "事件"
    head = f"{symbol or '标的'} " if symbol else ""
    win_rate = post["win_rate"]
    win_txt = "无法统计" if win_rate is None else f"{win_rate * 100:.1f}%"
    answer = (
        f"{head}历史「{label}」事件 {n_events} 次，事件窗 ±{window} 日平均收益 "
        f"{cars['car'] if cars['car'] is not None else 'NA'}，事后 {window} 日均值 "
        f"{post['mean'] if post['mean'] is not None else 'NA'}、胜率 {win_txt}；"
        f"末段 {window} 日 CAR "
        f"{f21['result']['car'] if f21.get('result') else 'NA'}。"
        f"{'事件数 < 30，仅作短样本描述，等级降级。' if n_events < EVENT_GATE else ''}"
        f"{CAVEAT}。"
    )
    return build(
        capability="D-E04",
        intent=INTENT_EVENT,
        answer=answer,
        data={
            "capabilities": {
                "D-E04": {
                    "gate": "ok",
                    "methods": ["F19", "F21", "F23"],
                    "car": cars["car"],
                    "cars": cars["cars"],
                    "n_events": n_events,
                    "window": window,
                    "win_rate": win_rate,
                    "post_event": {
                        "mean": post["mean"],
                        "median": post["median"],
                        "std": post["std"],
                        "win_rate": win_rate,
                        "n_events": post["n_events"],
                    },
                    "event_type": event_type or None,
                }
            },
            "params": {
                "min_n": MIN_EVENT_STUDY,
                "event_gate": EVENT_GATE,
                "window": window,
                "as_of": price_dates[-1].isoformat() if price_dates else None,
            },
            "symbol": symbol or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-G23 事件窗 CAR + Patell/BMP ----------------


def event_car_significance(
    prices: Sequence[Any],
    *,
    events: Optional[Sequence[Any]] = None,
    dates: Optional[Sequence[Any]] = None,
    est_window: Sequence[int] = (-120, -20),
    event_window: Sequence[int] = (-5, 10),
    event_type: str = "",
    symbol: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Q10 均值调整 CAR + Q11 Patell/BMP；与 D-E04 的描述性事件研究分开。"""
    px = _floats(prices)
    returns = _returns(px)
    if len(returns) < MIN_EVENT_STUDY:
        return unavailable(
            capability="D-G23",
            intent=INTENT_EVENT,
            reason=f"收益样本 {len(returns)} < {MIN_EVENT_STUDY}（事件研究样本门禁）",
            trace_id=trace_id,
        )
    if not events:
        return unavailable(
            capability="D-G23",
            intent=INTENT_EVENT,
            reason="缺少事件日期（mm_events 为空或未提供 events）",
            trace_id=trace_id,
        )
    ds = _parse_dates(dates)
    if ds and len(ds) < len(px):
        return unavailable(
            capability="D-G23",
            intent=INTENT_EVENT,
            reason="价格与日期轴长度不一致，无法把事件对齐到收益轴",
            trace_id=trace_id,
        )
    price_dates = ds[-len(px) :] if ds else []
    price_indices = _event_index_map(price_dates, events)
    # prices[i-1] → prices[i] 的收盘收益在 returns[i-1]，不能沿用价格下标。
    event_indices = [index - 1 for index in price_indices if index > 0]
    if not event_indices:
        return unavailable(
            capability="D-G23",
            intent=INTENT_EVENT,
            reason="事件日期无法映射到收益轴（需提供 dates 或有效的价格下标）",
            trace_id=trace_id,
        )
    est = [int(value) for value in est_window]
    ev = [int(value) for value in event_window]
    payload = {"series": returns}
    params = {"events": event_indices, "est_window": est, "event_window": ev}
    car = _call("Q10", payload, **params)
    if car["gate"] != "ok":
        return unavailable(
            capability="D-G23",
            intent=INTENT_EVENT,
            reason="估计窗或事件窗越界，未形成有效 CAR 样本",
            trace_id=trace_id,
        )
    patell = _call("Q11", payload, **params)
    car_result = car["result"]
    patell_result = patell["result"] if patell["gate"] == "ok" else None
    n_events = int(car_result["n"])
    q = quality_for(
        len(returns),
        min_n=MIN_EVENT_STUDY,
        span=_span(price_dates) if price_dates else None,
        sources=["market.candles", "mm_events"],
        align_method="event_to_next_trading_day",
        timezone="UTC",
    )
    if n_events < EVENT_GATE:
        q = _degrade(q, "events_lt_30")
    if patell_result is None:
        q = _degrade(q, "patell_bmp_unavailable")
    label = event_type or "事件"
    head = f"{symbol or '标的'} " if symbol else ""
    if patell_result is None:
        inference = "Patell/BMP 因估计窗波动不可用而降级，仅保留 CAR"
    else:
        inference = (
            f"Patell z={patell_result['z_patell']}，BMP z={patell_result['z_bmp']}，"
            f"双侧 p={patell_result['p']}（有效检验事件 {patell_result['n']} 次）"
        )
    short_note = "事件数 < 30，统计推断降级；" if n_events < EVENT_GATE else ""
    answer = (
        f"{head}历史「{label}」均值调整 CAR={car_result['car']}（{n_events} 次，"
        f"估计窗 {est}，事件窗 {ev}）；{inference}。{short_note}{CAVEAT}。"
    )
    return build(
        capability="D-G23",
        intent=INTENT_EVENT,
        answer=answer,
        data={
            "capabilities": {
                "D-G23": {
                    "gate": (
                        "ok"
                        if n_events >= EVENT_GATE and patell_result is not None
                        else "insufficient_samples"
                    ),
                    "methods": ["Q10", "Q11"],
                    "car": car_result,
                    "patell_bmp": patell_result,
                    "n_events": n_events,
                    "event_type": event_type or None,
                }
            },
            "params": {
                "min_n": MIN_EVENT_STUDY,
                "event_gate": EVENT_GATE,
                "est_window": est,
                "event_window": ev,
                "as_of": price_dates[-1].isoformat() if price_dates else None,
            },
            "symbol": symbol or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-E09 计数与共现 ----------------


def count_series(
    values: Optional[Sequence[Any]] = None,
    *,
    pairs: Optional[Mapping[str, Sequence[Any]]] = None,
    label: str = "该事件",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """计数与共现：R09 涨跌次数 + B17/R10 双条件共现，全部复用方法层。"""
    xs = _floats(values) if values is not None else []
    pair_panel: Dict[str, List[Any]] = {}
    if isinstance(pairs, Mapping) and len(pairs) >= 2:
        first, second = list(pairs.values())[:2]
        pair_panel = {"x": list(first), "y": list(second)}
    if not xs and not pair_panel:
        return unavailable(
            capability="D-E09",
            intent=INTENT_METRIC_SERIES,
            reason="缺少计数序列或共现双序列",
            trace_id=trace_id,
        )
    n_values = len(xs)
    pair_n = min(len(v) for v in pair_panel.values()) if pair_panel else 0
    if xs and n_values < MIN_COUNT:
        return unavailable(
            capability="D-E09",
            intent=INTENT_METRIC_SERIES,
            reason=f"计数序列 {n_values} < {MIN_COUNT}",
            trace_id=trace_id,
        )
    if pair_panel and pair_n < MIN_COUNT:
        return unavailable(
            capability="D-E09",
            intent=INTENT_METRIC_SERIES,
            reason=f"共现对齐点 {pair_n} < {MIN_COUNT}",
            trace_id=trace_id,
        )
    methods: List[str] = []
    payload: Dict[str, Any] = {}
    phrases: List[str] = []
    if xs:
        counts = _call("R09", xs, label=label)
        if counts["gate"] != "ok":
            return unavailable(
                capability="D-E09",
                intent=INTENT_METRIC_SERIES,
                reason="涨跌次数计算失败",
                trace_id=trace_id,
            )
        methods.append("R09")
        payload.update(
            {
                "up_n": counts["result"]["up_n"],
                "down_n": counts["result"]["down_n"],
                "total": counts["result"]["total"],
                "phrase": counts["result"]["phrase"],
            }
        )
        phrases.append(counts["result"]["phrase"])
    if pair_panel:
        counts = _call("B17", pair_panel)
        co = _call("R10", pair_panel, label=label)
        if counts["gate"] != "ok" or co["gate"] != "ok":
            return unavailable(
                capability="D-E09",
                intent=INTENT_METRIC_SERIES,
                reason="共现统计失败",
                trace_id=trace_id,
            )
        methods.extend(["B17", "R10"])
        payload.update(
            {
                "count": counts["result"]["count"],
                "ratio": counts["result"]["ratio"],
                "total": counts["result"]["n"],
                "phrase": co["result"]["phrase"],
            }
        )
        phrases.append(co["result"]["phrase"])
    q = quality_for(
        n_values or pair_n,
        min_n=MIN_COUNT,
        sources=["19-DAL mm_events" if pair_panel else "market.candles"],
        align_method="series_native",
        timezone="UTC",
    )
    return build(
        capability="D-E09",
        intent=INTENT_METRIC_SERIES,
        answer="".join(phrases) + f"{CAVEAT}。",
        data={
            "capabilities": {"D-E09": {"gate": "ok", "methods": methods, **payload}},
            "params": {
                "min_n": MIN_COUNT,
                "label": label,
                "n": n_values or pair_n,
            },
            "symbol": None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-E15 趋势曲线（平滑 + 斜率 + ADX） ----------------

MIN_TREND = 250
TREND_WINDOWS = (20, 60, 120, 250)
EMA_PERIODS = (12, 26, 50)
MAX_TREND_POINTS = 500


def _ema_order(ema: Mapping[str, Any]) -> str:
    fast = ema.get(str(EMA_PERIODS[0]))
    mid = ema.get(str(EMA_PERIODS[1]))
    slow = ema.get(str(EMA_PERIODS[2]))
    if fast is None or mid is None or slow is None:
        return "unavailable"
    if fast > mid > slow:
        return "bull"
    if fast < mid < slow:
        return "bear"
    return "mixed"


def _slope_row(window: int, prices: Sequence[float]) -> Dict[str, Any]:
    """单窗口斜率：调用 T08，se/t 由 r2 与 n 精确反解（不引入新口径）。"""
    if len(prices) < window:
        return {
            "window": window,
            "slope": None,
            "se": None,
            "t": None,
            "r2": None,
            "n": len(prices),
            "hac_corrected": False,
            "degraded": True,
            "degraded_reason": "window_gt_sample",
        }
    out = _call("T08", list(prices[-window:]))
    if out["gate"] != "ok":
        return {
            "window": window,
            "slope": None,
            "se": None,
            "t": None,
            "r2": None,
            "n": len(prices),
            "hac_corrected": False,
            "degraded": True,
            "degraded_reason": f"t08_{out['gate']}",
        }
    result = out["result"]
    slope = result.get("slope_per_day")
    r2 = result.get("r2")
    n = int(result.get("n") or window)
    t = se = None
    if slope is not None and r2 is not None and 0.0 <= r2 < 1.0 and n > 2:
        t = math.copysign(math.sqrt(r2 * (n - 2) / (1.0 - r2)), slope)
        if t:
            se = slope / t
    return {
        "window": window,
        "slope": slope,
        "se": se,
        "t": t,
        "r2": r2,
        "n": n,
        "hac_corrected": False,
        "degraded": False,
        "degraded_reason": None,
    }


def trend(
    prices: Sequence[Any],
    *,
    dates: Optional[Sequence[Any]] = None,
    highs: Optional[Sequence[Any]] = None,
    lows: Optional[Sequence[Any]] = None,
    symbol: str = "",
    windows: Sequence[int] = TREND_WINDOWS,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """D-E15：EMA 平滑 + 多窗口斜率 + ADX（T2 曲线 / L1-D 方向输入 / T3 全景叶）。

    对外只给统计事实（ADR-V10 对外口径）：斜率符号、ADX 区间、EMA 排列，
    不给任何方向建议。
    """
    px = _floats(prices)
    ds = _parse_dates(dates)
    if len(px) < 2:
        return unavailable(
            capability="D-E15",
            intent=INTENT_TREND,
            reason="价格样本不足 2 点",
            trace_id=trace_id,
        )

    ema_block = _call("I02", {"close": px}, periods=EMA_PERIODS)
    ema = ema_block["result"]["ema"] if ema_block["gate"] == "ok" else {}
    order = _ema_order(ema)

    rows = [_slope_row(int(w), px) for w in windows]

    adx_block: Optional[Dict[str, Any]] = None
    degraded_reasons: List[str] = []
    if highs is not None and lows is not None:
        adx_out = _call("I32", {"high": _floats(highs), "low": _floats(lows), "close": px})
        if adx_out["gate"] == "ok":
            adx_block = adx_out["result"]
    if adx_block is None:
        degraded_reasons.append("adx_unavailable")

    ema_paths: Dict[int, List[float]] = {}
    for period in EMA_PERIODS:
        if len(px) >= period:
            ema_paths[period] = _ema_series(px, period)
    tail = min(len(px), MAX_TREND_POINTS)
    start = len(px) - tail
    smoothed: List[Dict[str, Any]] = []
    for i in range(start, len(px)):
        smoothed.append(
            {
                "date": ds[i].isoformat() if i < len(ds) else None,
                "ema12": round(ema_paths[12][i], 6) if 12 in ema_paths else None,
                "ema26": round(ema_paths[26][i], 6) if 26 in ema_paths else None,
                "ema50": round(ema_paths[50][i], 6) if 50 in ema_paths else None,
            }
        )

    q = quality_for(
        len(px),
        min_n=MIN_TREND,
        span=_span(ds),
        sources=["market.candles"],
        align_method="utc_daily_close",
        timezone="UTC",
    )
    if q["status"] != STATUS_GOOD:
        q = _degrade(q, "trend_sample_lt_250")
        degraded_reasons.append("sample_lt_250")
    if any(row["degraded"] for row in rows):
        degraded_reasons.append("slope_window_gt_sample")

    parts: List[str] = []
    for row in rows:
        if row["slope"] is None:
            parts.append(f"{row['window']}日 —")
        else:
            parts.append(f"{row['window']}日 {row['slope'] * 100:.4f}%/日")
    slope_txt = "、".join(parts)
    adx_txt = (
        "ADX 不可用（缺少高低价）"
        if adx_block is None
        else (
            f"ADX14={adx_block['adx']:.2f}（+DI {adx_block['plus_di']:.2f} / -DI {adx_block['minus_di']:.2f}）"
        )
    )
    head = f"{symbol or '标的'} " if symbol else ""
    note = "样本不足 250 点，趋势仅为短窗口描述；" if q["status"] != STATUS_GOOD else ""
    answer = (
        f"{note}{head}EMA 排列 {order}（12={ema.get('12')} / 26={ema.get('26')} / 50={ema.get('50')}）；"
        f"对数价格趋势斜率 {slope_txt}；{adx_txt}。"
        f"平滑口径 EMA(12/26/50)，斜率窗口 {list(windows)}，n={len(px)}。{CAVEAT}。"
    )

    payload = {
        "capabilities": {
            "D-E15": {
                "gate": "ok",
                "methods": ["I02", "T08"] + (["I32"] if adx_block else []),
                "ema": ema,
                "ema_order": order,
                "slope_table": rows,
                "adx": adx_block,
                "prices": [round(px[i], 6) for i in range(start, len(px))],
                "smoothed": smoothed,
                "meta": {
                    "smoothing": {"method": "EMA", "periods": list(EMA_PERIODS)},
                    "windows": list(windows),
                    "degraded_reasons": degraded_reasons,
                    "n": len(px),
                },
            }
        },
        "params": {"min_n": MIN_TREND, "windows": list(windows)},
        "symbol": symbol or None,
    }

    return build(
        capability="D-E15",
        intent=INTENT_TREND,
        answer=answer,
        data=payload,
        quality_block=q,
        trace_id=trace_id,
        visual=build_visual(capability="D-E15", data=payload, quality_block=q),
    )


# ---------------- D-J02 季节强度与调整 ----------------


def seasonal_adjustment(
    series: Sequence[Any],
    *,
    dates: Optional[Sequence[Any]] = None,
    symbol: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    valid_indices, values, _ = _paired_rows(series, series)
    if len(values) < MIN_SEASONALITY:
        return unavailable(
            capability="D-J02",
            intent=INTENT_SEASONALITY,
            reason=f"样本 {len(values)} < {MIN_SEASONALITY}",
            trace_id=trace_id,
        )
    parsed_dates = _parse_dates(dates)
    if len(parsed_dates) != len(series):
        return unavailable(
            capability="D-J02",
            intent=INTENT_SEASONALITY,
            reason="缺少完整日期轴，无法计算月度季节强度",
            trace_id=trace_id,
        )
    aligned_dates = [parsed_dates[index] for index in valid_indices]
    iso_dates = [value.isoformat() for value in aligned_dates]
    method_ids = ("C13", "T10", "SC91")
    calls = {
        "C13": _call("C13", {"series": values, "dates": iso_dates}),
        "T10": _call("T10", values),
        "SC91": _call("SC91", values),
    }
    failed = [method_id for method_id in method_ids if calls[method_id]["gate"] != "ok"]
    if failed:
        return unavailable(
            capability="D-J02",
            intent=INTENT_SEASONALITY,
            reason=f"季节调整方法失败：{', '.join(failed)}",
            trace_id=trace_id,
        )
    results = {method_id: calls[method_id]["result"] for method_id in method_ids}
    strengths = {
        "C13": results["C13"]["strength"],
        "T10": results["T10"]["seasonal_strength"],
        "SC91": results["SC91"]["seasonal_strength"],
    }
    q = quality_for(
        len(values),
        min_n=MIN_SEASONALITY,
        span=_span(aligned_dates),
        sources=["market.candles", "mm_metrics"],
        align_method="input_order",
        timezone="UTC",
    )
    span_days = (aligned_dates[-1] - aligned_dates[0]).days
    depth_note = ""
    if span_days < MIN_SEASONAL_ADJUSTMENT_SPAN_DAYS:
        q = _degrade(q, "seasonality_depth_lt_3y")
        depth_note = f"样本覆盖 {span_days} 天，不足 3 年，仅作描述。"
    c13_strength = strengths["C13"]
    c13_text = "不可用" if c13_strength is None else f"{c13_strength:.4f}"
    answer = (
        f"{symbol + ' ' if symbol else ''}季节强度：C13={c13_text}，"
        f"STL(period={results['T10']['period']})={strengths['T10']:.4f}，"
        f"X-13 风格(period={results['SC91']['period']})={strengths['SC91']:.4f}。"
        f"{depth_note}样本 n={len(values)}。{CAVEAT}。"
    )
    return build(
        capability="D-J02",
        intent=INTENT_SEASONALITY,
        answer=answer,
        data={
            "capabilities": {
                "D-J02": {
                    "gate": "ok",
                    "methods": list(method_ids),
                    "results": results,
                    "seasonal_strength": strengths,
                }
            },
            "params": {
                "min_n": MIN_SEASONALITY,
                "min_span_days": MIN_SEASONAL_ADJUSTMENT_SPAN_DAYS,
                "periods": {
                    "T10": results["T10"]["period"],
                    "SC91": results["SC91"]["period"],
                },
                "as_of": iso_dates[-1],
            },
            "symbol": symbol or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-J04 变点检测 ----------------


def change_point(
    series: Sequence[Any],
    *,
    dates: Optional[Sequence[Any]] = None,
    symbol: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    valid_indices, values, _ = _paired_rows(series, series)
    if len(values) < MIN_CHANGE_POINT:
        return unavailable(
            capability="D-J04",
            intent=INTENT_CHANGE_POINT,
            reason=f"样本 {len(values)} < {MIN_CHANGE_POINT}",
            trace_id=trace_id,
        )
    parsed_dates = _parse_dates(dates)
    aligned_dates = (
        [parsed_dates[index] for index in valid_indices] if len(parsed_dates) == len(series) else []
    )
    method_ids = ("T22", "T23", "SC49", "SC50", "SC51")
    calls = {method_id: _call(method_id, values) for method_id in method_ids}
    failed = [method_id for method_id, out in calls.items() if out["gate"] != "ok"]
    if failed:
        return unavailable(
            capability="D-J04",
            intent=INTENT_CHANGE_POINT,
            reason=f"变点检测方法失败：{', '.join(failed)}",
            trace_id=trace_id,
        )
    results = {method_id: calls[method_id]["result"] for method_id in method_ids}

    def point_dates(indices: Sequence[int]) -> List[str]:
        return [aligned_dates[index].isoformat() for index in indices if index < len(aligned_dates)]

    breakpoint_dates: Dict[str, Any] = {
        method_id: point_dates(results[method_id]["breakpoints"])
        for method_id in ("T22", "T23", "SC49", "SC50")
    }
    pettitt = results["SC51"]
    pettitt_point = pettitt["point"]
    breakpoint_dates["SC51"] = (
        aligned_dates[pettitt_point].isoformat() if pettitt_point < len(aligned_dates) else None
    )
    q = quality_for(
        len(values),
        min_n=MIN_CHANGE_POINT,
        span=_span(aligned_dates),
        sources=["market.candles", "mm_metrics"],
        align_method="input_order",
        timezone="UTC",
    )
    location = breakpoint_dates["SC51"] or f"下标 {pettitt_point}（0 基）"
    answer = (
        f"{symbol + ' ' if symbol else ''}变点检测：Pettitt 候选变点 {location}，"
        f"p={pettitt['p']:.4g}；精确 PELT 检出 {len(results['SC50']['breakpoints'])} 个变点。"
        f"样本 n={len(values)}。{CAVEAT}。"
    )
    return build(
        capability="D-J04",
        intent=INTENT_CHANGE_POINT,
        answer=answer,
        data={
            "capabilities": {
                "D-J04": {
                    "gate": "ok",
                    "methods": list(method_ids),
                    "results": results,
                    "breakpoint_dates": breakpoint_dates,
                }
            },
            "params": {
                "min_n": MIN_CHANGE_POINT,
                "index_base": 0,
                "as_of": aligned_dates[-1].isoformat() if aligned_dates else None,
            },
            "symbol": symbol or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- 统一调度（能力 ID → executor） ----------------

_EXECUTORS = {
    "D-A14": crowding,
    "D-E01": conditional_return,
    "D-E02": percentile_forward,
    "D-E03": seasonality,
    "D-E04": event_study,
    "D-E05": correlation,
    "D-E06": correlation,
    "D-E07": state_transition,
    "D-E08": conditional_ic,
    "D-E09": count_series,
    "D-E10": drawdown,
    "D-E11": correlation,
    "D-E12": alignment_slice,
    "D-E14": conditional_distribution,
    "D-E15": trend,
    "D-G22": hac_significance,
    "D-G23": event_car_significance,
    "D-J02": seasonal_adjustment,
    "D-J04": change_point,
}


# 共用执行器的能力 → 信封 intent（与 capability_manifest.yaml 一致）。
# correlation() 同时服务 D-E05/D-E06/D-E11，必须由调度层注入请求能力，否则信封会被错标为 D-E05。
_EXECUTOR_INTENTS = {
    "D-E05": INTENT_CORRELATION,
    "D-E06": INTENT_CORRELATION,
    "D-E11": INTENT_CROSS,
}


def run_capability(capability_id: str, **kwargs: Any) -> Dict[str, Any]:
    """按能力 ID 调度；未知能力直接抛 KeyError（注册表校验在 manifest 层）。"""
    executor = _EXECUTORS.get(capability_id)
    if executor is None:
        raise KeyError(f"unregistered capability: {capability_id}")
    intent = _EXECUTOR_INTENTS.get(capability_id)
    if intent is not None:
        kwargs.setdefault("capability_id", capability_id)
        kwargs.setdefault("intent", intent)
    return executor(**kwargs)


def supported() -> Tuple[str, ...]:
    return tuple(sorted(_EXECUTORS))
