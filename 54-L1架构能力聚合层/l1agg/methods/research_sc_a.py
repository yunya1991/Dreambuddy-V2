# -*- coding: utf-8 -*-
"""科研方法族 SC01–SC46（推断/不确定度、回归诊断、实验设计、降维与结构、频谱）。

来源：docs/RESEARCH-SCIENTIFIC-METHODS.md §2.1–§2.5。
编号/名称/层级/最小样本取自 `research.spec_of`（SSoT），本模块只负责真实实现。

约束：
  - 无网络、无 DB、无 LLM；随机过程固定 seed（Bootstrap/置换/ICA/K-Means = 42）；
  - 迭代优化固定容差（RLM/QuantReg/FactorAnalysis/GraphicalLasso）；
  - 输入契约在函数内兼容 series / x-y / X-y / matrix / groups；
  - 输出键与 `output_schema` 完全一致，浮点统一 6 位（比率类 4 位）；
  - SC42/SC43 在无 pywt 时用 Haar/复 Morlet 自实现（确定性近似）。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Sequence

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from scipy.cluster.hierarchy import linkage
from scipy.ndimage import uniform_filter1d
from scipy.signal import butter, filtfilt, hilbert, lombscargle, savgol_filter, welch
from scipy.spatial.distance import squareform
from sklearn.cluster import KMeans
from sklearn.covariance import GraphicalLasso
from sklearn.decomposition import PCA, FactorAnalysis, FastICA
from sklearn.linear_model import Ridge
from sklearn.metrics import silhouette_score
from statsmodels.formula.api import ols as sm_ols
from statsmodels.stats.anova import AnovaRM, anova_lm
from statsmodels.stats.diagnostic import het_breuschpagan, het_white
from statsmodels.stats.multicomp import pairwise_tukeyhsd
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.stats.power import TTestPower
from statsmodels.stats.stattools import durbin_watson

from .registry import register
from .research import spec_of

_EPS = 1e-12
_SEED = 42

# ---------------------------------------------------------------- 通用工具


def _f(v: Any, nd: int = 6) -> Any:
    """float 收敛：非有限返回 None，其余按 nd 位四舍五入。"""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return round(x, nd) if math.isfinite(x) else None


def _lst(v: Any, nd: int = 6) -> List[Any]:
    arr = np.asarray(v, dtype=float).ravel()
    return [_f(x, nd) for x in arr]


def _mtx(v: Any, nd: int = 6) -> List[List[Any]]:
    arr = np.asarray(v, dtype=float)
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    return [[_f(x, nd) for x in row] for row in arr]


def _vals(seq: Any) -> np.ndarray:
    """一维数值数组（去 None / 非有限）。"""
    out = []
    for v in list(seq):
        if v is None:
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(x):
            out.append(x)
    return np.asarray(out, dtype=float)


def _series(data: Any) -> np.ndarray:
    """单序列：list / {x|series|values|value|y|returns|price|indicator}。"""
    if isinstance(data, Mapping):
        for key in ("x", "series", "values", "value", "y", "returns", "price", "indicator"):
            if key in data and not _is_nested(data[key]):
                return _vals(data[key])
        raise ValueError("series data must contain x/series/values/value/y")
    return _vals(data)


def _is_nested(seq: Any) -> bool:
    if isinstance(seq, (str, bytes)):
        return False
    try:
        first = list(seq)[0]
    except (TypeError, IndexError):
        return False
    return isinstance(first, (list, tuple, np.ndarray))


def _matrix(data: Any) -> np.ndarray:
    """设计矩阵/数据矩阵：X / matrix / design / features / list-of-lists。"""
    if isinstance(data, Mapping):
        for key in ("X", "matrix", "design", "features", "data"):
            if key in data and _is_nested(data[key]):
                return np.asarray(data[key], dtype=float)
        if "x" in data and not _is_nested(data["x"]):
            return _vals(data["x"]).reshape(-1, 1)
        cols = []
        for key, val in data.items():
            if key in (
                "y",
                "target",
                "value",
                "label",
                "w",
                "weights",
                "t",
                "u",
                "c",
                "group",
                "state",
                "a",
                "b",
            ):
                continue
            if _is_nested(val) or isinstance(val, (list, tuple, np.ndarray, pd.Series)):
                try:
                    col = np.asarray(val, dtype=float)
                except (TypeError, ValueError):
                    continue
                if col.ndim == 1 and col.size:
                    cols.append(col)
        if cols:
            m = min(len(c) for c in cols)
            return np.column_stack([c[:m] for c in cols])
        raise ValueError("matrix data must contain X/matrix/design or numeric columns")
    arr = np.asarray(data, dtype=float)
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    return arr


def _target(data: Any) -> np.ndarray:
    if isinstance(data, Mapping):
        for key in ("y", "target", "value", "label", "z"):
            if key in data:
                return _vals(data[key])
        raise ValueError("target data must contain y/target/value")
    raise ValueError("target requires mapping input")


def _xy(data: Any):
    X = _matrix(data)
    y = _target(data)
    m = min(X.shape[0], len(y))
    return X[:m], y[:m]


def _design(data: Any, add_const: bool = True):
    X = _matrix(data)
    return (sm.add_constant(X, has_constant="add") if add_const else X), X.shape[1]


def _groups(data: Any) -> List[np.ndarray]:
    """分组：groups / state+target / group+value / 扁平多键 / list-of-lists / 对半切。"""
    if isinstance(data, Mapping) and "groups" in data:
        return [_vals(g) for g in data["groups"]]
    if isinstance(data, Mapping) and "state" in data and "target" in data:
        return _by_label(data["state"], data["target"])
    if isinstance(data, Mapping) and "group" in data and "value" in data:
        return _by_label(data["group"], data["value"])
    if isinstance(data, Mapping):
        # 扁平多键形式 {"g1": [...], "g2": [...]}（可附带等长 series 汇总键）
        blocks = {}
        for key, val in data.items():
            if key in ("series", "n", "meta"):
                continue
            if isinstance(val, (list, tuple, np.ndarray, pd.Series)) and not _is_nested(val):
                arr = _vals(val)
                if len(arr):
                    blocks[key] = arr
        if len(blocks) >= 2:
            return list(blocks.values())
        raise ValueError("grouped data must contain groups / state+target / group+value / 多键分组")
    seq = list(data)
    if seq and isinstance(seq[0], (list, tuple, np.ndarray)):
        return [_vals(g) for g in seq]
    xs = _vals(seq)
    half = len(xs) // 2
    return [xs[:half], xs[half:]]


def _by_label(labels: Any, values: Any) -> List[np.ndarray]:
    order: List[str] = []
    bucket: Dict[str, List[float]] = {}
    lv = list(labels)
    vv = _vals(values)
    m = min(len(lv), len(vv))
    for i in range(m):
        key = str(lv[i])
        if key not in bucket:
            bucket[key] = []
            order.append(key)
        bucket[key].append(float(vv[i]))
    return [np.asarray(bucket[k], dtype=float) for k in order]


def _two_samples(data: Any):
    if isinstance(data, Mapping) and "x" in data and "y" in data:
        return _vals(data["x"]), _vals(data["y"])
    groups = _groups(data)
    if len(groups) < 2:
        raise ValueError("need at least 2 groups")
    return groups[0], groups[1]


def _ols(data: Any):
    X, p = _design(data, add_const=True)
    y = _target(data)
    m = min(X.shape[0], len(y))
    X, y = X[:m], y[:m]
    return sm.OLS(y, X).fit(), p


def _reg(mid: str, input_kind: str, output_schema: Sequence[str], notes: str = ""):
    """按 research.py 的 SSoT 取 name/group/layer/min_n 并登记。"""
    _, name, group, layer, min_n = spec_of(mid)
    return register(
        mid,
        name=name,
        group=group,
        layer=layer,
        input_kind=input_kind,
        min_n=min_n,
        output_schema=output_schema,
        notes=notes,
    )


# ======================================================================
# §2.1 推断与不确定度（SC01–SC12）
# ======================================================================


@_reg(
    "SC01",
    "series",
    ("power", "n", "effect_size", "alpha"),
    "1−β（statsmodels TTestPower）；效应量缺省用 mean/sd",
)
def sc01_power(data: Any, effect_size: float = None, alpha: float = 0.05) -> Dict[str, Any]:
    xs = _series(data)
    n = len(xs)
    sd = float(np.std(xs, ddof=1)) if n > 1 else 0.0
    d = (
        abs(float(effect_size))
        if effect_size is not None
        else (abs(float(np.mean(xs)) / sd) if sd > _EPS else 0.0)
    )
    if d <= 0.0 or n < 2:
        return {"power": _f(alpha), "n": n, "effect_size": 0.0, "alpha": _f(alpha)}
    power = float(TTestPower().power(effect_size=d, nobs=n, alpha=alpha, alternative="two-sided"))
    if not math.isfinite(power):  # 大样本下非中心 t 数值溢出 → 正态近似
        power = float(stats.norm.cdf(d * math.sqrt(n) - stats.norm.ppf(1 - alpha / 2)))
    return {
        "power": _f(min(max(power, 0.0), 1.0)),
        "n": n,
        "effect_size": _f(d),
        "alpha": _f(alpha, 4),
    }


@_reg(
    "SC02",
    "series",
    ("n_star", "effect_size", "alpha", "power_target"),
    "最小样本量（α=0.05, power=0.8）",
)
def sc02_min_n(
    data: Any, effect_size: float = None, alpha: float = 0.05, power_target: float = 0.8
) -> Dict[str, Any]:
    xs = _series(data)
    sd = float(np.std(xs, ddof=1)) if len(xs) > 1 else 0.0
    d = (
        abs(float(effect_size))
        if effect_size is not None
        else (abs(float(np.mean(xs)) / sd) if sd > _EPS else 0.0)
    )
    if d <= 0.0:
        return {
            "n_star": None,
            "effect_size": 0.0,
            "alpha": _f(alpha, 4),
            "power_target": _f(power_target, 4),
        }
    n_star = TTestPower().solve_power(
        effect_size=d, alpha=alpha, power=power_target, alternative="two-sided"
    )
    return {
        "n_star": int(math.ceil(float(n_star))),
        "effect_size": _f(d),
        "alpha": _f(alpha, 4),
        "power_target": _f(power_target, 4),
    }


@_reg(
    "SC03",
    "pairs",
    ("p", "p_low", "p_high", "equivalent", "bound", "n"),
    "TOST 双单侧 t：H0 差值越出 ±bound",
)
def sc03_tost(data: Any, bound: float = None, alpha: float = 0.05) -> Dict[str, Any]:
    if isinstance(data, Mapping) and "x" in data and "y" in data:
        diffs = _vals(data["x"]) - _vals(data["y"])[: len(_vals(data["x"]))]
    else:
        diffs = _series(data)
    n = len(diffs)
    if n < 3:
        return {
            "p": None,
            "p_low": None,
            "p_high": None,
            "equivalent": False,
            "bound": None,
            "n": n,
        }
    mu = float(np.mean(diffs))
    se = float(np.std(diffs, ddof=1) / math.sqrt(n))
    b = abs(float(bound)) if bound is not None else max(0.1 * float(np.std(diffs, ddof=1)), 1e-9)
    if se <= _EPS:
        equivalent = abs(mu) < b
        return {
            "p": 0.0 if equivalent else 1.0,
            "p_low": _f(0.0 if equivalent else 1.0),
            "p_high": _f(0.0 if equivalent else 1.0),
            "equivalent": bool(equivalent),
            "bound": _f(b),
            "n": n,
        }
    df = n - 1
    p_low = float(stats.t.sf((mu + b) / se, df))
    p_high = float(stats.t.cdf((mu - b) / se, df))
    p = max(p_low, p_high)
    return {
        "p": _f(p),
        "p_low": _f(p_low),
        "p_high": _f(p_high),
        "equivalent": bool(p < alpha),
        "bound": _f(b),
        "n": n,
    }


@_reg("SC04", "pairs", ("p_perm", "stat", "n", "trials"), "置换检验（N=1000, seed=42）：均值差")
def sc04_permutation(data: Any, trials: int = 1000, seed: int = _SEED) -> Dict[str, Any]:
    a, b = _two_samples(data)
    n1, n2 = len(a), len(b)
    obs = float(np.mean(a) - np.mean(b))
    pooled = np.concatenate([a, b])
    rng = np.random.default_rng(seed)
    hits = 0
    for _ in range(int(trials)):
        perm = rng.permutation(pooled)
        stat = float(np.mean(perm[:n1]) - np.mean(perm[n1 : n1 + n2]))
        if abs(stat) >= abs(obs) - _EPS:
            hits += 1
    return {
        "p_perm": _f((hits + 1) / (int(trials) + 1)),
        "stat": _f(obs),
        "n": n1 + n2,
        "trials": int(trials),
    }


@_reg(
    "SC05",
    "series",
    ("ci_low", "ci_high", "mean", "n", "trials"),
    "Bootstrap 百分位区间（B=1000, seed=42）",
)
def sc05_bootstrap_ci(
    data: Any, trials: int = 1000, alpha: float = 0.05, seed: int = _SEED
) -> Dict[str, Any]:
    xs = _series(data)
    n = len(xs)
    if n < 2:
        return {"ci_low": None, "ci_high": None, "mean": None, "n": n, "trials": int(trials)}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(int(trials), n))
    means = xs[idx].mean(axis=1)
    lo, hi = np.percentile(means, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return {
        "ci_low": _f(lo),
        "ci_high": _f(hi),
        "mean": _f(np.mean(xs)),
        "n": n,
        "trials": int(trials),
    }


@_reg(
    "SC06",
    "series",
    ("ci_low", "ci_high", "mean", "n", "alpha"),
    "Bootstrap BCa（偏差校正 + 加速）",
)
def sc06_bootstrap_bca(
    data: Any, trials: int = 1000, alpha: float = 0.05, seed: int = _SEED
) -> Dict[str, Any]:
    xs = _series(data)
    n = len(xs)
    if n < 3:
        return {"ci_low": None, "ci_high": None, "mean": None, "n": n, "alpha": _f(alpha, 4)}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(int(trials), n))
    boot = xs[idx].mean(axis=1)
    theta = float(np.mean(xs))
    jack = np.asarray([np.mean(np.delete(xs, i)) for i in range(n)], dtype=float)
    jbar = float(np.mean(jack))
    denom = float(np.sum((jbar - jack) ** 2))
    accel = 0.0
    if denom > _EPS:
        accel = float(np.sum((jbar - jack) ** 3) / (6.0 * denom**1.5))
    prop = float(np.mean(boot < theta))
    prop = min(max(prop, 1.0 / (int(trials) + 1)), 1.0 - 1.0 / (int(trials) + 1))
    z0 = float(stats.norm.ppf(prop))
    zlo, zhi = stats.norm.ppf(alpha / 2), stats.norm.ppf(1 - alpha / 2)

    def _adj(z: float) -> float:
        num = z0 + z
        den = 1.0 - accel * num
        return float(stats.norm.cdf(z0 + num / den)) if abs(den) > _EPS else 0.5

    lo = float(np.quantile(boot, min(max(_adj(zlo), 0.0), 1.0)))
    hi = float(np.quantile(boot, min(max(_adj(zhi), 0.0), 1.0)))
    return {"ci_low": _f(lo), "ci_high": _f(hi), "mean": _f(theta), "n": n, "alpha": _f(alpha, 4)}


@_reg("SC07", "series", ("theta", "se_jack", "bias", "n"), "Jackknife 留一标准误")
def sc07_jackknife(data: Any) -> Dict[str, Any]:
    xs = _series(data)
    n = len(xs)
    if n < 3:
        return {"theta": None, "se_jack": None, "bias": None, "n": n}
    theta = float(np.mean(xs))
    jack = np.asarray([np.mean(np.delete(xs, i)) for i in range(n)], dtype=float)
    se = math.sqrt((n - 1) / n * float(np.sum((jack - np.mean(jack)) ** 2)))
    bias = (n - 1) * (float(np.mean(jack)) - theta)
    return {"theta": _f(theta), "se_jack": _f(se), "bias": _f(bias), "n": n}


@_reg("SC08", "pairs", ("estimate", "se", "n"), "Delta 法：ratio=mean(y)/mean(x)，Var≈∇fᵀ(Σ/n)∇f")
def sc08_delta(data: Any) -> Dict[str, Any]:
    x, y = _two_samples(data)
    n = min(len(x), len(y))
    x, y = x[:n], y[:n]
    mx, my = float(np.mean(x)), float(np.mean(y))
    if n < 3 or abs(mx) <= _EPS:
        return {"estimate": None, "se": None, "n": n}
    cov = np.cov(np.vstack([x, y]))
    grad = np.asarray([-my / mx**2, 1.0 / mx])
    var = float(grad @ (cov / n) @ grad)
    return {"estimate": _f(my / mx), "se": _f(math.sqrt(max(var, 0.0))), "n": n}


@_reg("SC09", "series", ("u_c", "U", "k", "n"), "GUM 合成标准不确定度：u_c=√Σ(c_i·u_i)²，U=2·u_c")
def sc09_gum(data: Any, k: float = 2.0) -> Dict[str, Any]:
    if isinstance(data, Mapping) and "u" in data:
        u = _vals(data["u"])
        c = _vals(data["c"]) if "c" in data else np.ones(len(u))
    else:
        u = _series(data)
        c = np.ones(len(u))
    m = min(len(u), len(c))
    u, c = u[:m], c[:m]
    if m == 0:
        return {"u_c": None, "U": None, "k": _f(k, 4), "n": 0}
    uc = float(math.sqrt(np.sum((c * u) ** 2)))
    return {"u_c": _f(uc), "U": _f(k * uc), "k": _f(k, 4), "n": m}


@_reg("SC10", "pairs", ("yhat", "pi_low", "pi_high", "x0", "n"), "OLS 预测区间：ŷ±t·s√(1+1/n)")
def sc10_prediction_interval(data: Any, x0: float = None, alpha: float = 0.05) -> Dict[str, Any]:
    x, y = _two_samples(data)
    n = min(len(x), len(y))
    x, y = x[:n], y[:n]
    if n < 4:
        return {"yhat": None, "pi_low": None, "pi_high": None, "x0": None, "n": n}
    X = sm.add_constant(x, has_constant="add")
    fit = sm.OLS(y, X).fit()
    point = float(x0) if x0 is not None else float(x[-1])
    pred = fit.get_prediction(np.asarray([[1.0, point]])).summary_frame(alpha=alpha)
    return {
        "yhat": _f(pred["mean"].iloc[0]),
        "pi_low": _f(pred["obs_ci_lower"].iloc[0]),
        "pi_high": _f(pred["obs_ci_upper"].iloc[0]),
        "x0": _f(point),
        "n": n,
    }


@_reg(
    "SC11",
    "series",
    ("ti_low", "ti_high", "coverage", "confidence", "k", "n"),
    "正态容忍区间（Wald-Hahn 近似）",
)
def sc11_tolerance_interval(
    data: Any, coverage: float = 0.95, confidence: float = 0.95
) -> Dict[str, Any]:
    xs = _series(data)
    n = len(xs)
    if n < 3:
        return {
            "ti_low": None,
            "ti_high": None,
            "coverage": _f(coverage, 4),
            "confidence": _f(confidence, 4),
            "k": None,
            "n": n,
        }
    mu, sd = float(np.mean(xs)), float(np.std(xs, ddof=1))
    z = float(stats.norm.ppf((1.0 + coverage) / 2.0))
    chi = float(stats.chi2.ppf(confidence, n - 1))
    k = z * math.sqrt((n - 1) / chi) * math.sqrt(1.0 + 1.0 / n)
    return {
        "ti_low": _f(mu - k * sd),
        "ti_high": _f(mu + k * sd),
        "coverage": _f(coverage, 4),
        "confidence": _f(confidence, 4),
        "k": _f(k),
        "n": n,
    }


@_reg(
    "SC12", "pairs", ("yhat", "ci_low", "ci_high", "alpha", "n"), "分割共形区间（校准集残差分位）"
)
def sc12_conformal(data: Any, x0: float = None, alpha: float = 0.1) -> Dict[str, Any]:
    x, y = _two_samples(data)
    n = min(len(x), len(y))
    x, y = x[:n], y[:n]
    m = n // 2
    if m < 4:
        return {"yhat": None, "ci_low": None, "ci_high": None, "alpha": _f(alpha, 4), "n": n}
    Xtr = sm.add_constant(x[:m], has_constant="add")
    fit = sm.OLS(y[:m], Xtr).fit()
    Xc = sm.add_constant(x[m:], has_constant="add")
    scores = np.abs(y[m:] - fit.predict(Xc))
    nc = len(scores)
    q_level = min(1.0, math.ceil((nc + 1) * (1 - alpha)) / nc)
    q = float(np.quantile(scores, q_level, method="higher")) if nc else 0.0
    point = float(x0) if x0 is not None else float(x[-1])
    yhat = float(fit.predict(np.asarray([[1.0, point]]))[0])
    return {
        "yhat": _f(yhat),
        "ci_low": _f(yhat - q),
        "ci_high": _f(yhat + q),
        "alpha": _f(alpha, 4),
        "n": n,
    }


# ======================================================================
# §2.2 回归与模型诊断（SC13–SC24）
# ======================================================================


@_reg("SC13", "pairs", ("betas", "intercept", "se", "r2", "n"), "OLS（含常数项）")
def sc13_ols(data: Any, add_const: bool = True) -> Dict[str, Any]:
    X = _matrix(data)
    y = _target(data)
    m = min(X.shape[0], len(y))
    X, y = X[:m], y[:m]
    design = sm.add_constant(X, has_constant="add") if add_const else X
    fit = sm.OLS(y, design).fit()
    params = np.asarray(fit.params, dtype=float)
    if add_const:
        intercept, betas, se = params[0], params[1:], np.asarray(fit.bse, dtype=float)[1:]
    else:
        intercept, betas, se = 0.0, params, np.asarray(fit.bse, dtype=float)
    return {
        "betas": _lst(betas),
        "intercept": _f(intercept),
        "se": _lst(se),
        "r2": _f(fit.rsquared, 4),
        "n": m,
    }


@_reg(
    "SC14", "pairs", ("betas", "intercept", "r2", "n"), "WLS（权重取 data[w]/[weights]，缺省等权）"
)
def sc14_wls(data: Any) -> Dict[str, Any]:
    X = _matrix(data)
    y = _target(data)
    m = min(X.shape[0], len(y))
    X, y = X[:m], y[:m]
    w = None
    if isinstance(data, Mapping):
        for key in ("w", "weights"):
            if key in data:
                w = _vals(data[key])[:m]
                break
    if w is None or len(w) != m or float(np.sum(w)) <= _EPS:
        w = np.ones(m)
    design = sm.add_constant(X, has_constant="add")
    fit = sm.WLS(y, design, weights=w).fit()
    return {
        "betas": _lst(fit.params[1:]),
        "intercept": _f(fit.params[0]),
        "r2": _f(fit.rsquared, 4),
        "n": m,
    }


@_reg(
    "SC15",
    "panel",
    ("coef", "intercept", "odds_ratio", "pseudo_r2", "n"),
    "Logistic MLE；非 0/1 目标按中位数二值化",
)
def sc15_logistic(data: Any) -> Dict[str, Any]:
    X, y = _xy(data)
    n = len(y)
    if n < 4:
        return {"coef": [], "intercept": None, "odds_ratio": [], "pseudo_r2": None, "n": n}
    if not set(np.unique(y)).issubset({0.0, 1.0}):
        y = (y > float(np.median(y))).astype(float)
    design = sm.add_constant(X, has_constant="add")
    try:
        fit = sm.Logit(y, design).fit(disp=0, maxiter=200)
        coef = np.asarray(fit.params, dtype=float)
        pseudo = float(fit.prsquared)
        odds = np.exp(coef[1:])
    except Exception:  # 完全分离等数值失败 → sklearn 兜底（确定性）
        from sklearn.linear_model import LogisticRegression

        clf = LogisticRegression(max_iter=1000, random_state=_SEED)
        clf.fit(X, y)
        coef = np.concatenate([[float(clf.intercept_[0])], np.asarray(clf.coef_[0], dtype=float)])
        probs = clf.predict_proba(X)[:, 1]
        eps = 1e-12
        ll = float(np.sum(y * np.log(probs + eps) + (1 - y) * np.log(1 - probs + eps)))
        p0 = float(np.mean(y))
        ll0 = float(n * (p0 * math.log(p0 + eps) + (1 - p0) * math.log(1 - p0 + eps)))
        pseudo = 1.0 - ll / ll0 if abs(ll0) > eps else 0.0
        odds = np.exp(coef[1:])
    return {
        "coef": _lst(coef[1:]),
        "intercept": _f(coef[0]),
        "odds_ratio": _lst(odds),
        "pseudo_r2": _f(pseudo, 4),
        "n": n,
    }


@_reg(
    "SC16", "panel", ("coef", "intercept", "irr", "deviance", "n"), "Poisson GLM（负目标整体平移）"
)
def sc16_poisson(data: Any) -> Dict[str, Any]:
    X, y = _xy(data)
    n = len(y)
    if n < 4:
        return {"coef": [], "intercept": None, "irr": [], "deviance": None, "n": n}
    if float(np.min(y)) < 0:
        y = y - float(np.min(y))
    design = sm.add_constant(X, has_constant="add")
    fit = sm.GLM(y, design, family=sm.families.Poisson()).fit(maxiter=200, tol=1e-8)
    coef = np.asarray(fit.params, dtype=float)
    return {
        "coef": _lst(coef[1:]),
        "intercept": _f(coef[0]),
        "irr": _lst(np.exp(coef[1:])),
        "deviance": _f(fit.deviance),
        "n": n,
    }


@_reg("SC17", "pairs", ("betas", "taus", "n"), "分位数回归 τ=0.1/0.5/0.9（statsmodels QuantReg）")
def sc17_quantile_regression(data: Any, taus: Sequence[float] = (0.1, 0.5, 0.9)) -> Dict[str, Any]:
    X, y = _xy(data)
    n = len(y)
    design = sm.add_constant(X, has_constant="add")
    out: Dict[str, List[Any]] = {}
    for tau in taus:
        fit = sm.QuantReg(y, design).fit(q=float(tau), max_iter=1000)
        out[str(_f(tau, 2))] = _lst(fit.params)
    return {"betas": out, "taus": [_f(t, 2) for t in taus], "n": n}


@_reg("SC18", "pairs", ("betas", "intercept", "scale", "n"), "Huber 稳健回归（ε=1.35, 固定容差）")
def sc18_huber(data: Any) -> Dict[str, Any]:
    X, y = _xy(data)
    n = len(y)
    if n < 4:
        return {"betas": [], "intercept": None, "scale": None, "n": n}
    design = sm.add_constant(X, has_constant="add")
    fit = sm.RLM(y, design, M=sm.robust.norms.HuberT(t=1.35)).fit(maxiter=100, tol=1e-8)
    coef = np.asarray(fit.params, dtype=float)
    return {"betas": _lst(coef[1:]), "intercept": _f(coef[0]), "scale": _f(fit.scale), "n": n}


@_reg("SC19", "pairs", ("betas", "intercept", "alpha", "n"), "Ridge（α=1.0，X 标准化后）")
def sc19_ridge(data: Any, alpha: float = 1.0) -> Dict[str, Any]:
    X, y = _xy(data)
    n = len(y)
    if n < 3:
        return {"betas": [], "intercept": None, "alpha": _f(alpha, 4), "n": n}
    mu = X.mean(axis=0)
    sd = X.std(axis=0, ddof=0)
    sd = np.where(sd > _EPS, sd, 1.0)
    Xs = (X - mu) / sd
    model = Ridge(alpha=float(alpha), random_state=_SEED).fit(Xs, y)
    return {
        "betas": _lst(model.coef_),
        "intercept": _f(model.intercept_),
        "alpha": _f(alpha, 4),
        "n": n,
    }


@_reg("SC20", "panel", ("vif", "max_vif", "n"), "方差膨胀因子 VIF=1/(1−R²_j)")
def sc20_vif(data: Any) -> Dict[str, Any]:
    X = _matrix(data)
    n, p = X.shape
    if p < 2:
        return {"vif": [1.0], "max_vif": 1.0, "n": n}
    design = sm.add_constant(X, has_constant="add")
    vals: List[Any] = []
    for j in range(p):
        try:
            v = float(variance_inflation_factor(design, j + 1))
        except Exception:
            v = float("nan")
        vals.append(_f(v))
    finite = [v for v in vals if v is not None]
    return {"vif": vals, "max_vif": _f(max(finite)) if finite else None, "n": n}


@_reg("SC21", "pairs", ("lm", "p", "f", "fp", "n"), "Breusch-Pagan 异方差检验")
def sc21_breusch_pagan(data: Any) -> Dict[str, Any]:
    fit, _ = _ols(data)
    design = np.asarray(fit.model.exog, dtype=float)
    lm, p, f, fp = het_breuschpagan(np.asarray(fit.resid, dtype=float), design)
    return {"lm": _f(lm), "p": _f(p), "f": _f(f), "fp": _f(fp), "n": int(fit.nobs)}


@_reg("SC22", "pairs", ("lm", "p", "f", "fp", "n"), "White 异方差检验（辅助回归）")
def sc22_white(data: Any) -> Dict[str, Any]:
    fit, _ = _ols(data)
    design = np.asarray(fit.model.exog, dtype=float)
    lm, p, f, fp = het_white(np.asarray(fit.resid, dtype=float), design)
    return {"lm": _f(lm), "p": _f(p), "f": _f(f), "fp": _f(fp), "n": int(fit.nobs)}


@_reg("SC23", "pairs", ("dw", "n"), "Durbin-Watson 残差自相关（≈2 无自相关）")
def sc23_durbin_watson(data: Any) -> Dict[str, Any]:
    fit, _ = _ols(data)
    dw = durbin_watson(np.asarray(fit.resid, dtype=float))
    return {"dw": _f(dw), "n": int(fit.nobs)}


@_reg(
    "SC24",
    "pairs",
    ("cooks_max", "leverage_max", "n_outliers", "flags", "n"),
    "Cook's D / 杠杆 h_ii（阈值 4/n）",
)
def sc24_influence(data: Any) -> Dict[str, Any]:
    fit, _ = _ols(data)
    infl = fit.get_influence()
    cooks = np.asarray(infl.cooks_distance[0], dtype=float)
    lev = np.asarray(infl.hat_matrix_diag, dtype=float)
    n = int(fit.nobs)
    thr = 4.0 / n if n else 0.0
    flags = [bool(v > thr) for v in cooks]
    return {
        "cooks_max": _f(np.max(cooks)),
        "leverage_max": _f(np.max(lev)),
        "n_outliers": int(sum(flags)),
        "flags": flags,
        "n": n,
    }


# ======================================================================
# §2.3 实验设计（SC25–SC30）
# ======================================================================


@_reg("SC25", "panel", ("f", "p", "eta2", "n", "k"), "单因素 ANOVA（F 检验 + η²）")
def sc25_anova(data: Any) -> Dict[str, Any]:
    groups = [g for g in _groups(data) if len(g) > 0]
    k = len(groups)
    n = int(sum(len(g) for g in groups))
    if k < 2 or n <= k:
        return {"f": None, "p": None, "eta2": None, "n": n, "k": k}
    f, p = stats.f_oneway(*groups)
    allv = np.concatenate(groups)
    grand = float(np.mean(allv))
    ssb = float(sum(len(g) * (np.mean(g) - grand) ** 2 for g in groups))
    sst = float(np.sum((allv - grand) ** 2))
    return {"f": _f(f), "p": _f(p), "eta2": _f(ssb / sst if sst > _EPS else 0.0, 4), "n": n, "k": k}


@_reg(
    "SC26", "panel", ("f", "p", "terms", "n"), "双因素 ANOVA（主效应+交互；矩阵输入退化为可加模型）"
)
def sc26_two_way_anova(data: Any) -> Dict[str, Any]:
    if isinstance(data, Mapping) and "y" in data:
        y = _target(data)
        keys = [k for k in data if k not in ("y", "target", "value", "w", "weights")]
        keys = [k for k in keys if isinstance(data[k], (list, tuple, np.ndarray, pd.Series))]
        if len(keys) >= 2:
            m = min([len(y)] + [len(data[k]) for k in keys[:2]])
            df = pd.DataFrame(
                {
                    "y": y[:m],
                    "a": [str(v) for v in list(data[keys[0]])[:m]],
                    "b": [str(v) for v in list(data[keys[1]])[:m]],
                }
            )
            fit = sm_ols("y ~ C(a) + C(b) + C(a):C(b)", data=df).fit()
            table = anova_lm(fit, typ=2)
            terms = [t for t in table.index if t != "Residual"]
            return {
                "f": [_f(table.loc[t, "F"]) for t in terms],
                "p": [_f(table.loc[t, "PR(>F)"]) for t in terms],
                "terms": terms,
                "n": int(len(df)),
            }
    M = _matrix(data)
    p = M.shape[1]
    if p < 2:
        return {"f": [], "p": [], "terms": [], "n": int(M.shape[0])}
    recs = []
    for i in range(M.shape[0]):
        for j in range(p):
            recs.append({"y": float(M[i, j]), "a": f"A{i}", "b": f"B{j}"})
    df = pd.DataFrame(recs)
    fit = sm_ols("y ~ C(a) + C(b)", data=df).fit()
    table = anova_lm(fit, typ=2)
    terms = [t for t in table.index if t != "Residual"]
    return {
        "f": [_f(table.loc[t, "F"]) for t in terms],
        "p": [_f(table.loc[t, "PR(>F)"]) for t in terms],
        "terms": terms,
        "n": int(len(df)),
    }


@_reg("SC27", "panel", ("f", "p", "coef_covariate", "n"), "ANCOVA：y ~ C(group) + 协变量")
def sc27_ancova(data: Any) -> Dict[str, Any]:
    y = _target(data)
    if not isinstance(data, Mapping) or "group" not in data:
        raise ValueError("ANCOVA needs group + covariate x")
    grp = list(data["group"])
    cov = _vals(data.get("x", data.get("covariate")))
    m = min(len(y), len(grp), len(cov))
    df = pd.DataFrame({"y": y[:m], "grp": [str(v) for v in grp[:m]], "x": cov[:m]})
    fit = sm_ols("y ~ C(grp) + x", data=df).fit()
    table = anova_lm(fit, typ=2)
    row = "C(grp)"
    return {
        "f": _f(table.loc[row, "F"]),
        "p": _f(table.loc[row, "PR(>F)"]),
        "coef_covariate": _f(fit.params.get("x")),
        "n": m,
    }


@_reg(
    "SC28",
    "panel",
    ("f", "p", "df_num", "df_den", "n"),
    "重复测量 ANOVA（AnovaRM，行=被试，列=条件）",
)
def sc28_repeated_measures(data: Any) -> Dict[str, Any]:
    M = _matrix(data)
    n_sub, k = M.shape
    if n_sub < 3 or k < 2:
        return {"f": None, "p": None, "df_num": None, "df_den": None, "n": n_sub}
    recs = [
        {"subject": i, "condition": str(j), "value": float(M[i, j])}
        for i in range(n_sub)
        for j in range(k)
    ]
    df = pd.DataFrame(recs)
    table = AnovaRM(df, "value", "subject", within=["condition"]).fit().anova_table
    return {
        "f": _f(table["F Value"].iloc[0]),
        "p": _f(table["Pr > F"].iloc[0]),
        "df_num": _f(table["Num DF"].iloc[0]),
        "df_den": _f(table["Den DF"].iloc[0]),
        "n": n_sub,
    }


@_reg("SC29", "panel", ("effects", "n", "k"), "析因设计主效应 + 两两交互（2^k 对比）")
def sc29_factorial_effects(data: Any) -> Dict[str, Any]:
    if isinstance(data, Mapping) and "y" in data:
        y = _target(data)
        fkeys = [k for k in data if k not in ("y", "target", "value", "w", "weights")]
        factors = {}
        for key in fkeys:
            arr = _vals(data[key])
            if len(arr) == len(y) and len(np.unique(arr)) <= 2:
                factors[key] = (arr > 0).astype(int)
        n = len(y)
    else:
        M = _matrix(data)
        y = M[:, -1]
        factors = {f"f{j + 1}": (M[:, j] > 0).astype(int) for j in range(M.shape[1] - 1)}
        n = int(M.shape[0])
    effects: Dict[str, Any] = {}
    for key, f in factors.items():
        hi, lo = y[f == 1], y[f == 0]
        effects[key] = _f(float(np.mean(hi) - np.mean(lo))) if len(hi) and len(lo) else None
    names = list(factors)
    for a in range(len(names)):
        for b in range(a + 1, len(names)):
            fa, fb = factors[names[a]], factors[names[b]]
            cells = [y[(fa == i) & (fb == j)] for i in (0, 1) for j in (0, 1)]
            if all(len(c) > 0 for c in cells):
                eff = (
                    float(np.mean(cells[3]))
                    - float(np.mean(cells[2]))
                    - float(np.mean(cells[1]))
                    + float(np.mean(cells[0]))
                )
                effects[f"interaction_{names[a]}_{names[b]}"] = _f(eff)
    return {"effects": effects, "n": n, "k": len(factors)}


@_reg("SC30", "panel", ("p_adj", "pairs", "reject", "n"), "事后多重比较 Tukey HSD")
def sc30_tukey(data: Any, alpha: float = 0.05) -> Dict[str, Any]:
    groups = [g for g in _groups(data) if len(g) > 0]
    if len(groups) < 2:
        return {"p_adj": [], "pairs": [], "reject": [], "n": int(sum(len(g) for g in groups))}
    labels: List[str] = []
    values: List[float] = []
    for i, g in enumerate(groups):
        labels.extend([f"g{i + 1}"] * len(g))
        values.extend(float(v) for v in g)
    res = pairwise_tukeyhsd(np.asarray(values), np.asarray(labels), alpha=alpha)
    pairs = [f"{r[0]}-{r[1]}" for r in res._results_table.data[1:]]
    return {
        "p_adj": _lst(res.pvalues),
        "pairs": pairs,
        "reject": [bool(v) for v in res.reject],
        "n": len(values),
    }


# ======================================================================
# §2.4 降维与结构（SC31–SC38）
# ======================================================================


@_reg(
    "SC31", "panel", ("ratio", "cum_ratio", "loadings", "k", "n"), "PCA 特征分解（sklearn，中心化）"
)
def sc31_pca(data: Any, k: int = None) -> Dict[str, Any]:
    M = _matrix(data)
    n, p = M.shape
    kk = int(k) if k is not None else min(n, p)
    kk = max(1, min(kk, n, p))
    model = PCA(n_components=kk, random_state=_SEED).fit(M)
    ratio = np.asarray(model.explained_variance_ratio_, dtype=float)
    return {
        "ratio": _lst(ratio, 4),
        "cum_ratio": _lst(np.cumsum(ratio), 4),
        "loadings": _mtx(model.components_),
        "k": kk,
        "n": n,
    }


@_reg("SC32", "panel", ("s", "u", "v", "n"), "SVD 奇异值分解（full_matrices=False）")
def sc32_svd(data: Any, k: int = None) -> Dict[str, Any]:
    M = _matrix(data)
    u, s, vt = np.linalg.svd(M, full_matrices=False)
    if k is not None:
        kk = max(1, min(int(k), len(s)))
        u, s, vt = u[:, :kk], s[:kk], vt[:kk, :]
    return {"s": _lst(s), "u": _mtx(u), "v": _mtx(vt), "n": int(M.shape[0])}


@_reg("SC33", "panel", ("loadings", "uniqueness", "k", "n"), "因子分析（固定 k 因子，固定容差）")
def sc33_factor_analysis(data: Any, k: int = 2) -> Dict[str, Any]:
    M = _matrix(data)
    n, p = M.shape
    kk = max(1, min(int(k), p))
    model = FactorAnalysis(n_components=kk, random_state=_SEED, max_iter=1000, tol=1e-6)
    model.fit(M)
    return {
        "loadings": _mtx(model.components_),
        "uniqueness": _lst(model.noise_variance_),
        "k": kk,
        "n": n,
    }


@_reg("SC34", "panel", ("sources", "mixing", "k", "n"), "ICA（FastICA, seed=42）")
def sc34_ica(data: Any, k: int = None) -> Dict[str, Any]:
    M = _matrix(data)
    n, p = M.shape
    kk = int(k) if k is not None else min(2, p)
    kk = max(1, min(kk, p))
    model = FastICA(
        n_components=kk, random_state=_SEED, max_iter=500, tol=1e-4, whiten="unit-variance"
    )
    sources = model.fit_transform(M)
    return {"sources": _mtx(sources), "mixing": _mtx(model.mixing_), "k": kk, "n": n}


@_reg(
    "SC35", "panel", ("precision", "edges", "alpha", "n"), "图 Lasso（固定 α=0.1，精度矩阵/边数）"
)
def sc35_graphical_lasso(data: Any, alpha: float = 0.1) -> Dict[str, Any]:
    M = _matrix(data)
    n, p = M.shape
    if p < 2:
        return {"precision": _mtx(np.zeros((1, 1))), "edges": 0, "alpha": _f(alpha, 4), "n": n}
    try:
        model = GraphicalLasso(alpha=float(alpha), max_iter=200, tol=1e-4).fit(M)
        prec = np.asarray(model.precision_, dtype=float)
    except Exception:
        prec = np.linalg.pinv(np.cov(M, rowvar=False))
    off = prec - np.diag(np.diag(prec))
    edges = int(np.sum(np.abs(off) > 1e-8) // 2)
    return {"precision": _mtx(prec), "edges": edges, "alpha": _f(alpha, 4), "n": n}


@_reg("SC36", "panel", ("linkage", "p", "n"), "层次聚类（相关距离 + average）")
def sc36_hierarchical(data: Any) -> Dict[str, Any]:
    M = _matrix(data)
    n, p = M.shape
    if p < 2:
        return {"linkage": [], "p": p, "n": n}
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = np.corrcoef(M, rowvar=False)
    corr = np.nan_to_num(corr, nan=0.0)
    dist = 1.0 - corr
    np.fill_diagonal(dist, 0.0)
    dist = np.clip(dist, 0.0, None)
    link = linkage(squareform(dist, checks=False), method="average")
    return {"linkage": _mtx(link), "p": p, "n": n}


@_reg("SC37", "panel", ("labels", "inertia", "k", "n"), "K-Means（seed=42, k 固定）")
def sc37_kmeans(data: Any, k: int = 3) -> Dict[str, Any]:
    M = _matrix(data)
    n = int(M.shape[0])
    kk = max(2, min(int(k), n))
    model = KMeans(n_clusters=kk, random_state=_SEED, n_init=10).fit(M)
    return {
        "labels": [int(v) for v in model.labels_],
        "inertia": _f(model.inertia_),
        "k": kk,
        "n": n,
    }


@_reg("SC38", "panel", ("silhouette", "k", "n"), "轮廓系数（无标签时用 K-Means k=3 生成）")
def sc38_silhouette(data: Any, k: int = 3, labels: Sequence[int] = None) -> Dict[str, Any]:
    M = _matrix(data)
    n = int(M.shape[0])
    if labels is not None:
        lab = np.asarray(list(labels), dtype=int)[:n]
        kk = int(len(np.unique(lab)))
    else:
        kk = max(2, min(int(k), n))
        lab = KMeans(n_clusters=kk, random_state=_SEED, n_init=10).fit_predict(M)
    if kk < 2 or kk >= n:
        return {"silhouette": None, "k": kk, "n": n}
    return {"silhouette": _f(silhouette_score(M, lab), 4), "k": kk, "n": n}


# ======================================================================
# §2.5 信号与频谱（SC39–SC46）
# ======================================================================


@_reg("SC39", "series", ("freq", "amp", "dominant_freq", "n"), "FFT 幅值谱（单边）")
def sc39_fft(data: Any) -> Dict[str, Any]:
    xs = _series(data)
    n = len(xs)
    spec = np.fft.rfft(xs - np.mean(xs))
    amp = 2.0 * np.abs(spec) / n
    if len(amp):
        amp[0] *= 0.5
    freq = np.fft.rfftfreq(n, d=1.0)
    dom = float(freq[int(np.argmax(amp[1:])) + 1]) if len(amp) > 1 else 0.0
    return {"freq": _lst(freq), "amp": _lst(amp), "dominant_freq": _f(dom), "n": n}


@_reg("SC40", "series", ("freq", "psd", "n"), "Welch 功率谱（段长 256/重叠 50%）")
def sc40_welch(data: Any, fs: float = 1.0) -> Dict[str, Any]:
    xs = _series(data)
    n = len(xs)
    nperseg = int(min(256, n))
    if nperseg < 4:
        return {"freq": [], "psd": [], "n": n}
    freq, psd = welch(xs, fs=fs, nperseg=nperseg, noverlap=nperseg // 2)
    return {"freq": _lst(freq), "psd": _lst(psd), "n": n}


@_reg("SC41", "series", ("freq", "power", "period", "n"), "Lomb-Scargle 周期图（非均匀采样）")
def sc41_lomb_scargle(data: Any) -> Dict[str, Any]:
    xs = _series(data)
    n = len(xs)
    if n < 4:
        return {"freq": [], "power": [], "period": None, "n": n}
    t = _vals(data["t"]) if isinstance(data, Mapping) and "t" in data else np.arange(n, dtype=float)
    if len(t) != n:
        t = np.arange(n, dtype=float)
    freq = np.linspace(1.0 / n, 0.5, 500)
    power = lombscargle(t, xs, 2.0 * np.pi * freq, normalize=True)
    period = 1.0 / float(freq[int(np.argmax(power))])
    return {"freq": _lst(freq, 6), "power": _lst(power), "period": _f(period), "n": n}


@_reg(
    "SC42",
    "series",
    ("coeffs", "energy", "levels", "n"),
    "离散小波（Haar，4 层；无 pywt 时确定性近似）",
)
def sc42_dwt(data: Any, levels: int = 4) -> Dict[str, Any]:
    xs = _series(data)
    n = len(xs)
    approx = xs.copy()
    coeffs: List[List[Any]] = []
    energy: List[Any] = []
    total = float(np.sum(xs**2))
    used = 0
    for _ in range(max(1, int(levels))):
        if len(approx) < 2:
            break
        even = approx[0::2]
        odd = approx[1::2]
        m = min(len(even), len(odd))
        a = (even[:m] + odd[:m]) / math.sqrt(2.0)
        d = (even[:m] - odd[:m]) / math.sqrt(2.0)
        coeffs.append(_lst(d))
        energy.append(_f(float(np.sum(d**2)) / total, 4) if total > _EPS else 0.0)
        approx = a
        used += 1
    coeffs.append(_lst(approx))
    energy.append(_f(float(np.sum(approx**2)) / total, 4) if total > _EPS else 0.0)
    return {"coeffs": coeffs, "energy": energy, "levels": used, "n": n}


def _cwt(x: np.ndarray, scales: np.ndarray, w0: float = 6.0) -> np.ndarray:
    """复 Morlet 连续小波变换（numpy 实现，确定性）。"""
    n = len(x)
    sd = float(np.std(x))
    z = (x - float(np.mean(x))) / (sd if sd > _EPS else 1.0)
    out = np.zeros((len(scales), n), dtype=complex)
    for i, s in enumerate(scales):
        half = max(1, int(3 * s))
        t = np.arange(-half, half + 1, dtype=float)
        wavelet = np.exp(1j * w0 * t / s) * np.exp(-0.5 * (t / s) ** 2) / math.sqrt(s)
        # mode="full" 后按小波中心对齐裁剪为 n，避免长小波把输出撑大
        full = np.convolve(z, wavelet, mode="full")
        start = (len(wavelet) - 1) // 2
        out[i] = full[start : start + n]
    return out


@_reg(
    "SC43",
    "pairs",
    ("coherence", "mean_coherence", "max_coherence", "scales", "n"),
    "小波相干（复 Morlet CWT + 时频平滑）",
)
def sc43_wavelet_coherence(data: Any) -> Dict[str, Any]:
    x, y = _two_samples(data)
    n = min(len(x), len(y))
    x, y = x[:n], y[:n]
    if n < 8:
        return {
            "coherence": [],
            "mean_coherence": None,
            "max_coherence": None,
            "scales": [],
            "n": n,
        }
    scales = np.arange(1.0, max(2.0, min(8.0, n / 4.0)) + 1.0, 1.0)
    wx, wy = _cwt(x, scales), _cwt(y, scales)
    sxy = uniform_filter1d(uniform_filter1d(wx * np.conj(wy), size=3, axis=1), size=2, axis=0)
    sxx = uniform_filter1d(uniform_filter1d(np.abs(wx) ** 2, size=3, axis=1), size=2, axis=0)
    syy = uniform_filter1d(uniform_filter1d(np.abs(wy) ** 2, size=3, axis=1), size=2, axis=0)
    coh = np.abs(sxy) ** 2 / (sxx * syy + _EPS)
    coh = np.clip(coh, 0.0, 1.0)
    return {
        "coherence": _mtx(coh, 4),
        "mean_coherence": _f(np.mean(coh), 4),
        "max_coherence": _f(np.max(coh), 4),
        "scales": _lst(scales, 2),
        "n": n,
    }


@_reg(
    "SC44",
    "series",
    ("smoothed", "window", "polyorder", "n"),
    "Savitzky-Golay 平滑（窗口 11, 阶 3）",
)
def sc44_savgol(data: Any, window: int = 11, polyorder: int = 3) -> Dict[str, Any]:
    xs = _series(data)
    n = len(xs)
    w = int(window) if n >= int(window) else (n if n % 2 == 1 else n - 1)
    w = max(3, w)
    order = max(1, min(int(polyorder), w - 1))
    if n < 3:
        return {"smoothed": _lst(xs), "window": w, "polyorder": order, "n": n}
    return {"smoothed": _lst(savgol_filter(xs, w, order)), "window": w, "polyorder": order, "n": n}


@_reg(
    "SC45",
    "series",
    ("filtered", "order", "cutoff", "n"),
    "Butterworth 零相位滤波（4 阶，固定截止）",
)
def sc45_butterworth(data: Any, order: int = 4, cutoff: float = 0.2) -> Dict[str, Any]:
    xs = _series(data)
    n = len(xs)
    wn = min(max(float(cutoff), 0.01), 0.99)
    if n < 16:
        return {"filtered": _lst(xs), "order": int(order), "cutoff": _f(wn, 4), "n": n}
    b, a = butter(int(order), wn, btype="low")
    try:
        filtered = filtfilt(b, a, xs)
    except ValueError:
        filtered = filtfilt(b, a, xs, padlen=min(len(xs) - 1, 3 * max(len(a), len(b))))
    return {"filtered": _lst(filtered), "order": int(order), "cutoff": _f(wn, 4), "n": n}


@_reg("SC46", "series", ("envelope", "phase", "n"), "Hilbert 解析信号：包络/瞬时相位")
def sc46_hilbert(data: Any) -> Dict[str, Any]:
    xs = _series(data)
    n = len(xs)
    if n < 4:
        return {"envelope": _lst(np.abs(xs)), "phase": _lst(np.zeros(n)), "n": n}
    analytic = hilbert(xs)
    return {
        "envelope": _lst(np.abs(analytic)),
        "phase": _lst(np.unwrap(np.angle(analytic))),
        "n": n,
    }
