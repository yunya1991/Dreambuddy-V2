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
INTENT_CYCLE = "cycle_query"
INTENT_METRIC_DERIVED = "metric_derived"
INTENT_TECHNICAL = "technical_indicator"

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
MIN_TAIL_DEPENDENCE = 60
MIN_TAIL_EVENTS = 30
MIN_CYCLE = 60
MIN_CYCLE_SPAN_DAYS = 2920
CYCLE_REFERENCE_DAYS = 1460
MIN_CHANGE_POINT = 60
MIN_PORTFOLIO_RISK = 60
MIN_IC_PROFILE = 250
MIN_DIMENSION_REDUCTION = 60
MIN_EWMA_RISK = 60
MIN_SERIES = 30
MIN_CHANGE = 2
MIN_CAGR = 2
MIN_PERCENTILE = 30
MIN_PERCENTILE_LOOKBACK = 60
MIN_VOL_WINDOW = 60
MIN_YOY_SAMPLE = 13
MIN_MOM_SAMPLE = 2
MIN_REAL_RATE = 13
MIN_ROLLING_CORR = 60
MIN_SLOPE = 60
MIN_MOMENTUM = 60
MIN_VOL_TARGET = 60
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


def _panel_rows(
    series: Mapping[str, Sequence[Any]],
) -> Tuple[List[str], Dict[str, List[float]], List[List[float]], List[int]]:
    """多列面板按原始行做 complete-case，保留行号供日期轴同步过滤。"""
    names = sorted(str(key) for key in series)
    raw = [list(series[key]) for key in names]
    n = min((len(column) for column in raw), default=0)
    indices: List[int] = []
    rows: List[List[float]] = []
    for index in range(n):
        values: List[float] = []
        for column in raw:
            try:
                value = float(column[index])
            except (TypeError, ValueError):
                break
            if not math.isfinite(value):
                break
            values.append(value)
        else:
            indices.append(index)
            rows.append(values)
    panel = {name: [row[position] for row in rows] for position, name in enumerate(names)}
    return names, panel, rows, indices


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
    capability_id: str = "D-E10",
    intent: str = INTENT_DRAWDOWN,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    px = _floats(prices)
    ds = _parse_dates(dates)
    if len(px) < 2:
        return unavailable(
            capability=capability_id,
            intent=intent,
            reason="价格样本不足 2 点",
            trace_id=trace_id,
        )
    profile = _call("D20", px)
    duration = _call("D21", px)
    if profile["gate"] != "ok" or duration["gate"] != "ok":
        return unavailable(
            capability=capability_id,
            intent=intent,
            reason="回撤画像计算失败",
            trace_id=trace_id,
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
            capability_id: {
                "gate": "ok",
                "methods": ["D20", "D21"],
                "mdd": mdd["mdd"],
                "drawdown": current_dd,
                "peak_ts": peak_date,
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
        capability=capability_id,
        intent=intent,
        answer=answer,
        data=payload,
        quality_block=q,
        trace_id=trace_id,
        visual=build_visual(capability=capability_id, data=payload, quality_block=q),
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


TIER_LABELS = {4: "A", 3: "B", 2: "D"}  # 二维档位：4×4 / 3×3 / 2×2


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
    factor2: Optional[Sequence[Any]] = None,
    name2: str = "第二维状态",
    buckets_per_axis: Optional[int] = None,
    symbol: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """相关状态经 R02 PIT 分桶，输出 h=1/2 前瞻分布与共享桶内统计。

    一维：默认 4 桶，主期限每桶非重叠不足 250 时降 2 桶。
    二维（传 `factor2`）：按「每格非重叠 ≥`min_bucket_n`」做档位阶梯
    4×4=A（≥4,000 日）→ 3×3=B（≥2,250 日）→ 2×2=D（≥1,000 日）；
    三档均不达标则不出二维结论，回退一维并披露 `degraded_reason=insufficient_2d`。
    实际档位/格数/每格 n 一律显式返回（`tier`/`cells`/`min_cell_nonoverlap_n`），不静默降级。
    """
    two_axis = factor2 is not None
    if len(factor) != len(prices):
        return unavailable(
            capability="D-E14",
            intent=INTENT_CONDITIONAL_DISTRIBUTION,
            reason="相关状态与价格长度不一致",
            trace_id=trace_id,
        )
    if two_axis and len(factor2) != len(prices):
        return unavailable(
            capability="D-E14",
            intent=INTENT_CONDITIONAL_DISTRIBUTION,
            reason="第二维相关状态与价格长度不一致",
            trace_id=trace_id,
        )
    fx, px = _floats(factor), _floats(prices)
    fx2 = _floats(factor2) if two_axis else []
    invalid = (
        len(fx) != len(factor)
        or len(px) != len(prices)
        or not all(math.isfinite(value) for value in fx + px)
        or (two_axis and (len(fx2) != len(factor2) or not all(math.isfinite(v) for v in fx2)))
    )
    if invalid:
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
        requested_axis = requested_buckets if buckets_per_axis is None else int(buckets_per_axis)
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
    if two_axis and requested_axis < 2:
        return unavailable(
            capability="D-E14",
            intent=INTENT_CONDITIONAL_DISTRIBUTION,
            reason="二维 buckets_per_axis 须 ≥ 2",
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

    def evaluate(k: int, axis2: bool = False) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "buckets": k,
            "horizons": hs,
            "label": name or "相关状态",
            "pit": True,
            "window": window,
            "include_states": True,
        }
        target = dict(payload)
        if axis2:
            target["indicator2"] = fx2
            params["label2"] = name2 or "第二维状态"
        if as_of is not None:
            params["as_of"] = as_of
        return _call("R02", target, **params)

    def gate_rows(result: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
        return result["by_horizon"][0][key]

    def primary_passed(result: Dict[str, Any], key: str) -> bool:
        rows = gate_rows(result, key)
        return bool(rows) and all(row["nonoverlap_n"] >= min_bucket_n for row in rows)

    dim = 2 if two_axis else 1
    tier: Optional[str] = None
    requested_tier: Optional[str] = None
    degraded_tier: Optional[str] = None
    attempts: List[Dict[str, Any]] = []
    actual_axis = 0
    bucket_downgraded_from: Optional[int] = None
    degraded_reason: Optional[str] = None
    chosen: Optional[Dict[str, Any]] = None
    if two_axis:
        ladder = [k for k in (4, 3, 2) if k <= requested_axis]
        requested_tier = TIER_LABELS.get(ladder[0]) if ladder else None
        for k in ladder:
            env = evaluate(k, axis2=True)
            if env["result"] is None:
                attempts.append(
                    {
                        "buckets_per_axis": k,
                        "tier": TIER_LABELS.get(k),
                        "gate": env.get("gate"),
                        "reason": env.get("reason"),
                    }
                )
                continue
            cells_min = min(
                (row["nonoverlap_n"] for row in gate_rows(env["result"], "by_cell")), default=0
            )
            ok = primary_passed(env["result"], "by_cell")
            attempts.append(
                {
                    "buckets_per_axis": k,
                    "cells": k * k,
                    "tier": TIER_LABELS.get(k),
                    "min_cell_nonoverlap_n": cells_min,
                    "passed": ok,
                }
            )
            if ok:
                chosen, tier, actual_axis = env, TIER_LABELS.get(k), k
                break
        if chosen is None:
            dim = 1
            degraded_reason = "insufficient_2d"
        elif tier != requested_tier:
            degraded_tier = tier
            degraded_reason = "bucket_nonoverlap_lt_250"

    if dim == 1:
        chosen = evaluate(requested_buckets)
        if chosen["result"] is None:
            return unavailable(
                capability="D-E14",
                intent=INTENT_CONDITIONAL_DISTRIBUTION,
                reason=str(chosen.get("reason") or chosen["gate"]),
                trace_id=trace_id,
            )
        if not primary_passed(chosen["result"], "by_bucket"):
            if requested_buckets <= 2:
                return unavailable(
                    capability="D-E14",
                    intent=INTENT_CONDITIONAL_DISTRIBUTION,
                    reason=f"主期限每桶非重叠样本不足 {min_bucket_n}",
                    trace_id=trace_id,
                )
            fallback = evaluate(2)
            if fallback["result"] is None or not primary_passed(fallback["result"], "by_bucket"):
                return unavailable(
                    capability="D-E14",
                    intent=INTENT_CONDITIONAL_DISTRIBUTION,
                    reason=f"降为 2 桶后主期限每桶非重叠样本仍不足 {min_bucket_n}",
                    trace_id=trace_id,
                )
            chosen = fallback
            bucket_downgraded_from = requested_buckets
            if degraded_reason is None:
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
    key = "by_cell" if dim == 2 else "by_bucket"
    actual_buckets = len(gate_rows(result, key))
    if dim == 2:
        actual_axis = int(result.get("buckets_per_axis") or actual_axis)
    current_state = str(result["cell"]) if dim == 2 else str(result["bucket"])

    from ..align import forward_returns

    rows: List[Dict[str, Any]] = []
    weak_horizons: List[int] = []
    for distribution in result["by_horizon"]:
        h = int(distribution["h"])
        if any(row["nonoverlap_n"] < min_bucket_n for row in distribution[key]):
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
        monotonic = None
        if dim == 1:
            monotonic = _call(
                "R08",
                pair,
                k=len(distribution[key]),
                label=name or "相关状态",
                prebinned=True,
            )
        conditional = expression = None
        required = [percentiles]
        if monotonic is not None:
            required.append(monotonic)
        if h == 1:
            conditional = _call("B05", pair)
            expression = _call("R01", pair, h=h, state=current_state)
            required.extend([conditional, expression])
        if any(block["gate"] != "ok" or block["result"] is None for block in required):
            return unavailable(
                capability="D-E14",
                intent=INTENT_CONDITIONAL_DISTRIBUTION,
                reason=f"h={h} 条件分位或单调性计算失败" if dim == 1 else f"h={h} 条件分位计算失败",
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
                "monotonic": monotonic["result"] if monotonic else None,
            }
        )

    if weak_horizons and degraded_reason is None:
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
        main.get(field) is None for field in ("mean", "median", "p10", "p90", "win_rate")
    ):
        return unavailable(
            capability="D-E14",
            intent=INTENT_CONDITIONAL_DISTRIBUTION,
            reason="当前相关状态桶无有效前瞻分布",
            trace_id=trace_id,
        )
    notes: List[str] = []
    if dim == 2:
        min_cell = min(row["nonoverlap_n"] for row in gate_rows(result, key))
        if degraded_tier:
            notes.append(
                f"降级：{requested_tier} 档每格非重叠样本不足，"
                f"降为 {actual_axis}×{actual_axis}（Tier {tier}）"
            )
    else:
        min_cell = None
        if bucket_downgraded_from:
            notes.append(
                f"降级：{bucket_downgraded_from} 桶非重叠样本不足，降为 {actual_buckets} 桶"
            )
        if degraded_reason == "insufficient_2d":
            notes.append(
                f"降级：二维 2×2 每格非重叠样本不足 {min_bucket_n}，"
                f"不出二维结论，回退一维 {actual_buckets} 桶"
            )
    if weak_horizons:
        weak_text = "、".join(f"h={h}" for h in weak_horizons)
        notes.append(f"降级：{weak_text} 每桶非重叠样本不足，仅作描述")
    note = f"{'；'.join(notes)}。" if notes else ""
    head = f"{symbol} " if symbol else ""
    if dim == 2:
        main_text = (
            f"{head}截至 {result['as_of']}，{name or '相关状态'}处于 "
            f"{result['current_percentile']:.1f}% 分位、{name2 or '第二维状态'}处于 "
            f"{result['current_percentile_2']:.1f}% 分位"
            f"（{actual_axis}×{actual_axis} 网格共 {actual_buckets} 格，Tier {tier}）；"
            f"历史同格后 {main['h']} 日均值 {main['mean'] * 100:+.2f}%、"
            f"中位 {main['median'] * 100:+.2f}%、80% 历史区间 "
            f"[{main['p10'] * 100:+.2f}%, {main['p90'] * 100:+.2f}%]、"
            f"上涨 {main['win_rate'] * 100:.1f}%（有效 n={main['effective_n']}，"
            f"非重叠 n={main['nonoverlap_n']}，每格非重叠下限 {min_cell}）。"
        )
    else:
        main_text = (
            f"{head}截至 {result['as_of']}，{name or '相关状态'}处于 "
            f"{result['current_percentile']:.1f}% 分位；历史同状态后 {main['h']} 日均值 "
            f"{main['mean'] * 100:+.2f}%、中位 {main['median'] * 100:+.2f}%、80% 历史区间 "
            f"[{main['p10'] * 100:+.2f}%, {main['p90'] * 100:+.2f}%]、"
            f"上涨 {main['win_rate'] * 100:.1f}%（{actual_buckets} 桶，"
            f"有效 n={main['effective_n']}，非重叠 n={main['nonoverlap_n']}）。"
        )
    monotonic_text = main_row["monotonic"]["phrase"] if main_row["monotonic"] else ""
    answer = f"{main_text}{monotonic_text}{note}{CAVEAT}。"
    public_result = {name_key: value for name_key, value in result.items() if name_key != "states"}
    return build(
        capability="D-E14",
        intent=INTENT_CONDITIONAL_DISTRIBUTION,
        answer=answer,
        data={
            "capabilities": {
                "D-E14": {
                    "gate": "insufficient_samples" if degraded_reason else "ok",
                    "methods": (
                        ["B05", "B10", "R01", "R02", "R08"]
                        if dim == 1
                        else ["B05", "B10", "R01", "R02"]
                    ),
                    "dim": dim,
                    "state_name": name or "相关状态",
                    "state_name_2": (name2 or "第二维状态") if dim == 2 else None,
                    "pit": True,
                    "as_of": result["as_of"],
                    "requested_buckets": requested_buckets,
                    "buckets": actual_axis if dim == 2 else actual_buckets,
                    "requested_buckets_per_axis": requested_axis if two_axis else None,
                    "buckets_per_axis": actual_axis if dim == 2 else None,
                    "cells": actual_buckets if dim == 2 else None,
                    "tier": tier,
                    "requested_tier": requested_tier,
                    "degraded_tier": degraded_tier,
                    "tier_attempts": attempts,
                    "min_bucket_nonoverlap_n": min_bucket_n,
                    "min_cell_nonoverlap_n": min_cell,
                    "degraded_reason": degraded_reason,
                    "weak_horizons": weak_horizons,
                    "conditional_distribution": public_result,
                    "by_horizon": rows,
                }
            },
            "params": {
                "min_n": MIN_CONDITIONAL,
                "dim": dim,
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


# ---------------- D-G16 组合 VaR / CVaR ----------------


def portfolio_risk(
    series: Mapping[str, Sequence[Any]],
    *,
    weights: Any = None,
    quantile: float = 0.05,
    z: float = 1.645,
    dates: Optional[Sequence[Any]] = None,
    name: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """组合与逐资产尾部风险并列输出，所有统计量均由方法层计算。"""
    panel: Dict[str, List[float]] = {}
    if isinstance(series, Mapping):
        for symbol, values in series.items():
            if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
                cleaned = _floats(values)
                if cleaned:
                    panel[str(symbol)] = cleaned
    if not panel:
        return unavailable(
            capability="D-G16",
            intent=INTENT_METRIC_SERIES,
            reason="缺少各资产收益序列",
            trace_id=trace_id,
        )
    n = min(len(values) for values in panel.values())
    if n < MIN_PORTFOLIO_RISK:
        return unavailable(
            capability="D-G16",
            intent=INTENT_METRIC_SERIES,
            reason=f"组合对齐样本 {n} < {MIN_PORTFOLIO_RISK}",
            trace_id=trace_id,
        )
    symbols = sorted(panel)
    payload = {"series": panel, "weights": weights}
    parametric = _call("P09", payload, z=z)
    historical = _call("P10", payload, quantile=quantile)
    if parametric["gate"] != "ok" or historical["gate"] != "ok":
        return unavailable(
            capability="D-G16",
            intent=INTENT_METRIC_SERIES,
            reason="组合 VaR/CVaR 计算失败",
            trace_id=trace_id,
        )
    historical_result = historical["result"]
    q_percent = float(historical_result["quantile"]) * 100.0
    assets: Dict[str, Any] = {}
    for symbol in symbols:
        aligned = panel[symbol][:n]
        var = _call("D17", aligned, q=q_percent)
        cvar = _call("D18", aligned, q=q_percent)
        if var["gate"] != "ok" or cvar["gate"] != "ok":
            return unavailable(
                capability="D-G16",
                intent=INTENT_METRIC_SERIES,
                reason=f"{symbol} 单资产 VaR/CVaR 计算失败",
                trace_id=trace_id,
            )
        assets[symbol] = {"var": var["result"], "cvar": cvar["result"]}
    parsed_dates = _parse_dates(dates)
    aligned_dates = parsed_dates[:n] if len(parsed_dates) >= n else []
    q = quality_for(
        n,
        min_n=MIN_PORTFOLIO_RISK,
        span=_span(aligned_dates),
        sources=["market.candles"],
        align_method="min_common_length",
        timezone="UTC",
    )
    parametric_result = parametric["result"]
    confidence = 100.0 - float(historical_result["quantile"]) * 100.0
    prefix = f"{name} " if name else "组合 "
    answer = (
        f"{prefix}{confidence:g}% 单期尾部风险（损失正数口径）："
        f"参数法 VaR={parametric_result['var']:.6f}，"
        f"历史法 VaR={historical_result['var_hist']:.6f}，"
        f"CVaR={historical_result['cvar']:.6f}；逐资产历史 VaR/CVaR 并列输出。"
        f"对齐样本 n={n}。{CAVEAT}。"
    )
    return build(
        capability="D-G16",
        intent=INTENT_METRIC_SERIES,
        answer=answer,
        data={
            "capabilities": {
                "D-G16": {
                    "gate": "ok",
                    "methods": ["D17", "D18", "P09", "P10"],
                    "symbols": symbols,
                    "portfolio": {
                        "parametric": parametric_result,
                        "historical": historical_result,
                    },
                    "assets": assets,
                }
            },
            "params": {
                "min_n": MIN_PORTFOLIO_RISK,
                "quantile": historical_result["quantile"],
                "z": parametric_result["z"],
                "as_of": aligned_dates[-1].isoformat() if aligned_dates else None,
            },
            "name": name or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-G19 IC / ICIR / 衰减表 ----------------


def ic_profile(
    factor: Sequence[Any],
    forward: Sequence[Any],
    *,
    prices: Optional[Sequence[Any]] = None,
    window: int = 20,
    horizons: Sequence[int] = (1, 3, 5, 10, 20),
    lookback: int = 20,
    dates: Optional[Sequence[Any]] = None,
    name: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """因子 IC/RankIC、分段 ICIR 与两类 IC 衰减表；统计量全部由方法层计算。"""
    indices, aligned_factor, aligned_forward = _paired_rows(factor, forward)
    n = len(aligned_factor)
    if n < MIN_IC_PROFILE:
        return unavailable(
            capability="D-G19",
            intent=INTENT_METRIC_SERIES,
            reason=f"因子/前瞻收益对齐样本 {n} < {MIN_IC_PROFILE}",
            trace_id=trace_id,
        )

    pair = {"factor": aligned_factor, "target": aligned_forward}
    # Q03 的 returns[t] 是当期收益；右移已对齐 forward，避免 h=1 多预测一期。
    decay_pair = {
        "factor": aligned_factor,
        "returns": [0.0] + aligned_forward[:-1],
    }
    ic = _call("B13", pair)
    rank_ic = _call("B14", pair)
    research_ic = _call("Q01", pair)
    icir = _call("Q02", pair, window=window)
    decay = _call("Q03", decay_pair, horizons=horizons)
    core_calls = (ic, rank_ic, research_ic, icir, decay)
    if any(call["gate"] != "ok" for call in core_calls):
        return unavailable(
            capability="D-G19",
            intent=INTENT_METRIC_SERIES,
            reason="IC/ICIR/衰减表计算失败",
            trace_id=trace_id,
        )

    methods = ["B13", "B14", "Q01", "Q02", "Q03"]
    price_decay_result: Optional[Dict[str, Any]] = None
    price_decay_gate = "not_provided"
    if prices is not None:
        price_decay = _call("B15", _floats(prices), lookback=lookback, horizons=horizons)
        price_decay_gate = price_decay["gate"]
        if price_decay["gate"] == "ok":
            price_decay_result = price_decay["result"]
            methods = ["B13", "B14", "B15", "Q01", "Q02", "Q03"]
    degraded_reason = None if price_decay_result is not None else "price_history_unavailable"

    parsed_dates = _parse_dates(dates)
    aligned_dates = (
        [parsed_dates[index] for index in indices]
        if len(parsed_dates) == len(factor) and len(parsed_dates) == len(forward)
        else []
    )
    q = quality_for(
        n,
        min_n=MIN_IC_PROFILE,
        span=_span(aligned_dates),
        sources=["market.candles"],
        align_method="paired_complete_case",
        timezone="UTC",
    )
    if degraded_reason is not None:
        q = _degrade(q, degraded_reason)

    ic_result = ic["result"]
    rank_ic_result = rank_ic["result"]
    icir_result = icir["result"]
    decay_result = decay["result"]
    prefix = f"{name} " if name else ""
    answer = (
        f"{prefix}因子 IC={ic_result['ic']}（p={ic_result['p']}），"
        f"RankIC={rank_ic_result['rank_ic']}（p={rank_ic_result['p']}），"
        f"ICIR={icir_result['icir']}（{icir_result['n_periods']} 段，window={window}）；"
        f"Q03 衰减期限 h={decay_result['horizons']}。"
    )
    if price_decay_result is None:
        answer += "价格序列缺失或不足，B15 价格动量衰减降级未输出；"
    else:
        answer += "B15 价格动量重叠/非重叠 IC 衰减已并列输出；"
    answer += f"对齐样本 n={n}。{CAVEAT}。"

    return build(
        capability="D-G19",
        intent=INTENT_METRIC_SERIES,
        answer=answer,
        data={
            "capabilities": {
                "D-G19": {
                    "gate": "degraded" if degraded_reason else "ok",
                    "methods": methods,
                    "ic": ic_result,
                    "rank_ic": rank_ic_result,
                    "research_ic": research_ic["result"],
                    "icir": icir_result,
                    "ic_decay": decay_result,
                    "price_ic_decay": price_decay_result,
                    "price_ic_decay_gate": price_decay_gate,
                }
            },
            "params": {
                "min_n": MIN_IC_PROFILE,
                "window": window,
                "horizons": list(horizons),
                "lookback": lookback,
                "q03_returns_alignment": "zero_prefix_shift_1",
                "as_of": aligned_dates[-1].isoformat() if aligned_dates else None,
            },
            "name": name or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-G20 分位组合 / 单调性检验 ----------------


def quantile_monotonic(
    factor: Sequence[Any],
    forward: Sequence[Any],
    *,
    k: int = 5,
    dates: Optional[Sequence[Any]] = None,
    name: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """分位组统计、严格单调性与分位序号 Spearman 检验；不合成交易收益。"""
    indices, aligned_factor, aligned_forward = _paired_rows(factor, forward)
    n = len(aligned_factor)
    if n < MIN_CONDITIONAL:
        return unavailable(
            capability="D-G20",
            intent=INTENT_METRIC_SERIES,
            reason=f"因子/前瞻收益对齐样本 {n} < {MIN_CONDITIONAL}",
            trace_id=trace_id,
        )

    pair = {"factor": aligned_factor, "target": aligned_forward}
    grouped = _call("B16", pair, k=k)
    monotonic = _call("B11", pair, k=k)
    quantile_test = _call("Q04", pair, k=k)
    if any(call["gate"] != "ok" for call in (grouped, monotonic, quantile_test)):
        return unavailable(
            capability="D-G20",
            intent=INTENT_METRIC_SERIES,
            reason="分位组合/单调性计算失败",
            trace_id=trace_id,
        )

    parsed_dates = _parse_dates(dates)
    aligned_dates = (
        [parsed_dates[index] for index in indices]
        if len(parsed_dates) == len(factor) and len(parsed_dates) == len(forward)
        else []
    )
    q = quality_for(
        n,
        min_n=MIN_CONDITIONAL,
        span=_span(aligned_dates),
        sources=["market.candles"],
        align_method="paired_complete_case",
        timezone="UTC",
    )
    grouped_result = grouped["result"]
    monotonic_result = monotonic["result"]
    quantile_result = quantile_test["result"]
    bottom, top = grouped_result["table"][0], grouped_result["table"][-1]
    prefix = f"{name} " if name else ""
    answer = (
        f"{prefix}因子 {grouped_result['k']} 分位组合：最低组均值 {bottom['mean'] * 100:+.3f}%，"
        f"最高组均值 {top['mean'] * 100:+.3f}%，最高−最低 spread={grouped_result['spread']:+.6f}"
        "（描述性统计，非策略收益）；"
        f"B11 单调性 {monotonic_result['monotonic']}（ρ_bin={monotonic_result['rho_bin']}），"
        f"Q04 Spearman ρ={quantile_result['rho']}（p={quantile_result['p']}）。"
        f"对齐样本 n={n}。{CAVEAT}。"
    )
    return build(
        capability="D-G20",
        intent=INTENT_METRIC_SERIES,
        answer=answer,
        data={
            "capabilities": {
                "D-G20": {
                    "gate": "ok",
                    "methods": ["B11", "B16", "Q04"],
                    "group_stats": grouped_result,
                    "monotonic": monotonic_result,
                    "quantile_test": quantile_result,
                }
            },
            "params": {
                "min_n": MIN_CONDITIONAL,
                "k": grouped_result["k"],
                "as_of": aligned_dates[-1].isoformat() if aligned_dates else None,
            },
            "name": name or None,
        },
        quality_block=q,
        trace_id=trace_id,
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


def _pre_holiday_effect(
    px: Sequence[float],
    price_dates: Sequence[_dt.date],
    holidays: Optional[Sequence[Any]],
    *,
    lookback: int,
    symbol: str,
    trace_id: Optional[str],
) -> Dict[str, Any]:
    """C11 节假日前效应（节假日可由日期轴缺失工作日派生，或显式传入）。"""
    if not price_dates or len(price_dates) < len(px):
        return unavailable(
            capability="D-E04",
            intent=INTENT_EVENT,
            reason="节前效应需要与价格等长的交易日日期轴（用交易日完整的日线派生日历）",
            trace_id=trace_id,
        )
    returns = _returns(px)
    ret_dates = price_dates[1:][-len(returns) :] if returns else []
    params: Dict[str, Any] = {"lookback": max(1, int(lookback))}
    if holidays:
        params["holidays"] = [str(h)[:10] for h in holidays]
    out = _call(
        "C11",
        {"returns": returns, "dates": [d.isoformat() for d in ret_dates]},
        **params,
    )
    if out["gate"] != "ok" or out["result"] is None:
        return unavailable(
            capability="D-E04",
            intent=INTENT_EVENT,
            reason="节前效应计算失败（收益样本或日期轴不足）",
            trace_id=trace_id,
        )
    r = out["result"]
    n_holidays = int(r.get("n_holidays") or 0)
    if n_holidays == 0:
        return unavailable(
            capability="D-E04",
            intent=INTENT_EVENT,
            reason="日期轴内无工作日缺口（7×24 或周度序列），节前效应不适用",
            trace_id=trace_id,
        )
    q = quality_for(
        len(px),
        min_n=MIN_EVENT_STUDY,
        span=_span(price_dates),
        sources=["market.candles"],
        align_method="business_day_gap_calendar",
        timezone="UTC",
    )
    n_pre = int(r["n_pre"])
    if n_pre < EVENT_GATE:
        q = _degrade(q, "holiday_events_lt_30")

    def _pct(value: Optional[float]) -> str:
        return "NA" if value is None else f"{value * 100:.2f}%"

    head = f"{symbol or '标的'} " if symbol else ""
    diff = r["diff"]
    diff_txt = "NA" if diff is None else f"{diff * 100:+.2f} 个百分点"
    t_txt = "NA" if r["t"] is None else f"{r['t']:.2f}"
    p_txt = "NA" if r["p"] is None else f"{r['p']:.3f}"
    source_txt = "显式日历" if r["calendar"] == "explicit" else "日期轴工作日缺口派生"
    gap_txt = (
        f"，另有 {r['excluded_gaps']} 个工作日连续缺口按数据缺口排除" if r["excluded_gaps"] else ""
    )
    answer = (
        f"{head}节前效应：识别节假日 {n_holidays} 个（{source_txt}{gap_txt}），"
        f"节前 {r['lookback']} 个交易日收益均值 {_pct(r['pre_mean'])}，"
        f"非节前 {_pct(r['base_mean'])}，差 {diff_txt}（t={t_txt}，p={p_txt}）；"
        f"节前样本 {n_pre} 天"
        f"{'，<30 天仅作短样本描述，等级降级。' if n_pre < EVENT_GATE else '。'}"
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
                    "methods": ["C11"],
                    "pre_holiday": {
                        "pre_mean": r["pre_mean"],
                        "base_mean": r["base_mean"],
                        "diff": r["diff"],
                        "t": r["t"],
                        "p": r["p"],
                        "n_pre": n_pre,
                        "n_base": r["n_base"],
                        "n_holidays": n_holidays,
                        "lookback": r["lookback"],
                        "calendar": r["calendar"],
                        "excluded_gaps": r["excluded_gaps"],
                        "pre_dates": r["pre_dates"],
                    },
                }
            },
            "params": {
                "min_n": MIN_EVENT_STUDY,
                "event_gate": EVENT_GATE,
                "lookback": r["lookback"],
                "calendar_source": r["calendar"],
                "as_of": price_dates[-1].isoformat() if price_dates else None,
            },
            "symbol": symbol or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


def event_study(
    prices: Sequence[Any],
    *,
    events: Optional[Sequence[Any]] = None,
    dates: Optional[Sequence[Any]] = None,
    k: int = 5,
    event_type: str = "",
    symbol: str = "",
    holidays: Optional[Sequence[Any]] = None,
    pre_holiday: bool = False,
    lookback: int = 1,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """事件研究窗：事件日对齐到价格轴后，用 F19 事件窗收益 + F23 事件后分布 + F21 CAR。

    `pre_holiday=True` 或提供 `holidays` 时走 C11 节前效应分支（节假日可由日期轴
    缺失工作日派生，无需外部日历表）。
    """
    px = _floats(prices)
    if len(px) < MIN_EVENT_STUDY:
        return unavailable(
            capability="D-E04",
            intent=INTENT_EVENT,
            reason=f"价格样本 {len(px)} < {MIN_EVENT_STUDY}（事件研究样本门禁）",
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
    if pre_holiday or holidays:
        return _pre_holiday_effect(
            px,
            price_dates,
            holidays,
            lookback=lookback,
            symbol=symbol,
            trace_id=trace_id,
        )
    if not events:
        return unavailable(
            capability="D-E04",
            intent=INTENT_EVENT,
            reason="缺少事件日期（mm_events 为空或未提供 events）",
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

    kalman_block: Optional[Dict[str, Any]] = None
    kalman_out = _call("I37", {"values": px})
    if kalman_out["gate"] == "ok":
        raw = kalman_out["result"]
        kalman_block = {
            "level": raw["level"],
            "slope": raw["slope"],
            "level_sigma": raw["level_sigma"],
            "slope_se": raw["slope_se"],
            "band": raw["band"],
            "trail": [
                {
                    "date": ds[point["index"]].isoformat() if point["index"] < len(ds) else None,
                    "level": point["level"],
                    "lower": point["lower"],
                    "upper": point["upper"],
                }
                for point in raw["path"]
            ],
        }
    else:
        degraded_reasons.append("kalman_unavailable")

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
    kalman_txt = (
        ""
        if kalman_block is None
        else (
            f"Kalman 局部线性趋势 level={kalman_block['level']}（±1σ {kalman_block['level_sigma']}）、"
            f"slope={kalman_block['slope']}（se {kalman_block['slope_se']}）；"
        )
    )
    answer = (
        f"{note}{head}EMA 排列 {order}（12={ema.get('12')} / 26={ema.get('26')} / 50={ema.get('50')}）；"
        f"对数价格趋势斜率 {slope_txt}；{kalman_txt}{adx_txt}。"
        f"平滑口径 EMA(12/26/50)，斜率窗口 {list(windows)}，n={len(px)}。{CAVEAT}。"
    )

    payload = {
        "capabilities": {
            "D-E15": {
                "gate": "ok",
                "methods": ["I02", "T08"]
                + (["I32"] if adx_block else [])
                + (["I37"] if kalman_block else []),
                "ema": ema,
                "ema_order": order,
                "slope_table": rows,
                "adx": adx_block,
                "kalman": kalman_block,
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


# ---------------- D-J22 PCA / SVD / 因子分析 ----------------


def dimension_reduction(
    series: Mapping[str, Sequence[Any]],
    *,
    k: int = 3,
    dates: Optional[Sequence[Any]] = None,
    name: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """面板降维：相关阵 PCA、载荷、sklearn PCA、SVD 与因子分析并列输出。"""
    if not isinstance(series, Mapping) or not series:
        return unavailable(
            capability="D-J22",
            intent=INTENT_METRIC_SERIES,
            reason="缺少面板序列",
            trace_id=trace_id,
        )
    try:
        components = int(k)
    except (TypeError, ValueError):
        components = 0
    if components < 1:
        return unavailable(
            capability="D-J22",
            intent=INTENT_METRIC_SERIES,
            reason="主成分个数 k 必须 ≥ 1",
            trace_id=trace_id,
        )
    names, panel, rows, indices = _panel_rows(series)
    if len(names) < 2:
        return unavailable(
            capability="D-J22",
            intent=INTENT_METRIC_SERIES,
            reason="面板至少需要 2 个变量",
            trace_id=trace_id,
        )
    n = len(indices)
    if n < MIN_DIMENSION_REDUCTION:
        return unavailable(
            capability="D-J22",
            intent=INTENT_METRIC_SERIES,
            reason=f"面板对齐样本 {n} < {MIN_DIMENSION_REDUCTION}",
            trace_id=trace_id,
        )

    series_payload = {"series": panel}
    matrix_payload = {"X": rows}
    pca_variance = _call("M19", series_payload, k=components)
    pca_loadings = _call("M20", series_payload, k=components)
    sklearn_pca = _call("SC31", matrix_payload, k=components)
    svd = _call("SC32", matrix_payload, k=components)
    factor_analysis = _call("SC33", matrix_payload, k=components)
    calls = (pca_variance, pca_loadings, sklearn_pca, svd, factor_analysis)
    if any(call["gate"] != "ok" for call in calls):
        return unavailable(
            capability="D-J22",
            intent=INTENT_METRIC_SERIES,
            reason="PCA/SVD/因子分析计算失败",
            trace_id=trace_id,
        )

    parsed_dates = _parse_dates(dates)
    aligned_dates = (
        [parsed_dates[index] for index in indices]
        if parsed_dates and indices[-1] < len(parsed_dates)
        else []
    )
    q = quality_for(
        n,
        min_n=MIN_DIMENSION_REDUCTION,
        span=_span(aligned_dates),
        sources=["market.candles", "mm_metrics"],
        align_method="panel_complete_case",
        timezone="UTC",
    )

    variance_result = pca_variance["result"]
    ratio = float(variance_result["ratio"][0])
    cumulative = float(variance_result["cum_ratio"][-1])
    prefix = f"{name} " if name else ""
    answer = (
        f"{prefix}面板 {len(names)} 个变量 / {n} 个对齐样本："
        f"M19 相关阵 PCA 前 {variance_result['k']} 个主成分解释方差占比 "
        f"PC1={ratio:.4f}、累计={cumulative:.4f}；"
        "M20 载荷与 SC31 PCA、SC32 SVD、SC33 因子分析并列输出。"
        f"降维结果仅描述数据结构，不构成交易信号。{CAVEAT}。"
    )
    return build(
        capability="D-J22",
        intent=INTENT_METRIC_SERIES,
        answer=answer,
        data={
            "capabilities": {
                "D-J22": {
                    "gate": "ok",
                    "methods": ["M19", "M20", "SC31", "SC32", "SC33"],
                    "variables": names,
                    "n_features": len(names),
                    "pca_variance": variance_result,
                    "pca_loadings": pca_loadings["result"],
                    "sklearn_pca": sklearn_pca["result"],
                    "svd": svd["result"],
                    "factor_analysis": factor_analysis["result"],
                }
            },
            "params": {
                "min_n": MIN_DIMENSION_REDUCTION,
                "k": variance_result["k"],
                "as_of": aligned_dates[-1].isoformat() if aligned_dates else None,
            },
            "name": name or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-J24 相关网络与社区发现 ----------------


def correlation_network(
    series: Mapping[str, Sequence[Any]],
    *,
    k: int = 3,
    threshold: float = 0.5,
    dates: Optional[Sequence[Any]] = None,
    name: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """同期相关网络：M05 相关矩阵 → 阈值邻接 → SC71 中心性 + SC72 社区 + M21 层次聚类。"""
    if not isinstance(series, Mapping) or not series:
        return unavailable(
            capability="D-J24",
            intent=INTENT_METRIC_SERIES,
            reason="缺少面板序列",
            trace_id=trace_id,
        )
    try:
        clusters = int(k)
        cut = float(threshold)
    except (TypeError, ValueError):
        return unavailable(
            capability="D-J24",
            intent=INTENT_METRIC_SERIES,
            reason="聚类组数 k 与相关阈值 threshold 必须为数值",
            trace_id=trace_id,
        )
    if clusters < 1:
        return unavailable(
            capability="D-J24",
            intent=INTENT_METRIC_SERIES,
            reason="聚类组数 k 必须 ≥ 1",
            trace_id=trace_id,
        )
    if not 0.0 <= cut <= 1.0:
        return unavailable(
            capability="D-J24",
            intent=INTENT_METRIC_SERIES,
            reason="相关阈值 threshold 必须位于 [0, 1]",
            trace_id=trace_id,
        )
    names, panel, _, indices = _panel_rows(series)
    if len(names) < 2:
        return unavailable(
            capability="D-J24",
            intent=INTENT_METRIC_SERIES,
            reason="相关网络至少需要 2 个变量",
            trace_id=trace_id,
        )
    n = len(indices)
    if n < MIN_CORR:
        return unavailable(
            capability="D-J24",
            intent=INTENT_METRIC_SERIES,
            reason=f"面板对齐样本 {n} < {MIN_CORR}",
            trace_id=trace_id,
        )

    payload = {"series": panel}
    matrix_call = _call("M05", payload)
    clusters_call = _call("M21", payload, k=clusters)
    if matrix_call["gate"] != "ok" or clusters_call["gate"] != "ok":
        return unavailable(
            capability="D-J24",
            intent=INTENT_METRIC_SERIES,
            reason="相关矩阵或层次聚类计算失败",
            trace_id=trace_id,
        )

    matrix_result = matrix_call["result"]
    matrix = matrix_result["matrix"]
    order = list(matrix_result["names"])
    adjacency = [
        [0.0 if left == right or abs(float(matrix[left][right])) < cut else 1.0 for right in order]
        for left in order
    ]
    graph_payload = {"adj": adjacency}
    centrality_call = _call_soft("SC71", graph_payload)
    communities_call = _call_soft("SC72", graph_payload)
    allowed = {"ok", "degraded"}
    if centrality_call["gate"] not in allowed or communities_call["gate"] not in allowed:
        return unavailable(
            capability="D-J24",
            intent=INTENT_METRIC_SERIES,
            reason="网络中心性或社区发现计算失败",
            trace_id=trace_id,
        )

    edges = []
    for left_index, left in enumerate(order):
        for right_index in range(left_index + 1, len(order)):
            if adjacency[left_index][right_index] > 0.0:
                right = order[right_index]
                edges.append({"source": left, "target": right, "rho": matrix[left][right]})

    parsed_dates = _parse_dates(dates)
    aligned_dates = (
        [parsed_dates[index] for index in indices]
        if parsed_dates and indices[-1] < len(parsed_dates)
        else []
    )
    q = quality_for(
        n,
        min_n=MIN_CORR,
        span=_span(aligned_dates),
        sources=["market.candles", "mm_metrics"],
        align_method="panel_complete_case",
        timezone="UTC",
    )
    if "degraded" in (centrality_call["gate"], communities_call["gate"]):
        q = _degrade(q, "网络节点数低于中心性/社区发现方法门禁，网络指标仅作描述")
        degraded_note = "网络节点数低于方法门禁，中心性/社区指标降级为描述。"
    else:
        degraded_note = ""

    centrality_result = centrality_call["result"]
    communities_result = communities_call["result"]
    cluster_result = clusters_call["result"]
    prefix = f"{name} " if name else ""
    answer = (
        f"{prefix}同期相关网络：{len(order)} 个变量、|ρ|≥{cut:g} 下 "
        f"{centrality_result['n_edges']} 条边，"
        f"Louvain 识别 {communities_result['n_communities']} 个社区"
        f"（模块度 Q={communities_result['modularity']}），"
        f"介数中心性最高节点 #{centrality_result['top_node']}；"
        f"M21 层次聚类 {cluster_result['n_clusters']} 组。"
        f"{degraded_note}"
        f"网络结构仅描述同期相关关系，不构成交易信号。{CAVEAT}。"
    )
    return build(
        capability="D-J24",
        intent=INTENT_METRIC_SERIES,
        answer=answer,
        data={
            "capabilities": {
                "D-J24": {
                    "gate": "ok",
                    "methods": ["M05", "M21", "SC71", "SC72"],
                    "nodes": order,
                    "edges": edges,
                    "n_edges": centrality_result["n_edges"],
                    "threshold": cut,
                    "correlation": matrix_result,
                    "centrality": centrality_result,
                    "communities": communities_result,
                    "hierarchical": cluster_result,
                }
            },
            "params": {
                "min_n": MIN_CORR,
                "k": cluster_result["k"],
                "threshold": cut,
                "as_of": aligned_dates[-1].isoformat() if aligned_dates else None,
            },
            "name": name or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-G14 EWMA 波动 / 协方差 ----------------


def ewma_risk(
    series: Mapping[str, Sequence[Any]],
    *,
    lam: float = 0.94,
    init_window: int = 20,
    periods: int = 365,
    dates: Optional[Sequence[Any]] = None,
    name: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """EWMA 风险：P07 组合 EWMA 协方差（多资产）+ T19 逐资产 EWMA 波动序列。"""
    if not isinstance(series, Mapping) or not series:
        return unavailable(
            capability="D-G14",
            intent=INTENT_METRIC_SERIES,
            reason="缺少收益面板序列",
            trace_id=trace_id,
        )
    try:
        decay = float(lam)
        init = int(init_window)
        horizon = int(periods)
    except (TypeError, ValueError):
        return unavailable(
            capability="D-G14",
            intent=INTENT_METRIC_SERIES,
            reason="衰减系数 lam、初始化窗口 init_window 与年化周期 periods 必须为数值",
            trace_id=trace_id,
        )
    if not 0.0 < decay < 1.0:
        return unavailable(
            capability="D-G14",
            intent=INTENT_METRIC_SERIES,
            reason="衰减系数 lam 必须位于 (0, 1)",
            trace_id=trace_id,
        )
    if horizon <= 0:
        return unavailable(
            capability="D-G14",
            intent=INTENT_METRIC_SERIES,
            reason="年化周期 periods 必须为正整数",
            trace_id=trace_id,
        )
    if init < 2:
        return unavailable(
            capability="D-G14",
            intent=INTENT_METRIC_SERIES,
            reason="初始化窗口 init_window 必须 ≥ 2",
            trace_id=trace_id,
        )

    names, panel, _, indices = _panel_rows(series)
    n = len(indices)
    if n < MIN_EWMA_RISK:
        return unavailable(
            capability="D-G14",
            intent=INTENT_METRIC_SERIES,
            reason=f"面板对齐样本 {n} < {MIN_EWMA_RISK}",
            trace_id=trace_id,
        )

    covariance: Optional[Dict[str, Any]] = None
    if len(names) >= 2:
        cov_call = _call("P07", {"series": panel}, lam=decay, init_window=init, periods=horizon)
        if cov_call["gate"] != "ok":
            return unavailable(
                capability="D-G14",
                intent=INTENT_METRIC_SERIES,
                reason="EWMA 组合协方差计算失败",
                trace_id=trace_id,
            )
        covariance = cov_call["result"]

    volatility: Dict[str, Any] = {}
    for label in names:
        vol_call = _call("T19", {"series": panel[label]}, lam=decay)
        if vol_call["gate"] != "ok":
            return unavailable(
                capability="D-G14",
                intent=INTENT_METRIC_SERIES,
                reason=f"{label} 的 EWMA 波动序列计算失败",
                trace_id=trace_id,
            )
        volatility[label] = vol_call["result"]

    parsed_dates = _parse_dates(dates)
    aligned_dates = (
        [parsed_dates[index] for index in indices]
        if parsed_dates and indices[-1] < len(parsed_dates)
        else []
    )
    q = quality_for(
        n,
        min_n=MIN_EWMA_RISK,
        span=_span(aligned_dates),
        sources=["market.candles"] + (["mm_metrics"] if covariance is not None else []),
        align_method="panel_complete_case",
        timezone="UTC",
    )

    prefix = f"{name} " if name else ""
    if covariance is not None:
        methods = ["P07", "T19"]
        annualized = covariance["vol"]
        vol_text = "、".join(f"{key}={value:.4f}" for key, value in annualized.items())
        answer = (
            f"{prefix}EWMA(λ={decay:g}) 风险：{len(names)} 个资产、对齐样本 {n}，"
            f"P07 组合 EWMA 协方差 {len(names)}×{len(names)}，"
            f"年化波动 {vol_text}；T19 逐资产波动序列并列输出。"
            f"历史统计仅描述样本内风险结构，不构成交易信号。{CAVEAT}。"
        )
    else:
        methods = ["T19"]
        answer = (
            f"{prefix}EWMA(λ={decay:g}) 波动：单资产 {names[0]}、对齐样本 {n}，"
            f"T19 输出逐日波动序列；单资产无组合协方差。"
            f"历史统计仅描述样本内风险结构，不构成交易信号。{CAVEAT}。"
        )

    block: Dict[str, Any] = {
        "gate": "ok",
        "methods": methods,
        "lam": covariance["lam"] if covariance is not None else volatility[names[0]]["lam"],
        "assets": names,
        "volatility_series": volatility,
    }
    if covariance is not None:
        block["covariance"] = covariance
    return build(
        capability="D-G14",
        intent=INTENT_METRIC_SERIES,
        answer=answer,
        data={
            "capabilities": {"D-G14": block},
            "params": {
                "min_n": MIN_EWMA_RISK,
                "lam": decay,
                "init_window": init,
                "periods": horizon,
                "as_of": aligned_dates[-1].isoformat() if aligned_dates else None,
            },
            "name": name or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-A01 历史序列 ----------------


def _bucket_key(day: _dt.date, freq: str) -> Tuple[int, ...]:
    if freq == "weekly":
        iso = day.isocalendar()
        return (iso[0], iso[1])
    if freq == "monthly":
        return (day.year, day.month)
    return (day.toordinal(),)


def history_series(
    values: Sequence[Any],
    *,
    dates: Sequence[Any],
    freq: str = "daily",
    unit: Optional[str] = None,
    name: str = "",
    symbol: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """单序列区间取点 + 日/周/月降采样；当前历史分位复用方法层 S25。"""
    px = _floats(values)
    if len(px) != len(values) or not all(math.isfinite(value) for value in px):
        return unavailable(
            capability="D-A01",
            intent=INTENT_METRIC_SERIES,
            reason="序列包含无效值",
            trace_id=trace_id,
        )
    ds = _parse_dates(dates)
    if len(ds) != len(values) or not ds:
        return unavailable(
            capability="D-A01",
            intent=INTENT_METRIC_SERIES,
            reason="历史序列需要与数值等长的有效日期轴",
            trace_id=trace_id,
        )
    if len(px) < MIN_SERIES:
        return unavailable(
            capability="D-A01",
            intent=INTENT_METRIC_SERIES,
            reason=f"有效样本 {len(px)} < {MIN_SERIES}",
            trace_id=trace_id,
        )
    normalized = {
        "daily": "daily",
        "day": "daily",
        "d": "daily",
        "weekly": "weekly",
        "week": "weekly",
        "w": "weekly",
        "monthly": "monthly",
        "month": "monthly",
        "m": "monthly",
    }.get(str(freq).strip().lower())
    if normalized is None:
        return unavailable(
            capability="D-A01",
            intent=INTENT_METRIC_SERIES,
            reason="freq 仅支持 daily/weekly/monthly",
            trace_id=trace_id,
        )

    percentile = _call("S25", px)
    if percentile["gate"] != "ok":
        return unavailable(
            capability="D-A01",
            intent=INTENT_METRIC_SERIES,
            reason="历史分位计算失败",
            trace_id=trace_id,
        )

    order = sorted(range(len(px)), key=lambda i: (ds[i], i))
    buckets: Dict[Tuple[int, ...], Tuple[_dt.date, float]] = {}
    for index in order:  # 升序后写覆盖 = 每个区间取最后一个观测
        buckets[_bucket_key(ds[index], normalized)] = (ds[index], px[index])
    points = [
        {"date": day.isoformat(), "value": round(value, 6)}
        for _, (day, value) in sorted(buckets.items(), key=lambda item: item[1][0])
    ]

    unique_days = len(set(ds))
    span_days = (max(ds) - min(ds)).days + 1
    missing_rate = round(1.0 - unique_days / span_days, 4) if span_days else None
    span = _span(sorted(ds))
    q = quality_for(
        len(px),
        min_n=MIN_SERIES,
        span=span,
        sources=["datacenter.series"],
        missing_rate=missing_rate,
        align_method=f"series_last_per_{normalized}",
        timezone="UTC",
    )
    sparse = missing_rate is not None and missing_rate > 0.2
    if sparse and q["status"] != STATUS_EMPTY:
        q = _degrade(q, "sparse_series")

    stats = percentile["result"]
    head = f"{symbol} " if symbol else ""
    label = name or "序列"
    unit_text = f" {unit}" if unit else ""
    last_value = points[-1]["value"]
    note = (
        f"；样本缺失率 {missing_rate * 100:.1f}%，仅作描述"
        if sparse and missing_rate is not None
        else ""
    )
    answer = (
        f"{head}{label} 历史序列 {points[0]['date']}~{points[-1]['date']} 共 {len(px)} 个观测，"
        f"{normalized} 降采样后 {len(points)} 点，当前 {last_value:.6g}{unit_text}，"
        f"处于历史 {stats['percentile']:.2f}% 分位（n={stats['n']}）{note}。{CAVEAT}。"
    )
    return build(
        capability="D-A01",
        intent=INTENT_METRIC_SERIES,
        answer=answer,
        data={
            "capabilities": {
                "D-A01": {
                    "gate": "ok" if q["status"] == STATUS_GOOD else "partial",
                    "methods": ["S25"],
                    "points": points,
                    "span": span,
                    "unit": unit,
                    "freq": normalized,
                    "percentile": stats,
                    "missing_rate": missing_rate,
                }
            },
            "params": {"min_n": MIN_SERIES, "freq": normalized, "point_count": len(points)},
            "name": name or None,
            "symbol": symbol or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-A02 变化率 ----------------


def change_rate(
    values: Sequence[Any],
    *,
    window: int = 1,
    dates: Optional[Sequence[Any]] = None,
    unit: Optional[str] = None,
    name: str = "",
    symbol: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """区间变化量与变化率，复用方法层 S15/S16。"""
    px = _floats(values)
    if len(px) != len(values) or not all(math.isfinite(value) for value in px):
        return unavailable(
            capability="D-A02",
            intent=INTENT_METRIC_SERIES,
            reason="序列包含无效值",
            trace_id=trace_id,
        )
    try:
        k = int(window)
    except (TypeError, ValueError):
        return unavailable(
            capability="D-A02",
            intent=INTENT_METRIC_SERIES,
            reason="window 参数无效",
            trace_id=trace_id,
        )
    if k < 1 or len(px) <= k:
        return unavailable(
            capability="D-A02",
            intent=INTENT_METRIC_SERIES,
            reason=f"有效样本 {len(px)} 不足以覆盖 window={k} 的区间变化",
            trace_id=trace_id,
        )
    ds = _parse_dates(dates)
    if dates and len(ds) != len(px):
        return unavailable(
            capability="D-A02",
            intent=INTENT_METRIC_SERIES,
            reason="日期轴与数值长度不一致或日期无效",
            trace_id=trace_id,
        )

    diff = _call("S15", px, k=k)
    pct = _call("S16", px, k=k)
    if diff["gate"] != "ok" or pct["gate"] != "ok":
        return unavailable(
            capability="D-A02",
            intent=INTENT_METRIC_SERIES,
            reason="区间变化计算失败",
            trace_id=trace_id,
        )
    diff_result = diff["result"]
    pct_result = pct["result"]

    q = quality_for(
        len(px),
        min_n=MIN_CHANGE,
        span=_span(ds) if ds else None,
        sources=["datacenter.series"],
        align_method="window_endpoints",
        timezone="UTC",
    )
    pct_missing = pct_result.get("pct") is None
    if pct_missing and q["status"] != STATUS_EMPTY:
        q = _degrade(q, "change_pct_unavailable")

    head = f"{symbol} " if symbol else ""
    label = name or "序列"
    unit_text = f" {unit}" if unit else ""
    diff_text = (
        f"{diff_result['diff']:+.6g}{unit_text}"
        if diff_result.get("diff") is not None
        else "不可用"
    )
    if pct_missing:
        pct_text = f"变化率不可用（基期值为 0，样本 n={len(px)}）"
    else:
        pct_text = f"{pct_result['pct'] * 100.0:+.2f}%"
    answer = f"{head}{label} 最近 {k} 期变化 {diff_text}，变化率 {pct_text}。{CAVEAT}。"
    return build(
        capability="D-A02",
        intent=INTENT_METRIC_SERIES,
        answer=answer,
        data={
            "capabilities": {
                "D-A02": {
                    "gate": "ok" if q["status"] == STATUS_GOOD else "partial",
                    "methods": ["S15", "S16"],
                    "change": diff_result.get("diff"),
                    "change_pct": pct_result.get("pct"),
                    "window": k,
                    "n": diff_result.get("n"),
                }
            },
            "params": {"min_n": MIN_CHANGE, "window": k},
            "name": name or None,
            "symbol": symbol or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-A03 CAGR ----------------


def cagr(
    values: Sequence[Any],
    *,
    dates: Optional[Sequence[Any]] = None,
    name: str = "",
    symbol: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """首末值年化复合增长率，复用方法层 S19。"""
    px = _floats(values)
    if len(px) != len(values) or not all(math.isfinite(value) for value in px):
        return unavailable(
            capability="D-A03",
            intent=INTENT_METRIC_SERIES,
            reason="序列包含无效值",
            trace_id=trace_id,
        )
    if len(px) < MIN_CAGR:
        return unavailable(
            capability="D-A03",
            intent=INTENT_METRIC_SERIES,
            reason=f"有效样本 {len(px)} < {MIN_CAGR}",
            trace_id=trace_id,
        )
    ds = _parse_dates(dates)
    if dates and len(ds) != len(px):
        return unavailable(
            capability="D-A03",
            intent=INTENT_METRIC_SERIES,
            reason="日期轴与数值长度不一致或日期无效",
            trace_id=trace_id,
        )
    days: Optional[float] = None
    if ds:
        days = float((ds[-1] - ds[0]).days)
        if days <= 0:
            return unavailable(
                capability="D-A03",
                intent=INTENT_METRIC_SERIES,
                reason="首末日期跨度须为正",
                trace_id=trace_id,
            )

    params: Dict[str, Any] = {"days": days} if days is not None else {}
    result_call = _call("S19", px, **params)
    if result_call["gate"] != "ok":
        return unavailable(
            capability="D-A03",
            intent=INTENT_METRIC_SERIES,
            reason="CAGR 计算失败",
            trace_id=trace_id,
        )
    result = result_call["result"]
    if result.get("cagr") is None or result.get("years") is None:
        return unavailable(
            capability="D-A03",
            intent=INTENT_METRIC_SERIES,
            reason="CAGR 要求起点与终点均为正数且跨度为正",
            trace_id=trace_id,
        )

    q = quality_for(
        len(px),
        min_n=MIN_CAGR,
        span=_span(ds) if ds else None,
        sources=["datacenter.series"],
        align_method="first_last",
        timezone="UTC",
    )
    short_span = result["years"] < 1.0
    if short_span:
        q = _degrade(q, "short_span")

    head = f"{symbol} " if symbol else ""
    label = name or "序列"
    note = "；跨度不足 1 年，年化结果仅供参考" if short_span else ""
    answer = (
        f"{head}{label} 首末值 {px[0]:.6g} → {px[-1]:.6g}，"
        f"跨度 {result['years']:.2f} 年，CAGR {result['cagr'] * 100.0:+.2f}%{note}。{CAVEAT}。"
    )
    return build(
        capability="D-A03",
        intent=INTENT_METRIC_SERIES,
        answer=answer,
        data={
            "capabilities": {
                "D-A03": {
                    "gate": "ok" if q["status"] == STATUS_GOOD else "partial",
                    "methods": ["S19"],
                    "cagr": result.get("cagr"),
                    "years": result.get("years"),
                    "n": result.get("n"),
                }
            },
            "params": {"min_n": MIN_CAGR, "days": days},
            "name": name or None,
            "symbol": symbol or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-A04 历史分位 ----------------


def percentile_rank(
    values: Sequence[Any],
    *,
    lookback: Optional[int] = None,
    dates: Optional[Sequence[Any]] = None,
    unit: Optional[str] = None,
    name: str = "",
    symbol: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """末值在最近 lookback 期历史中的分位，复用方法层 S25。"""
    px = _floats(values)
    if len(px) != len(values) or not all(math.isfinite(value) for value in px):
        return unavailable(
            capability="D-A04",
            intent=INTENT_PERCENTILE,
            reason="序列包含无效值",
            trace_id=trace_id,
        )
    ds = _parse_dates(dates)
    if dates and len(ds) != len(px):
        return unavailable(
            capability="D-A04",
            intent=INTENT_PERCENTILE,
            reason="日期轴与数值长度不一致或日期无效",
            trace_id=trace_id,
        )
    if lookback is None:
        k = len(px)
    else:
        try:
            k = int(lookback)
        except (TypeError, ValueError):
            return unavailable(
                capability="D-A04",
                intent=INTENT_PERCENTILE,
                reason="lookback 参数无效",
                trace_id=trace_id,
            )
        if k < MIN_PERCENTILE:
            return unavailable(
                capability="D-A04",
                intent=INTENT_PERCENTILE,
                reason=f"lookback {k} < {MIN_PERCENTILE}，历史分位无统计意义",
                trace_id=trace_id,
            )

    window = px[-k:]
    if len(window) < MIN_PERCENTILE:
        return unavailable(
            capability="D-A04",
            intent=INTENT_PERCENTILE,
            reason=f"有效样本 {len(window)} < {MIN_PERCENTILE}",
            trace_id=trace_id,
        )
    window_dates = ds[-len(window) :] if ds else []

    result_call = _call("S25", window)
    if result_call["gate"] != "ok":
        return unavailable(
            capability="D-A04",
            intent=INTENT_PERCENTILE,
            reason="历史分位计算失败",
            trace_id=trace_id,
        )
    result = result_call["result"]

    q = quality_for(
        len(window),
        min_n=MIN_PERCENTILE,
        span=_span(window_dates) if window_dates else None,
        sources=["datacenter.series"],
        align_method="trailing_sample",
        timezone="UTC",
    )
    truncated = k > len(px)
    short_lookback = len(window) < MIN_PERCENTILE_LOOKBACK
    reasons = []
    if truncated:
        reasons.append("lookback_truncated")
    if short_lookback:
        reasons.append("short_lookback")
    if reasons:
        q = _degrade(q, ",".join(reasons))

    head = f"{symbol} " if symbol else ""
    label = name or "序列"
    unit_text = f" {unit}" if unit else ""
    notes = []
    if truncated:
        notes.append(f"可用历史仅 {len(window)} 期，不足 lookback={k}")
    if short_lookback:
        notes.append("样本较短，分位精度有限")
    note = f"；{'；'.join(notes)}" if notes else ""
    answer = (
        f"{head}{label} 末值 {result['value']:.6g}{unit_text} 处于最近 {len(window)} 期历史"
        f" {result['percentile']:.2f}% 分位（n={result['n']}）{note}。{CAVEAT}。"
    )
    return build(
        capability="D-A04",
        intent=INTENT_PERCENTILE,
        answer=answer,
        data={
            "capabilities": {
                "D-A04": {
                    "gate": "ok" if q["status"] == STATUS_GOOD else "partial",
                    "methods": ["S25"],
                    "percentile": result.get("percentile"),
                    "value": result.get("value"),
                    "lookback": len(window),
                    "sample_n": result.get("n"),
                }
            },
            "params": {"min_n": MIN_PERCENTILE, "lookback": k},
            "name": name or None,
            "symbol": symbol or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-A06 年化波动率 ----------------


def annualized_volatility(
    values: Sequence[Any],
    *,
    window: Optional[int] = None,
    dates: Optional[Sequence[Any]] = None,
    unit: Optional[str] = None,
    name: str = "",
    symbol: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """日简单收益标准差 × √365，复用方法层 F05。"""
    px = _floats(values)
    if len(px) != len(values) or not all(math.isfinite(value) for value in px):
        return unavailable(
            capability="D-A06",
            intent=INTENT_METRIC_SERIES,
            reason="序列包含无效值",
            trace_id=trace_id,
        )
    ds = _parse_dates(dates)
    if dates and len(ds) != len(px):
        return unavailable(
            capability="D-A06",
            intent=INTENT_METRIC_SERIES,
            reason="日期轴与数值长度不一致或日期无效",
            trace_id=trace_id,
        )
    if window is None:
        k = len(px)
    else:
        try:
            k = int(window)
        except (TypeError, ValueError):
            return unavailable(
                capability="D-A06",
                intent=INTENT_METRIC_SERIES,
                reason="window 参数无效",
                trace_id=trace_id,
            )
        if k < MIN_PERCENTILE:
            return unavailable(
                capability="D-A06",
                intent=INTENT_METRIC_SERIES,
                reason=f"window {k} < {MIN_PERCENTILE}，年化波动率无统计意义",
                trace_id=trace_id,
            )

    sample = px[-k:]
    if len(sample) < MIN_PERCENTILE:
        return unavailable(
            capability="D-A06",
            intent=INTENT_METRIC_SERIES,
            reason=f"有效样本 {len(sample)} < {MIN_PERCENTILE}",
            trace_id=trace_id,
        )
    sample_dates = ds[-len(sample) :] if ds else []

    result_call = _call("F05", sample)
    if result_call["gate"] != "ok":
        return unavailable(
            capability="D-A06",
            intent=INTENT_METRIC_SERIES,
            reason="年化波动率计算失败",
            trace_id=trace_id,
        )
    result = result_call["result"]

    q = quality_for(
        len(sample),
        min_n=MIN_PERCENTILE,
        span=_span(sample_dates) if sample_dates else None,
        sources=["datacenter.series"],
        align_method="trailing_sample",
        timezone="UTC",
    )
    short_window = len(sample) < MIN_VOL_WINDOW
    if short_window:
        q = _degrade(q, "short_window")

    head = f"{symbol} " if symbol else ""
    label = name or "序列"
    note = "；样本较短，年化波动率不稳定" if short_window else ""
    answer = (
        f"{head}{label} 最近 {len(sample)} 期日收益年化波动率 {result['vol'] * 100:.2f}%"
        f"（√365 年化，n={result['n']}，均值日收益 {result['mean_ret'] * 100:.4f}%）{note}。{CAVEAT}。"
    )
    return build(
        capability="D-A06",
        intent=INTENT_METRIC_SERIES,
        answer=answer,
        data={
            "capabilities": {
                "D-A06": {
                    "gate": "partial" if short_window else "ok",
                    "methods": ["F05"],
                    "volatility": result.get("vol"),
                    "mean_ret": result.get("mean_ret"),
                    "window": len(sample),
                    "sample_n": result.get("n"),
                }
            },
            "params": {"min_n": MIN_PERCENTILE, "window": k, "ann_factor": 365},
            "name": name or None,
            "symbol": symbol or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-A08 同比 ----------------


def yoy_change(
    values: Sequence[Any],
    *,
    period: int = 12,
    dates: Optional[Sequence[Any]] = None,
    unit: Optional[str] = None,
    name: str = "",
    symbol: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """与 period 期前比较的同比，复用方法层 S16。"""
    px = _floats(values)
    if len(px) != len(values) or not all(math.isfinite(value) for value in px):
        return unavailable(
            capability="D-A08",
            intent=INTENT_METRIC_SERIES,
            reason="序列包含无效值",
            trace_id=trace_id,
        )
    ds = _parse_dates(dates)
    if dates and len(ds) != len(px):
        return unavailable(
            capability="D-A08",
            intent=INTENT_METRIC_SERIES,
            reason="日期轴与数值长度不一致或日期无效",
            trace_id=trace_id,
        )
    try:
        k = int(period)
    except (TypeError, ValueError):
        return unavailable(
            capability="D-A08",
            intent=INTENT_METRIC_SERIES,
            reason="period 参数无效",
            trace_id=trace_id,
        )
    if k < 1:
        return unavailable(
            capability="D-A08",
            intent=INTENT_METRIC_SERIES,
            reason=f"period {k} < 1，同比无统计意义",
            trace_id=trace_id,
        )
    if len(px) <= k:
        return unavailable(
            capability="D-A08",
            intent=INTENT_METRIC_SERIES,
            reason=f"有效样本 {len(px)} 不足以覆盖 period={k}",
            trace_id=trace_id,
        )

    result_call = _call("S16", px, k=k)
    if result_call["gate"] != "ok":
        return unavailable(
            capability="D-A08",
            intent=INTENT_METRIC_SERIES,
            reason="同比计算失败",
            trace_id=trace_id,
        )
    result = result_call["result"]
    span = _span([ds[-1 - k], ds[-1]]) if ds else None
    base_ts = span[0] if span else None

    q = quality_for(
        len(px),
        min_n=MIN_YOY_SAMPLE,
        span=span,
        sources=["datacenter.series"],
        align_method="period_offset",
        timezone="UTC",
    )
    yoy = result.get("pct")
    reasons = []
    if yoy is None:
        reasons.append("yoy_unavailable")
    elif len(px) < 2 * k + 1:
        reasons.append("short_history")
    if reasons:
        q = _degrade(q, ",".join(reasons))

    head = f"{symbol} " if symbol else ""
    label = name or "序列"
    unit_text = f" {unit}" if unit else ""
    base_text = f"（基期 {base_ts}）" if base_ts else f"（基期前 {k} 期）"
    if yoy is None:
        body = (
            f"{head}{label} 最新读数 {px[-1]:.6g}{unit_text} 基期值为 0，"
            f"同比不可计算（降级：基期不足）{base_text}"
        )
    else:
        body = (
            f"{head}{label} 最新读数 {px[-1]:.6g}{unit_text} 较前 {k} 期"
            f"同比 {yoy * 100:.2f}%{base_text}"
        )
    note = "；历史长度不足 2 个完整周期，同比稳定性有限" if "short_history" in reasons else ""
    answer = f"{body}{note}。{CAVEAT}。"
    return build(
        capability="D-A08",
        intent=INTENT_METRIC_SERIES,
        answer=answer,
        data={
            "capabilities": {
                "D-A08": {
                    "gate": "partial" if q["status"] == STATUS_PARTIAL else "ok",
                    "methods": ["S16"],
                    "yoy": yoy,
                    "base_ts": base_ts,
                    "period": k,
                    "sample_n": result.get("n"),
                }
            },
            "params": {"min_n": MIN_YOY_SAMPLE, "period": k},
            "name": name or None,
            "symbol": symbol or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-A09 环比 ----------------


def mom_change(
    values: Sequence[Any],
    *,
    dates: Optional[Sequence[Any]] = None,
    unit: Optional[str] = None,
    name: str = "",
    symbol: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """与上一期比较的环比，复用方法层 S16（k=1）。"""
    px = _floats(values)
    if len(px) != len(values) or not all(math.isfinite(value) for value in px):
        return unavailable(
            capability="D-A09",
            intent=INTENT_METRIC_SERIES,
            reason="序列包含无效值",
            trace_id=trace_id,
        )
    ds = _parse_dates(dates)
    if dates and len(ds) != len(px):
        return unavailable(
            capability="D-A09",
            intent=INTENT_METRIC_SERIES,
            reason="日期轴与数值长度不一致或日期无效",
            trace_id=trace_id,
        )
    if len(px) < MIN_MOM_SAMPLE:
        return unavailable(
            capability="D-A09",
            intent=INTENT_METRIC_SERIES,
            reason=f"有效样本 {len(px)} < {MIN_MOM_SAMPLE}",
            trace_id=trace_id,
        )

    result_call = _call("S16", px, k=1)
    if result_call["gate"] != "ok":
        return unavailable(
            capability="D-A09",
            intent=INTENT_METRIC_SERIES,
            reason="环比计算失败",
            trace_id=trace_id,
        )
    result = result_call["result"]
    span = _span([ds[-2], ds[-1]]) if ds else None
    base_ts = span[0] if span else None

    q = quality_for(
        len(px),
        min_n=MIN_MOM_SAMPLE,
        span=span,
        sources=["datacenter.series"],
        align_method="period_offset",
        timezone="UTC",
    )
    mom = result.get("pct")
    if mom is None:
        q = _degrade(q, "mom_unavailable")

    head = f"{symbol} " if symbol else ""
    label = name or "序列"
    unit_text = f" {unit}" if unit else ""
    base_text = f"（基期 {base_ts}）" if base_ts else "（基期上一期）"
    if mom is None:
        body = (
            f"{head}{label} 最新读数 {px[-1]:.6g}{unit_text} 基期值为 0，"
            f"环比不可计算（降级：基期不足）{base_text}"
        )
    else:
        body = f"{head}{label} 最新读数 {px[-1]:.6g}{unit_text} 较上一期环比 {mom * 100:.2f}%{base_text}"
    answer = f"{body}。{CAVEAT}。"
    return build(
        capability="D-A09",
        intent=INTENT_METRIC_SERIES,
        answer=answer,
        data={
            "capabilities": {
                "D-A09": {
                    "gate": "partial" if q["status"] == STATUS_PARTIAL else "ok",
                    "methods": ["S16"],
                    "mom": mom,
                    "base_ts": base_ts,
                    "sample_n": result.get("n"),
                }
            },
            "params": {"min_n": MIN_MOM_SAMPLE, "period": 1},
            "name": name or None,
            "symbol": symbol or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-A10 实际利率 ----------------


def real_rate(
    nominal: Sequence[Any],
    cpi: Sequence[Any],
    *,
    period: int = 12,
    dates: Optional[Sequence[Any]] = None,
    unit: str = "%",
    name: str = "实际利率",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """名义利率 − CPI 同比通胀：通胀唯一由方法层 S16 执行，能力层只做差值组合。"""
    nom = _floats(nominal)
    idx = _floats(cpi)
    if (
        len(nom) != len(nominal)
        or len(idx) != len(cpi)
        or not all(math.isfinite(value) for value in nom + idx)
    ):
        return unavailable(
            capability="D-A10",
            intent=INTENT_METRIC_DERIVED,
            reason="名义利率或 CPI 包含无效值",
            trace_id=trace_id,
        )
    if len(nom) != len(idx):
        return unavailable(
            capability="D-A10",
            intent=INTENT_METRIC_DERIVED,
            reason="名义利率与 CPI 长度不一致",
            trace_id=trace_id,
        )
    try:
        k = int(period)
    except (TypeError, ValueError):
        return unavailable(
            capability="D-A10",
            intent=INTENT_METRIC_DERIVED,
            reason="period 参数无效",
            trace_id=trace_id,
        )
    if k < 1:
        return unavailable(
            capability="D-A10",
            intent=INTENT_METRIC_DERIVED,
            reason=f"period {k} < 1，同比通胀无统计意义",
            trace_id=trace_id,
        )
    if len(nom) <= k:
        return unavailable(
            capability="D-A10",
            intent=INTENT_METRIC_DERIVED,
            reason=f"有效样本 {len(nom)} 不足以覆盖 period={k}",
            trace_id=trace_id,
        )
    ds = _parse_dates(dates)
    if dates and len(ds) != len(nom):
        return unavailable(
            capability="D-A10",
            intent=INTENT_METRIC_DERIVED,
            reason="日期轴与数值长度不一致或日期无效",
            trace_id=trace_id,
        )

    inflation_call = _call("S16", idx, k=k)
    if inflation_call["gate"] != "ok":
        return unavailable(
            capability="D-A10",
            intent=INTENT_METRIC_DERIVED,
            reason="CPI 同比计算失败",
            trace_id=trace_id,
        )
    inflation = inflation_call["result"]
    span = _span([ds[-1 - k], ds[-1]]) if ds else None
    base_ts = span[0] if span else None

    nominal_last = round(nom[-1], 6)
    cpi_yoy = inflation.get("pct")
    inflation_pp = None if cpi_yoy is None else round(cpi_yoy * 100.0, 6)
    real = None if inflation_pp is None else round(nominal_last - inflation_pp, 6)

    q = quality_for(
        len(nom),
        min_n=MIN_REAL_RATE,
        span=span,
        sources=["datacenter.series"],
        align_method="period_offset",
        timezone="UTC",
    )
    reasons = []
    if real is None:
        reasons.append("inflation_unavailable")
    elif len(nom) < 2 * k + 1:
        reasons.append("short_history")
    if reasons:
        q = _degrade(q, ",".join(reasons))

    label = name or "实际利率"
    base_text = f"（通胀基期 {base_ts}）" if base_ts else f"（通胀基期前 {k} 期）"
    if real is None:
        body = (
            f"{label}名义利率 {nominal_last:.4f}{unit}，CPI 基期值为 0，通胀不可计算，"
            f"实际利率不可计算（降级：基期不足）{base_text}"
        )
    else:
        body = (
            f"{label}名义利率 {nominal_last:.4f}{unit}，CPI 同比通胀 {inflation_pp:.4f}{unit}，"
            f"实际利率 {real:.4f}{unit}（名义 − 通胀）{base_text}"
        )
    note = "；历史长度不足 2 个完整周期，通胀稳定性有限" if "short_history" in reasons else ""
    answer = f"{body}{note}。{CAVEAT}。"
    return build(
        capability="D-A10",
        intent=INTENT_METRIC_DERIVED,
        answer=answer,
        data={
            "capabilities": {
                "D-A10": {
                    "gate": "partial" if q["status"] == STATUS_PARTIAL else "ok",
                    "methods": ["S16"],
                    "real_rate": real,
                    "nominal": nominal_last,
                    "inflation": inflation_pp,
                    "base_ts": base_ts,
                    "period": k,
                    "sample_n": inflation.get("n"),
                }
            },
            "params": {"min_n": MIN_REAL_RATE, "period": k, "unit": unit or None},
            "name": name or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-A11 双序列滚动相关 ----------------


def rolling_correlation(
    x: Sequence[Any],
    y: Sequence[Any],
    *,
    window: int = 30,
    dates: Optional[Sequence[Any]] = None,
    name: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """双序列滚动 Pearson 相关：统计量唯一由 M04 执行，能力层只做配对、取点与信封。"""
    indices, xs, ys = _paired_rows(x, y)
    if len(xs) < 2:
        return unavailable(
            capability="D-A11",
            intent=INTENT_CORRELATION,
            reason="双序列有效配对不足 2 点",
            trace_id=trace_id,
        )
    try:
        k = int(window)
    except (TypeError, ValueError):
        return unavailable(
            capability="D-A11",
            intent=INTENT_CORRELATION,
            reason="window 参数无效",
            trace_id=trace_id,
        )
    if k < 2 or k > len(xs):
        return unavailable(
            capability="D-A11",
            intent=INTENT_CORRELATION,
            reason=f"window {k} 超出可用配对样本 2~{len(xs)}",
            trace_id=trace_id,
        )
    ds = _parse_dates(dates)
    if dates:
        if len(ds) != len(x) or len(x) != len(y):
            return unavailable(
                capability="D-A11",
                intent=INTENT_CORRELATION,
                reason="日期轴与双序列长度不一致或日期无效",
                trace_id=trace_id,
            )
        ds = [ds[i] for i in indices]

    out = _call_soft("M04", {"x": xs, "y": ys}, window=k)
    if out["gate"] not in ("ok", "degraded") or out["result"] is None:
        return unavailable(
            capability="D-A11",
            intent=INTENT_CORRELATION,
            reason="滚动相关计算失败",
            trace_id=trace_id,
        )
    result = out["result"]
    valid = [value for value in result["r"] if value is not None]
    corr = valid[-1] if valid else None

    q = quality_for(
        len(xs),
        min_n=MIN_ROLLING_CORR,
        span=_span(ds),
        sources=["datacenter.series"],
        align_method="paired_complete_case",
        timezone="UTC",
    )
    note = "样本充足"
    if q["status"] != STATUS_GOOD:
        q = _degrade(q, "insufficient_samples")
        note = f"有效配对 {len(xs)} < 60，滚动相关仅为短窗口描述（样本不足）"

    label = name or "双序列"
    corr_txt = "不可计算" if corr is None else f"{corr:.4f}"
    mean_txt = "不可计算" if result["mean_r"] is None else f"{result['mean_r']:.4f}"
    answer = (
        f"{label}最近 {k} 期滚动 Pearson 相关 {corr_txt}"
        f"（窗口均值 {mean_txt}，共 {result['n_windows']} 个窗口，n={result['sample_n']}）。"
        f"{note}，仅描述同期联动强弱，不说明领先关系或未来延续。{CAVEAT}。"
    )
    return build(
        capability="D-A11",
        intent=INTENT_CORRELATION,
        answer=answer,
        data={
            "capabilities": {
                "D-A11": {
                    "gate": "partial" if q["status"] == STATUS_PARTIAL else "ok",
                    "methods": ["M04"],
                    "corr": corr,
                    "mean_r": result["mean_r"],
                    "window": k,
                    "n_windows": result["n_windows"],
                    "sample_n": result["sample_n"],
                }
            },
            "params": {"min_n": MIN_ROLLING_CORR, "window": k},
            "name": name or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-A12 领先滞后相关 ----------------


def lead_lag_correlation(
    x: Sequence[Any],
    y: Sequence[Any],
    *,
    max_lag: int = 10,
    dates: Optional[Sequence[Any]] = None,
    x_name: str = "x",
    y_name: str = "y",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """lag 0–max_lag 的互相关：统计量唯一由 M11（全 lag + BH-FDR）与 M12（最优 lag）执行。"""
    indices, xs, ys = _paired_rows(x, y)
    if len(xs) < 2:
        return unavailable(
            capability="D-A12",
            intent=INTENT_CORRELATION,
            reason="双序列有效配对不足 2 点",
            trace_id=trace_id,
        )
    try:
        lag = int(max_lag)
    except (TypeError, ValueError):
        return unavailable(
            capability="D-A12",
            intent=INTENT_CORRELATION,
            reason="max_lag 参数无效",
            trace_id=trace_id,
        )
    if lag < 1 or lag >= len(xs):
        return unavailable(
            capability="D-A12",
            intent=INTENT_CORRELATION,
            reason=f"max_lag {lag} 超出可用配对样本 1~{len(xs) - 1}",
            trace_id=trace_id,
        )
    ds = _parse_dates(dates)
    if dates:
        if len(ds) != len(x) or len(x) != len(y):
            return unavailable(
                capability="D-A12",
                intent=INTENT_CORRELATION,
                reason="日期轴与双序列长度不一致或日期无效",
                trace_id=trace_id,
            )
        ds = [ds[i] for i in indices]

    pair = {"x": xs, "y": ys}
    family = _call_soft("M11", pair, max_lag=lag)
    best = _call_soft("M12", pair, max_lag=lag)
    if family["result"] is None or best["result"] is None:
        return unavailable(
            capability="D-A12",
            intent=INTENT_CORRELATION,
            reason="领先滞后相关计算失败",
            trace_id=trace_id,
        )
    ccf = family["result"]
    optimum = best["result"]
    corr_by_lag = [
        {
            "lag": lags,
            "r": ccf["r"][position],
            "p": ccf["p"][position],
            "q": ccf["q"][position],
            "significant": ccf["significant"][position],
        }
        for position, lags in enumerate(ccf["lags"])
    ]

    q = quality_for(
        len(xs),
        min_n=MIN_CCF,
        span=_span(ds),
        sources=["datacenter.series"],
        align_method="paired_complete_case",
        timezone="UTC",
    )
    note = "样本充足"
    if q["status"] != STATUS_GOOD:
        q = _degrade(q, "insufficient_history")
        note = f"有效配对 {len(xs)} < 120，领先滞后仅为描述性结果（样本不足）"

    best_lag = optimum["lag"]
    lead_text = (
        f"正 lag 表示 {x_name} 领先 {y_name}"
        if best_lag > 0
        else (f"负 lag 表示 {y_name} 领先 {x_name}" if best_lag < 0 else "同期同步")
    )
    answer = (
        f"{x_name} 与 {y_name} 领先滞后：最优 lag={best_lag}"
        f"（CCF={optimum['r']:.4f}，BH-FDR q={optimum['q']:.4f}），{lead_text}；"
        f"搜索 lag 0–{lag}，n={len(xs)}。{note}，"
        f"历史样本中的联动强弱不自动等于因果或未来可预测。{CAVEAT}。"
    )
    return build(
        capability="D-A12",
        intent=INTENT_CORRELATION,
        answer=answer,
        data={
            "capabilities": {
                "D-A12": {
                    "gate": "partial" if q["status"] == STATUS_PARTIAL else "ok",
                    "methods": ["M11", "M12"],
                    "best_lag": best_lag,
                    "best_corr": optimum["r"],
                    "best_p_adj": optimum["q"],
                    "corr_by_lag": corr_by_lag,
                    "max_lag": lag,
                    "sample_n": len(xs),
                }
            },
            "params": {"min_n": MIN_CCF, "max_lag": lag},
            "name": f"{x_name}~{y_name}",
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-A13 极端事件频率 ----------------


def extreme_frequency(
    values: Sequence[Any],
    *,
    threshold: Optional[float] = None,
    side: str = "above",
    quantile: float = 0.95,
    dates: Optional[Sequence[Any]] = None,
    name: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """超阈值天数与占比：阈值默认由 S11 分位给出，计数为纯聚合，不引入额外估计量。"""
    xs = _floats(values)
    if len(xs) != len(values) or not all(math.isfinite(value) for value in xs):
        return unavailable(
            capability="D-A13",
            intent=INTENT_METRIC_SERIES,
            reason="序列包含无效值",
            trace_id=trace_id,
        )
    if len(xs) < 2:
        return unavailable(
            capability="D-A13",
            intent=INTENT_METRIC_SERIES,
            reason="有效样本不足 2 点",
            trace_id=trace_id,
        )
    if side not in ("above", "below", "abs"):
        return unavailable(
            capability="D-A13",
            intent=INTENT_METRIC_SERIES,
            reason=f"side={side!r} 不支持（above/below/abs）",
            trace_id=trace_id,
        )
    ds = _parse_dates(dates)
    if dates and len(ds) != len(values):
        return unavailable(
            capability="D-A13",
            intent=INTENT_METRIC_SERIES,
            reason="日期轴与数值长度不一致或日期无效",
            trace_id=trace_id,
        )

    used: List[str] = []
    cut = None if threshold is None else float(threshold)
    if cut is not None and not math.isfinite(cut):
        return unavailable(
            capability="D-A13",
            intent=INTENT_METRIC_SERIES,
            reason="threshold 非有限值",
            trace_id=trace_id,
        )
    if cut is None:
        try:
            q = float(quantile)
        except (TypeError, ValueError):
            return unavailable(
                capability="D-A13",
                intent=INTENT_METRIC_SERIES,
                reason="quantile 参数无效",
                trace_id=trace_id,
            )
        if not 0.0 < q < 1.0:
            return unavailable(
                capability="D-A13",
                intent=INTENT_METRIC_SERIES,
                reason=f"quantile {q} 超出 (0, 1)",
                trace_id=trace_id,
            )
        pct = _call("S11", xs)
        if pct["gate"] != "ok":
            return unavailable(
                capability="D-A13",
                intent=INTENT_METRIC_SERIES,
                reason=f"样本 {len(xs)} 不足 30 且未提供 threshold，阈值不可确定",
                trace_id=trace_id,
            )
        used.append("S11")
        key = f"p{int(round(q * 100))}"
        cut = pct["result"].get(key)
        if cut is None:
            cut = pct["result"]["p95"]
        cut = float(cut)

    if side == "above":
        hits = [value for value in xs if value >= cut]
    elif side == "below":
        hits = [value for value in xs if value <= cut]
    else:
        hits = [value for value in xs if abs(value) >= abs(cut)]
    days = len(hits)
    ratio = round(days / len(xs), 6)

    q_block = quality_for(
        len(xs),
        min_n=MIN_SERIES,
        span=_span(ds),
        sources=["datacenter.series"],
        align_method="daily_close",
        timezone="UTC",
    )
    note = "样本充足"
    if q_block["status"] != STATUS_GOOD:
        q_block = _degrade(q_block, "insufficient_samples")
        note = f"样本 {len(xs)} < 30，超阈值占比仅为短窗口描述（样本不足）"

    label = name or "序列"
    side_text = {"above": "≥", "below": "≤", "abs": "|x| ≥"}[side]
    source = "S11 分位" if used else "调用方给定"
    answer = (
        f"{label}极端事件（{side_text} {cut:.6g} 阈值）：{days} 天 / {len(xs)} 天，"
        f"占比 {ratio * 100:.2f}%；阈值来源 {source}。{note}。{CAVEAT}。"
    )
    return build(
        capability="D-A13",
        intent=INTENT_METRIC_SERIES,
        answer=answer,
        data={
            "capabilities": {
                "D-A13": {
                    "gate": "partial" if q_block["status"] == STATUS_PARTIAL else "ok",
                    "methods": used,
                    "days": days,
                    "ratio": ratio,
                    "threshold": round(cut, 6),
                    "side": side,
                    "quantile": None if used == [] else float(quantile),
                    "sample_n": len(xs),
                }
            },
            "params": {"min_n": MIN_SERIES, "side": side},
            "name": name or None,
        },
        quality_block=q_block,
        trace_id=trace_id,
    )


# ---------------- D-B09 距 ATH 回撤 ----------------


def ath_drawdown(
    prices: Sequence[Any],
    *,
    symbol: str = "",
    dates: Optional[Sequence[Any]] = None,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """距历史高（ATH）回撤：复用 D-E10 的 D20/D21 执行器，补 ATH 别名契约。"""
    out = drawdown(
        prices,
        symbol=symbol,
        dates=dates,
        capability_id="D-B09",
        intent=INTENT_TECHNICAL,
        trace_id=trace_id,
    )
    if not out.get("ok"):
        return out
    block = out["data"]["capabilities"]["D-B09"]
    block["drawdown_from_ath"] = block["current_drawdown"]
    block["ath"] = block["peak_price"]
    block["ath_ts"] = block["peak_ts"]
    return out


# ---------------- D-G08 12-1 动量 ----------------


def momentum_12_1(
    prices: Sequence[Any],
    *,
    lookback: int = 252,
    skip: int = 21,
    dates: Optional[Sequence[Any]] = None,
    symbol: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """12-1 动量：跳过最近 skip 期后回溯 lookback 期的累计收益（F14 真实执行）。"""
    px = _floats(prices)
    if len(px) != len(prices) or not all(math.isfinite(value) for value in px):
        return unavailable(
            capability="D-G08",
            intent=INTENT_METRIC_DERIVED,
            reason="价格序列包含无效值",
            trace_id=trace_id,
        )
    try:
        lb = int(lookback)
        sk = int(skip)
    except (TypeError, ValueError):
        return unavailable(
            capability="D-G08",
            intent=INTENT_METRIC_DERIVED,
            reason=f"lookback/skip 不是整数：{lookback!r}/{skip!r}",
            trace_id=trace_id,
        )
    if lb < 2:
        return unavailable(
            capability="D-G08",
            intent=INTENT_METRIC_DERIVED,
            reason=f"lookback {lb} 小于 2",
            trace_id=trace_id,
        )
    if sk < 0:
        return unavailable(
            capability="D-G08",
            intent=INTENT_METRIC_DERIVED,
            reason=f"skip {sk} 小于 0",
            trace_id=trace_id,
        )
    ds = _parse_dates(dates)
    if dates and len(ds) != len(px):
        return unavailable(
            capability="D-G08",
            intent=INTENT_METRIC_DERIVED,
            reason="日期轴与价格长度不一致或日期无效",
            trace_id=trace_id,
        )
    if len(px) < MIN_MOMENTUM:
        return unavailable(
            capability="D-G08",
            intent=INTENT_METRIC_DERIVED,
            reason=f"价格样本 {len(px)} 小于 {MIN_MOMENTUM}",
            trace_id=trace_id,
        )

    truncated = False
    if len(px) < lb + sk + 1:
        lb = len(px) - sk - 1
        truncated = True
        if lb < 2:
            return unavailable(
                capability="D-G08",
                intent=INTENT_METRIC_DERIVED,
                reason=f"跳过 {sk} 期后无足够历史计算动量",
                trace_id=trace_id,
            )

    start = len(px) - (lb + sk + 1)
    end = len(px) - sk
    sample = px[start:end]
    ds_sample = ds[start:end] if ds else []

    call = _call_soft("F14", sample, k=lb)
    if call["gate"] not in ("ok", "degraded"):
        return unavailable(
            capability="D-G08",
            intent=INTENT_METRIC_DERIVED,
            reason="F14 风险调整动量不可用",
            trace_id=trace_id,
        )
    result = call["result"] or {}
    momentum = result.get("momentum")
    vol = result.get("vol")
    ratio = result.get("ratio")

    q = quality_for(
        len(sample),
        min_n=MIN_MOMENTUM,
        span=_span(ds_sample) if ds_sample else None,
        sources=["market.candles"],
        align_method="utc_daily_close",
        timezone="UTC",
    )
    reasons: List[str] = []
    if len(sample) < MIN_MOMENTUM:
        reasons.append("insufficient_samples")
    if truncated:
        reasons.append("short_history")
    if momentum is None:
        reasons.append("base_zero")
    if reasons:
        q = _degrade(q, ",".join(reasons))

    span_text = f"{ds_sample[0]}→{ds_sample[-1]}" if ds_sample else f"最近 {lb + sk + 1} 期"
    pct = "不可计算" if momentum is None else f"{round(float(momentum) * 100, 6)}%"
    head = f"{symbol} " if symbol else ""
    tail = []
    if truncated:
        tail.append(f"历史仅 {len(px)} 期，lookback 已截断为 {lb} 期（历史数据不足）")
    if momentum is None:
        tail.append("窗口起点价格非正，动量不可计算（样本不足）")
    note = f"；{'；'.join(tail)}" if tail else ""
    answer = (
        f"{head}12-1 动量（跳过最近 {sk} 期、回溯 {lb} 期，窗口 {span_text}）为 {pct}，"
        f"同期波动 {vol}，风险调整动量 {ratio}{note}。n={len(sample)}。{CAVEAT}。"
    )
    return build(
        capability="D-G08",
        intent=INTENT_METRIC_DERIVED,
        answer=answer,
        data={
            "capabilities": {
                "D-G08": {
                    "gate": "partial" if q["status"] == STATUS_PARTIAL else "ok",
                    "methods": ["F14"],
                    "momentum_12_1": momentum,
                    "lookback": lb,
                    "skip": sk,
                    "vol": vol,
                    "risk_adjusted": ratio,
                    "window_start_ts": ds_sample[0].isoformat() if ds_sample else None,
                    "window_end_ts": ds_sample[-1].isoformat() if ds_sample else None,
                    "truncated": truncated,
                    "sample_n": len(sample),
                }
            },
            "params": {"min_n": MIN_MOMENTUM, "lookback": lb, "skip": sk},
            "symbol": symbol or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-G09 波动率目标换算 ----------------


def vol_target_scale(
    prices: Sequence[Any],
    *,
    target_vol: float = 0.10,
    window: int = 20,
    periods: int = 365,
    dates: Optional[Sequence[Any]] = None,
    symbol: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """波动率目标换算：scale = 目标波动 / 实现波动，复用方法层 P02。"""
    px = _floats(prices)
    if len(px) != len(prices) or not all(math.isfinite(value) for value in px):
        return unavailable(
            capability="D-G09",
            intent=INTENT_METRIC_DERIVED,
            reason="价格序列包含无效值",
            trace_id=trace_id,
        )
    try:
        tv = float(target_vol)
    except (TypeError, ValueError):
        return unavailable(
            capability="D-G09",
            intent=INTENT_METRIC_DERIVED,
            reason=f"target_vol 不是数值：{target_vol!r}",
            trace_id=trace_id,
        )
    if not math.isfinite(tv) or tv <= 0:
        return unavailable(
            capability="D-G09",
            intent=INTENT_METRIC_DERIVED,
            reason=f"target_vol {target_vol!r} 必须为正数",
            trace_id=trace_id,
        )
    try:
        w = int(window)
        pp = int(periods)
    except (TypeError, ValueError):
        return unavailable(
            capability="D-G09",
            intent=INTENT_METRIC_DERIVED,
            reason=f"window/periods 不是整数：{window!r}/{periods!r}",
            trace_id=trace_id,
        )
    if w < 2:
        return unavailable(
            capability="D-G09",
            intent=INTENT_METRIC_DERIVED,
            reason=f"window {w} 小于 2",
            trace_id=trace_id,
        )
    if pp < 1:
        return unavailable(
            capability="D-G09",
            intent=INTENT_METRIC_DERIVED,
            reason=f"periods {pp} 小于 1",
            trace_id=trace_id,
        )
    ds = _parse_dates(dates)
    if dates and len(ds) != len(px):
        return unavailable(
            capability="D-G09",
            intent=INTENT_METRIC_DERIVED,
            reason="日期轴与价格长度不一致或日期无效",
            trace_id=trace_id,
        )
    if len(px) < MIN_VOL_TARGET + 1:
        return unavailable(
            capability="D-G09",
            intent=INTENT_METRIC_DERIVED,
            reason=f"价格样本 {len(px)} 不足以形成 {MIN_VOL_TARGET} 个收益",
            trace_id=trace_id,
        )

    rets = _returns(px)
    if len(rets) < MIN_VOL_TARGET:
        return unavailable(
            capability="D-G09",
            intent=INTENT_METRIC_DERIVED,
            reason=f"有效收益 {len(rets)} 小于 {MIN_VOL_TARGET}",
            trace_id=trace_id,
        )
    truncated = w > len(rets)
    if truncated:
        w = len(rets)

    key = symbol or "asset"
    # 扁平 {sym: returns} 契约：方法层 _sample_n 按列长度取样本，嵌套 returns 会被计为 1。
    call = _call("P02", {key: rets}, target_vol=tv, window=w, periods=pp)
    if call["gate"] != "ok":
        return unavailable(
            capability="D-G09",
            intent=INTENT_METRIC_DERIVED,
            reason="波动率目标换算不可用",
            trace_id=trace_id,
        )
    result = call["result"] or {}
    scale = (result.get("scale") or {}).get(key)
    realized = (result.get("realized") or {}).get(key)

    q = quality_for(
        len(rets),
        min_n=MIN_VOL_TARGET,
        span=_span(ds[1:]) if ds else None,
        sources=["market.candles"],
        align_method="utc_daily_close",
        timezone="UTC",
    )
    reasons: List[str] = []
    if realized is None or float(realized) <= 0:
        reasons.append("zero_volatility")
    if truncated:
        reasons.append("window_truncated")
    if reasons:
        q = _degrade(q, ",".join(reasons))

    head = f"{symbol} " if symbol else ""
    tail = []
    if truncated:
        tail.append(f"收益仅 {len(rets)} 期，window 已截断为 {w} 期")
    if realized is None or float(realized) <= 0:
        tail.append("样本内实现波动为 0，缩放系数无意义（样本不足）")
    note = f"；{'；'.join(tail)}" if tail else ""
    answer = (
        f"{head}波动率目标换算（目标年化 {round(tv * 100, 6)}%、窗口 {w} 期实现年化 "
        f"{'不可得' if realized is None else f'{round(float(realized) * 100, 6)}%'}）："
        f"仓位缩放系数 {scale}（= 目标/实现，>1 表示同风险预算下可放大基础仓位，<1 表示需缩小）{note}。"
        f"n={len(rets)}。该系数仅描述样本内实现波动与目标波动之比，不构成交易建议；{CAVEAT}。"
    )
    return build(
        capability="D-G09",
        intent=INTENT_METRIC_DERIVED,
        answer=answer,
        data={
            "capabilities": {
                "D-G09": {
                    "gate": "partial" if q["status"] == STATUS_PARTIAL else "ok",
                    "methods": ["P02"],
                    "scale": scale,
                    "target_vol": result.get("target_vol"),
                    "realized_vol": realized,
                    "window": w,
                    "periods": pp,
                    "returns_n": result.get("n"),
                    "sample_n": len(rets),
                }
            },
            "params": {"min_n": MIN_VOL_TARGET, "target_vol": tv, "window": w, "periods": pp},
            "symbol": symbol or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-B08 趋势斜率 ----------------


def slope_trend(
    prices: Sequence[Any],
    *,
    window: int = 90,
    dates: Optional[Sequence[Any]] = None,
    symbol: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """最近 window 期对数价格 OLS 斜率 + R² + 名义 t/p（T08/T09），不做 HAC 修正。"""
    px = _floats(prices)
    if len(px) != len(prices) or not all(math.isfinite(value) for value in px):
        return unavailable(
            capability="D-B08",
            intent=INTENT_TECHNICAL,
            reason="价格序列包含无效值",
            trace_id=trace_id,
        )
    try:
        k = int(window)
    except (TypeError, ValueError):
        k = 0
    if k < 30:
        return unavailable(
            capability="D-B08",
            intent=INTENT_TECHNICAL,
            reason=f"window {window!r} 小于 30",
            trace_id=trace_id,
        )
    ds = _parse_dates(dates)
    if dates and len(ds) != len(px):
        return unavailable(
            capability="D-B08",
            intent=INTENT_TECHNICAL,
            reason="日期轴与价格长度不一致或日期无效",
            trace_id=trace_id,
        )
    if len(px) < 30:
        return unavailable(
            capability="D-B08",
            intent=INTENT_TECHNICAL,
            reason=f"价格样本 {len(px)} 小于 30",
            trace_id=trace_id,
        )

    start = max(0, len(px) - k)
    sample = px[start:]
    ds_sample = ds[start:] if ds else []

    slope_block = _call("T08", sample)
    if slope_block["gate"] != "ok":
        return unavailable(
            capability="D-B08",
            intent=INTENT_TECHNICAL,
            reason="T08 趋势斜率不可用",
            trace_id=trace_id,
        )
    sig_block = _call_soft("T09", sample)
    sig = sig_block["result"] if sig_block["gate"] in ("ok", "degraded") else {}

    slope = slope_block["result"].get("slope_per_day")
    r2 = slope_block["result"].get("r2")
    q = quality_for(
        len(sample),
        min_n=MIN_SLOPE,
        span=_span(ds_sample) if ds_sample else None,
        sources=["market.candles"],
        align_method="utc_daily_close",
        timezone="UTC",
    )
    if q["status"] != STATUS_GOOD:
        q = _degrade(q, "short_window")

    head = f"{symbol} " if symbol else ""
    note = (
        "；样本低于 60 天，斜率仅为短窗口描述（样本不足）" if q["status"] == STATUS_PARTIAL else ""
    )
    answer = (
        f"{head}最近 {k} 日对数价格趋势斜率 {slope}/日（R²={r2}），"
        f"名义 t={sig.get('t')}，p={sig.get('p')}；名义 t 未做 HAC 修正，仅作相对比较"
        f"{note}。n={len(sample)}。{CAVEAT}。"
    )
    return build(
        capability="D-B08",
        intent=INTENT_TECHNICAL,
        answer=answer,
        data={
            "capabilities": {
                "D-B08": {
                    "gate": "partial" if q["status"] == STATUS_PARTIAL else "ok",
                    "methods": ["T08", "T09"],
                    "slope": slope,
                    "r2": r2,
                    "window": k,
                    "t": sig.get("t"),
                    "p": sig.get("p"),
                    "hac_corrected": False,
                    "sample_n": len(sample),
                }
            },
            "params": {"min_n": MIN_SLOPE, "window": k},
            "symbol": symbol or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-A15 净流入滚动和 ----------------


def etf_flow_rolling(
    values: Sequence[Any],
    *,
    windows: Sequence[int] = (7, 30),
    dates: Optional[Sequence[Any]] = None,
    unit: str = "",
    name: str = "",
    symbol: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """7/30 日净流入滚动和：S20 滚动均值经窗口长度还原为和，能力层不做分布估计。"""
    xs = _floats(values)
    if len(xs) != len(values) or not all(math.isfinite(value) for value in xs):
        return unavailable(
            capability="D-A15",
            intent=INTENT_METRIC_SERIES,
            reason="序列包含无效值",
            trace_id=trace_id,
        )
    ds = _parse_dates(dates)
    if dates and len(ds) != len(xs):
        return unavailable(
            capability="D-A15",
            intent=INTENT_METRIC_SERIES,
            reason="日期轴与数值长度不一致或日期无效",
            trace_id=trace_id,
        )
    ws: List[int] = []
    for raw in windows:
        try:
            k = int(raw)
        except (TypeError, ValueError):
            return unavailable(
                capability="D-A15",
                intent=INTENT_METRIC_SERIES,
                reason=f"window {raw!r} 不是整数",
                trace_id=trace_id,
            )
        if k < 1:
            return unavailable(
                capability="D-A15",
                intent=INTENT_METRIC_SERIES,
                reason=f"window {k} < 1",
                trace_id=trace_id,
            )
        if k not in ws:
            ws.append(k)
    if not ws:
        return unavailable(
            capability="D-A15",
            intent=INTENT_METRIC_SERIES,
            reason="windows 不可为空",
            trace_id=trace_id,
        )

    sums: Dict[str, Optional[float]] = {}
    short: List[int] = []
    for k in ws:
        if k > len(xs):
            sums[f"sum_{k}d"] = None
            short.append(k)
            continue
        call = _call_soft("S20", xs, k=k)
        if call["gate"] not in ("ok", "degraded"):
            sums[f"sum_{k}d"] = None
            short.append(k)
            continue
        means = call["result"].get("series") or []
        last = next((m for m in reversed(means) if m is not None), None)
        sums[f"sum_{k}d"] = None if last is None else round(float(last) * k, 6)

    if all(value is None for value in sums.values()):
        return unavailable(
            capability="D-A15",
            intent=INTENT_METRIC_SERIES,
            reason=f"有效样本 {len(xs)} 不足以覆盖任何窗口 {ws}",
            trace_id=trace_id,
        )

    span = _span(ds) if ds else None
    q = quality_for(
        len(xs),
        min_n=MIN_SERIES,
        span=span,
        sources=["datacenter.series"],
        align_method="daily_close",
        timezone="UTC",
    )
    reasons = []
    if len(xs) < MIN_SERIES:
        reasons.append("insufficient_samples")
    if short:
        reasons.append("short_history")
    if reasons:
        q = _degrade(q, ",".join(reasons))

    label = name or "序列"
    unit_text = f" {unit}" if unit else ""
    pieces = [
        f"{k} 日滚动和 {sums[f'sum_{k}d']:.6g}{unit_text}"
        for k in ws
        if sums[f"sum_{k}d"] is not None
    ]
    missing = [k for k in ws if sums[f"sum_{k}d"] is None]
    tail = ""
    if missing:
        tail = f"；{'/'.join(str(k) for k in missing)} 日窗口超出历史长度，历史数据不足"
    note = ""
    if len(xs) < MIN_SERIES:
        note = "；样本低于 30 天下限，滚动和仅为短窗口描述（样本不足）"
    head = f"{symbol} " if symbol else ""
    window_text = "/".join(str(k) for k in ws)
    answer = (
        f"{head}{label}（{window_text} 日）净流入滚动和：{'、'.join(pieces)}"
        f"{tail}{note}。{CAVEAT}。"
    )
    return build(
        capability="D-A15",
        intent=INTENT_METRIC_SERIES,
        answer=answer,
        data={
            "capabilities": {
                "D-A15": {
                    "gate": "partial" if q["status"] == STATUS_PARTIAL else "ok",
                    "methods": ["S20"],
                    **sums,
                    "windows": ws,
                    "sample_n": len(xs),
                }
            },
            "params": {"min_n": MIN_SERIES, "windows": ws},
            "name": name or None,
            "symbol": symbol or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-A16 稳定币规模增速 ----------------


def stablecoin_growth(
    values: Sequence[Any],
    *,
    windows: Sequence[int] = (7, 30),
    dates: Optional[Sequence[Any]] = None,
    name: str = "",
    symbol: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """7/30 日稳定币规模增速：S16 逐窗口真实执行，能力层只组装多窗口结果。"""
    xs = _floats(values)
    if len(xs) != len(values) or not all(math.isfinite(value) for value in xs):
        return unavailable(
            capability="D-A16",
            intent=INTENT_METRIC_SERIES,
            reason="序列包含无效值",
            trace_id=trace_id,
        )
    ds = _parse_dates(dates)
    if dates and len(ds) != len(xs):
        return unavailable(
            capability="D-A16",
            intent=INTENT_METRIC_SERIES,
            reason="日期轴与数值长度不一致或日期无效",
            trace_id=trace_id,
        )
    ws: List[int] = []
    for raw in windows:
        try:
            k = int(raw)
        except (TypeError, ValueError):
            return unavailable(
                capability="D-A16",
                intent=INTENT_METRIC_SERIES,
                reason=f"window {raw!r} 不是整数",
                trace_id=trace_id,
            )
        if k < 1:
            return unavailable(
                capability="D-A16",
                intent=INTENT_METRIC_SERIES,
                reason=f"window {k} < 1",
                trace_id=trace_id,
            )
        if k not in ws:
            ws.append(k)
    if not ws:
        return unavailable(
            capability="D-A16",
            intent=INTENT_METRIC_SERIES,
            reason="windows 不可为空",
            trace_id=trace_id,
        )

    growths: Dict[str, Optional[float]] = {}
    short: List[int] = []
    zero_base: List[int] = []
    for k in ws:
        key = f"growth_{k}d"
        if len(xs) <= k:
            growths[key] = None
            short.append(k)
            continue
        call = _call_soft("S16", xs, k=k)
        pct = call["result"].get("pct") if call["gate"] in ("ok", "degraded") else None
        if pct is None:
            growths[key] = None
            zero_base.append(k)
            continue
        growths[key] = round(float(pct) * 100, 6)

    if all(value is None for value in growths.values()):
        return unavailable(
            capability="D-A16",
            intent=INTENT_METRIC_SERIES,
            reason=f"有效样本 {len(xs)} 不足以覆盖任何窗口 {ws} 或基期为 0",
            trace_id=trace_id,
        )

    span = _span(ds) if ds else None
    q = quality_for(
        len(xs),
        min_n=MIN_SERIES,
        span=span,
        sources=["datacenter.series"],
        align_method="daily_close",
        timezone="UTC",
    )
    reasons = []
    if len(xs) < MIN_SERIES:
        reasons.append("insufficient_samples")
    if short:
        reasons.append("short_history")
    if zero_base:
        reasons.append("base_zero")
    if reasons:
        q = _degrade(q, ",".join(reasons))

    label = name or "序列"
    pieces = [
        f"{k} 日增速 {growths[f'growth_{k}d']:.6g}%"
        for k in ws
        if growths[f"growth_{k}d"] is not None
    ]
    missing = [k for k in ws if growths[f"growth_{k}d"] is None]
    tail = ""
    if missing:
        tail = f"；{'/'.join(str(k) for k in missing)} 日窗口不可算（历史不足或基期为 0）"
    note = ""
    if len(xs) < MIN_SERIES:
        note = "；样本低于 30 天下限，增速仅为短窗口描述（样本不足）"
    head = f"{symbol} " if symbol else ""
    window_text = "/".join(str(k) for k in ws)
    answer = (
        f"{head}{label}（{window_text} 日）规模增速：{'、'.join(pieces)}{tail}{note}。{CAVEAT}。"
    )
    return build(
        capability="D-A16",
        intent=INTENT_METRIC_SERIES,
        answer=answer,
        data={
            "capabilities": {
                "D-A16": {
                    "gate": "partial" if q["status"] == STATUS_PARTIAL else "ok",
                    "methods": ["S16"],
                    **growths,
                    "windows": ws,
                    "sample_n": len(xs),
                }
            },
            "params": {"min_n": MIN_SERIES, "windows": ws},
            "name": name or None,
            "symbol": symbol or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-J30 PIT / release_ts 全局校验 ----------------


def pit_alignment(
    indicator: Sequence[Any],
    prices: Sequence[Any],
    *,
    dates: Optional[Sequence[Any]] = None,
    release_ts: Optional[Sequence[Any]] = None,
    used_ts: Optional[Sequence[Any]] = None,
    as_of: Any = None,
    buckets: int = 4,
    horizons: Sequence[int] = (1,),
    window: int = MIN_CONDITIONAL,
    name: str = "指标",
    symbol: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """SC90 校验「可用时间 ≤ 使用时间」+ R02 `pit=true` 前瞻分布，全局前视规避出口。"""
    if len(indicator) != len(prices):
        return unavailable(
            capability="D-J30",
            intent=INTENT_PERCENTILE,
            reason="指标与价格长度不一致",
            trace_id=trace_id,
        )
    ind, px = _floats(indicator), _floats(prices)
    if (
        len(ind) != len(indicator)
        or len(px) != len(prices)
        or not all(math.isfinite(value) for value in ind + px)
    ):
        return unavailable(
            capability="D-J30",
            intent=INTENT_PERCENTILE,
            reason="指标或价格包含无效值",
            trace_id=trace_id,
        )
    if len(px) < MIN_CONDITIONAL:
        return unavailable(
            capability="D-J30",
            intent=INTENT_PERCENTILE,
            reason=f"对齐样本 {len(px)} < {MIN_CONDITIONAL}",
            trace_id=trace_id,
        )
    try:
        requested_buckets = int(buckets)
        window = int(window)
        hs = tuple(sorted({int(h) for h in horizons}))
    except (TypeError, ValueError):
        return unavailable(
            capability="D-J30",
            intent=INTENT_PERCENTILE,
            reason="horizons/buckets/window 参数无效",
            trace_id=trace_id,
        )
    if not hs or min(hs) < 1 or requested_buckets < 2 or window < 2:
        return unavailable(
            capability="D-J30",
            intent=INTENT_PERCENTILE,
            reason="horizons 须为正整数，buckets ≥ 2 且 window ≥ 2",
            trace_id=trace_id,
        )

    n = len(px)
    timestamps = list(dates) if dates else list(range(n))
    ds = _parse_dates(dates)
    if len(timestamps) != n or (dates and len(ds) != n):
        return unavailable(
            capability="D-J30",
            intent=INTENT_PERCENTILE,
            reason="日期轴与指标/价格长度不一致或日期无效",
            trace_id=trace_id,
        )
    if release_ts is not None and len(release_ts) != n:
        return unavailable(
            capability="D-J30",
            intent=INTENT_PERCENTILE,
            reason="release_ts 与指标/价格长度不一致",
            trace_id=trace_id,
        )
    if used_ts is not None and len(used_ts) != n:
        return unavailable(
            capability="D-J30",
            intent=INTENT_PERCENTILE,
            reason="used_ts 与指标/价格长度不一致",
            trace_id=trace_id,
        )

    available = list(release_ts) if release_ts is not None else list(timestamps)
    used = list(used_ts) if used_ts is not None else list(timestamps)
    pit_call = _call("SC90", {"available": available, "used": used})
    if pit_call["gate"] != "ok":
        return unavailable(
            capability="D-J30",
            intent=INTENT_PERCENTILE,
            reason="PIT 时间校验无法执行",
            trace_id=trace_id,
        )
    pit_check = pit_call["result"]

    payload: Dict[str, Any] = {
        "indicator": ind,
        "price": px,
        "timestamps": timestamps,
        "align_method": "release_ts_pit",
    }
    if release_ts is not None:
        payload["release_ts"] = list(release_ts)
    r02_params: Dict[str, Any] = {
        "buckets": requested_buckets,
        "horizons": hs,
        "label": name or "指标",
        "pit": True,
        "window": window,
    }
    if as_of is not None:
        r02_params["as_of"] = as_of
    r02_call = _call("R02", payload, **r02_params)
    r02 = r02_call["result"] if r02_call["gate"] == "ok" else None

    q = quality_for(
        n,
        min_n=MIN_CONDITIONAL,
        span=_span(ds) if ds else None,
        sources=["market.candles"] + (["mm_metrics"] if release_ts is not None else []),
        align_method="release_ts_pit",
        timezone="UTC",
    )
    notes: List[str] = []
    if not pit_check["pass"]:
        q = _degrade(q, "pit_violations")
        notes.append(
            f"PIT 校验发现 {pit_check['n_violations']} 条样本可用时间晚于使用时间"
            f"（最大超前 {pit_check['max_lag']:.0f} 秒），存在前视风险"
        )
    if r02 is None:
        if pit_check["pass"]:
            return unavailable(
                capability="D-J30",
                intent=INTENT_PERCENTILE,
                reason="R02 PIT 前瞻分布计算失败",
                trace_id=trace_id,
            )
        notes.append("按 release_ts 过滤后可见样本不足 PIT 窗口，未输出前瞻分布")

    if r02 is not None:
        horizon_block = r02["by_horizon"][0] if r02["by_horizon"] else None
        if horizon_block and horizon_block.get("effective_n"):
            stats_text = (
                f"当前 {name or '指标'} 处于 {r02['current_percentile']:.1f}% 分位，"
                f"历史同分位区间后 {horizon_block['h']} 日均值 "
                f"{(horizon_block['mean'] or 0.0) * 100.0:+.2f}%、"
                f"上涨 {(horizon_block['win_rate'] or 0.0) * 100.0:.1f}%"
                f"（有效 n={horizon_block['effective_n']}，"
                f"非重叠 n={horizon_block['nonoverlap_n']}）"
            )
        else:
            stats_text = f"当前 {name or '指标'} 处于 {r02['current_percentile']:.1f}% 分位，历史同分位区间样本不足"
    else:
        stats_text = "PIT 过滤后无法输出前瞻分布"
    check_text = (
        f"PIT 校验通过（可用时间 ≤ 使用时间，n={pit_check['n']}）"
        if pit_check["pass"]
        else (
            f"PIT 校验失败：{pit_check['n_violations']} 条样本可用时间晚于使用时间，"
            f"最大超前 {pit_check['max_lag']:.0f} 秒"
        )
    )
    as_of_text = r02["as_of"] if r02 is not None else timestamps[-1]
    note_text = f"{'；'.join(notes)}。" if notes else ""
    head = f"{symbol} " if symbol else ""
    answer = f"{head}截至 {as_of_text}，{check_text}；{stats_text}。{note_text}{CAVEAT}。"

    return build(
        capability="D-J30",
        intent=INTENT_PERCENTILE,
        answer=answer,
        data={
            "capabilities": {
                "D-J30": {
                    "gate": "ok" if (pit_check["pass"] and r02 is not None) else "partial",
                    "methods": ["SC90", "R02"],
                    "pit_check": pit_check,
                    "r02": r02,
                    "release_ts_applied": release_ts is not None,
                    "as_of": as_of_text,
                }
            },
            "params": {
                "min_n": MIN_CONDITIONAL,
                "buckets": requested_buckets,
                "horizons": list(hs),
                "window": window,
                "as_of": as_of_text,
            },
            "name": name or None,
            "symbol": symbol or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- D-G25 尾部相关（两两） ----------------


def tail_dependence(
    series: Mapping[str, Sequence[Any]],
    *,
    q: float = 0.2,
    symbol: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """P13 下行/上行尾部两两相关（横截面均值分位切尾后的样本内 Pearson）。

    P13 只定义下行尾（横截面均值收益 ≤ q 分位）；上行尾用收益符号取反后复用同一
    方法（相关系数对符号对称、掩码翻转为上行），不在此另写相关口径。
    """
    if not isinstance(series, Mapping) or len(series) < 2:
        return unavailable(
            capability="D-G25",
            intent=INTENT_CORRELATION,
            reason="尾部相关需要 ≥2 个资产的收益序列面板",
            trace_id=trace_id,
        )
    try:
        qq = float(q)
    except (TypeError, ValueError):
        return unavailable(
            capability="D-G25",
            intent=INTENT_CORRELATION,
            reason="q 非数值",
            trace_id=trace_id,
        )
    if not 0.0 < qq <= 0.5:
        return unavailable(
            capability="D-G25",
            intent=INTENT_CORRELATION,
            reason="q 需在 (0, 0.5] 区间",
            trace_id=trace_id,
        )
    names, panel, _, indices = _panel_rows(series)
    n = len(indices)
    if n < MIN_TAIL_DEPENDENCE:
        return unavailable(
            capability="D-G25",
            intent=INTENT_CORRELATION,
            reason=f"对齐样本 {n} < {MIN_TAIL_DEPENDENCE}（尾部相关样本门禁）",
            trace_id=trace_id,
        )
    down = _call("P13", panel, q=qq)
    flipped = {name: [-v for v in values] for name, values in panel.items()}
    up = _call("P13", flipped, q=qq)
    if down["gate"] != "ok" or up["gate"] != "ok":
        return unavailable(
            capability="D-G25",
            intent=INTENT_CORRELATION,
            reason="尾部相关计算失败（切尾后共现样本不足）",
            trace_id=trace_id,
        )
    d, u = down["result"], up["result"]
    pairs = {
        key: {
            "rho_down": d["rho_down"].get(key),
            "rho_up": u["rho_down"].get(key),
            "rho_full": d["rho_full"].get(key),
        }
        for key in d["rho_down"]
    }
    amplifications = {
        key: (
            None
            if item["rho_down"] is None or item["rho_full"] is None
            else round(item["rho_down"] - item["rho_full"], 4)
        )
        for key, item in pairs.items()
    }
    qb = quality_for(
        n,
        min_n=MIN_TAIL_DEPENDENCE,
        sources=["market.candles"],
        align_method="row_complete_case",
        timezone="UTC",
    )
    n_tail = int(d["n_down"])
    if n_tail < MIN_TAIL_EVENTS:
        qb = _degrade(qb, "tail_events_lt_30")
    strongest = max(
        (key for key in amplifications if amplifications[key] is not None),
        key=lambda key: amplifications[key],
        default=None,
    )
    head = f"{symbol} " if symbol else ""
    if strongest is None:
        detail = "下行/上行尾相关不可计算（切尾样本不足）"
    else:
        item = pairs[strongest]
        detail = (
            f"尾部共现最强放大的资产对 {strongest}：下行尾 ρ={item['rho_down']}，"
            f"全样本 ρ={item['rho_full']}（差 {amplifications[strongest]:+.3f}），"
            f"上行尾 ρ={item['rho_up']}"
        )
    tail_sample = f"下行尾样本 {n_tail} 天（q={qq}）"
    answer = (
        f"{head}共 {len(names)} 个资产、{len(pairs)} 个两两组合，{tail_sample}；{detail}。"
        f"{'尾部共现样本 <30 天，仅作短样本描述，等级降级。' if n_tail < MIN_TAIL_EVENTS else ''}"
        f"尾部相关只描述同期共跌/共涨程度，不含因果。{CAVEAT}。"
    )
    return build(
        capability="D-G25",
        intent=INTENT_CORRELATION,
        answer=answer,
        data={
            "capabilities": {
                "D-G25": {
                    "gate": "ok",
                    "methods": ["P13"],
                    "q": qq,
                    "n_tail": n_tail,
                    "n": n,
                    "pairs": pairs,
                    "amplification": amplifications,
                    "strongest_pair": strongest,
                }
            },
            "params": {
                "min_n": MIN_TAIL_DEPENDENCE,
                "tail_event_gate": MIN_TAIL_EVENTS,
                "q": qq,
                "upper_tail_by_sign_flip": True,
                "assets": names,
            },
            "symbol": symbol or None,
        },
        quality_block=qb,
        trace_id=trace_id,
    )


# ---------------- D-J05 周期/频谱 ----------------


def cycle_spectrum(
    series: Sequence[Any],
    *,
    dates: Optional[Sequence[Any]] = None,
    symbol: str = "",
    reference_days: int = CYCLE_REFERENCE_DAYS,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """T25 谱分析主周期 + T26 周期强度 + C14 月度一致性；按历史覆盖周期数门禁。"""
    values = _floats(series)
    n = len(values)
    if n < MIN_CYCLE:
        return unavailable(
            capability="D-J05",
            intent=INTENT_CYCLE,
            reason=f"价格样本 {n} < {MIN_CYCLE}（频谱样本门禁）",
            trace_id=trace_id,
        )
    ds = _parse_dates(dates)
    if ds and len(ds) != n:
        return unavailable(
            capability="D-J05",
            intent=INTENT_CYCLE,
            reason="日期轴与价格长度不一致",
            trace_id=trace_id,
        )
    t25 = _call("T25", values)
    t26 = _call("T26", values)
    if t25["gate"] != "ok" or t26["gate"] != "ok":
        return unavailable(
            capability="D-J05",
            intent=INTENT_CYCLE,
            reason="频谱主周期计算失败（样本不足）",
            trace_id=trace_id,
        )
    spec = t25["result"]
    strength = t26["result"]
    returns = _returns(values)
    c14_call = {"gate": "skipped", "result": None}
    if ds and returns:
        c14_call = _call(
            "C14",
            {"returns": returns, "dates": [d.isoformat() for d in ds[1:][-len(returns) :]]},
        )
    c14 = c14_call["result"] if c14_call["gate"] == "ok" else None
    period = spec["period"]
    span_days = (ds[-1] - ds[0]).days if ds else None
    cycles = round(span_days / period, 2) if (span_days and period) else None
    q = quality_for(
        n,
        min_n=MIN_CYCLE,
        span=_span(ds) if ds else None,
        sources=["market.candles"],
        align_method="utc_daily_close",
        timezone="UTC",
    )
    notes: List[str] = []
    if not ds:
        q = _degrade(q, "dates_missing")
        notes.append("缺日期轴，无法判断历史覆盖了几个周期，周期样本不足，降级为频谱描述")
    elif span_days is not None and span_days < MIN_CYCLE_SPAN_DAYS:
        q = _degrade(q, "cycles_lt_2")
        notes.append(
            f"历史跨度 {span_days} 天 < {MIN_CYCLE_SPAN_DAYS} 天（≥2 个 1,460 日周期），"
            "样本跨度不足，周期结论降级为描述"
        )
    elif cycles is not None and cycles < 2:
        q = _degrade(q, "cycles_lt_2")
        notes.append(f"历史仅覆盖 {cycles} 个主周期（<2），周期样本不足，降级为描述")
    ref = max(1, int(reference_days))
    ratio = round(period / ref, 3) if period else None
    head = f"{symbol} " if symbol else ""
    period_txt = "未识别出显著主周期" if not period else f"主周期 {period:.0f} 天"
    strength_txt = "NA" if strength["power_ratio"] is None else f"{strength['power_ratio']:.2f}"
    cycle_txt = f"，历史覆盖约 {cycles} 个周期" if cycles is not None else ""
    ref_txt = (
        f"，与 {ref} 天参照周期比 {ratio}"
        if ratio is not None and ref == CYCLE_REFERENCE_DAYS
        else ""
    )
    month_txt = ""
    if c14 and c14["table"]:
        best = max(c14["table"], key=lambda row: row["consistency"])
        month_txt = (
            f"；月度一致性最高为 {best['month']} 月（{best['consistency'] * 100:.0f}%，"
            f"{best['years']} 年）"
        )
    note_text = f"{'；'.join(notes)}。" if notes else ""
    answer = (
        f"{head}去趋势频谱：{period_txt}，周期强度 {strength_txt}{cycle_txt}{ref_txt}{month_txt}。"
        f"{note_text}{CAVEAT}。"
    )
    return build(
        capability="D-J05",
        intent=INTENT_CYCLE,
        answer=answer,
        data={
            "capabilities": {
                "D-J05": {
                    "gate": "ok",
                    "methods": ["T25", "T26"] + (["C14"] if c14 else []),
                    "period": period,
                    "freq_index": spec["freq_index"],
                    "amplitude": spec["amplitude"],
                    "power_ratio": strength["power_ratio"],
                    "span_days": span_days,
                    "cycles": cycles,
                    "reference_days": ref,
                    "period_to_reference": ratio,
                    "month_consistency": c14,
                }
            },
            "params": {
                "min_n": MIN_CYCLE,
                "min_span_days": MIN_CYCLE_SPAN_DAYS,
                "reference_days": ref,
                "detrend": "linear",
                "as_of": ds[-1].isoformat() if ds else None,
            },
            "symbol": symbol or None,
        },
        quality_block=q,
        trace_id=trace_id,
    )


# ---------------- 统一调度（能力 ID → executor） ----------------


# 展示层四出口（D-E16–E19）真实实现在 aggregate/flow/lights，这里只做延迟导入薄壳：
# 避免 `capabilities/__init__` → stats → aggregate 在包初始化期形成循环依赖。
def aggregate_curve(**kwargs: Any) -> Dict[str, Any]:
    from .aggregate import aggregate_curve as impl

    return impl(**kwargs)


def class_board(**kwargs: Any) -> Dict[str, Any]:
    from .aggregate import class_board as impl

    return impl(**kwargs)


def flow_graph(**kwargs: Any) -> Dict[str, Any]:
    from .flow import flow_graph as impl

    return impl(**kwargs)


def lights(**kwargs: Any) -> Dict[str, Any]:
    from .lights import lights as impl

    return impl(**kwargs)


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
    "D-E16": aggregate_curve,
    "D-E17": class_board,
    "D-E18": flow_graph,
    "D-E19": lights,
    "D-G14": ewma_risk,
    "D-G16": portfolio_risk,
    "D-G19": ic_profile,
    "D-G20": quantile_monotonic,
    "D-G22": hac_significance,
    "D-G23": event_car_significance,
    "D-G25": tail_dependence,
    "D-J02": seasonal_adjustment,
    "D-J04": change_point,
    "D-J05": cycle_spectrum,
    "D-J22": dimension_reduction,
    "D-J24": correlation_network,
    "D-J30": pit_alignment,
    "D-A01": history_series,
    "D-A02": change_rate,
    "D-A03": cagr,
    "D-A04": percentile_rank,
    "D-A06": annualized_volatility,
    "D-A07": drawdown,
    "D-A08": yoy_change,
    "D-A09": mom_change,
    "D-A10": real_rate,
    "D-A11": rolling_correlation,
    "D-A12": lead_lag_correlation,
    "D-A13": extreme_frequency,
    "D-A15": etf_flow_rolling,
    "D-A16": stablecoin_growth,
    "D-B08": slope_trend,
    "D-B09": ath_drawdown,
    "D-G08": momentum_12_1,
    "D-G09": vol_target_scale,
}


# 共用执行器的能力 → 信封 intent（与 capability_manifest.yaml 一致）。
# correlation() 同时服务 D-E05/D-E06/D-E11，必须由调度层注入请求能力，否则信封会被错标为 D-E05。
_EXECUTOR_INTENTS = {
    "D-E05": INTENT_CORRELATION,
    "D-E06": INTENT_CORRELATION,
    "D-E11": INTENT_CROSS,
    "D-A07": INTENT_DRAWDOWN,
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
