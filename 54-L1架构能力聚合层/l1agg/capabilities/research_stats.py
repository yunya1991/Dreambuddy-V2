# -*- coding: utf-8 -*-
"""J 组科研方法能力出口（D-J01…D-J29，批次 B-23…B-46）。

分工：能力层只做「输入规范化 + 门禁 + 信封 + 一句话」，所有统计量一律调用
`l1agg.methods.run`（方法层唯一 SSoT），不在此重算任何口径。

输入契约（与 `research_sc_a/_b` 的辅助函数一致）：
  - 单序列：`[num, ...]` 或 `{"x": [...]}`；
  - 双序列：`{"x": [...], "y": [...]}`；
  - 面板/矩阵：`{"X": [[...], ...]}` 或 `{"series": {sym: [...]}}`（时点为行、标的为列）；
  - 空间：`{"coords": [[x, y], ...], "values": [...]}`；
  - 生存：`{"time": [...], "event": [...], "group": [...], "x": [...]}`；
  - meta：`{"effect": [...], "se": [...]}`。

门禁统一为方法层 `min_n=30`（`_sample_n` 对面板取最短序列长度，即时点数）；
不足时返回 `status=empty`，不抛异常给 L1。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..methods import run as run_method
from .envelope import (
    build,
    quality_for,
    unavailable,
)

INTENT_TREND_TEST = "trend_test"
INTENT_OUTLIER = "outlier_query"
INTENT_SIGNAL = "signal_decomposition"
INTENT_INFORMATION = "information_query"
INTENT_COMPLEXITY = "complexity_query"
INTENT_EXTREME = "extreme_value"
INTENT_UNCERTAINTY = "uncertainty_query"
INTENT_DESIGN = "experiment_design"
INTENT_GROUP = "group_comparison"
INTENT_DIAGNOSTIC = "regression_diagnostic"
INTENT_CLUSTER = "clustering_query"
INTENT_SPATIAL = "spatial_query"
INTENT_SURVIVAL = "survival_query"
INTENT_RELIABILITY = "reliability_query"
INTENT_META = "meta_analysis"
INTENT_MISSING = "missing_data_query"

MIN_SERIES = 30
MIN_PANEL = 30
MIN_PAIRS = 30
MIN_SURVIVAL = 30
MIN_SPATIAL = 30
MIN_META = 30

SOURCE_SERIES = "datacenter.series"
SOURCE_PANEL = "datacenter.panel"
SOURCE_SPATIAL = "datacenter.spatial_frame"


# ---------------- 通用工具 ----------------


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


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


def _series_of(data: Any) -> List[float]:
    """单序列：list / {"x"|"series"|"values"|"value"|"y": [...]}。"""
    if isinstance(data, Mapping):
        for key in ("x", "series", "values", "value", "y", "returns", "price"):
            if key in data and not isinstance(data[key], Mapping):
                return _floats(data[key])
        raise ValueError("series data must contain x/series/values")
    return _floats(data)


def _frame_of(data: Any) -> Tuple[List[str], List[List[float]]]:
    """矩阵输入 → (列名, 行列表)。支持 {"X": [[...]]} 与 {"series": {sym: [...]}}。"""
    if data is None:
        raise ValueError("panel data is required")
    if isinstance(data, Mapping) and "series" in data and isinstance(data["series"], Mapping):
        raw = data["series"]
        names = sorted(str(k) for k in raw)
        cols = [_floats(raw[k]) for k in names]
        m = min((len(c) for c in cols), default=0)
        rows = [[c[i] for c in cols] for i in range(m)]
        return names, rows
    rows_raw = None
    if isinstance(data, Mapping):
        for key in ("X", "matrix", "design", "features", "rows", "table"):
            if key in data and isinstance(data[key], Sequence):
                rows_raw = data[key]
                break
        if rows_raw is None:
            cols = []
            names = []
            for key, val in data.items():
                if key in (
                    "y",
                    "target",
                    "value",
                    "label",
                    "group",
                    "state",
                    "time",
                    "event",
                    "coords",
                ):
                    continue
                if isinstance(val, Sequence) and not isinstance(val, str):
                    cols.append(_floats(val))
                    names.append(str(key))
            m = min((len(c) for c in cols), default=0)
            rows_raw = [[c[i] for c in cols] for i in range(m)]
            return names, rows_raw
    else:
        rows_raw = data
    rows = [[float(v) for v in row] for row in rows_raw]
    width = min((len(r) for r in rows), default=0)
    rows = [r[:width] for r in rows]
    return [f"c{i}" for i in range(width)], rows


def _call(method_id: str, data: Any, **params: Any) -> Dict[str, Any]:
    """调方法层；输入/门禁/数值问题一律收敛为结构化块，不抛给 L1。"""
    try:
        env = run_method(method_id, data, **params)
    except ValueError as exc:
        return {
            "gate": "insufficient_history",
            "reason": str(exc),
            "result": None,
            "method": method_id,
        }
    except Exception as exc:  # noqa: BLE001 - 数值退化不阻断能力出口
        return {
            "gate": "calculation_failed",
            "reason": str(exc),
            "result": None,
            "method": method_id,
        }
    if env.get("gate") != "ok":
        return {"gate": env.get("gate"), "result": None, "method": method_id}
    return {"gate": "ok", "result": env["result"], "method": method_id}


def _ok(blocks: Mapping[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {mid: blk for mid, blk in blocks.items() if blk["gate"] == "ok"}


def _quality(n: int, min_n: int, source: str, align: str) -> Dict[str, Any]:
    return quality_for(
        n,
        min_n=min_n,
        span=None,
        sources=[source],
        align_method=align,
        timezone="UTC",
    )


def _empty(
    capability_id: str,
    intent: str,
    reason: str,
    trace_id: Optional[str],
    source: str = SOURCE_SERIES,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    out = unavailable(
        capability=capability_id,
        intent=intent,
        reason=reason,
        trace_id=trace_id,
    )
    data = out.get("data")
    if isinstance(data, dict):
        data.setdefault("params", dict(params or {}))
        data.setdefault("sources", [source])
    return out


def _fmt(value: Any, digits: int = 4) -> str:
    return "n/a" if not _is_num(value) else f"{float(value):.{digits}f}"


# ---------------- D-J01 趋势检验 ----------------


def trend_test(
    series: Any = None,
    *,
    alpha: float = 0.05,
    capability_id: str = "D-J01",
    intent: str = INTENT_TREND_TEST,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    xs = _series_of(series)
    if len(xs) < MIN_SERIES:
        return _empty(
            capability_id,
            intent,
            f"序列样本不足 {MIN_SERIES} 点",
            trace_id,
            params={"alpha": alpha},
        )
    mk = _call("SC52", {"x": xs}, alpha=alpha)
    sen = _call("SC53", {"x": xs}, alpha=alpha)
    ok = _ok({"SC52": mk, "SC53": sen})
    if "SC52" not in ok:
        return _empty(
            capability_id,
            intent,
            "Mann-Kendall 趋势检验计算失败",
            trace_id,
            params={"alpha": alpha},
        )
    mk_r = mk["result"]
    sen_r = sen["result"] if "SC53" in ok else None
    parts = [
        f"Mann-Kendall τ={_fmt(mk_r['tau'])}，z={_fmt(mk_r['z'], 2)}，p={_fmt(mk_r['p'])}，判定「{mk_r['trend']}」"
    ]
    if sen_r is not None:
        parts.append(
            f"Sen 斜率 {_fmt(sen_r['slope'], 6)}（95% CI {_fmt(sen_r['ci_low'], 6)} ~ {_fmt(sen_r['ci_high'], 6)}）"
        )
    n = int(mk_r["n"])
    answer = "；".join(parts) + f"。样本为 {n} 个时点，趋势检验只描述历史方向，不代表未来延续。"
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"alpha": alpha},
            "capabilities": {
                capability_id: {
                    "methods": sorted(ok),
                    "n": n,
                    "trend": mk_r["trend"],
                    "tau": mk_r["tau"],
                    "z": mk_r["z"],
                    "p": mk_r["p"],
                    "slope": None if sen_r is None else sen_r["slope"],
                    "slope_ci": None if sen_r is None else [sen_r["ci_low"], sen_r["ci_high"]],
                }
            },
        },
        quality_block=_quality(n, MIN_SERIES, SOURCE_SERIES, "series_time"),
        trace_id=trace_id,
    )


# ---------------- D-J03 异常点识别 ----------------


def outlier_scan(
    series: Any = None,
    *,
    k: float = 3.0,
    capability_id: str = "D-J03",
    intent: str = INTENT_OUTLIER,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    xs = _series_of(series)
    if len(xs) < MIN_SERIES:
        return _empty(
            capability_id, intent, f"序列样本不足 {MIN_SERIES} 点", trace_id, params={"k": k}
        )
    blk = _call("SC92", {"x": xs}, k=k)
    if blk["gate"] != "ok":
        return _empty(capability_id, intent, "异常点识别计算失败", trace_id, params={"k": k})
    r = blk["result"]
    n = int(r["n"])
    answer = (
        f"异常点 {r['n_outliers']} 个（σ={_fmt(r['sigma'], 6)}，阈值 {_fmt(r['threshold'], 6)}，k={_fmt(k, 2)}）。"
        f"样本为 {n} 个时点，异常点为统计偏离标记，不构成买卖信号。"
    )
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"k": k},
            "capabilities": {
                capability_id: {
                    "methods": ["SC92"],
                    "n": n,
                    "outliers": r["outliers"],
                    "n_outliers": r["n_outliers"],
                    "sigma": r["sigma"],
                    "threshold": r["threshold"],
                }
            },
        },
        quality_block=_quality(n, MIN_SERIES, SOURCE_SERIES, "series_time"),
        trace_id=trace_id,
    )


# ---------------- D-J06 平滑滤波 ----------------


def smoothing_filter(
    series: Any = None,
    *,
    window: int = 11,
    polyorder: int = 3,
    levels: int = 4,
    capability_id: str = "D-J06",
    intent: str = INTENT_SIGNAL,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    xs = _series_of(series)
    if len(xs) < MIN_SERIES:
        return _empty(capability_id, intent, f"序列样本不足 {MIN_SERIES} 点", trace_id)
    savgol = _call("SC44", {"x": xs}, window=window, polyorder=polyorder)
    dwt = _call("SC42", {"x": xs}, levels=levels)
    butter = _call("SC45", {"x": xs})
    ok = _ok({"SC44": savgol, "SC42": dwt, "SC45": butter})
    if "SC44" not in ok:
        return _empty(capability_id, intent, "平滑滤波计算失败", trace_id)
    sg = savgol["result"]
    n = int(sg["n"])
    bits = [f"Savitzky-Golay 平滑（window={sg['window']}，polyorder={sg['polyorder']}）"]
    if "SC42" in ok:
        energy = dwt["result"]["energy"]
        total = sum(v for v in energy if _is_num(v)) if isinstance(energy, list) else energy
        bits.append(f"小波能量合计 {_fmt(total, 4)}")
    if "SC45" in ok:
        bits.append(
            f"Butterworth {butter['result']['order']} 阶低通（截止 {_fmt(butter['result']['cutoff'], 3)}）"
        )
    answer = "；".join(bits) + f"。样本为 {n} 个时点，滤波只改变噪声呈现，不改变历史事实。"
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"window": window, "polyorder": polyorder, "levels": levels},
            "capabilities": {
                capability_id: {
                    "methods": sorted(ok),
                    "n": n,
                    "smoothed": sg["smoothed"],
                    "wavelet_energy": None if "SC42" not in ok else dwt["result"]["energy"],
                    "filtered": None if "SC45" not in ok else butter["result"]["filtered"],
                }
            },
        },
        quality_block=_quality(n, MIN_SERIES, SOURCE_SERIES, "series_time"),
        trace_id=trace_id,
    )


# ---------------- D-J07 Hilbert 包络 / 瞬时相位 ----------------


def spectral_envelope(
    series: Any = None,
    *,
    levels: int = 4,
    capability_id: str = "D-J07",
    intent: str = INTENT_SIGNAL,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    xs = _series_of(series)
    if len(xs) < MIN_SERIES:
        return _empty(capability_id, intent, f"序列样本不足 {MIN_SERIES} 点", trace_id)
    hilbert = _call("SC46", {"x": xs})
    dwt = _call("SC42", {"x": xs}, levels=levels)
    ok = _ok({"SC46": hilbert, "SC42": dwt})
    if "SC46" not in ok:
        return _empty(capability_id, intent, "Hilbert 包络计算失败", trace_id)
    r = hilbert["result"]
    n = int(r["n"])
    env = [v for v in r["envelope"] if _is_num(v)]
    answer = (
        f"Hilbert 包络（n={n}）：末端包络 {_fmt(env[-1] if env else None, 6)}，"
        f"瞬时相位末端 {_fmt(r['phase'][-1] if r['phase'] else None, 4)}。"
        f"样本为 {n} 个时点，包络/相位仅描述周期结构，不含方向判断。"
    )
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"levels": levels},
            "capabilities": {
                capability_id: {
                    "methods": sorted(ok),
                    "n": n,
                    "envelope": r["envelope"],
                    "phase": r["phase"],
                    "wavelet_energy": None if "SC42" not in ok else dwt["result"]["energy"],
                }
            },
        },
        quality_block=_quality(n, MIN_SERIES, SOURCE_SERIES, "series_time"),
        trace_id=trace_id,
    )


# ---------------- D-J08 Kalman 状态空间 ----------------


def state_space_filter(
    series: Any = None,
    *,
    process_var: float = 0.01,
    obs_var: float = 1.0,
    capability_id: str = "D-J08",
    intent: str = INTENT_SIGNAL,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    xs = _series_of(series)
    if len(xs) < MIN_SERIES:
        return _empty(capability_id, intent, f"序列样本不足 {MIN_SERIES} 点", trace_id)
    blk = _call("SC47", {"x": xs}, process_var=process_var, obs_var=obs_var)
    if blk["gate"] != "ok":
        return _empty(capability_id, intent, "Kalman 滤波计算失败", trace_id)
    r = blk["result"]
    n = int(r["n"])
    answer = (
        f"Kalman 局部水平（Q={_fmt(process_var, 3)}，R={_fmt(obs_var, 3)}）："
        f"末态 {_fmt(r['last_state'], 6)}，对数似然 {_fmt(r['loglik'], 2)}。"
        f"样本为 {n} 个时点，状态估计只做去噪，不含预测方向。"
    )
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"process_var": process_var, "obs_var": obs_var},
            "capabilities": {
                capability_id: {
                    "methods": ["SC47"],
                    "n": n,
                    "state": r["state"],
                    "last_state": r["last_state"],
                    "gain": r["gain"],
                    "loglik": r["loglik"],
                }
            },
        },
        quality_block=_quality(n, MIN_SERIES, SOURCE_SERIES, "series_time"),
        trace_id=trace_id,
    )


# ---------------- D-J09 相干分析 ----------------


def coherence_analysis(
    x: Any = None,
    *,
    y: Any = None,
    nperseg: int = 0,
    capability_id: str = "D-J09",
    intent: str = INTENT_SIGNAL,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    a = _series_of(x)
    b = _series_of(y)
    if len(a) < MIN_PAIRS or len(b) < MIN_PAIRS:
        return _empty(capability_id, intent, f"双序列样本不足 {MIN_PAIRS} 点", trace_id)
    m = min(len(a), len(b))
    coh = _call("SC48", {"x": a[:m], "y": b[:m]}, nperseg=nperseg)
    wav = _call("SC43", {"x": a[:m], "y": b[:m]})
    ok = _ok({"SC48": coh, "SC43": wav})
    if "SC48" not in ok:
        return _empty(capability_id, intent, "互谱相干计算失败", trace_id)
    r = coh["result"]
    n = int(r["n"])
    answer = (
        f"互谱相干（n={n}）：峰值相干 {_fmt(r['peak_coherence'])} @ {_fmt(r['peak_freq'], 4)}。"
        f"样本为 {n} 对时点，相干只描述频域同步程度，不含因果方向，不代表未来。"
    )
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"nperseg": nperseg},
            "capabilities": {
                capability_id: {
                    "methods": sorted(ok),
                    "n": n,
                    "freqs": r["freqs"],
                    "coherence": r["coherence"],
                    "peak_coherence": r["peak_coherence"],
                    "peak_freq": r["peak_freq"],
                    "wavelet_mean": None if "SC43" not in ok else wav["result"]["mean_coherence"],
                }
            },
        },
        quality_block=_quality(n, MIN_PAIRS, SOURCE_SERIES, "dual_series_aligned"),
        trace_id=trace_id,
    )


# ---------------- D-J10 熵 / 互信息 / KL ----------------


def information_measures(
    series: Any = None,
    *,
    other: Any = None,
    bins: int = 10,
    capability_id: str = "D-J10",
    intent: str = INTENT_INFORMATION,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    xs = _series_of(series)
    if len(xs) < MIN_SERIES:
        return _empty(
            capability_id, intent, f"序列样本不足 {MIN_SERIES} 点", trace_id, params={"bins": bins}
        )
    ent = _call("SC55", {"x": xs}, bins=bins)
    blocks: Dict[str, Dict[str, Any]] = {"SC55": ent}
    n = len(xs)
    if other is not None:
        ys = _series_of(other)
        m = min(len(xs), len(ys))
        if m >= MIN_PAIRS:
            blocks["SC56"] = _call("SC56", {"x": xs[:m], "y": ys[:m]}, bins=bins)
            blocks["SC58"] = _call("SC58", {"x": xs[:m], "y": ys[:m]}, bins=bins)
            n = m
    ok = _ok(blocks)
    if "SC55" not in ok:
        return _empty(capability_id, intent, "香农熵计算失败", trace_id)
    h = ent["result"]
    bits = [f"香农熵 {_fmt(h['h'])}（归一化 {_fmt(h['h_norm'])}，bins={h['bins']}）"]
    if "SC56" in ok:
        bits.append(
            f"互信息 {_fmt(ok['SC56']['result']['mi'], 6)}（归一化 {_fmt(ok['SC56']['result']['mi_norm'])}）"
        )
    if "SC58" in ok:
        kl = ok["SC58"]["result"]
        bits.append(f"KL 散度 {_fmt(kl['kl'], 6)}，JS 距离 {_fmt(kl['js'], 6)}")
    answer = "；".join(bits) + f"。样本为 {n} 个时点，信息量指标只刻画分布差异，不含方向。"
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"bins": bins, "paired": other is not None},
            "capabilities": {
                capability_id: {
                    "methods": sorted(ok),
                    "n": n,
                    "entropy": h["h"],
                    "entropy_norm": h["h_norm"],
                    "mutual_info": None if "SC56" not in ok else ok["SC56"]["result"]["mi"],
                    "kl": None if "SC58" not in ok else ok["SC58"]["result"]["kl"],
                    "js": None if "SC58" not in ok else ok["SC58"]["result"]["js"],
                }
            },
        },
        quality_block=_quality(
            n,
            MIN_SERIES,
            SOURCE_SERIES,
            "dual_series_aligned" if other is not None else "series_time",
        ),
        trace_id=trace_id,
    )


# ---------------- D-J11 传递熵 ----------------


def transfer_entropy(
    x: Any = None,
    *,
    y: Any = None,
    bins: int = 8,
    lag: int = 1,
    capability_id: str = "D-J11",
    intent: str = INTENT_INFORMATION,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    a = _series_of(x)
    b = _series_of(y)
    if len(a) < MIN_PAIRS or len(b) < MIN_PAIRS:
        return _empty(capability_id, intent, f"双序列样本不足 {MIN_PAIRS} 点", trace_id)
    m = min(len(a), len(b))
    blk = _call("SC57", {"x": a[:m], "y": b[:m]}, bins=bins, lag=lag)
    if blk["gate"] != "ok":
        return _empty(capability_id, intent, "传递熵计算失败", trace_id)
    r = blk["result"]
    n = int(r["n"])
    answer = (
        f"传递熵（n={n}，lag={r['lag']}）：x→y {_fmt(r['te'], 6)}，y→x {_fmt(r['te_reverse'], 6)}，净 {_fmt(r['net'], 6)}。"
        f"样本为 {n} 对时点，净传递熵只表示历史信息流强弱，不构成因果或买卖结论。"
    )
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"bins": bins, "lag": lag},
            "capabilities": {
                capability_id: {
                    "methods": ["SC57"],
                    "n": n,
                    "te": r["te"],
                    "te_reverse": r["te_reverse"],
                    "net": r["net"],
                }
            },
        },
        quality_block=_quality(n, MIN_PAIRS, SOURCE_SERIES, "dual_series_aligned"),
        trace_id=trace_id,
    )


# ---------------- D-J12 复杂度 ----------------


def complexity_measures(
    series: Any = None,
    *,
    m: int = 2,
    tau: int = 1,
    capability_id: str = "D-J12",
    intent: str = INTENT_COMPLEXITY,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    xs = _series_of(series)
    if len(xs) < MIN_SERIES:
        return _empty(capability_id, intent, f"序列样本不足 {MIN_SERIES} 点", trace_id)
    lz = _call("SC59", {"x": xs})
    se = _call("SC60", {"x": xs}, m=m)
    pe = _call("SC61", {"x": xs}, m=max(2, int(m) + 1), tau=tau)
    ok = _ok({"SC59": lz, "SC60": se, "SC61": pe})
    if not ok:
        return _empty(capability_id, intent, "复杂度指标全部计算失败", trace_id)
    n = len(xs)
    bits = []
    if "SC59" in ok:
        r = ok["SC59"]["result"]
        bits.append(f"Lempel-Ziv 归一化复杂度 {_fmt(r['c'])}（原始段数 {r['c_raw']}）")
    if "SC60" in ok:
        bits.append(f"样本熵 {_fmt(ok['SC60']['result']['sampen'], 4)}")
    if "SC61" in ok:
        bits.append(f"排列熵 {_fmt(ok['SC61']['result']['pe_norm'], 4)}（归一化）")
    answer = "；".join(bits) + f"。样本为 {n} 个时点，复杂度只刻画序列不规则程度，不代表可预测性。"
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"m": m, "tau": tau},
            "capabilities": {
                capability_id: {
                    "methods": sorted(ok),
                    "n": n,
                    "lempel_ziv": None if "SC59" not in ok else ok["SC59"]["result"]["c"],
                    "sample_entropy": None if "SC60" not in ok else ok["SC60"]["result"]["sampen"],
                    "permutation_entropy": (
                        None if "SC61" not in ok else ok["SC61"]["result"]["pe_norm"]
                    ),
                }
            },
        },
        quality_block=_quality(n, MIN_SERIES, SOURCE_SERIES, "series_time"),
        trace_id=trace_id,
    )


# ---------------- D-J13 长记忆 DFA / Hurst ----------------


def long_memory(
    series: Any = None,
    *,
    n_scales: int = 10,
    capability_id: str = "D-J13",
    intent: str = INTENT_COMPLEXITY,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    xs = _series_of(series)
    if len(xs) < MIN_SERIES:
        return _empty(capability_id, intent, f"序列样本不足 {MIN_SERIES} 点", trace_id)
    blk = _call("SC62", {"x": xs}, n_scales=n_scales)
    if blk["gate"] != "ok":
        return _empty(capability_id, intent, "DFA/Hurst 计算失败", trace_id)
    r = blk["result"]
    n = int(r["n"])
    answer = (
        f"DFA α={_fmt(r['alpha'])}，Hurst={_fmt(r['h'])}（{r['scales']} 个尺度）。"
        f"样本为 {n} 个时点，H>0.5 表示历史存在长记忆，但不保证未来持续。"
    )
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"n_scales": n_scales},
            "capabilities": {
                capability_id: {
                    "methods": ["SC62"],
                    "n": n,
                    "alpha": r["alpha"],
                    "hurst": r["h"],
                    "scales": r["scales"],
                }
            },
        },
        quality_block=_quality(n, MIN_SERIES, SOURCE_SERIES, "series_time"),
        trace_id=trace_id,
    )


# ---------------- D-J14 极值风险 ----------------


def tail_risk_extreme(
    series: Any = None,
    *,
    block_size: int = 0,
    q: float = 0.95,
    return_period: float = 10.0,
    capability_id: str = "D-J14",
    intent: str = INTENT_EXTREME,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    xs = _series_of(series)
    if len(xs) < MIN_SERIES:
        return _empty(capability_id, intent, f"序列样本不足 {MIN_SERIES} 点", trace_id)
    gev = _call("SC63", {"x": xs}, block_size=block_size)
    gpd = _call("SC64", {"x": xs}, q=q)
    lvl = _call("SC65", {"x": xs}, return_period=return_period)
    ok = _ok({"SC63": gev, "SC64": gpd, "SC65": lvl})
    if not ok:
        return _empty(capability_id, intent, "极值分布全部计算失败", trace_id)
    n = len(xs)
    bits = []
    if "SC63" in ok:
        r = ok["SC63"]["result"]
        bits.append(f"GEV μ={_fmt(r['mu'])}，σ={_fmt(r['sigma'])}，ξ={_fmt(r['xi'])}")
    if "SC64" in ok:
        r = ok["SC64"]["result"]
        bits.append(f"GPD ξ={_fmt(r['xi'])}，β={_fmt(r['beta'])}（超阈值 {r['n_exceed']} 个）")
    if "SC65" in ok:
        r = ok["SC65"]["result"]
        bits.append(f"{_fmt(r['return_period'], 1)} 期重现水平 {_fmt(r['level'], 6)}")
    answer = (
        "；".join(bits) + f"。样本为 {n} 个时点，极值参数基于历史尾部分布，不代表未来最大损失。"
    )
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"block_size": block_size, "q": q, "return_period": return_period},
            "capabilities": {
                capability_id: {
                    "methods": sorted(ok),
                    "n": n,
                    "gev": None if "SC63" not in ok else ok["SC63"]["result"],
                    "gpd": None if "SC64" not in ok else ok["SC64"]["result"],
                    "return_level": None if "SC65" not in ok else ok["SC65"]["result"],
                }
            },
        },
        quality_block=_quality(n, MIN_SERIES, SOURCE_SERIES, "series_time"),
        trace_id=trace_id,
    )


# ---------------- D-J15 测量不确定度 ----------------


def measurement_uncertainty(
    series: Any = None,
    *,
    components: Any = None,
    k: float = 2.0,
    coverage: float = 0.95,
    confidence: float = 0.95,
    capability_id: str = "D-J15",
    intent: str = INTENT_UNCERTAINTY,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    xs = _series_of(series)
    if len(xs) < MIN_SERIES:
        return _empty(capability_id, intent, f"序列样本不足 {MIN_SERIES} 点", trace_id)
    payload: Any = {"x": xs}
    if components is not None:
        comp = _floats(components)
        payload = {"u": comp, "c": [1.0] * len(comp)} if comp else {"x": xs}
    gum = (
        _call("SC09", payload, k=k)
        if components is not None
        else {"gate": "skipped", "result": None, "method": "SC09"}
    )
    tol = _call("SC11", {"x": xs}, coverage=coverage, confidence=confidence)
    ok = _ok({"SC09": gum, "SC11": tol})
    if not ok:
        return _empty(capability_id, intent, "不确定度计算失败", trace_id)
    n = len(xs)
    bits = []
    if "SC09" in ok:
        r = ok["SC09"]["result"]
        bits.append(
            f"合成标准不确定度 u_c={_fmt(r['u_c'], 6)}，扩展不确定度 U={_fmt(r['U'], 6)}（k={_fmt(r['k'], 2)}）"
        )
    else:
        bits.append("未提供分量不确定度输入，仅给出容忍区间（u_c/U 不计算）")
    if "SC11" in ok:
        r = ok["SC11"]["result"]
        bits.append(
            f"{_fmt(r['coverage'], 2)} 覆盖容忍区间 [{_fmt(r['ti_low'], 6)}, {_fmt(r['ti_high'], 6)}]"
        )
    answer = "；".join(bits) + f"。样本为 {n} 个时点，不确定度只量化估计精度，不改变点估计。"
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"k": k, "coverage": coverage, "confidence": confidence},
            "capabilities": {
                capability_id: {
                    "methods": sorted(ok),
                    "n": n,
                    "u_c": None if "SC09" not in ok else ok["SC09"]["result"]["u_c"],
                    "U": None if "SC09" not in ok else ok["SC09"]["result"]["U"],
                    "interval": (
                        None
                        if "SC11" not in ok
                        else [ok["SC11"]["result"]["ti_low"], ok["SC11"]["result"]["ti_high"]]
                    ),
                }
            },
        },
        quality_block=_quality(n, MIN_SERIES, SOURCE_SERIES, "series_time"),
        trace_id=trace_id,
    )


# ---------------- D-J16 区间估计 ----------------


def interval_estimate(
    x: Any = None,
    *,
    y: Any = None,
    alpha: float = 0.05,
    x0: Optional[float] = None,
    coverage: float = 0.95,
    confidence: float = 0.95,
    capability_id: str = "D-J16",
    intent: str = INTENT_UNCERTAINTY,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    xs = _series_of(x)
    blocks: Dict[str, Dict[str, Any]] = {}
    n = len(xs)
    if y is not None:
        ys = _series_of(y)
        m = min(len(xs), len(ys))
        if m < MIN_PAIRS:
            return _empty(capability_id, intent, f"双序列样本不足 {MIN_PAIRS} 点", trace_id)
        pair = {"x": xs[:m], "y": ys[:m]}
        blocks["SC10"] = _call("SC10", pair, alpha=alpha, x0=x0)
        blocks["SC12"] = _call("SC12", pair, alpha=alpha, x0=x0)
        n = m
    else:
        if n < MIN_SERIES:
            return _empty(capability_id, intent, f"序列样本不足 {MIN_SERIES} 点", trace_id)
        blocks["SC11"] = _call("SC11", {"x": xs}, coverage=coverage, confidence=confidence)
    ok = _ok(blocks)
    if not ok:
        return _empty(capability_id, intent, "区间估计计算失败", trace_id)
    bits = []
    if "SC10" in ok:
        r = ok["SC10"]["result"]
        bits.append(
            f"预测区间 ŷ={_fmt(r['yhat'], 6)}，[{_fmt(r['pi_low'], 6)}, {_fmt(r['pi_high'], 6)}]"
        )
    if "SC12" in ok:
        r = ok["SC12"]["result"]
        bits.append(f"分割共形区间 [{_fmt(r['ci_low'], 6)}, {_fmt(r['ci_high'], 6)}]")
    if "SC11" in ok:
        r = ok["SC11"]["result"]
        bits.append(
            f"容忍区间 [{_fmt(r['ti_low'], 6)}, {_fmt(r['ti_high'], 6)}]（coverage={_fmt(r['coverage'], 2)}）"
        )
    answer = "；".join(bits) + f"。样本为 {n} 个观测，区间宽度反映历史波动，不保证未来覆盖。"
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"alpha": alpha, "x0": x0, "coverage": coverage, "confidence": confidence},
            "capabilities": {
                capability_id: {
                    "methods": sorted(ok),
                    "n": n,
                    "prediction": None if "SC10" not in ok else ok["SC10"]["result"],
                    "conformal": None if "SC12" not in ok else ok["SC12"]["result"],
                    "tolerance": None if "SC11" not in ok else ok["SC11"]["result"],
                }
            },
        },
        quality_block=_quality(
            n, MIN_SERIES, SOURCE_SERIES, "series_time" if y is None else "dual_series_aligned"
        ),
        trace_id=trace_id,
    )


# ---------------- D-J17 功效与样本量 ----------------


def power_sample_size(
    series: Any = None,
    *,
    effect_size: Optional[float] = None,
    alpha: float = 0.05,
    power_target: float = 0.8,
    capability_id: str = "D-J17",
    intent: str = INTENT_DESIGN,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    xs = _series_of(series)
    if len(xs) < MIN_SERIES:
        return _empty(capability_id, intent, f"序列样本不足 {MIN_SERIES} 点", trace_id)
    payload = {"x": xs}
    power = _call("SC01", payload, effect_size=effect_size, alpha=alpha)
    nmin = _call("SC02", payload, effect_size=effect_size, alpha=alpha, power_target=power_target)
    ok = _ok({"SC01": power, "SC02": nmin})
    if not ok:
        return _empty(capability_id, intent, "功效/样本量计算失败", trace_id)
    n = len(xs)
    bits = []
    if "SC01" in ok:
        bits.append(
            f"当前样本统计功效 {_fmt(ok['SC01']['result']['power'])}（效应量 d={_fmt(ok['SC01']['result']['effect_size'])}）"
        )
    if "SC02" in ok:
        r = ok["SC02"]["result"]
        bits.append(
            f"达到 power={_fmt(r['power_target'], 2)} 所需样本量 {r['n_star'] if r['n_star'] is not None else 'n/a'}"
        )
    answer = "；".join(bits) + f"。样本为 {n} 个观测，功效分析用于实验设计，不构成策略有效性结论。"
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"effect_size": effect_size, "alpha": alpha, "power_target": power_target},
            "capabilities": {
                capability_id: {
                    "methods": sorted(ok),
                    "n": n,
                    "power": None if "SC01" not in ok else ok["SC01"]["result"]["power"],
                    "n_star": None if "SC02" not in ok else ok["SC02"]["result"]["n_star"],
                    "effect_size": (
                        None if "SC01" not in ok else ok["SC01"]["result"]["effect_size"]
                    ),
                }
            },
        },
        quality_block=_quality(n, MIN_SERIES, SOURCE_SERIES, "series_time"),
        trace_id=trace_id,
    )


# ---------------- D-J18 等效性检验 TOST ----------------


def equivalence_test(
    x: Any = None,
    *,
    y: Any = None,
    bound: Optional[float] = None,
    alpha: float = 0.05,
    capability_id: str = "D-J18",
    intent: str = INTENT_DESIGN,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    xs = _series_of(x)
    payload: Any = {"x": xs}
    n = len(xs)
    if y is not None:
        ys = _series_of(y)
        m = min(len(xs), len(ys))
        if m < MIN_PAIRS:
            return _empty(capability_id, intent, f"双序列样本不足 {MIN_PAIRS} 点", trace_id)
        payload = {"x": xs[:m], "y": ys[:m]}
        n = m
    elif n < MIN_PAIRS:
        return _empty(capability_id, intent, f"序列样本不足 {MIN_PAIRS} 点", trace_id)
    blk = _call("SC03", payload, bound=bound, alpha=alpha)
    if blk["gate"] != "ok":
        return _empty(capability_id, intent, "TOST 等效性检验计算失败", trace_id)
    r = blk["result"]
    verdict = "等效" if r["equivalent"] else "未达等效"
    answer = (
        f"TOST（n={r['n']}，边界 ±{_fmt(r['bound'], 6)}）：p={_fmt(r['p'])}，判定「{verdict}」。"
        f"样本为 {r['n']} 个观测，等效性检验只说明差异是否在预设边界内，不含收益结论。"
    )
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"bound": bound, "alpha": alpha},
            "capabilities": {
                capability_id: {
                    "methods": ["SC03"],
                    "n": int(r["n"]),
                    "p": r["p"],
                    "bound": r["bound"],
                    "equivalent": r["equivalent"],
                }
            },
        },
        quality_block=_quality(
            int(r["n"]),
            MIN_PAIRS,
            SOURCE_SERIES,
            "dual_series_aligned" if y is not None else "series_time",
        ),
        trace_id=trace_id,
    )


# ---------------- D-J19 分组比较 ----------------


def group_comparison(
    values: Any = None,
    *,
    groups: Any = None,
    alpha: float = 0.05,
    capability_id: str = "D-J19",
    intent: str = INTENT_GROUP,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    if groups is None:
        if isinstance(values, Mapping) and "groups" in values:
            raw_groups = [_floats(g) for g in values["groups"]]
        elif isinstance(values, Sequence) and values and isinstance(values[0], Sequence):
            raw_groups = [_floats(g) for g in values]
        else:
            xs = _floats(values or [])
            half = len(xs) // 2
            raw_groups = [xs[:half], xs[half:]]
    else:
        raw_groups = [_floats(g) for g in groups]
    # 方法层门禁按「最短序列长度」取值，故展开为扁平多键形式（g1/g2/...），而非外层 groups 列表
    payload: Dict[str, Any] = {f"g{i + 1}": g for i, g in enumerate(raw_groups)}
    total = sum(len(g) for g in raw_groups)
    if total < MIN_PANEL or len(raw_groups) < 2:
        return _empty(
            capability_id, intent, f"分组样本不足 {MIN_PANEL} 或组数 <2", trace_id, SOURCE_PANEL
        )
    anova = _call("SC25", payload)
    tukey = _call("SC30", payload, alpha=alpha)
    ok = _ok({"SC25": anova, "SC30": tukey})
    if "SC25" not in ok:
        return _empty(capability_id, intent, "ANOVA 计算失败", trace_id, SOURCE_PANEL)
    r = anova["result"]
    n = int(r["n"])
    bits = [
        f"单因素 ANOVA F={_fmt(r['f'], 3)}，p={_fmt(r['p'])}，η²={_fmt(r['eta2'])}（k={r['k']} 组）"
    ]
    if "SC30" in ok:
        t = ok["SC30"]["result"]
        reject_n = sum(1 for v in t["reject"] if v)
        bits.append(f"Tukey HSD {len(t['pairs'])} 对中 {reject_n} 对显著")
    answer = "；".join(bits) + f"。样本为 {n} 个观测，分组差异只描述历史分布，不代表未来收益差异。"
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"alpha": alpha, "k_groups": len(raw_groups)},
            "capabilities": {
                capability_id: {
                    "methods": sorted(ok),
                    "n": n,
                    "f": r["f"],
                    "p": r["p"],
                    "eta2": r["eta2"],
                    "tukey": None if "SC30" not in ok else ok["SC30"]["result"],
                }
            },
        },
        quality_block=_quality(n, MIN_PANEL, SOURCE_PANEL, "grouped_observations"),
        trace_id=trace_id,
    )


# ---------------- D-J20 回归诊断 ----------------


def regression_diagnostics(
    X: Any = None,
    *,
    y: Any = None,
    capability_id: str = "D-J20",
    intent: str = INTENT_DIAGNOSTIC,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    names, rows = _frame_of(X)
    targets = _floats(y if y is not None else [])
    m = min(len(rows), len(targets)) if targets else len(rows)
    if m < MIN_PANEL or not rows:
        return _empty(
            capability_id,
            intent,
            f"回归样本不足 {MIN_PANEL} 行或缺少目标列",
            trace_id,
            SOURCE_PANEL,
        )
    payload = {"X": rows[:m], "y": targets[:m]} if targets else {"X": rows[:m]}
    blocks = {
        "SC20": _call("SC20", payload),
        "SC21": (
            _call("SC21", payload)
            if targets
            else {"gate": "skipped", "result": None, "method": "SC21"}
        ),
        "SC22": (
            _call("SC22", payload)
            if targets
            else {"gate": "skipped", "result": None, "method": "SC22"}
        ),
        "SC23": (
            _call("SC23", payload)
            if targets
            else {"gate": "skipped", "result": None, "method": "SC23"}
        ),
        "SC24": (
            _call("SC24", payload)
            if targets
            else {"gate": "skipped", "result": None, "method": "SC24"}
        ),
    }
    ok = _ok(blocks)
    if "SC20" not in ok:
        return _empty(capability_id, intent, "VIF 计算失败", trace_id, SOURCE_PANEL)
    n = int(ok["SC20"]["result"]["n"])
    bits = [f"最大 VIF {_fmt(ok['SC20']['result']['max_vif'], 3)}（列数 {len(names)}）"]
    if "SC21" in ok:
        bits.append(f"Breusch-Pagan p={_fmt(ok['SC21']['result']['p'])}")
    if "SC23" in ok:
        bits.append(f"DW={_fmt(ok['SC23']['result']['dw'], 3)}")
    if "SC24" in ok:
        bits.append(f"影响点 {ok['SC24']['result']['n_outliers']} 个")
    answer = "；".join(bits) + f"。样本为 {n} 行，诊断只评估模型设定，不评价预测能力。"
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"columns": names},
            "capabilities": {
                capability_id: {
                    "methods": sorted(ok),
                    "n": n,
                    "vif": ok["SC20"]["result"]["vif"],
                    "max_vif": ok["SC20"]["result"]["max_vif"],
                    "bp_p": None if "SC21" not in ok else ok["SC21"]["result"]["p"],
                    "dw": None if "SC23" not in ok else ok["SC23"]["result"]["dw"],
                    "n_influence": None if "SC24" not in ok else ok["SC24"]["result"]["n_outliers"],
                }
            },
        },
        quality_block=_quality(n, MIN_PANEL, SOURCE_PANEL, "panel_rows"),
        trace_id=trace_id,
    )


# ---------------- D-J21 稳健与分位回归 ----------------


def robust_regression(
    X: Any = None,
    *,
    y: Any = None,
    taus: Sequence[float] = (0.1, 0.5, 0.9),
    capability_id: str = "D-J21",
    intent: str = INTENT_DIAGNOSTIC,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    names, rows = _frame_of(X)
    targets = _floats(y if y is not None else [])
    m = min(len(rows), len(targets))
    if m < MIN_PANEL:
        return _empty(
            capability_id,
            intent,
            f"回归样本不足 {MIN_PANEL} 行或缺少目标列",
            trace_id,
            SOURCE_PANEL,
        )
    payload = {"X": rows[:m], "y": targets[:m]}
    qr = _call("SC17", payload, taus=tuple(taus))
    huber = _call("SC18", payload)
    ok = _ok({"SC17": qr, "SC18": huber})
    if not ok:
        return _empty(capability_id, intent, "稳健回归全部计算失败", trace_id, SOURCE_PANEL)
    n = int((ok.get("SC17") or ok.get("SC18"))["result"]["n"])
    bits = []
    if "SC17" in ok:
        taus_used = ok["SC17"]["result"]["taus"]
        bits.append(f"分位数回归 τ={taus_used}")
    if "SC18" in ok:
        r = ok["SC18"]["result"]
        bits.append(f"Huber 稳健回归截距 {_fmt(r['intercept'], 6)}，尺度 {_fmt(r['scale'], 6)}")
    answer = "；".join(bits) + f"。样本为 {n} 行，稳健回归只降低异常点影响，不保证外推有效。"
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"columns": names, "taus": list(taus)},
            "capabilities": {
                capability_id: {
                    "methods": sorted(ok),
                    "n": n,
                    "quantile": None if "SC17" not in ok else ok["SC17"]["result"],
                    "huber": None if "SC18" not in ok else ok["SC18"]["result"],
                }
            },
        },
        quality_block=_quality(n, MIN_PANEL, SOURCE_PANEL, "panel_rows"),
        trace_id=trace_id,
    )


# ---------------- D-J23 聚类结构 ----------------


def cluster_structure(
    X: Any = None,
    *,
    k: int = 3,
    capability_id: str = "D-J23",
    intent: str = INTENT_CLUSTER,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    names, rows = _frame_of(X)
    if len(rows) < MIN_PANEL or not rows or len(rows[0]) < 2:
        return _empty(
            capability_id, intent, f"聚类样本不足 {MIN_PANEL} 行或列数 <2", trace_id, SOURCE_PANEL
        )
    payload = {"X": rows}
    kk = max(2, min(int(k), len(rows) - 1))
    hier = _call("SC36", payload)
    km = _call("SC37", payload, k=kk)
    sil = _call("SC38", payload, k=kk)
    ok = _ok({"SC36": hier, "SC37": km, "SC38": sil})
    if "SC37" not in ok:
        return _empty(capability_id, intent, "K-Means 聚类计算失败", trace_id, SOURCE_PANEL)
    n = int(km["result"]["n"])
    bits = [f"K-Means（k={km['result']['k']}）惯性 {_fmt(km['result']['inertia'], 4)}"]
    if "SC38" in ok:
        bits.append(f"轮廓系数 {_fmt(ok['SC38']['result']['silhouette'])}")
    if "SC36" in ok:
        bits.append(f"层次聚类 linkage={ok['SC36']['result']['linkage']}")
    answer = (
        "；".join(bits) + f"。样本为 {n} 行，聚类只刻画历史相似性结构，不含标签含义或交易建议。"
    )
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"k": kk, "columns": names},
            "capabilities": {
                capability_id: {
                    "methods": sorted(ok),
                    "n": n,
                    "labels": km["result"]["labels"],
                    "inertia": km["result"]["inertia"],
                    "silhouette": None if "SC38" not in ok else ok["SC38"]["result"]["silhouette"],
                    "hierarchical_p": None if "SC36" not in ok else ok["SC36"]["result"]["p"],
                }
            },
        },
        quality_block=_quality(n, MIN_PANEL, SOURCE_PANEL, "panel_rows"),
        trace_id=trace_id,
    )


# ---------------- D-J25 空间自相关 ----------------


def spatial_autocorrelation(
    coords: Any = None,
    *,
    values: Any = None,
    k: int = 4,
    n_bins: int = 8,
    capability_id: str = "D-J25",
    intent: str = INTENT_SPATIAL,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    if coords is None or values is None:
        return _empty(
            capability_id, intent, "空间输入需要 coords 与 values", trace_id, SOURCE_SPATIAL
        )
    payload = {"coords": coords, "values": _floats(values)}
    n = min(len(payload["values"]), len(coords))
    if n < MIN_SPATIAL:
        return _empty(
            capability_id, intent, f"空间样本不足 {MIN_SPATIAL} 点", trace_id, SOURCE_SPATIAL
        )
    moran = _call("SC67", payload, k=k)
    geary = _call("SC68", payload, k=k)
    semi = _call("SC69", payload, n_bins=n_bins)
    ok = _ok({"SC67": moran, "SC68": geary, "SC69": semi})
    if "SC67" not in ok:
        return _empty(capability_id, intent, "Moran's I 计算失败", trace_id, SOURCE_SPATIAL)
    r = moran["result"]
    bits = [f"Moran's I={_fmt(r['i'])}（z={_fmt(r['z'], 3)}，p={_fmt(r['p'])}）"]
    if "SC68" in ok:
        bits.append(f"Geary's C={_fmt(ok['SC68']['result']['c'])}")
    if "SC69" in ok:
        bits.append(f"半变异函数 {len(ok['SC69']['result']['lags'])} 个滞后分箱")
    answer = (
        "；".join(bits) + f"。样本为 {int(r['n'])} 个空间点，自相关只描述横截面聚集，不含因果。"
    )
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"k": k, "n_bins": n_bins},
            "capabilities": {
                capability_id: {
                    "methods": sorted(ok),
                    "n": int(r["n"]),
                    "moran_i": r["i"],
                    "moran_p": r["p"],
                    "geary_c": None if "SC68" not in ok else ok["SC68"]["result"]["c"],
                    "semivariogram": None if "SC69" not in ok else ok["SC69"]["result"],
                }
            },
        },
        quality_block=_quality(int(r["n"]), MIN_SPATIAL, SOURCE_SPATIAL, "spatial_coords"),
        trace_id=trace_id,
    )


# ---------------- D-J26 生存分析 ----------------


def survival_analysis(
    time: Any = None,
    *,
    event: Any = None,
    group: Any = None,
    covariate: Any = None,
    capability_id: str = "D-J26",
    intent: str = INTENT_SURVIVAL,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    durations = _floats(time)
    if len(durations) < MIN_SURVIVAL:
        return _empty(
            capability_id, intent, f"生存样本不足 {MIN_SURVIVAL} 条", trace_id, SOURCE_PANEL
        )
    payload: Dict[str, Any] = {"time": durations}
    if event is not None:
        payload["event"] = _floats(event)
    if group is not None:
        payload["group"] = list(group)
    if covariate is not None:
        payload["x"] = covariate
    km = _call("SC73", payload)
    weib = _call("SC76", {"x": durations})
    blocks: Dict[str, Dict[str, Any]] = {"SC73": km, "SC76": weib}
    if group is not None:
        blocks["SC74"] = _call("SC74", payload)
    if covariate is not None:
        blocks["SC75"] = _call("SC75", payload)
    ok = _ok(blocks)
    if "SC73" not in ok:
        return _empty(capability_id, intent, "Kaplan-Meier 计算失败", trace_id, SOURCE_PANEL)
    r = km["result"]
    n = int(r["n"])
    bits = [f"Kaplan-Meier 中位生存 {_fmt(r['median'], 2)}，事件 {r['n_events']} 个"]
    if "SC74" in ok:
        bits.append(
            f"Log-rank χ²={_fmt(ok['SC74']['result']['chi2'], 3)}，p={_fmt(ok['SC74']['result']['p'])}"
        )
    if "SC75" in ok:
        hrs = ok["SC75"]["result"]["hr"]
        bits.append(f"Cox HR {[round(v, 3) for v in hrs if _is_num(v)]}")
    if "SC76" in ok:
        bits.append(f"Weibull shape={_fmt(ok['SC76']['result']['shape'], 3)}")
    answer = "；".join(bits) + f"。样本为 {n} 条生存记录，生存曲线只描述历史事件节奏，不代表未来。"
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"has_group": group is not None, "has_covariate": covariate is not None},
            "capabilities": {
                capability_id: {
                    "methods": sorted(ok),
                    "n": n,
                    "km": {"times": r["times"], "survival": r["survival"], "median": r["median"]},
                    "logrank": None if "SC74" not in ok else ok["SC74"]["result"],
                    "cox": None if "SC75" not in ok else ok["SC75"]["result"],
                    "weibull": None if "SC76" not in ok else ok["SC76"]["result"],
                }
            },
        },
        quality_block=_quality(n, MIN_SURVIVAL, SOURCE_PANEL, "survival_records"),
        trace_id=trace_id,
    )


# ---------------- D-J27 可靠性与控制图 ----------------


def reliability_metrics(
    time: Any = None,
    *,
    event: Any = None,
    series: Any = None,
    lam: float = 0.2,
    L: float = 3.0,
    capability_id: str = "D-J27",
    intent: str = INTENT_RELIABILITY,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    durations = _floats(time if time is not None else series)
    if len(durations) < MIN_SURVIVAL:
        return _empty(
            capability_id, intent, f"可靠性样本不足 {MIN_SURVIVAL} 条", trace_id, SOURCE_PANEL
        )
    payload: Dict[str, Any] = {"time": durations}
    if event is not None:
        payload["event"] = _floats(event)
    mtbf = _call("SC77", payload)
    chart = _call("SC78", {"x": durations}, lam=lam, L=L)
    ok = _ok({"SC77": mtbf, "SC78": chart})
    if "SC77" not in ok:
        return _empty(capability_id, intent, "MTBF 计算失败", trace_id, SOURCE_PANEL)
    r = mtbf["result"]
    n = int(r["n"])
    bits = [
        f"MTBF {_fmt(r['mtbf'], 2)}，失效率 {_fmt(r['failure_rate'], 6)}（失效 {r['n_events']} 次）"
    ]
    if "SC78" in ok:
        c = ok["SC78"]["result"]
        bits.append(
            f"EWMA 控制图告警 {sum(1 for v in c['alarms'] if v)} 点（UCL {_fmt(c['ucl'], 4)} / LCL {_fmt(c['lcl'], 4)}）"
        )
    answer = "；".join(bits) + f"。样本为 {n} 条记录，可靠性指标基于历史失效节奏，不代表未来表现。"
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"lam": lam, "L": L},
            "capabilities": {
                capability_id: {
                    "methods": sorted(ok),
                    "n": n,
                    "mtbf": r["mtbf"],
                    "failure_rate": r["failure_rate"],
                    "alarms": None if "SC78" not in ok else ok["SC78"]["result"]["alarms"],
                }
            },
        },
        quality_block=_quality(n, MIN_SURVIVAL, SOURCE_PANEL, "survival_records"),
        trace_id=trace_id,
    )


# ---------------- D-J28 Meta 分析 ----------------


def meta_analysis(
    effects: Any = None,
    *,
    se: Any = None,
    capability_id: str = "D-J28",
    intent: str = INTENT_META,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    eff = _floats(effects if effects is not None else [])
    sig = _floats(se if se is not None else [])
    m = min(len(eff), len(sig))
    if m < MIN_META:
        return _empty(
            capability_id, intent, f"Meta 样本不足 {MIN_META} 项", trace_id, SOURCE_SERIES
        )
    payload = {"effect": eff[:m], "se": sig[:m]}
    fixed = _call("SC79", payload)
    rand = _call("SC80", payload)
    het = _call("SC81", payload)
    funnel = _call("SC82", payload)
    trim = _call("SC83", payload)
    ok = _ok({"SC79": fixed, "SC80": rand, "SC81": het, "SC82": funnel, "SC83": trim})
    if "SC79" not in ok:
        return _empty(capability_id, intent, "固定效应 Meta 计算失败", trace_id, SOURCE_SERIES)
    r = fixed["result"]
    n = int(r["n"])
    bits = [
        f"固定效应合并 {_fmt(r['pooled'], 6)}（95% CI {_fmt(r['ci_low'], 6)} ~ {_fmt(r['ci_high'], 6)}，p={_fmt(r['p'])}）"
    ]
    if "SC80" in ok:
        rr = ok["SC80"]["result"]
        bits.append(
            f"随机效应合并 {_fmt(rr['pooled'], 6)}（τ²={_fmt(rr['tau2'], 6)}，I²={_fmt(rr['i2'])}）"
        )
    if "SC82" in ok:
        bits.append(f"漏斗图截距 p={_fmt(ok['SC82']['result']['p'])}")
    if "SC83" in ok:
        bits.append(f"Trim-and-fill 填补 {ok['SC83']['result']['n_filled']} 项")
    answer = "；".join(bits) + f"。样本为 {n} 项研究，合并效应只汇总历史证据，不代表未来。"
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"k_studies": m},
            "capabilities": {
                capability_id: {
                    "methods": sorted(ok),
                    "n": n,
                    "fixed": r,
                    "random": None if "SC80" not in ok else ok["SC80"]["result"],
                    "heterogeneity": None if "SC81" not in ok else ok["SC81"]["result"],
                    "trim_fill": None if "SC83" not in ok else ok["SC83"]["result"],
                }
            },
        },
        quality_block=_quality(n, MIN_META, SOURCE_SERIES, "study_effects"),
        trace_id=trace_id,
    )


# ---------------- D-J29 缺失数据 ----------------


def missing_data_profile(
    X: Any = None,
    *,
    capability_id: str = "D-J29",
    intent: str = INTENT_MISSING,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    if X is None:
        return _empty(capability_id, intent, "缺失画像需要面板输入", trace_id, SOURCE_PANEL)
    if isinstance(X, Mapping) and "series" in X:
        names, rows = _frame_of(X)
        payload: Any = {"X": [[None if not _is_num(v) else v for v in row] for row in rows]}
        cols = names
    else:
        rows_raw = X.get("X") if isinstance(X, Mapping) else X
        if not isinstance(rows_raw, Sequence):
            return _empty(capability_id, intent, "缺失画像需要矩阵行", trace_id, SOURCE_PANEL)
        payload = {"X": [[None if v is None else v for v in row] for row in rows_raw]}
        cols = [f"c{i}" for i in range(len(payload["X"][0]) if payload["X"] else 0)]
    n = len(payload["X"])
    if n < MIN_PANEL:
        return _empty(
            capability_id, intent, f"缺失画像样本不足 {MIN_PANEL} 行", trace_id, SOURCE_PANEL
        )
    mech = _call("SC84", payload)
    impute = _call("SC85", payload, k=5)
    maha = _call("SC86", payload)
    patterns = _call("SC87", payload)
    ok = _ok({"SC84": mech, "SC85": impute, "SC86": maha, "SC87": patterns})
    if not ok:
        return _empty(capability_id, intent, "缺失画像全部计算失败", trace_id, SOURCE_PANEL)
    bits = []
    if "SC84" in ok:
        r = ok["SC84"]["result"]
        bits.append(
            f"缺失率 {_fmt(r['missing_rate'])}（{r['n_missing']} 个缺失单元），MCAR 检验 p={_fmt(r['p'])}"
        )
    if "SC87" in ok:
        r = ok["SC87"]["result"]
        bits.append(f"缺失模式 {r['n_patterns']} 种")
    if "SC86" in ok:
        bits.append(f"马氏距离离群 {ok['SC86']['result']['n_outliers']} 行")
    if "SC85" in ok:
        bits.append(f"KNN 插补 {ok['SC85']['result']['n_filled']} 个单元")
    answer = (
        "；".join(bits) + f"。样本为 {n} 行，缺失诊断只描述数据完整性，不代表补全后的结论可靠。"
    )
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"columns": cols},
            "capabilities": {
                capability_id: {
                    "methods": sorted(ok),
                    "n": n,
                    "mechanism": None if "SC84" not in ok else ok["SC84"]["result"],
                    "patterns": None if "SC87" not in ok else ok["SC87"]["result"],
                    "mahalanobis": None if "SC86" not in ok else ok["SC86"]["result"],
                    "imputed": None if "SC85" not in ok else ok["SC85"]["result"],
                }
            },
        },
        quality_block=_quality(n, MIN_PANEL, SOURCE_PANEL, "panel_rows"),
        trace_id=trace_id,
    )
