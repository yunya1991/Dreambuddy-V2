# -*- coding: utf-8 -*-
"""季节性与日历效应（C 组，C01–C18）。

覆盖 METHOD_LIBRARY §5：C01–C18 全部已实现。

口径：
  - 输入 `data` 为日频收益序列（`returns`/`series`/`values` 或裸序列），
    `dates` 可走函数参数或 `data["dates"]`，支持 `date`/`datetime`/ISO 字符串/unix 秒；
  - 所有分组统计输出 `n`，跨组比较同时给 `p`（t 分布，`stats_core.t_two_sided_p`）；
  - C11 节假日日历由日期轴派生（工作日缺失=节假日，可由 DGS10/NASDAQCOM 等
    交易日完整的日线还原），也可显式传 `holidays`；连续缺口 >10 个工作日视为
    数据缺口而非节假日并计入 `excluded_gaps`；
  - 纯 stdlib，同输入同输出；`dates` 缺失或长度不符直接 ValueError（由上层收敛为退化门禁）。
"""

from __future__ import annotations

import bisect
import datetime as _dt
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import _helpers as H
from .registry import MethodChecks, register
from .stats_core import t_two_sided_p

_WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MAX_HOLIDAY_GAP_WEEKDAYS = 10


def _raw(data: Any) -> Any:
    if isinstance(data, Mapping):
        for key in ("returns", "series", "values", "x"):
            if key in data:
                return data[key]
        raise ValueError("C 组需要 data.returns / data.series")
    return data


def _parse_one(value: Any) -> _dt.datetime:
    if isinstance(value, _dt.datetime):
        return value
    if isinstance(value, _dt.date):
        return _dt.datetime(value.year, value.month, value.day)
    if isinstance(value, (int, float)):
        return _dt.datetime.fromtimestamp(float(value), _dt.timezone.utc).replace(tzinfo=None)
    text = str(value).strip()
    try:
        return _dt.datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return _dt.datetime.strptime(text[:10], "%Y-%m-%d")


def _rets_dates(
    data: Any, dates: Optional[Sequence[Any]] = None
) -> Tuple[List[float], List[_dt.datetime]]:
    raw = _raw(data)
    if isinstance(data, Mapping) and dates is None:
        dates = data.get("dates")
    if dates is None:
        raise ValueError("C 组需要 dates（日期序列）")
    ys = H.floats(raw)
    ds = [_parse_one(d) for d in dates]
    n = min(len(ys), len(ds))
    if n == 0:
        raise ValueError("empty series")
    return ys[:n], ds[:n]


def _group(ys: Sequence[float], keys: Sequence[Any]) -> Dict[Any, List[float]]:
    out: Dict[Any, List[float]] = {}
    for k, y in zip(keys, ys, strict=False):
        out.setdefault(k, []).append(y)
    return out


def _stats(vals: Sequence[float]) -> Dict[str, Any]:
    return {
        "mean": H.r6(H.mean(vals)),
        "median": H.r6(H.median(list(vals))),
        "win_rate": H.r4(sum(1 for v in vals if v > 0) / len(vals)) if vals else None,
        "n": len(vals),
    }


def _diff_t(a: Sequence[float], b: Sequence[float]) -> Dict[str, Any]:
    """两组均值差 + Welch t 与双侧 p。"""
    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return {"diff": None, "t": None, "p": None}
    v1, v2 = H.var(a) / n1, H.var(b) / n2
    se = (v1 + v2) ** 0.5
    diff = H.mean(a) - H.mean(b)
    if se <= H.EPS:
        # 两组均为常数：均值差可报，t/p 无定义（避免 df 分母为 0）
        return {"diff": H.r6(diff), "t": None, "p": None}
    t = diff / se
    df = (v1 + v2) ** 2 / ((v1**2) / (n1 - 1) + (v2**2) / (n2 - 1))
    return {"diff": H.r6(diff), "t": H.r4(t), "p": t_two_sided_p(t, df) if t is not None else None}


