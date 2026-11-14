# -*- coding: utf-8 -*-
"""时间序列结构（T）与金融专用（F）补充。

覆盖 METHOD_LIBRARY：
  §4 T01–T28（全量）
  §9 F07–F26（F01–F06 已在 conditional.py）

口径冻结（METHOD_LIBRARY §16）：
  - T08/T09 直接复用 `persistence.metrics.trend_slope`（对数价格 OLS，未做 HAC）
  - T13 复用 `hurst_rs`、T14 复用 `variance_ratio`、T20/T21 复用 `ar1_halflife`
  - T24 复用 `transition_matrix`、F18 复用 `run_length_stats`
  - 价格类方法输入为**价格序列**，收益类方法输入为**简单收益序列**
  - T05/T06 优先 statsmodels，缺失时用 OLS / LM 统计量 + 临界值线性插值 p（简化口径，结果中 `method` 标注）
  - T10 优先 statsmodels STL，缺失时用经典分解（居中 MA + 相位均值，简化口径）
  - T18 未安装 arch：方差目标 + 固定网格搜索的确定性 GARCH(1,1) 近似（简化口径）
  - T23 未安装 ruptures：二元分割 + BIC 惩罚的 PELT 近似（简化口径）
  - T25/T26 为纯 stdlib DFT（rfft 同口径），无随机
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..persistence._stats import pearson
from ..persistence.constants import PersistenceError
from ..persistence.metrics import (
    ar1_halflife,
    hurst_rs,
    run_length_stats,
    transition_matrix,
    trend_slope,
    variance_ratio,
)
from . import _helpers as H
from .registry import MethodChecks, register

_S = H.series
_EPS = H.EPS


def _guard(fn, defaults: Mapping[str, Any], *args: Any, **kwargs: Any) -> Dict[str, Any]:
    try:
        return fn(*args, **kwargs)
    except (PersistenceError, ValueError, ZeroDivisionError):
        return dict(defaults)


def returns_of(prices: Sequence[float]) -> List[float]:
    """简单收益（r_t = P_t/P_{t−1} − 1，首点丢弃；非正值跳过）。"""
    out: List[float] = []
    for a, b in zip(prices, prices[1:], strict=False):
        out.append(0.0 if a <= 0 else b / a - 1.0)
    return out


def _synth(values: Sequence[float], **params: Any) -> Dict[str, Any]:
    return {"data": {"series": list(values)}, "params": dict(params)}


def _expect(values: Sequence[float], expects: Mapping[str, Any], **params: Any) -> Dict[str, Any]:
    case = _synth(values, **params)
    case["expect"] = dict(expects)
    return case


def _pacf(xs: Sequence[float], max_lag: int) -> List[Optional[float]]:
    """Durbin-Levinson 递推 PACF。"""
    r = H.acf(xs, max_lag)
    if any(v is None for v in r):
        return [None] * max_lag
    rho = [1.0] + [float(v) for v in r]  # rho[k]=ACF(k)
    phi = [[0.0] * (max_lag + 1) for _ in range(max_lag + 1)]
    out: List[Optional[float]] = []
    for k in range(1, max_lag + 1):
        if k == 1:
            phi[1][1] = rho[1]
        else:
            num = rho[k] - sum(phi[k - 1][j] * rho[k - j] for j in range(1, k))
            den = 1.0 - sum(phi[k - 1][j] * rho[j] for j in range(1, k))
            phi[k][k] = num / den if abs(den) > _EPS else 0.0
            for j in range(1, k):
                phi[k][j] = phi[k - 1][j] - phi[k][k] * phi[k - 1][k - j]
        out.append(H.r4(phi[k][k]))
    return out


def _panel_map(data: Any) -> Dict[str, List[float]]:
    """面板输入：{"series": {name: [...]}} 或 {name: [...]}。"""
    if not isinstance(data, Mapping):
        raise ValueError("panel data must be a mapping of name -> series")
    inner = data.get("series")
    if isinstance(inner, Mapping):
        return {str(k): H.clean(v) for k, v in inner.items()}
    return {
        str(k): H.clean(v)
        for k, v in data.items()
        if isinstance(v, Sequence) and not isinstance(v, str)
    }


def _event_indices(data: Any) -> List[int]:
    """事件输入：list[int] / list[{index|i|t}] / {"events": [...]}。"""
    raw = None
    if isinstance(data, Mapping):
        for key in ("events", "event_index", "event_indices", "indices"):
            if key in data:
                raw = data[key]
                break
    else:
        raw = data
    if raw is None:
        raise ValueError("events data must contain event indices")
    out: List[int] = []
    for e in raw:
        if isinstance(e, Mapping):
            val = e.get("index", e.get("i", e.get("t")))
        else:
            val = e
        if val is None:
            raise ValueError("event item missing index")
        out.append(int(val))
    return out


def _event_prices(data: Any) -> List[float]:
    if isinstance(data, Mapping):
        for key in ("prices", "price", "series", "close", "closes"):
            if key in data:
                return H.clean(data[key])
    raise ValueError("event study needs a price series")


def _ols_t_stat(y: Sequence[float], cols: Sequence[Sequence[float]]) -> Optional[float]:
    """最小二乘第 2 个回归元的 t 统计量（第 1 列为常数项）。"""
    try:
        import numpy as np  # noqa: PLC0415
    except ImportError:
        return None
    x = np.asarray(cols, dtype=float)
    yv = np.asarray(y, dtype=float)
    if x.ndim != 2 or x.shape[0] != yv.shape[0] or x.shape[1] < 2:
        return None
    try:
        beta, *_ = np.linalg.lstsq(x, yv, rcond=None)
        resid = yv - x @ beta
        dof = x.shape[0] - x.shape[1]
        if dof <= 0:
            return None
        s2 = float(resid @ resid) / dof
        cov = s2 * np.linalg.inv(x.T @ x)
        se = float(np.sqrt(cov[1, 1]))
    except (ValueError, ZeroDivisionError, np.linalg.LinAlgError):
        return None
    return float(beta[1]) / se if se > _EPS else None


def _interp_p(stat: float, points: Sequence[Sequence[float]]) -> float:
    """按临界值表线性插值 p（points 为按 stat 升序的 (stat,p)）。"""
    if stat <= points[0][0]:
        return float(points[0][1])
    if stat >= points[-1][0]:
        return float(points[-1][1])
    for (s0, p0), (s1, p1) in zip(points, points[1:], strict=False):
        if s0 <= stat <= s1:
            frac = (stat - s0) / (s1 - s0) if s1 > s0 else 0.0
            return float(p0 + frac * (p1 - p0))
    return float(points[-1][1])


def _dft_power(xs: Sequence[float]) -> List[tuple]:
    """去线性趋势后的单边 DFT 功率 [(k, |X_k|²)]，k=1..n//2（纯 stdlib）。"""
    n = len(xs)
    fit = H.ols_slope(xs)
    slope = fit["slope"]
    if slope is None:
        vals = [v - H.mean(xs) for v in xs]
    else:
        intercept = H.mean(xs) - slope * (n - 1) / 2.0
        vals = [v - (intercept + slope * i) for i, v in enumerate(xs)]
    out: List[tuple] = []
    for k in range(1, n // 2 + 1):
        w = 2.0 * math.pi * k / n
        re = im = 0.0
        for t, v in enumerate(vals):
            re += v * math.cos(w * t)
            im -= v * math.sin(w * t)
        out.append((k, re * re + im * im))
    return out


# ======================================================================
# T 组：时间序列结构
# ======================================================================


@register(
    "T01",
    name="自相关 ACF(k)",
    group="T",
    layer="D2",
    input_kind="series",
    min_n=10,
    output_schema=("acf", "max_lag", "n"),
    checks=MethodChecks(
        synthetic=lambda: {
            "data": [1.0, 2.0] * 20,
            "params": {"max_lag": 3},
            "expect": {"result.acf.1": "non_empty"},
        }
    ),
)
def t01_acf(data: Any, max_lag: int = 10) -> Dict[str, Any]:
    xs = _S(data)
    m = max(1, min(int(max_lag), max(1, len(xs) - 3)))
    return {"acf": H.acf(xs, m), "max_lag": m, "n": len(xs)}


@register(
    "T02",
    name="偏自相关 PACF(k)",
    group="T",
    layer="D2",
    input_kind="series",
    min_n=10,
    output_schema=("pacf", "max_lag", "n"),
    notes="Durbin-Levinson 递推",
)
def t02_pacf(data: Any, max_lag: int = 10) -> Dict[str, Any]:
    xs = _S(data)
    m = max(1, min(int(max_lag), max(1, len(xs) - 3)))
    return {"pacf": _pacf(xs, m), "max_lag": m, "n": len(xs)}


@register(
    "T03",
    name="交叉相关 CCF(k)",
    group="T",
    layer="D2",
    input_kind="pairs",
    min_n=10,
    output_schema=("lags", "ccf", "max_lag", "n"),
    notes="ccf(k)=corr(x_t, y_{t+k})；k>0 表示 x 领先 y",
)
def t03_ccf(data: Mapping[str, Any], max_lag: int = 10) -> Dict[str, Any]:
    xs, ys = H.two(data)
    n = len(xs)
    m = max(1, min(int(max_lag), n - 4))
    lags, vals = [], []
    for k in range(-m, m + 1):
        if k >= 0:
            a, b = xs[: n - k], ys[k:]
        else:
            a, b = xs[-k:], ys[: n + k]
        lags.append(k)
        vals.append(H.r4(pearson(a, b)))
    return {"lags": lags, "ccf": vals, "max_lag": m, "n": n}


@register(
    "T04",
    name="最优领先/滞后",
    group="T",
    layer="D2",
    input_kind="pairs",
    min_n=10,
    output_schema=("lag", "ccf", "max_lag", "n"),
    notes="argmax|CCF|；lag>0 表示 x 领先 y",
)
def t04_best_lag(data: Mapping[str, Any], max_lag: int = 10) -> Dict[str, Any]:
    out = t03_ccf(data, max_lag)
    pairs = [
        (abs(v), lag) for lag, v in zip(out["lags"], out["ccf"], strict=False) if v is not None
    ]
    if not pairs:
        return {"lag": None, "ccf": None, "max_lag": out["max_lag"], "n": out["n"]}
    best = max(pairs, key=lambda t: t[0])
    lag = best[1]
    ccf = out["ccf"][out["lags"].index(lag)]
    return {"lag": lag, "ccf": ccf, "max_lag": out["max_lag"], "n": out["n"]}


@register(
    "T05",
    name="ADF 单位根检验",
    group="T",
    layer="D3",
    input_kind="series",
    min_n=60,
    output_schema=("stat", "p", "used_lag", "n", "stationary", "method"),
    notes="H0=存在单位根；statsmodels adfuller(regression='c', autolag=None) 固定滞后；"
    "缺失时 OLS t 统计量 + DF 临界值线性插值 p（简化口径）",
)
def t05_adf(data: Any, max_lag: Optional[int] = None) -> Dict[str, Any]:
    xs = _S(data)
    n = len(xs)
    lag = int(max_lag) if max_lag else min(12, max(1, int(12 * (n / 100.0) ** 0.25)))
    lag = max(1, min(lag, max(1, n // 4)))
    stat: Optional[float] = None
    p: Optional[float] = None
    used = lag
    method = "statsmodels_adfuller"
    try:
        import warnings  # noqa: PLC0415

        from statsmodels.tsa.stattools import adfuller  # noqa: PLC0415

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = adfuller(xs, maxlag=lag, regression="c", autolag=None)
        stat, p, used = float(res[0]), float(res[1]), int(res[2])
    except Exception:  # noqa: BLE001 - 库缺失/数值失败均回退确定性 OLS
        method = "ols_t_fallback"
        dy = [xs[i] - xs[i - 1] for i in range(1, n)]
        rows, ys = [], []
        for t in range(lag + 1, n):
            rows.append([1.0, xs[t - 1]] + [dy[t - 1 - j] for j in range(1, lag + 1)])
            ys.append(dy[t - 1])
        stat = _ols_t_stat(ys, rows)
        if stat is not None:
            p = _interp_p(
                stat,
                [
                    (-4.0, 0.001),
                    (-3.43, 0.01),
                    (-2.86, 0.05),
                    (-2.57, 0.10),
                    (-1.94, 0.50),
                    (0.0, 0.85),
                    (2.0, 0.99),
                ],
            )
    stationary = None if p is None else bool(p < 0.05)
    return {
        "stat": H.r4(stat),
        "p": H.r6(p),
        "used_lag": used,
        "n": n,
        "stationary": stationary,
        "method": method,
    }


@register(
    "T06",
    name="KPSS 平稳性检验",
    group="T",
    layer="D3",
    input_kind="series",
    min_n=60,
    output_schema=("stat", "p", "lags", "n", "stationary", "method"),
    notes="H0=序列平稳（level）；statsmodels kpss(regression='c') 固定 nlags；"
    "缺失时自实现 LM 统计量 + 临界值线性插值 p（简化口径）",
)
def t06_kpss(data: Any, max_lag: Optional[int] = None) -> Dict[str, Any]:
    xs = _S(data)
    n = len(xs)
    lag = int(max_lag) if max_lag else max(1, int(4 * (n / 100.0) ** 0.25))
    lag = max(1, min(lag, max(1, n // 4)))
    stat: Optional[float] = None
    p: Optional[float] = None
    method = "statsmodels_kpss"
    try:
        import warnings  # noqa: PLC0415

        from statsmodels.tsa.stattools import kpss  # noqa: PLC0415

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = kpss(xs, regression="c", nlags=lag)
        stat, p, lag = float(res[0]), float(res[1]), int(res[2])
    except Exception:  # noqa: BLE001 - 库缺失/数值失败均回退自实现 LM
        method = "lm_fallback"
        mu = H.mean(xs)
        resid = [v - mu for v in xs]
        acc, cum = 0.0, []
        for e in resid:
            acc += e
            cum.append(acc)
        g0 = sum(e * e for e in resid) / n
        lrv = g0
        for j in range(1, lag + 1):
            gj = sum(resid[i] * resid[i - j] for i in range(j, n)) / n
            lrv += 2.0 * (1.0 - j / (lag + 1.0)) * gj
        if lrv > _EPS:
            stat = sum(s * s for s in cum) / (n * n * lrv)
            p = _interp_p(
                stat,
                [
                    (0.10, 0.20),
                    (0.347, 0.10),
                    (0.463, 0.05),
                    (0.574, 0.025),
                    (0.739, 0.01),
                    (1.20, 0.001),
                ],
            )
    stationary = None if p is None else bool(p > 0.05)
    return {
        "stat": H.r4(stat),
        "p": H.r6(p),
        "lags": lag,
        "n": n,
        "stationary": stationary,
        "method": method,
    }


@register(
    "T07",
    name="Ljung-Box 自相关检验",
    group="T",
    layer="D3",
    input_kind="series",
    min_n=10,
    output_schema=("q", "p", "df", "n"),
    notes="Q=n(n+2)Σ r_k²/(n−k)，χ²(m) 上尾",
)
def t07_ljung_box(data: Any, max_lag: int = 10) -> Dict[str, Any]:
    xs = _S(data)
    n = len(xs)
    m = max(1, min(int(max_lag), n - 3))
    rs = H.acf(xs, m)
    if any(v is None for v in rs):
        return {"q": None, "p": None, "df": m, "n": n}
    q = n * (n + 2) * sum(float(v) ** 2 / (n - k) for k, v in enumerate(rs, start=1))
    return {"q": H.r4(q), "p": H.r6(H.chi2_sf(q, m)), "df": m, "n": n}


@register(
    "T08",
    name="趋势斜率（OLS）",
    group="T",
    layer="D2",
    input_kind="series",
    min_n=30,
    output_schema=("slope_per_day", "annualized_log", "r2", "n"),
    notes="复用 persistence.metrics.trend_slope（对数价格 OLS）",
    checks=MethodChecks(
        synthetic=lambda: _expect(
            [100.0 * math.exp(0.001 * i) for i in range(60)],
            {"result.slope_per_day": 0.001, "result.r2": 1.0},
        )
    ),
)
def t08_trend_slope(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    out = _guard(
        trend_slope, {"slope_per_day": None, "annualized_log": None, "r2": None, "n": len(xs)}, xs
    )
    return {
        "slope_per_day": out.get("slope_per_day"),
        "annualized_log": out.get("annualized_log"),
        "r2": out.get("r2"),
        "n": out.get("n", len(xs)),
    }


@register(
    "T09",
    name="趋势显著性",
    group="T",
    layer="D2",
    input_kind="series",
    min_n=30,
    output_schema=("t", "p", "hac_corrected", "n"),
    notes="名义 t，未做 HAC 修正，仅作相对比较",
)
def t09_trend_significance(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    out = _guard(trend_slope, {"t": None, "p": None, "n": len(xs)}, xs)
    return {
        "t": out.get("t"),
        "p": out.get("p"),
        "hac_corrected": False,
        "n": out.get("n", len(xs)),
    }


@register(
    "T10",
    name="STL 分解",
    group="T",
    layer="D2",
    input_kind="series",
    min_n=60,
    output_schema=(
        "trend",
        "seasonal",
        "resid",
        "period",
        "trend_strength",
        "seasonal_strength",
        "n",
        "method",
    ),
    notes="statsmodels STL(robust=True) 固定 period；缺失时经典分解（居中 MA + 相位均值）"
    "，简化口径；trend+seasonal+resid 与输入逐点相等",
)
def t10_stl(data: Any, period: int = 7) -> Dict[str, Any]:
    xs = _S(data)
    n = len(xs)
    p = max(2, int(period))
    if n <= 2 * p:
        raise ValueError(f"STL needs more than 2 periods ({2 * p + 1} points)")
    trend: List[float] = []
    seasonal: List[float] = []
    resid: List[float] = []
    method = "statsmodels_stl"
    try:
        from statsmodels.tsa.seasonal import STL  # noqa: PLC0415

        fit = STL(xs, period=p, robust=True).fit()
        trend = [float(v) for v in fit.trend]
        seasonal = [float(v) for v in fit.seasonal]
        resid = [float(v) for v in fit.resid]
    except Exception:  # noqa: BLE001 - 库缺失/数值失败均回退经典分解
        method = "classical_fallback"
        half = p // 2
        for i in range(n):
            lo, hi = max(0, i - half), min(n, i + half + 1)
            trend.append(H.mean(xs[lo:hi]))
        detrended = [x - t for x, t in zip(xs, trend, strict=False)]
        phase_mean = [H.mean(detrended[i::p]) for i in range(p)]
        center = H.mean(phase_mean)
        seasonal = [phase_mean[i % p] - center for i in range(n)]
        resid = [x - t - s for x, t, s in zip(xs, trend, seasonal, strict=False)]
    var_x = H.var(xs)
    var_resid = H.var(resid)
    var_detrended = H.var([x - t for x, t in zip(xs, trend, strict=False)])
    trend_strength = max(0.0, 1.0 - var_resid / var_x) if var_x > _EPS else 0.0
    seasonal_strength = max(0.0, 1.0 - var_resid / var_detrended) if var_detrended > _EPS else 0.0
    return {
        "trend": [H.r6(v) for v in trend],
        "seasonal": [H.r6(v) for v in seasonal],
        "resid": [H.r6(v) for v in resid],
        "period": p,
        "trend_strength": H.r4(trend_strength),
        "seasonal_strength": H.r4(seasonal_strength),
        "n": n,
        "method": method,
    }


@register(
    "T11",
    name="移动平均去趋势",
    group="T",
    layer="D1",
    input_kind="series",
    min_n=3,
    output_schema=("detrended", "k", "n"),
)
def t11_detrend_ma(data: Any, k: int = 5) -> Dict[str, Any]:
    xs = _S(data)
    if k < 1 or k > len(xs):
        return {"detrended": [], "k": k, "n": len(xs)}
    out: List[Optional[float]] = []
    for i, v in enumerate(xs):
        out.append(None if i + 1 < k else H.r6(v - H.mean(xs[i + 1 - k : i + 1])))
    return {"detrended": out, "k": k, "n": len(xs)}


@register(
    "T12",
    name="差分（1 阶/季节）",
    group="T",
    layer="D1",
    input_kind="series",
    min_n=3,
    output_schema=("series", "order", "season", "n"),
)
def t12_difference(data: Any, season: int = 1) -> Dict[str, Any]:
    xs = _S(data)
    s = max(1, int(season))
    if len(xs) <= s:
        return {"series": [], "order": 1, "season": s, "n": len(xs)}
    return {
        "series": [H.r6(xs[i] - xs[i - s]) for i in range(s, len(xs))],
        "order": 1,
        "season": s,
        "n": len(xs),
    }


@register(
    "T13",
    name="Hurst 指数（R/S）",
    group="T",
    layer="D2",
    input_kind="series",
    min_n=64,
    output_schema=("h", "regime", "confidence", "loglog_r2", "n"),
    notes="复用 persistence.metrics.hurst_rs；输入应为收益序列",
)
def t13_hurst(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    defaults = {"h": None, "regime": None, "confidence": None, "loglog_r2": None, "n": len(xs)}
    out = _guard(hurst_rs, defaults, xs)
    return {k: out.get(k) for k in defaults}


@register(
    "T14",
    name="方差比检验",
    group="T",
    layer="D2",
    input_kind="series",
    min_n=30,
    output_schema=("vr", "z", "p", "q", "interpretation", "n"),
    notes="复用 persistence.metrics.variance_ratio；输入为收益序列",
)
def t14_variance_ratio(data: Any, q: int = 5) -> Dict[str, Any]:
    xs = _S(data)
    qq = max(2, int(q))
    defaults = {"vr": None, "z": None, "p": None, "q": qq, "interpretation": None, "n": len(xs)}
    out = _guard(variance_ratio, defaults, xs, qq)
    return {k: out.get(k) for k in defaults}


@register(
    "T15",
    name="波动率（年化）",
    group="T",
    layer="D1",
    input_kind="series",
    min_n=30,
    output_schema=("vol", "std", "periods", "n"),
    notes="输入为对数/简单收益；σ×√periods",
)
def t15_annualized_vol(data: Any, periods: int = 365) -> Dict[str, Any]:
    xs = _S(data)
    sd = H.std(xs) if len(xs) > 1 else 0.0
    return {
        "vol": H.r6(sd * math.sqrt(periods)),
        "std": H.r6(sd),
        "periods": int(periods),
        "n": len(xs),
    }


@register(
    "T16",
    name="滚动波动率",
    group="T",
    layer="D2",
    input_kind="series",
    min_n=5,
    output_schema=("series", "k", "periods", "n"),
    notes="输入为收益；输出年化滚动 σ",
)
def t16_rolling_vol(data: Any, k: int = 20, periods: int = 365) -> Dict[str, Any]:
    xs = _S(data)
    if k < 2 or k > len(xs):
        return {"series": [], "k": k, "periods": int(periods), "n": len(xs)}
    scale = math.sqrt(periods)
    out: List[Optional[float]] = []
    for i in range(len(xs)):
        out.append(None if i + 1 < k else H.r6(H.std(xs[i + 1 - k : i + 1]) * scale))
    return {"series": out, "k": k, "periods": int(periods), "n": len(xs)}


@register(
    "T17",
    name="波动率聚集（ACF of |r|）",
    group="T",
    layer="D2",
    input_kind="series",
    min_n=10,
    output_schema=("acf", "max_lag", "n"),
    notes="输入为收益；|r| 的 ACF",
)
def t17_vol_cluster(data: Any, max_lag: int = 10) -> Dict[str, Any]:
    xs = _S(data)
    m = max(1, min(int(max_lag), max(1, len(xs) - 3)))
    return {"acf": H.acf([abs(v) for v in xs], m), "max_lag": m, "n": len(xs)}


@register(
    "T18",
    name="GARCH(1,1) 拟合",
    group="T",
    layer="D3",
    input_kind="series",
    min_n=120,
    output_schema=(
        "params",
        "forecast",
        "omega",
        "alpha",
        "beta",
        "persistence",
        "forecast_vol",
        "loglik",
        "n",
        "method",
    ),
    notes="输入为收益序列；params={omega,alpha,beta}，forecast=σ²_{t+1}（方差），"
    "forecast_vol=√forecast；arch 未安装 → 方差目标 + 固定网格搜索的高斯拟极大似然"
    "（确定性、无随机，简化口径）",
)
def t18_garch(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    n = len(xs)
    var0 = sum(v * v for v in xs) / n
    if var0 <= _EPS:
        return {
            "params": {"omega": 0.0, "alpha": 0.0, "beta": 0.0},
            "forecast": 0.0,
            "omega": 0.0,
            "alpha": 0.0,
            "beta": 0.0,
            "persistence": 0.0,
            "forecast_vol": 0.0,
            "loglik": None,
            "n": n,
            "method": "degenerate",
        }

    def loglik(a: float, b: float) -> Optional[float]:
        w = var0 * (1.0 - a - b)
        if w <= 0.0:
            return None
        s2 = var0
        total = 0.0
        for v in xs:
            total += math.log(2.0 * math.pi * s2) + v * v / s2
            s2 = w + a * v * v + b * s2
        return -0.5 * total

    def search(
        alphas: Sequence[float],
        betas: Sequence[float],
        center_a: Optional[float] = None,
        center_b: Optional[float] = None,
    ):
        best = (None, center_a or 0.05, center_b or 0.90)
        for a in alphas:
            for b in betas:
                if a <= 0.0 or b <= 0.0 or a + b >= 0.999:
                    continue
                ll = loglik(a, b)
                if ll is not None and (best[0] is None or ll > best[0]):
                    best = (ll, a, b)
        return best

    ll, alpha, beta = search(
        [0.02 * i for i in range(1, 21)],
        [0.50 + 0.04 * i for i in range(13)],
    )
    if ll is not None:
        ll, alpha, beta = search(
            [alpha + 0.0025 * i for i in range(-4, 5)],
            [beta + 0.0025 * i for i in range(-4, 5)],
            alpha,
            beta,
        )
    if ll is None:
        return {
            "params": None,
            "forecast": None,
            "omega": None,
            "alpha": None,
            "beta": None,
            "persistence": None,
            "forecast_vol": None,
            "loglik": None,
            "n": n,
            "method": "grid_failed",
        }
    omega = var0 * (1.0 - alpha - beta)
    s2 = var0
    for v in xs:
        s2 = omega + alpha * v * v + beta * s2
    forecast_var = omega + alpha * xs[-1] ** 2 + beta * s2
    return {
        "params": {"omega": H.r6(omega), "alpha": H.r6(alpha), "beta": H.r6(beta)},
        "forecast": H.r6(forecast_var),
        "omega": H.r6(omega),
        "alpha": H.r6(alpha),
        "beta": H.r6(beta),
        "persistence": H.r6(alpha + beta),
        "forecast_vol": H.r6(math.sqrt(forecast_var)),
        "loglik": H.r4(ll),
        "n": n,
        "method": "grid_qmle_variance_targeting",
    }


@register(
    "T19",
    name="EWMA 波动率",
    group="T",
    layer="D2",
    input_kind="series",
    min_n=10,
    output_schema=("series", "lam", "n"),
    notes="λ=0.94（RiskMetrics 日频）；输入为收益",
)
def t19_ewma_vol(data: Any, lam: float = 0.94) -> Dict[str, Any]:
    xs = _S(data)
    if not 0.0 < lam < 1.0:
        raise ValueError("lam must be in (0,1)")
    v = xs[0] ** 2
    out: List[Optional[float]] = [None]
    for r in xs[1:]:
        v = lam * v + (1.0 - lam) * r * r
        out.append(H.r6(math.sqrt(v)))
    return {"series": out, "lam": lam, "n": len(xs)}


@register(
    "T20",
    name="半衰期",
    group="T",
    layer="D2",
    input_kind="series",
    min_n=30,
    output_schema=("phi", "halflife_days", "n"),
    notes="复用 ar1_halflife；ln2/ln|φ|",
)
def t20_halflife(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    d = {"phi": None, "halflife_days": None, "n": len(xs)}
    return {k: _guard(ar1_halflife, d, xs).get(k) for k in d}


@register(
    "T21",
    name="均值回复（OU 近似）",
    group="T",
    layer="D2",
    input_kind="series",
    min_n=30,
    output_schema=("phi", "halflife_days", "regime", "n"),
    notes="φ<1 均值回复、φ≈1 随机游走、φ>1 发散",
)
def t21_mean_reversion(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    d = {"phi": None, "halflife_days": None, "n": len(xs)}
    out = _guard(ar1_halflife, d, xs)
    phi = out.get("phi")
    regime = None
    if phi is not None:
        regime = "mean_revert" if phi < 0.95 else ("random_walk" if phi <= 1.05 else "divergent")
    return {
        "phi": phi,
        "halflife_days": out.get("halflife_days"),
        "regime": regime,
        "n": out.get("n", len(xs)),
    }


@register(
    "T22",
    name="变点检测（CUSUM）",
    group="T",
    layer="D2",
    input_kind="series",
    min_n=10,
    output_schema=("breakpoints", "max_abs", "threshold", "n"),
    notes="标准化累计偏差首次超限点",
)
def t22_cusum(data: Any, threshold: float = 5.0) -> Dict[str, Any]:
    xs = _S(data)
    n = len(xs)
    mu, sd = H.mean(xs), H.std(xs)
    if sd <= _EPS:
        return {"breakpoints": [], "max_abs": 0.0, "threshold": threshold, "n": n}
    scale = sd * math.sqrt(n)
    z, acc = [], 0.0
    for v in xs:
        acc += v - mu
        z.append(acc / scale)
    breaks, prev = [], 0.0
    for i, val in enumerate(z):
        if abs(val) > threshold >= abs(prev):
            breaks.append(i)
        prev = val
    return {
        "breakpoints": breaks,
        "max_abs": H.r4(max(abs(v) for v in z)),
        "threshold": threshold,
        "n": n,
    }


@register(
    "T23",
    name="变点检测（PELT 近似）",
    group="T",
    layer="D2",
    input_kind="series",
    min_n=60,
    output_schema=("breakpoints", "n_changepoints", "penalty", "min_size", "n", "method"),
    notes="ruptures 未安装 → 二元分割最小化分段 SSE，BIC 惩罚 penalty·σ²·ln n"
    "（确定性，简化口径）",
)
def t23_pelt(
    data: Any, penalty: float = 1.0, min_size: int = 5, max_changepoints: int = 10
) -> Dict[str, Any]:
    xs = _S(data)
    n = len(xs)
    m = max(2, int(min_size))
    sigma2 = H.var(xs)
    if sigma2 <= _EPS or n < 3 * m:
        return {
            "breakpoints": [],
            "n_changepoints": 0,
            "penalty": H.r4(penalty),
            "min_size": m,
            "n": n,
            "method": "binary_segmentation_bic",
        }
    threshold = float(penalty) * sigma2 * math.log(n)

    def sse(lo: int, hi: int) -> float:
        seg = xs[lo:hi]
        mu = H.mean(seg)
        return sum((v - mu) ** 2 for v in seg)

    found: List[int] = []

    def split(lo: int, hi: int, depth: int) -> None:
        if depth >= max_changepoints or hi - lo < 2 * m:
            return
        base = sse(lo, hi)
        best_gain, best_k = 0.0, None
        for k in range(lo + m, hi - m + 1):
            gain = base - sse(lo, k) - sse(k, hi)
            if gain > best_gain:
                best_gain, best_k = gain, k
        if best_k is None or best_gain <= threshold:
            return
        found.append(best_k)
        split(lo, best_k, depth + 1)
        split(best_k, hi, depth + 1)

    split(0, n, 0)
    breaks = sorted(found)
    return {
        "breakpoints": breaks,
        "n_changepoints": len(breaks),
        "penalty": H.r4(penalty),
        "min_size": m,
        "n": n,
        "method": "binary_segmentation_bic",
    }


@register(
    "T24",
    name="状态持续性",
    group="T",
    layer="D2",
    input_kind="series",
    min_n=30,
    output_schema=("dwell_up_days", "dwell_down_days", "steady_up", "n"),
    notes="复用 transition_matrix；输入为收益",
)
def t24_dwell(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    d = {"dwell_up_days": None, "dwell_down_days": None, "steady_up": None, "n": len(xs)}
    return {k: _guard(transition_matrix, d, xs).get(k) for k in d}


@register(
    "T25",
    name="谱分析主周期",
    group="T",
    layer="D2",
    input_kind="series",
    min_n=60,
    output_schema=("period", "freq_index", "amplitude", "n"),
    notes="去线性趋势后单边 DFT（rfft 同口径），排除 k=1；period=n/k、amplitude=2|X|/n",
)
def t25_fft_period(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    n = len(xs)
    power = _dft_power(xs)
    if len(power) < 2:
        return {"period": None, "freq_index": None, "amplitude": None, "n": n}
    candidates = power[1:] if len(power) > 1 else power
    k, pk = max(candidates, key=lambda item: item[1])
    if pk <= _EPS:
        return {"period": None, "freq_index": None, "amplitude": 0.0, "n": n}
    return {
        "period": H.r4(n / k),
        "freq_index": k,
        "amplitude": H.r6(2.0 * math.sqrt(pk) / n),
        "n": n,
    }


@register(
    "T26",
    name="周期强度",
    group="T",
    layer="D2",
    input_kind="series",
    min_n=60,
    output_schema=("period", "power_ratio", "n"),
    notes="主周期功率 / 全部非零频功率（去线性趋势后 DFT，简化口径）",
)
def t26_cycle_strength(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    n = len(xs)
    power = _dft_power(xs)
    total = sum(v for _, v in power)
    if not power or total <= _EPS:
        return {"period": None, "power_ratio": None, "n": n}
    candidates = power[1:] if len(power) > 1 else power
    k, pk = max(candidates, key=lambda item: item[1])
    return {"period": H.r4(n / k), "power_ratio": H.r4(pk / total), "n": n}


@register(
    "T27",
    name="分形维数（近似）",
    group="T",
    layer="D2",
    input_kind="series",
    min_n=20,
    output_schema=("fd", "sizes", "n"),
    notes="盒计数：logN = fd·log k（k 为每轴网格数）",
)
def t27_fractal_dim(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    n = len(xs)
    lo, hi = min(xs), max(xs)
    if hi <= lo or n < 4:
        return {"fd": None, "sizes": [], "n": n}
    yn = [(v - lo) / (hi - lo) for v in xs]
    xn = [i / (n - 1) for i in range(n)]
    sizes = [k for k in (2, 4, 8, 16, 32, 64) if k <= n]
    if len(sizes) < 2:
        return {"fd": None, "sizes": sizes, "n": n}
    lx, ly = [], []
    for k in sizes:
        boxes = {
            (min(int(x * k), k - 1), min(int(y * k), k - 1)) for x, y in zip(xn, yn, strict=False)
        }
        lx.append(math.log(k))
        ly.append(math.log(len(boxes)))
    mx, my = H.mean(lx), H.mean(ly)
    den = sum((a - mx) ** 2 for a in lx)
    slope = (
        sum((a - mx) * (b - my) for a, b in zip(lx, ly, strict=False)) / den if den > _EPS else 0.0
    )
    return {"fd": H.r4(slope), "sizes": sizes, "n": n}


@register(
    "T28",
    name="样本熵",
    group="T",
    layer="D3",
    input_kind="series",
    min_n=20,
    output_schema=("sampen", "m", "r_ratio", "n"),
    notes="SampEn(m=2, r=0.2σ)",
)
def t28_sample_entropy(data: Any, m: int = 2, r_ratio: float = 0.2) -> Dict[str, Any]:
    xs = _S(data)
    n = len(xs)
    mm = max(1, int(m))
    if n <= mm + 1:
        return {"sampen": None, "m": mm, "r_ratio": r_ratio, "n": n}
    r = r_ratio * H.std(xs)

    def count(size: int) -> int:
        total = 0
        for i in range(n - size + 1):
            for j in range(i + 1, n - size + 1):
                if max(abs(xs[i + k] - xs[j + k]) for k in range(size)) <= r:
                    total += 1
        return total

    b, a = count(mm), count(mm + 1)
    sampen = -math.log(a / b) if a > 0 and b > 0 else None
    return {"sampen": H.r4(sampen), "m": mm, "r_ratio": r_ratio, "n": n}


# ======================================================================
# F 组：金融专用（补充）
# ======================================================================


@register(
    "F07",
    name="索提诺比率",
    group="F",
    layer="D2",
    input_kind="series",
    min_n=30,
    output_schema=("sortino", "ann_ret", "downside_vol", "n"),
    notes="(年化收益−rf)/年化下行波动；输入为价格",
)
def f07_sortino(data: Any, rf: float = 0.0, periods: int = 365) -> Dict[str, Any]:
    xs = _S(data)
    rs = returns_of(xs)
    mu = H.mean(rs)
    ann = (1.0 + mu) ** periods - 1.0
    dd = math.sqrt(sum(min(v, 0.0) ** 2 for v in rs) / len(rs)) * math.sqrt(periods) if rs else 0.0
    return {
        "sortino": None if dd <= _EPS else H.r6((ann - rf) / dd),
        "ann_ret": H.r6(ann),
        "downside_vol": H.r6(dd),
        "n": len(xs),
    }


@register(
    "F08",
    name="卡玛比率",
    group="F",
    layer="D2",
    input_kind="series",
    min_n=30,
    output_schema=("calmar", "ann_ret", "mdd", "n"),
    notes="年化收益/|MDD|；输入为价格",
)
def f08_calmar(data: Any, periods: int = 365) -> Dict[str, Any]:
    xs = _S(data)
    ann = (1.0 + H.mean(returns_of(xs))) ** periods - 1.0
    mdd = H.drawdown_profile(xs)["mdd"] or 0.0
    return {
        "calmar": None if mdd <= _EPS else H.r6(ann / mdd),
        "ann_ret": H.r6(ann),
        "mdd": mdd,
        "n": len(xs),
    }


@register(
    "F09",
    name="最大回撤",
    group="F",
    layer="D1",
    input_kind="series",
    min_n=2,
    output_schema=("mdd", "peak_index", "trough_index", "n"),
    notes="与 D20 同口径（价格序列）",
    checks=MethodChecks(synthetic=lambda: _expect([100, 120, 90, 110], {"result.mdd": 0.25})),
)
def f09_mdd(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    p = H.drawdown_profile(xs)
    return {
        "mdd": p["mdd"],
        "peak_index": p["peak_index"],
        "trough_index": p["trough_index"],
        "n": p["n"],
    }


@register(
    "F10",
    name="回撤恢复时间",
    group="F",
    layer="D1",
    input_kind="series",
    min_n=2,
    output_schema=("duration_days", "recovery_days", "recovered", "n"),
)
def f10_recovery(data: Any) -> Dict[str, Any]:
    p = H.drawdown_profile(_S(data))
    return {
        "duration_days": p["duration_days"],
        "recovery_days": p["recovery_days"],
        "recovered": p["recovered"],
        "n": p["n"],
    }


@register(
    "F11",
    name="收益偏度/峰度",
    group="F",
    layer="D2",
    input_kind="series",
    min_n=4,
    output_schema=("skew", "kurt", "n"),
    notes="输入为价格；对简单收益取矩",
)
def f11_return_moments(data: Any) -> Dict[str, Any]:
    rs = returns_of(_S(data))
    return {"skew": H.r6(H.skewness(rs)), "kurt": H.r6(H.kurtosis_excess(rs)), "n": len(rs)}


@register(
    "F12",
    name="自相关（收益）",
    group="F",
    layer="D2",
    input_kind="series",
    min_n=10,
    output_schema=("acf", "max_lag", "n"),
    notes="输入为价格；简单收益的 ACF(1..max_lag)",
)
def f12_return_acf(data: Any, max_lag: int = 5) -> Dict[str, Any]:
    rs = returns_of(_S(data))
    m = max(1, min(int(max_lag), max(1, len(rs) - 3)))
    return {"acf": H.acf(rs, m), "max_lag": m, "n": len(rs)}


@register(
    "F13",
    name="波动率聚集",
    group="F",
    layer="D2",
    input_kind="series",
    min_n=10,
    output_schema=("acf", "max_lag", "n"),
    notes="输入为价格；|简单收益| 的 ACF",
)
def f13_vol_clustering(data: Any, max_lag: int = 5) -> Dict[str, Any]:
    rs = returns_of(_S(data))
    m = max(1, min(int(max_lag), max(1, len(rs) - 3)))
    return {"acf": H.acf([abs(v) for v in rs], m), "max_lag": m, "n": len(rs)}


@register(
    "F14",
    name="风险调整动量",
    group="F",
    layer="D2",
    input_kind="series",
    min_n=30,
    output_schema=("ratio", "momentum", "vol", "n"),
    notes="k 期收益 / 同期波动；输入为价格",
)
def f14_risk_adj_momentum(data: Any, k: int = 20) -> Dict[str, Any]:
    xs = _S(data)
    kk = max(1, min(int(k), len(xs) - 1))
    mom = xs[-1] / xs[-1 - kk] - 1.0 if xs[-1 - kk] > 0 else None
    rs = returns_of(xs[-kk - 1 :])
    vol = H.std(rs) * math.sqrt(kk) if len(rs) > 1 else 0.0
    ratio = None if (mom is None or vol <= _EPS) else mom / vol
    return {"ratio": H.r4(ratio), "momentum": H.r6(mom), "vol": H.r6(vol), "n": len(xs)}


@register(
    "F15",
    name="相对强弱 RS",
    group="F",
    layer="D2",
    input_kind="pairs",
    min_n=30,
    output_schema=("ratio", "asset_ret", "bench_ret", "rs", "n"),
    notes="输入 x=标的价、y=基准价；RS 线=P/P_bench（起点归一 1），ratio 取末值",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {
                "x": [100.0 + i for i in range(40)],
                "y": [100.0 + 0.5 * i for i in range(40)],
            },
            "params": {},
            "expect": {"result.ratio": "non_empty"},
        }
    ),
)
def f15_relative_strength(data: Mapping[str, Any]) -> Dict[str, Any]:
    xs, ys = H.two(data)
    n = min(len(xs), len(ys))
    if xs[0] <= 0 or ys[0] <= 0:
        raise ValueError("prices must be positive")
    rs = [(xs[i] / xs[0]) / (ys[i] / ys[0]) for i in range(n)]
    return {
        "ratio": H.r6(rs[-1]),
        "asset_ret": H.r6(xs[n - 1] / xs[0] - 1.0),
        "bench_ret": H.r6(ys[n - 1] / ys[0] - 1.0),
        "rs": [H.r6(v) for v in rs],
        "n": n,
    }


@register(
    "F16",
    name="动量排序",
    group="F",
    layer="D2",
    input_kind="panel",
    min_n=30,
    output_schema=("ranking", "k", "n_assets", "n"),
    notes="跨资产 k 期价格收益降序排名（1=最强）；输入 {name: 价格序列}",
)
def f16_momentum_ranking(data: Any, k: int = 20) -> Dict[str, Any]:
    panel = _panel_map(data)
    if not panel:
        raise ValueError("momentum ranking needs at least one asset series")
    kk = max(1, int(k))
    rows = []
    for name, prices in panel.items():
        if len(prices) <= kk or prices[-1 - kk] <= 0:
            continue
        rows.append({"asset": name, "ret": prices[-1] / prices[-1 - kk] - 1.0})
    rows.sort(key=lambda r: r["ret"], reverse=True)
    ranking = [
        {"asset": r["asset"], "ret": H.r6(r["ret"]), "rank": i + 1} for i, r in enumerate(rows)
    ]
    n = min((len(v) for v in panel.values()), default=0)
    return {"ranking": ranking, "k": kk, "n_assets": len(ranking), "n": n}


@register(
    "F17",
    name="反转统计",
    group="F",
    layer="D1",
    input_kind="series",
    min_n=10,
    output_schema=("p_down_given_up", "p_up_given_down", "n"),
    notes="上期涨→本期跌、上期跌→本期涨的条件比例；输入为价格",
)
def f17_reversal(data: Any) -> Dict[str, Any]:
    rs = returns_of(_S(data))
    up_prev = [b for a, b in zip(rs, rs[1:], strict=False) if a > 0]
    dn_prev = [b for a, b in zip(rs, rs[1:], strict=False) if a < 0]
    p_dn = sum(1 for b in up_prev if b < 0) / len(up_prev) if up_prev else None
    p_up = sum(1 for b in dn_prev if b > 0) / len(dn_prev) if dn_prev else None
    return {"p_down_given_up": H.r4(p_dn), "p_up_given_down": H.r4(p_up), "n": len(rs)}


@register(
    "F18",
    name="连胜/连败",
    group="F",
    layer="D1",
    input_kind="series",
    min_n=12,
    output_schema=("max_run", "max_up", "max_down", "mean_run", "n_runs", "n"),
    notes="复用 run_length_stats；输入为收益",
)
def f18_runs(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    d = {
        "max_run": None,
        "max_up": None,
        "max_down": None,
        "mean_run": None,
        "n_runs": None,
        "n": len(xs),
    }
    return {k: _guard(run_length_stats, d, xs).get(k) for k in d}


@register(
    "F19",
    name="事件窗收益",
    group="F",
    layer="D2",
    input_kind="events",
    min_n=30,
    output_schema=("cars", "car", "n_events", "window", "n"),
    notes="事件日 t 的 [t−k,t+k] 累计收益 CAR=P_{t+k}/P_{t−k}−1（越界截断）；"
    "输入 {prices:[...], events:[idx...]}；events 兼容 list[{index|i|t}]",
)
def f19_event_window(data: Any, k: int = 5) -> Dict[str, Any]:
    prices = _event_prices(data)
    idx = _event_indices(data)
    n = len(prices)
    kk = max(1, int(k))
    cars = []
    for t in idx:
        if t < 0 or t >= n:
            continue
        lo, hi = max(0, t - kk), min(n - 1, t + kk)
        if hi <= lo or prices[lo] <= 0:
            continue
        cars.append(prices[hi] / prices[lo] - 1.0)
    if not cars:
        return {"cars": [], "car": None, "n_events": 0, "window": kk, "n": n}
    return {
        "cars": [H.r6(v) for v in cars],
        "car": H.r6(H.mean(cars)),
        "n_events": len(cars),
        "window": kk,
        "n": n,
    }


@register(
    "F20",
    name="异常收益 AR",
    group="F",
    layer="D1",
    input_kind="series",
    min_n=30,
    output_schema=("ar", "mean", "n"),
    notes="r − E[r]；输入为收益序列",
)
def f20_abnormal_return(data: Any) -> Dict[str, Any]:
    xs = _S(data)
    mu = H.mean(xs)
    return {"ar": [H.r6(v - mu) for v in xs], "mean": H.r6(mu), "n": len(xs)}


@register(
    "F21",
    name="累计异常收益 CAR",
    group="F",
    layer="D1",
    input_kind="series",
    min_n=30,
    output_schema=("car", "window", "n"),
    notes="末 window 期 AR 之和；输入为收益序列",
)
def f21_car(data: Any, window: int = 5) -> Dict[str, Any]:
    xs = _S(data)
    w = max(1, min(int(window), len(xs)))
    mu = H.mean(xs)
    car = sum(v - mu for v in xs[-w:])
    return {"car": H.r6(car), "window": w, "n": len(xs)}


@register(
    "F22",
    name="事件次数统计",
    group="F",
    layer="D1",
    input_kind="events",
    min_n=30,
    output_schema=("event", "count", "unique", "total"),
    notes="事件标签序列（list 或 {events:[...]}）中，末次事件标签的历史发生次数",
)
def f22_event_count(data: Any) -> Dict[str, Any]:
    raw = data.get("events", data.get("labels")) if isinstance(data, Mapping) else data
    if raw is None:
        raise ValueError("event count needs event labels")
    labels = [str(v) for v in raw]
    counts: Dict[str, int] = {}
    for lab in labels:
        counts[lab] = counts.get(lab, 0) + 1
    last = labels[-1]
    return {"event": last, "count": counts[last], "unique": len(counts), "total": len(labels)}


@register(
    "F23",
    name="事件后分布",
    group="F",
    layer="D2",
    input_kind="events",
    min_n=30,
    output_schema=("dist", "mean", "median", "std", "win_rate", "n_events", "n"),
    notes="事件日 t 后 k 期前瞻收益 P_{t+k}/P_t−1 的经验分布；"
    "输入 {prices:[...], events:[idx...]}",
)
def f23_post_event_dist(data: Any, k: int = 5) -> Dict[str, Any]:
    prices = _event_prices(data)
    idx = _event_indices(data)
    n = len(prices)
    kk = max(1, int(k))
    dist = []
    for t in idx:
        if t < 0 or t + kk >= n or prices[t] <= 0:
            continue
        dist.append(prices[t + kk] / prices[t] - 1.0)
    if not dist:
        return {
            "dist": [],
            "mean": None,
            "median": None,
            "std": None,
            "win_rate": None,
            "n_events": 0,
            "n": n,
        }
    return {
        "dist": [H.r6(v) for v in dist],
        "mean": H.r6(H.mean(dist)),
        "median": H.r6(H.median(dist)),
        "std": H.r6(H.std(dist)),
        "win_rate": H.r4(sum(1 for v in dist if v > 0) / len(dist)),
        "n_events": len(dist),
        "n": n,
    }


@register(
    "F24",
    name="资金费率年化",
    group="F",
    layer="D1",
    input_kind="series",
    min_n=30,
    output_schema=("apr", "mean_rate", "periods_per_day", "n"),
    notes="APR=mean(每期费率)×periods_per_day(默认 3/日)×365（单利口径）",
)
def f24_funding_apr(data: Any, periods_per_day: int = 3, days: int = 365) -> Dict[str, Any]:
    xs = _S(data)
    mu = H.mean(xs)
    apr = mu * int(periods_per_day) * int(days)
    return {
        "apr": H.r6(apr),
        "mean_rate": H.r6(mu),
        "periods_per_day": int(periods_per_day),
        "n": len(xs),
    }


@register(
    "F25",
    name="基差",
    group="F",
    layer="D1",
    input_kind="pairs",
    min_n=30,
    output_schema=("basis", "mean_basis", "futures", "spot", "n"),
    notes="(futures−spot)/spot；输入 {futures:[...], spot:[...]}（或 x/y），取末值",
    checks=MethodChecks(
        synthetic=lambda: {
            "data": {"futures": [110.0] * 40, "spot": [100.0] * 40},
            "params": {},
            "expect": {"result.basis": 0.1},
        }
    ),
)
def f25_basis(data: Mapping[str, Any]) -> Dict[str, Any]:
    if isinstance(data, Mapping) and "futures" in data and "spot" in data:
        fs = H.clean(data["futures"])
        ss = H.clean(data["spot"])
    else:
        fs, ss = H.two(data)
    n = min(len(fs), len(ss))
    if n == 0 or ss[n - 1] == 0:
        raise ValueError("basis needs non-zero spot price")
    pairs = [(f / s - 1.0) for f, s in zip(fs[:n], ss[:n], strict=False) if s != 0]
    return {
        "basis": H.r6(fs[n - 1] / ss[n - 1] - 1.0),
        "mean_basis": H.r6(H.mean(pairs)) if pairs else None,
        "futures": H.r6(fs[n - 1]),
        "spot": H.r6(ss[n - 1]),
        "n": n,
    }


@register(
    "F26",
    name="拥挤度合成",
    group="F",
    layer="D2",
    input_kind="panel",
    min_n=60,
    output_schema=("score", "components", "weights", "n"),
    notes="各指标末值在自身历史中的分位（#x≤last/n），固定权重 0.4/0.3/0.3"
    "（最多取前三个指标，权重归一）；输入 {name: 序列} 或 {series:{name: 序列}}",
)
def f26_crowding_score(data: Any) -> Dict[str, Any]:
    panel = _panel_map(data)
    if not panel:
        raise ValueError("crowding score needs indicator series")
    names = list(panel)[:3]
    base_w = [0.4, 0.3, 0.3][: len(names)]
    wsum = sum(base_w)
    weights = [w / wsum for w in base_w]
    components: Dict[str, float] = {}
    score = 0.0
    for name, w in zip(names, weights, strict=False):
        vals = panel[name]
        if not vals:
            raise ValueError(f"empty indicator series: {name}")
        last = vals[-1]
        pct = sum(1 for v in vals if v <= last) / len(vals)
        components[name] = H.r4(pct)
        score += w * pct
    return {
        "score": H.r4(score),
        "components": components,
        "weights": [H.r4(w) for w in weights],
        "n": min(len(v) for v in panel.values()),
    }