# ---------------- synthetic cases ----------------


def _case(n: int = 400, *, step: int = 1) -> Dict[str, Any]:
    """构造 n 天日频序列（含跨月/跨周），收益按周末略高的确定性模式。"""
    start = _dt.datetime(2024, 1, 1)
    dates: List[str] = []
    rets: List[float] = []
    for i in range(n):
        d = start + _dt.timedelta(days=i * step)
        dates.append(d.strftime("%Y-%m-%d"))
        rets.append(0.001 if d.weekday() < 5 else 0.002)
    return {"data": {"returns": rets, "dates": dates}, "params": {}}


def _synth(expect: Mapping[str, Any], n: int = 400) -> Dict[str, Any]:
    case = _case(n)
    case["expect"] = dict(expect)
    return case


# ======================================================================
# 月份维度（C01–C04、C14、C15）
# ======================================================================


@register(
    "C01",
    name="月份效应",
    group="C",
    layer="D1",
    input_kind="series",
    min_n=60,
    output_schema=("table", "n"),
    notes="按自然月分组收益均值/中位数/胜率；口径=自然月非月内节奏",
    checks=MethodChecks(synthetic=lambda: _synth({"result.table.0.month": 1}, n=400)),
)
def c01_month_effect(data: Any, dates: Optional[Sequence[Any]] = None, **_: Any) -> Dict[str, Any]:
    ys, ds = _rets_dates(data, dates)
    table = [
        dict(month=int(m), **_stats(v))
        for m, v in sorted(_group(ys, [d.month for d in ds]).items())
    ]
    return {"table": table, "n": len(ys)}


@register(
    "C02",
    name="月份胜率",
    group="C",
    layer="D1",
    input_kind="series",
    min_n=60,
    output_schema=("table", "n"),
    notes="按月 r>0 占比",
    checks=MethodChecks(synthetic=lambda: _synth({"result.table.0.win_rate": 1.0}, n=400)),
)
def c02_month_win_rate(
    data: Any, dates: Optional[Sequence[Any]] = None, **_: Any
) -> Dict[str, Any]:
    ys, ds = _rets_dates(data, dates)
    table = []
    for m, vals in sorted(_group(ys, [d.month for d in ds]).items()):
        table.append(
            {
                "month": int(m),
                "win_rate": H.r4(sum(1 for v in vals if v > 0) / len(vals)),
                "n": len(vals),
            }
        )
    return {"table": table, "n": len(ys)}


@register(
    "C03",
    name="月份次数统计",
    group="C",
    layer="D1",
    input_kind="series",
    min_n=60,
    output_schema=("table", "n"),
    notes="每月上涨/下跌/持平次数",
    checks=MethodChecks(synthetic=lambda: _synth({"result.table.0.month": 1}, n=400)),
)
def c03_month_counts(data: Any, dates: Optional[Sequence[Any]] = None, **_: Any) -> Dict[str, Any]:
    ys, ds = _rets_dates(data, dates)
    table = []
    for m, vals in sorted(_group(ys, [d.month for d in ds]).items()):
        up = sum(1 for v in vals if v > 0)
        down = sum(1 for v in vals if v < 0)
        table.append(
            {"month": int(m), "up": up, "down": down, "flat": len(vals) - up - down, "n": len(vals)}
        )
    return {"table": table, "n": len(ys)}


@register(
    "C04",
    name="月份排名",
    group="C",
    layer="D1",
    input_kind="series",
    min_n=60,
    output_schema=("ranking", "n"),
    notes="按月份均值降序排名（纯排序，无 p 值）",
    checks=MethodChecks(synthetic=lambda: _synth({"result.ranking.0.rank": 1}, n=400)),
)
def c04_month_ranking(data: Any, dates: Optional[Sequence[Any]] = None, **_: Any) -> Dict[str, Any]:
    ys, ds = _rets_dates(data, dates)
    table = [
        {"month": int(m), "mean": H.r6(H.mean(v)), "n": len(v)}
        for m, v in _group(ys, [d.month for d in ds]).items()
    ]
    table.sort(key=lambda row: row["mean"], reverse=True)
    ranking = [dict(rank=i + 1, **row) for i, row in enumerate(table)]
    return {"ranking": ranking, "n": len(ys)}


@register(
    "C14",
    name="月份一致性",
    group="C",
    layer="D2",
    input_kind="series",
    min_n=60,
    output_schema=("table", "n"),
    notes="按年×月聚合成月收益，再统计同月跨年同向比例（涨月占比或跌月占比取大者）",
    checks=MethodChecks(synthetic=lambda: _synth({"result.table.0.consistency": 1.0}, n=400)),
)
def c14_month_consistency(
    data: Any, dates: Optional[Sequence[Any]] = None, **_: Any
) -> Dict[str, Any]:
    ys, ds = _rets_dates(data, dates)
    monthly = _monthly_returns(ys, ds)
    table = []
    for month in range(1, 13):
        signs = [
            1 if ret > 0 else (-1 if ret < 0 else 0)
            for (y, m), ret in monthly.items()
            if m == month
        ]
        if not signs:
            continue
        up = sum(1 for s in signs if s > 0)
        consistency = max(up, len(signs) - up) / len(signs)
        table.append(
            {"month": month, "years": len(signs), "up_years": up, "consistency": H.r4(consistency)}
        )
    return {"table": table, "n": len(ys)}


@register(
    "C15",
    name="月度转移",
    group="C",
    layer="D1",
    input_kind="series",
    min_n=60,
    output_schema=("matrix", "n"),
    notes="上月涨跌 → 本月涨跌 2×2 计数矩阵",
    checks=MethodChecks(synthetic=lambda: _synth({"result.labels.0": "up"}, n=400)),
)
def c15_month_transition(
    data: Any, dates: Optional[Sequence[Any]] = None, **_: Any
) -> Dict[str, Any]:
    ys, ds = _rets_dates(data, dates)
    monthly = [ret for _, ret in sorted(_monthly_returns(ys, ds).items())]
    matrix = [[0, 0], [0, 0]]
    for prev, cur in zip(monthly, monthly[1:], strict=False):
        matrix[0 if prev > 0 else 1][0 if cur > 0 else 1] += 1
    total = sum(sum(row) for row in matrix)
    probs = [[H.r4(c / sum(row)) if sum(row) else None for c in row] for row in matrix]
    return {
        "labels": ["up", "down"],
        "matrix": matrix,
        "prob": probs,
        "months": len(monthly),
        "transitions": total,
    }


def _monthly_returns(
    ys: Sequence[float], ds: Sequence[_dt.datetime]
) -> Dict[Tuple[int, int], float]:
    buckets: Dict[Tuple[int, int], List[float]] = {}
    for y, d in zip(ys, ds, strict=False):
        buckets.setdefault((d.year, d.month), []).append(y)
    out: Dict[Tuple[int, int], float] = {}
    for key, vals in buckets.items():
        acc = 1.0
        for v in vals:
            acc *= 1.0 + v
        out[key] = acc - 1.0
    return out


# ======================================================================
# 星期 / 小时 / 月内日 / 季度（C05–C07、C09）
# ======================================================================


@register(
    "C05",
    name="星期效应",
    group="C",
    layer="D1",
    input_kind="series",
    min_n=30,
    output_schema=("table", "n"),
    notes="按 weekday 分组（0=周一，含周末，加密 7×24）",
    checks=MethodChecks(synthetic=lambda: _synth({"result.table.0.mean": 0.001}, n=400)),
)
def c05_weekday_effect(
    data: Any, dates: Optional[Sequence[Any]] = None, **_: Any
) -> Dict[str, Any]:
    ys, ds = _rets_dates(data, dates)
    table = [
        dict(weekday=int(w), label=_WEEKDAY_LABELS[w], **_stats(v))
        for w, v in sorted(_group(ys, [d.weekday() for d in ds]).items())
    ]
    return {"table": table, "n": len(ys)}


@register(
    "C06",
    name="小时效应",
    group="C",
    layer="D1",
    input_kind="series",
    min_n=24,
    output_schema=("table", "hour_available", "n"),
    notes="按小时分组；日频数据全为 0 点时 hour_available=false，上层不得据此下结论",
    checks=MethodChecks(synthetic=lambda: _synth({"result.hour_available": False}, n=400)),
)
def c06_hour_effect(data: Any, dates: Optional[Sequence[Any]] = None, **_: Any) -> Dict[str, Any]:
    ys, ds = _rets_dates(data, dates)
    hours = [d.hour for d in ds]
    table = [dict(hour=int(h), **_stats(v)) for h, v in sorted(_group(ys, hours).items())]
    return {"table": table, "hour_available": len(set(hours)) > 1, "n": len(ys)}


@register(
    "C07",
    name="月内日效应",
    group="C",
    layer="D1",
    input_kind="series",
    min_n=60,
    output_schema=("table", "n"),
    notes="按 day-of-month（1–31）分组",
    checks=MethodChecks(synthetic=lambda: _synth({"result.table.0.day": 1}, n=400)),
)
def c07_day_of_month(data: Any, dates: Optional[Sequence[Any]] = None, **_: Any) -> Dict[str, Any]:
    ys, ds = _rets_dates(data, dates)
    table = [
        dict(day=int(d), **_stats(v)) for d, v in sorted(_group(ys, [x.day for x in ds]).items())
    ]
    return {"table": table, "n": len(ys)}


@register(
    "C09",
    name="季度效应",
    group="C",
    layer="D1",
    input_kind="series",
    min_n=60,
    output_schema=("table", "n"),
    notes="按季度分组",
    checks=MethodChecks(synthetic=lambda: _synth({"result.table.0.quarter": 1}, n=400)),
)
def c09_quarter_effect(
    data: Any, dates: Optional[Sequence[Any]] = None, **_: Any
) -> Dict[str, Any]:
    ys, ds = _rets_dates(data, dates)
    groups = _group(ys, [(d.month - 1) // 3 + 1 for d in ds])
    table = [dict(quarter=int(q), **_stats(v)) for q, v in sorted(groups.items())]
    return {"table": table, "n": len(ys)}


# ======================================================================
# 月初/月末、半年度、年内位置、季节性强度（C08、C10、C12、C13）
# ======================================================================


@register(
    "C08",
    name="月初/月末效应",
    group="C",
    layer="D2",
    input_kind="series",
    min_n=60,
    output_schema=("first_mean", "last_mean", "diff", "t", "p", "n"),
    notes="每月前 3 日 vs 后 3 日；Welch t",
    checks=MethodChecks(synthetic=lambda: _synth({"result.n": 400}, n=400)),
)
def c08_month_edge(data: Any, dates: Optional[Sequence[Any]] = None, **_: Any) -> Dict[str, Any]:
    ys, ds = _rets_dates(data, dates)
    last_days: Dict[Tuple[int, int], int] = {}
    for d in ds:
        key = (d.year, d.month)
        last_days[key] = max(last_days.get(key, 0), d.day)
    first, last = [], []
    for y, d in zip(ys, ds, strict=False):
        if d.day <= 3:
            first.append(y)
        elif d.day > last_days[(d.year, d.month)] - 3:
            last.append(y)
    cmp = _diff_t(first, last)
    return {
        "first_mean": H.r6(H.mean(first)) if first else None,
        "last_mean": H.r6(H.mean(last)) if last else None,
        "first_n": len(first),
        "last_n": len(last),
        **cmp,
        "n": len(ys),
    }


@register(
    "C10",
    name="年内位置",
    group="C",
    layer="D1",
    input_kind="series",
    min_n=30,
    output_schema=("points", "n"),
    notes="距年初天数 + 当期年内位置分位",
    checks=MethodChecks(synthetic=lambda: _synth({"result.n": 400}, n=400)),
)
def c10_year_position(data: Any, dates: Optional[Sequence[Any]] = None, **_: Any) -> Dict[str, Any]:
    ys, ds = _rets_dates(data, dates)
    points = [
        {"doy": d.timetuple().tm_yday, "value": H.r6(v)} for v, d in zip(ys, ds, strict=False)
    ]
    doy_now = points[-1]["doy"]
    below = sum(1 for p in points if p["doy"] <= doy_now)
    return {"points": points, "doy": doy_now, "percentile": H.r4(below / len(points)), "n": len(ys)}


@register(
    "C12",
    name="半年度对比",
    group="C",
    layer="D2",
    input_kind="series",
    min_n=60,
    output_schema=("h1_mean", "h2_mean", "diff", "t", "p", "n"),
    notes="H1（1–6 月）vs H2（7–12 月）",
    checks=MethodChecks(synthetic=lambda: _synth({"result.n": 400}, n=400)),
)
def c12_half_year(data: Any, dates: Optional[Sequence[Any]] = None, **_: Any) -> Dict[str, Any]:
    ys, ds = _rets_dates(data, dates)
    h1 = [y for y, d in zip(ys, ds, strict=False) if d.month <= 6]
    h2 = [y for y, d in zip(ys, ds, strict=False) if d.month > 6]
    cmp = _diff_t(h1, h2)
    return {
        "h1_mean": H.r6(H.mean(h1)) if h1 else None,
        "h2_mean": H.r6(H.mean(h2)) if h2 else None,
        "h1_n": len(h1),
        "h2_n": len(h2),
        **cmp,
        "n": len(ys),
    }


@register(
    "C13",
    name="季节性强度",
    group="C",
    layer="D2",
    input_kind="series",
    min_n=60,
    output_schema=("strength", "between_var", "n"),
    notes="月度组间方差 / 总方差（ANOVA 式分解，非 STL 季节项）",
    checks=MethodChecks(synthetic=lambda: _synth({"result.n": 400}, n=400)),
)
def c13_seasonal_strength(
    data: Any, dates: Optional[Sequence[Any]] = None, **_: Any
) -> Dict[str, Any]:
    ys, ds = _rets_dates(data, dates)
    groups = [v for v in _group(ys, [d.month for d in ds]).values() if v]
    total_var = H.var(ys) if len(ys) > 1 else 0.0
    if not groups or total_var <= H.EPS:
        return {"strength": None, "between_var": None, "n": len(ys)}
    grand = H.mean(ys)
    between = sum(len(g) * (H.mean(g) - grand) ** 2 for g in groups) / len(ys)
    return {
        "strength": H.r4(between / total_var),
        "between_var": H.r6(between),
        "months": len(groups),
        "n": len(ys),
    }


# ======================================================================
# 同日历年 / 剩余交易日 / 多资产周期对齐（C16–C18）
# ======================================================================


@register(
    "C16",
    name="同日历年分位",
    group="C",
    layer="D1",
    input_kind="series",
    min_n=60,
    output_schema=("month", "day", "percentile", "n"),
    notes="以最新日期的 (月,日) 为锚，取历史同月同日收益分布给当期水平分位",
    checks=MethodChecks(synthetic=lambda: _synth({"result.hist_n": "non_empty"}, n=400)),
)
def c16_same_day_percentile(
    data: Any, dates: Optional[Sequence[Any]] = None, **_: Any
) -> Dict[str, Any]:
    ys, ds = _rets_dates(data, dates)
    month, day = ds[-1].month, ds[-1].day
    hist = [y for y, d in zip(ys, ds, strict=False) if (d.month, d.day) == (month, day)]
    value = ys[-1]
    below = sum(1 for v in hist if v <= value)
    return {
        "month": month,
        "day": day,
        "value": H.r6(value),
        "percentile": H.r4(below / len(hist)) if hist else None,
        "hist_n": len(hist),
        "n": len(ys),
    }


@register(
    "C17",
    name="剩余交易日统计",
    group="C",
    layer="D2",
    input_kind="series",
    min_n=60,
    output_schema=("current", "hist_mean", "diff", "n_years"),
    notes="本月已实现累计收益 vs 历年同月同进度（同 day-of-month）均值",
    checks=MethodChecks(synthetic=lambda: _synth({"result.month": 2}, n=400)),
)
def c17_month_to_date(data: Any, dates: Optional[Sequence[Any]] = None, **_: Any) -> Dict[str, Any]:
    ys, ds = _rets_dates(data, dates)
    anchor = ds[-1]
    cur, hist = 1.0, []
    yearly: Dict[int, float] = {}
    for y, d in zip(ys, ds, strict=False):
        if d.month == anchor.month and d.day <= anchor.day:
            yearly[d.year] = yearly.get(d.year, 1.0) * (1.0 + y)
    for year, acc in yearly.items():
        if year == anchor.year:
            cur = acc
        elif year != anchor.year:
            hist.append(acc - 1.0)
    return {
        "month": anchor.month,
        "day": anchor.day,
        "current": H.r6(cur - 1.0),
        "hist_mean": H.r6(H.mean(hist)) if hist else None,
        "diff": H.r6((cur - 1.0) - H.mean(hist)) if hist else None,
        "n_years": len(hist),
        "n": len(ys),
    }


def _synth_pair(expect: Mapping[str, Any], n: int = 400) -> Dict[str, Any]:
    case = _case(n)
    rets, dates = case["data"]["returns"], case["data"]["dates"]
    case["data"] = {"a": rets, "b": list(rets), "dates": dates}
    case["expect"] = dict(expect)
    return case


@register(
    "C18",
    name="周期对齐（多资产）",
    group="C",
    layer="D2",
    input_kind="pairs",
    min_n=60,
    output_schema=("ratio", "pairs", "n"),
    notes="两资产月收益同向率；data={a,b,dates}，按自然月聚合后比较符号",
    checks=MethodChecks(synthetic=lambda: _synth_pair({"result.ratio": 1.0})),
)
def c18_cycle_alignment(
    data: Any, dates: Optional[Sequence[Any]] = None, **_: Any
) -> Dict[str, Any]:
    if not isinstance(data, Mapping) or "a" not in data or "b" not in data:
        raise ValueError("C18 needs data.a / data.b")
    ds = dates if dates is not None else data.get("dates")
    if ds is None:
        raise ValueError("C18 needs dates")
    a_ret, a_dates = _rets_dates(data["a"], ds)
    b_ret, b_dates = _rets_dates(data["b"], ds)
    ma = _monthly_returns(a_ret, a_dates)
    mb = _monthly_returns(b_ret, b_dates)
    keys = sorted(set(ma) & set(mb))
    same = sum(1 for k in keys if (ma[k] > 0) == (mb[k] > 0))
    return {
        "ratio": H.r4(same / len(keys)) if keys else None,
        "pairs": same,
        "months": len(keys),
        "n": min(len(a_ret), len(b_ret)),
    }


def _case_holidays(
    business_days: int = 300, holiday_idx: Tuple[int, ...] = (40, 90, 140, 190)
) -> Dict[str, Any]:
    """构造仅工作日交易的序列：指定工作日为节假日（从序列中缺失），节前收益 0.01。"""
    days: List[_dt.date] = []
    cursor = _dt.date(2024, 1, 1)
    while len(days) < business_days:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += _dt.timedelta(days=1)
    holidays = set(holiday_idx)
    dates: List[str] = []
    rets: List[float] = []
    for i, day in enumerate(days):
        if i in holidays:
            continue
        dates.append(day.isoformat())
        rets.append(0.01 if (i + 1) in holidays else 0.001)
    return {"data": {"returns": rets, "dates": dates}, "params": {}}


def derive_holidays(ds: Sequence[_dt.date]) -> Tuple[List[_dt.date], int]:
    """从日期轴派生节假日：工作日缺失=节假日；返回 (节假日, 超长缺口工作日数)。

    周末不计缺口；连续缺失 >`MAX_HOLIDAY_GAP_WEEKDAYS` 个工作日视为数据缺口，
    不当作节假日（避免长停更/停牌被误判）。
    """
    unique = sorted(set(ds))
    if len(unique) < 2:
        return [], 0
    present = set(unique)
    holidays: List[_dt.date] = []
    excluded = 0
    gap: List[_dt.date] = []

    def flush() -> None:
        nonlocal gap, excluded
        if not gap:
            return
        if len(gap) <= MAX_HOLIDAY_GAP_WEEKDAYS:
            holidays.extend(gap)
        else:
            excluded += len(gap)
        gap = []

    cursor = unique[0] + _dt.timedelta(days=1)
    while cursor <= unique[-1]:
        if cursor in present:
            flush()
        elif cursor.weekday() < 5:
            gap.append(cursor)
        cursor += _dt.timedelta(days=1)
    flush()
    return holidays, excluded


@register(
    "C11",
    name="节假日前效应",
    group="C",
    layer="D2",
    input_kind="events",
    min_n=60,
    output_schema=(
        "pre_mean",
        "base_mean",
        "diff",
        "t",
        "p",
        "n_pre",
        "n_holidays",
        "excluded_gaps",
        "calendar",
        "n",
    ),
    notes=(
        "节假日（工作日缺失=节假日，可由 DGS10/NASDAQCOM 日线派生）前 lookback 个交易日收益"
        " vs 非节前基线，Welch t；显式 holidays 优先，>10 工作日缺口视为数据缺口并披露"
    ),
    checks=MethodChecks(
        synthetic=lambda: dict(
            _case_holidays(),
            expect={
                "result.n_holidays": 4,
                "result.n_pre": 4,
                "result.pre_mean": 0.01,
                "result.calendar": "derived",
            },
        )
    ),
)
def c11_pre_holiday(
    data: Any,
    dates: Optional[Sequence[Any]] = None,
    holidays: Optional[Sequence[Any]] = None,
    lookback: int = 1,
    **_: Any,
) -> Dict[str, Any]:
    ys, ds = _rets_dates(data, dates)
    obs = [d.date() for d in ds]
    if holidays:
        holiday_dates = sorted({_parse_one(h).date() for h in holidays})
        excluded = 0
        source = "explicit"
    else:
        holiday_dates, excluded = derive_holidays(obs)
        source = "derived"
    lb = max(1, int(lookback))
    positions: List[int] = []
    for holiday in holiday_dates:
        idx = bisect.bisect_left(obs, holiday) - 1
        if 0 <= idx < len(ys):
            positions.append(idx)
    pre_idx = {k for idx in positions for k in range(idx, max(-1, idx - lb), -1) if k >= 0}
    pre = [ys[i] for i in sorted(pre_idx)]
    base = [ys[i] for i in range(len(ys)) if i not in pre_idx]
    cmp = _diff_t(pre, base)
    return {
        "pre_mean": H.r6(H.mean(pre)) if pre else None,
        "base_mean": H.r6(H.mean(base)) if base else None,
        **cmp,
        "n_pre": len(pre),
        "n_base": len(base),
        "n_holidays": len(positions),
        "excluded_gaps": excluded,
        "calendar": source,
        "lookback": lb,
        "pre_dates": [obs[i].isoformat() for i in sorted(pre_idx)][:50],
        "n": len(ys),
    }
