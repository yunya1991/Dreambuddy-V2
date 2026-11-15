# -*- coding: utf-8 -*-
"""G 组机构方法能力编排（D-G01/G02/G03/G04/G05/G06/G07/G10/G11/G12/G13/G15/G18/G21/G24）。

分工（ADR-V13）：能力层只做「输入归一 + 调方法层 + 门禁 + 信封 + 一句话」，
所有统计量一律调用 `l1agg.methods.run`（X/O/P/Q 组），不在此重算口径。

门禁：横截面类 n≥30、组合/风险类 n≥60、因子回归 n≥120、Fama-MacBeth n≥250；
不足一律 `status=partial`/`empty` 并披露样本量，不生成方向性结论。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..methods import run as run_method
from .envelope import (
    build,
    quality_for,
    unavailable,
)

INTENT_CROSS_SECTION = "cross_section_query"
INTENT_FACTOR = "factor_model_query"
INTENT_SEQUENCE = "sequence_operator"
INTENT_RISK = "risk_allocation_query"
INTENT_ATTRIBUTION = "attribution_query"
INTENT_REGRESSION = "cross_section_regression"
INTENT_CROWDING = "crowding_query"

MIN_CROSS = 30
MIN_PORTFOLIO = 60
MIN_FACTOR = 120
MIN_MACBETH = 250
SEQUENCE_OPS = (
    "O01",
    "O02",
    "O03",
    "O04",
    "O05",
    "O06",
    "O07",
    "O08",
    "O11",
    "O12",
    "O13",
    "O14",
    "O15",
)
PAIR_OPS = ("O09", "O10")
SOURCE_PANEL = "datacenter.panel"
SOURCE_SERIES = "datacenter.series"


# ---------------- 通用工具 ----------------


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _panel_of(data: Any) -> Dict[str, List[Any]]:
    """归一为 {symbol: series}；接受 {"series": {...}} 或直接面板映射。"""
    if not isinstance(data, Mapping):
        raise ValueError("panel 必须是 {symbol: series} 映射")
    panel = data.get("series") if isinstance(data.get("series"), Mapping) else data
    out: Dict[str, List[Any]] = {}
    for name, values in panel.items():
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
            out[str(name)] = list(values)
    if not out:
        raise ValueError("panel 不能为空")
    return out


def _series_of(data: Any) -> List[Any]:
    if isinstance(data, Mapping):
        for key in ("series", "values", "price", "prices"):
            if key in data:
                return list(data[key])
        raise ValueError("series 数据缺少 series/values 字段")
    if isinstance(data, Sequence) and not isinstance(data, (str, bytes)):
        return list(data)
    raise ValueError("series 必须是序列")


def _call(method_id: str, data: Any, **params: Any) -> Dict[str, Any]:
    """调方法层；门禁/输入问题收敛为结构化块，不抛给 L1。"""
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


def _latest_map(result: Mapping[str, Any]) -> Dict[str, Any]:
    """把方法输出压成「最后一个有效值」投影（仅用于展示，不重算）。"""
    out: Dict[str, Any] = {}
    for key, value in result.items():
        if key == "n":
            continue
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            nums = [v for v in value if _is_num(v)]
            out[key] = nums[-1] if nums else None
        elif _is_num(value):
            out[key] = value
        elif isinstance(value, Mapping):
            nums = [v for v in value.values() if _is_num(v)]
            out[key] = max(nums) if nums else None
    return out


def _empty(capability_id, intent, reason, trace_id, params=None):
    return unavailable(
        capability=capability_id,
        intent=intent,
        reason=reason,
        data={"params": params or {}},
        sources=[SOURCE_PANEL],
        trace_id=trace_id,
    )


def _quality(n: int, min_n: int, source: str, align: str):
    return quality_for(
        n,
        min_n=min_n,
        span=None,
        sources=[source],
        align_method=align,
        timezone="UTC",
    )


# ---------------- D-G01 横截面 z-score / rank ----------------


def cross_section_profile(
    panel: Any = None,
    *,
    capability_id: str = "D-G01",
    intent: str = INTENT_CROSS_SECTION,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    values = _panel_of(panel)
    z_block = _call("X01", {"series": values})
    pct_block = _call("X02", {"series": values})
    if z_block["gate"] != "ok" or pct_block["gate"] != "ok":
        return _empty(
            capability_id,
            intent,
            "横截面标的数不足或数据非法",
            trace_id,
            {"n_symbols": len(values)},
        )

    z = z_block["result"]["z"]
    pct = pct_block["result"]["pct"]
    n = int(z_block["result"]["n"])
    top = max(z.items(), key=lambda kv: kv[1])
    bottom = min(z.items(), key=lambda kv: kv[1])
    ranked = sorted(pct.items(), key=lambda kv: kv[1], reverse=True)
    answer = (
        f"横截面 {n} 个标的：z 最高 {top[0]}（{top[1]:.2f}）、最低 {bottom[0]}（{bottom[1]:.2f}）；"
        f"百分位最高 {ranked[0][0]}（{ranked[0][1]:.0%}）、最低 {ranked[-1][0]}（{ranked[-1][1]:.0%}）。"
        f"样本为当期横截面 {n} 个标的，仅为相对位置，不代表未来。"
    )
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"n_symbols": n},
            "capabilities": {
                capability_id: {"methods": ["X01", "X02"], "n": n, "z": z, "pct": pct}
            },
        },
        quality_block=_quality(n, MIN_CROSS, SOURCE_PANEL, "cross_section_latest"),
        trace_id=trace_id,
    )


# ---------------- D-G02 分组中性化 ----------------


def group_neutralize(
    panel: Any = None,
    *,
    groups: Any = None,
    capability_id: str = "D-G02",
    intent: str = INTENT_CROSS_SECTION,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    values = _panel_of(panel)
    if groups is not None and not isinstance(groups, Mapping):
        raise ValueError("groups 必须是 {symbol: 分组标签} 映射")
    block = _call("X03", {"series": values}, group=groups)
    if block["gate"] != "ok":
        return _empty(
            capability_id,
            intent,
            "分组中性化失败（样本不足或分组未对齐）",
            trace_id,
            {"n_symbols": len(values)},
        )

    resid = block["result"]["resid"]
    n = int(block["result"]["n"])
    labels = {str(v) for v in (groups or {}).values()} or {"all"}
    top = max(resid.items(), key=lambda kv: kv[1])
    bottom = min(resid.items(), key=lambda kv: kv[1])
    answer = (
        f"按 {len(labels)} 个分组去均值后（n={n}）：中性化值最高 {top[0]}（{top[1]:.4f}）、"
        f"最低 {bottom[0]}（{bottom[1]:.4f}）。样本为当期横截面 {n} 个标的，仅为组内相对位置，不含方向判断。"
    )
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"n_symbols": n, "n_groups": len(labels)},
            "capabilities": {capability_id: {"methods": ["X03"], "n": n, "resid": resid}},
        },
        quality_block=_quality(n, MIN_CROSS, SOURCE_PANEL, "cross_section_latest"),
        trace_id=trace_id,
    )


# ---------------- D-G03 分位组合与多空价差 ----------------


def quantile_portfolio(
    panel: Any = None,
    *,
    k: int = 5,
    capability_id: str = "D-G03",
    intent: str = INTENT_CROSS_SECTION,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    values = _panel_of(panel)
    buckets = _call("X04", {"series": values}, k=int(k))
    spread = _call("X05", {"series": values}, k=int(k))
    if buckets["gate"] != "ok" or spread["gate"] != "ok":
        return _empty(
            capability_id,
            intent,
            "分位组合失败（样本不足）",
            trace_id,
            {"n_symbols": len(values), "k": int(k)},
        )

    n = int(buckets["result"]["n"])
    counts = buckets["result"]["counts"]
    spread_val = spread["result"]["spread"]
    t_value = spread["result"]["t"]
    answer = (
        f"横截面按取值分 {len(counts)} 桶（各桶 {min(counts)}–{max(counts)} 个标的，n={n}）："
        f"最高桶减最低桶均值差 {spread_val:.4f}，Welch t={t_value:.2f}。"
        f"样本为当期横截面 {n} 个标的，价差只是当期描述，不构成多空建议。"
    )
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"n_symbols": n, "k": len(counts)},
            "capabilities": {
                capability_id: {
                    "methods": ["X04", "X05"],
                    "n": n,
                    "bucket": buckets["result"]["bucket"],
                    "counts": counts,
                    "spread": spread_val,
                    "t": t_value,
                }
            },
        },
        quality_block=_quality(n, MIN_CROSS, SOURCE_PANEL, "cross_section_latest"),
        trace_id=trace_id,
    )


# ---------------- D-G04 横截面离散度与市场宽度 ----------------


def dispersion_breadth(
    panel: Any = None,
    *,
    capability_id: str = "D-G04",
    intent: str = INTENT_CROSS_SECTION,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    values = _panel_of(panel)
    disp = _call("X06", {"series": values})
    breadth = _call("X07", {"series": values})
    if disp["gate"] != "ok" or breadth["gate"] != "ok":
        return _empty(
            capability_id,
            intent,
            "离散度/宽度计算失败（需至少 2 个时点且样本充足）",
            trace_id,
            {"n_symbols": len(values)},
        )

    n = int(disp["result"]["n"])
    b = breadth["result"]
    answer = (
        f"横截面 n={n}：离散度（std）={disp['result']['dispersion']:.4f}、均值={disp['result']['mean']:.4f}；"
        f"上涨 {b['advance']} 家 / 下跌 {b['decline']} 家，市场宽度={b['breadth']:.0%}。"
        f"样本为当期横截面 {n} 个标的，仅描述当期分化，不代表趋势。"
    )
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"n_symbols": n},
            "capabilities": {
                capability_id: {
                    "methods": ["X06", "X07"],
                    "n": n,
                    "dispersion": disp["result"]["dispersion"],
                    "mean": disp["result"]["mean"],
                    "breadth": b["breadth"],
                    "advance": b["advance"],
                    "decline": b["decline"],
                }
            },
        },
        quality_block=_quality(n, MIN_CROSS, SOURCE_PANEL, "cross_section_latest"),
        trace_id=trace_id,
    )


# ---------------- D-G05 同向率 ----------------


def co_movement(
    panel: Any = None,
    *,
    capability_id: str = "D-G05",
    intent: str = INTENT_CROSS_SECTION,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    values = _panel_of(panel)
    block = _call("X08", {"series": values})
    if block["gate"] != "ok":
        return _empty(
            capability_id,
            intent,
            "同向率计算失败（需至少 2 个时点且样本充足）",
            trace_id,
            {"n_symbols": len(values)},
        )

    out = block["result"]
    answer = (
        f"横截面同向率 {out['ratio']:.1%}：{out['agree']}/{out['pairs']} 对标的同涨同跌（n={out['n']}）。"
        f"样本为当期横截面 {out['n']} 个标的，同向率只反映联动程度，不含方向含义。"
    )
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"n_symbols": int(out["n"])},
            "capabilities": {capability_id: {"methods": ["X08"], **out}},
        },
        quality_block=_quality(int(out["n"]), MIN_CROSS, SOURCE_PANEL, "cross_section_latest"),
        trace_id=trace_id,
    )


# ---------------- D-G06 因子暴露与特质收益 ----------------


def factor_exposure(
    panel: Any = None,
    *,
    factor: Any = None,
    capability_id: str = "D-G06",
    intent: str = INTENT_FACTOR,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    values = _panel_of(panel)
    exposure = _call("X09", {"series": values}, factor=factor)
    specific = _call("X10", {"series": values}, factor=factor)
    if exposure["gate"] != "ok" or specific["gate"] != "ok":
        return _empty(
            capability_id,
            intent,
            "因子暴露回归失败（样本不足或暴露未对齐）",
            trace_id,
            {"n_symbols": len(values)},
        )

    n = int(exposure["result"]["n"])
    betas = exposure["result"]["betas"]
    head = max(betas.items(), key=lambda kv: abs(kv[1])) if betas else ("--", 0.0)
    answer = (
        f"横截面因子回归（n={n}）：R²={exposure['result']['r2']:.3f}，"
        f"最强暴露 {head[0]}={head[1]:.3f}；特质收益横截面 std={specific['result']['std']:.4f}。"
        f"样本为当期横截面 {n} 个标的，暴露为当期拟合结果，不含预测。"
    )
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"n_symbols": n},
            "capabilities": {
                capability_id: {
                    "methods": ["X09", "X10"],
                    "n": n,
                    "betas": betas,
                    "alpha": exposure["result"]["alpha"],
                    "r2": exposure["result"]["r2"],
                    "specific": specific["result"]["specific"],
                    "specific_std": specific["result"]["std"],
                }
            },
        },
        quality_block=_quality(n, MIN_FACTOR, SOURCE_PANEL, "cross_section_regression"),
        trace_id=trace_id,
    )


# ---------------- D-G07 序列算子族 ----------------


def sequence_operators(
    series: Any = None,
    *,
    d: int = 20,
    other: Any = None,
    capability_id: str = "D-G07",
    intent: str = INTENT_SEQUENCE,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    xs = _series_of(series)
    ops: Dict[str, Any] = {}
    methods: List[str] = []
    n = len(xs)
    for op in SEQUENCE_OPS:
        block = _call(op, xs, d=int(d))
        if block["gate"] == "ok":
            methods.append(op)
            ops[op] = _latest_map(block["result"])
    if other is not None:
        ys = _series_of(other)
        for op in PAIR_OPS:
            block = _call(op, {"x": xs, "y": ys}, d=int(d))
            if block["gate"] == "ok":
                methods.append(op)
                ops[op] = _latest_map(block["result"])
    if not ops:
        return unavailable(
            capability=capability_id,
            intent=intent,
            reason="序列样本不足 30 点",
            data={"params": {"n": n, "d": int(d)}},
            sources=[SOURCE_SERIES],
            trace_id=trace_id,
        )

    z_val = ops.get("O08", {}).get("series")
    rank_val = ops.get("O14", {}).get("rank")
    bits = []
    if z_val is not None:
        bits.append(f"ts_zscore={z_val:.3f}")
    if rank_val is not None:
        bits.append(f"rank={rank_val:.3f}")
    detail = "、".join(bits) if bits else "详见 data.capabilities"
    answer = (
        f"序列算子（n={n}，d={int(d)}）：可算 {len(ops)} 个算子，{detail}。"
        f"样本为 {n} 个时点，算子输出为当期值，写入 L2 前仅作特征候选。"
    )
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"n": n, "d": int(d)},
            "capabilities": {capability_id: {"methods": methods, "n": n, "ops": ops}},
        },
        quality_block=_quality(n, MIN_CROSS, SOURCE_SERIES, "time_series_rolling"),
        trace_id=trace_id,
    )


# ---------------- D-G10 逆波动权重 ----------------


def inverse_volatility_weights(
    panel: Any = None,
    *,
    capability_id: str = "D-G10",
    intent: str = INTENT_RISK,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    values = _panel_of(panel)
    block = _call("P03", {"series": values})
    if block["gate"] != "ok":
        return _empty(
            capability_id,
            intent,
            "逆波动权重失败（样本不足 60 期）",
            trace_id,
            {"n_symbols": len(values)},
        )

    out = block["result"]
    weights = out["weights"]
    head = max(weights.items(), key=lambda kv: kv[1])
    answer = (
        f"逆波动权重（n={out['n']}）：最大权重 {head[0]}={head[1]:.1%}，"
        f"权重和 {sum(weights.values()):.3f}。样本为 {out['n']} 期收益，权重为波动倒数归一化，不含预期收益。"
    )
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"n_symbols": int(out["n"])},
            "capabilities": {capability_id: {"methods": ["P03"], **out}},
        },
        quality_block=_quality(int(out["n"]), MIN_PORTFOLIO, SOURCE_PANEL, "panel_returns"),
        trace_id=trace_id,
    )


# ---------------- D-G11 等风险贡献权重 ----------------


def equal_risk_contribution(
    panel: Any = None,
    *,
    capability_id: str = "D-G11",
    intent: str = INTENT_RISK,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    values = _panel_of(panel)
    block = _call("P04", {"series": values})
    if block["gate"] != "ok":
        return _empty(
            capability_id,
            intent,
            "等风险贡献失败（样本不足 60 期）",
            trace_id,
            {"n_symbols": len(values)},
        )

    out = block["result"]
    contrib = out["risk_contrib"]
    spread = max(contrib.values()) - min(contrib.values()) if contrib else 0.0
    answer = (
        f"等风险贡献权重（n={out['n']}，迭代 {out['iterations']} 次）："
        f"风险贡献极差 {spread:.4f}（越接近 0 越均衡）。样本为 {out['n']} 期收益，权重为风险预算结果，不含预期收益。"
    )
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"n_symbols": int(out["n"])},
            "capabilities": {capability_id: {"methods": ["P04"], **out}},
        },
        quality_block=_quality(int(out["n"]), MIN_PORTFOLIO, SOURCE_PANEL, "panel_returns"),
        trace_id=trace_id,
    )


# ---------------- D-G12 风险贡献分解 ----------------


def risk_contribution(
    panel: Any = None,
    *,
    weights: Any = None,
    capability_id: str = "D-G12",
    intent: str = INTENT_RISK,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    values = _panel_of(panel)
    block = _call("P05", {"series": values, "weights": weights})
    if block["gate"] != "ok":
        return _empty(
            capability_id,
            intent,
            "风险贡献分解失败（样本不足 60 期或权重未对齐）",
            trace_id,
            {"n_symbols": len(values)},
        )

    out = block["result"]
    share = out["share"]
    head = max(share.items(), key=lambda kv: kv[1]) if share else ("--", 0.0)
    answer = (
        f"风险贡献分解（n={out['n']}）：总风险 {out['total_risk']:.4f}，"
        f"占比最高 {head[0]}={head[1]:.1%}。样本为 {out['n']} 期收益，分解基于历史协方差，不含预测。"
    )
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"n_symbols": int(out["n"])},
            "capabilities": {capability_id: {"methods": ["P05"], **out}},
        },
        quality_block=_quality(int(out["n"]), MIN_PORTFOLIO, SOURCE_PANEL, "panel_returns"),
        trace_id=trace_id,
    )


# ---------------- D-G13 协方差收缩 ----------------


def covariance_shrinkage(
    panel: Any = None,
    *,
    capability_id: str = "D-G13",
    intent: str = INTENT_RISK,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    values = _panel_of(panel)
    block = _call("P06", {"series": values})
    if block["gate"] != "ok":
        return _empty(
            capability_id,
            intent,
            "协方差收缩失败（样本不足 60 期）",
            trace_id,
            {"n_symbols": len(values)},
        )

    out = block["result"]
    answer = (
        f"Ledoit-Wolf 协方差收缩（n={out['n']}，backend={out['backend']}）："
        f"收缩强度 δ={out['delta']:.4f}（δ→1 表示越接近对角结构）。样本为 {out['n']} 期收益，收缩只改估计噪声，不含方向。"
    )
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"n_symbols": int(out["n"])},
            "capabilities": {capability_id: {"methods": ["P06"], **out}},
        },
        quality_block=_quality(int(out["n"]), MIN_PORTFOLIO, SOURCE_PANEL, "panel_returns"),
        trace_id=trace_id,
    )


# ---------------- D-G15 PCA 风险分解 ----------------


def pca_risk_decomposition(
    panel: Any = None,
    *,
    k: int = 3,
    capability_id: str = "D-G15",
    intent: str = INTENT_RISK,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    values = _panel_of(panel)
    block = _call("P08", {"series": values}, k=int(k))
    if block["gate"] != "ok":
        return _empty(
            capability_id,
            intent,
            "PCA 风险分解失败（样本不足 60 期）",
            trace_id,
            {"n_symbols": len(values)},
        )

    out = block["result"]
    ratio = out["ratio"]
    top_share = sum(ratio) if ratio else 0.0
    answer = (
        f"PCA 风险分解（n={out['n']}，k={out['k']}）：前 {len(ratio)} 个主成分解释 {top_share:.1%} 方差。"
        f"样本为 {out['n']} 期收益，主成分解释的是共同波动结构，不含方向判断。"
    )
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"n_symbols": int(out["n"]), "k": int(out["k"])},
            "capabilities": {capability_id: {"methods": ["P08"], **out}},
        },
        quality_block=_quality(int(out["n"]), MIN_PORTFOLIO, SOURCE_PANEL, "panel_returns"),
        trace_id=trace_id,
    )


# ---------------- D-G18 Brinson 归因 ----------------


def brinson_attribution(
    panel: Any = None,
    *,
    weights: Any = None,
    benchmark_weights: Any = None,
    sector: Any = None,
    capability_id: str = "D-G18",
    intent: str = INTENT_ATTRIBUTION,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    values = _panel_of(panel)
    block = _call(
        "P12",
        {
            "series": values,
            "weights": weights,
            "benchmark_weights": benchmark_weights,
            "sector": sector,
        },
    )
    if block["gate"] != "ok":
        return _empty(
            capability_id,
            intent,
            "Brinson 归因失败（样本不足 60 期或权重/分组未对齐）",
            trace_id,
            {"n_symbols": len(values)},
        )

    out = block["result"]
    answer = (
        f"Brinson 归因（n={out['n']}）：配置 {out['allocation']:.4f}、选股 {out['selection']:.4f}、"
        f"交互 {out['interaction']:.4f}，主动收益 {out['active_return']:.4f}。"
        f"样本为 {out['n']} 期收益，归因仅拆解历史主动收益来源，不评价未来。"
    )
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"n_symbols": int(out["n"])},
            "capabilities": {capability_id: {"methods": ["P12"], **out}},
        },
        quality_block=_quality(int(out["n"]), MIN_PORTFOLIO, SOURCE_PANEL, "panel_returns"),
        trace_id=trace_id,
    )


# ---------------- D-G21 Fama-MacBeth ----------------


def _matrix_of(data: Any, names: Sequence[str]) -> List[List[float]]:
    """把 {symbol: series} 面板转成 T×N 矩阵（列按 names 排序）。"""
    columns = [list(data[name]) for name in names]
    length = min((len(col) for col in columns), default=0)
    rows: List[List[float]] = []
    for t in range(length):
        try:
            rows.append([float(col[t]) for col in columns])
        except (TypeError, ValueError):
            continue
    return rows


def fama_macbeth(
    factor: Any = None,
    *,
    target: Any = None,
    capability_id: str = "D-G21",
    intent: str = INTENT_REGRESSION,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    if factor is None or target is None:
        raise ValueError("Fama-MacBeth 需要 factor 与 target（T×N 矩阵或 {symbol: series} 面板）")
    if isinstance(factor, Mapping) and isinstance(target, Mapping):
        names = sorted(set(map(str, factor)) & set(map(str, target)))
        if not names:
            raise ValueError("factor 与 target 无可对齐列")
        payload = {
            "factor": _matrix_of({str(k): v for k, v in factor.items()}, names),
            "target": _matrix_of({str(k): v for k, v in target.items()}, names),
        }
    else:
        payload = {"factor": factor, "target": target}

    block = _call("Q05", payload)
    if block["gate"] != "ok":
        return _empty(
            capability_id,
            intent,
            "Fama-MacBeth 失败（可用横截面期数不足 2 或样本不足 250）",
            trace_id,
            {},
        )

    out = block["result"]
    t_text = "不可算" if out["t"] is None else f"{out['t']:.2f}"
    answer = (
        f"Fama-MacBeth（{out['n_periods']} 期 × {out['n_assets']} 标的）：因子溢价 λ={out['lambda']:.4f}，"
        f"标准误 {out['se']:.4f}，t={t_text}。"
        f"样本为 {out['n_periods']} 期横截面，λ 为历史回归的均值溢价，不含预测。"
    )
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"n_periods": int(out["n_periods"]), "n_assets": int(out["n_assets"])},
            "capabilities": {capability_id: {"methods": ["Q05"], **out}},
        },
        quality_block=_quality(
            int(out["n_periods"]), MIN_MACBETH, SOURCE_PANEL, "cross_section_regression"
        ),
        trace_id=trace_id,
    )


# ---------------- D-G24 因子拥挤度 ----------------


def factor_crowding(
    panel: Any = None,
    *,
    q: float = 0.2,
    valuation_spread: Optional[float] = None,
    capability_id: str = "D-G24",
    intent: str = INTENT_CROWDING,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    values = _panel_of(panel)
    tail = _call("P13", {"series": values}, q=float(q))
    stability = _call("P14", {"series": values})
    if tail["gate"] != "ok":
        return _empty(
            capability_id,
            intent,
            "拥挤度失败（样本不足 60 期）",
            trace_id,
            {"n_symbols": len(values)},
        )

    out = tail["result"]
    rho_down = [v for v in out["rho_down"].values() if _is_num(v)]
    rho_full = [v for v in out["rho_full"].values() if _is_num(v)]
    avg_down = sum(rho_down) / len(rho_down) if rho_down else None
    avg_full = sum(rho_full) / len(rho_full) if rho_full else None
    stab = stability["result"] if stability["gate"] == "ok" else None
    stability_scalar: Optional[float] = None
    if stab is not None:
        mean_rho = stab.get("mean_rho")
        std_rho = stab.get("std_rho")
        if _is_num(mean_rho) and _is_num(std_rho) and abs(float(mean_rho)) > 1e-9:
            stability_scalar = float(std_rho) / abs(float(mean_rho))
    bits = []
    if avg_down is not None and avg_full is not None:
        bits.append(f"下行相关均值 {avg_down:.3f}（全样本 {avg_full:.3f}）")
    if stability_scalar is not None:
        bits.append(f"相关稳定性 {stability_scalar:.3f}")
    if valuation_spread is None:
        bits.append("估值价差未提供（需估值数据，本期不计算）")

    n = int(out["n"])
    answer = (
        f"因子拥挤度（n={n}）：「" + "；".join(bits) + "」。"
        f"样本为 {n} 期收益，下行相关抬升或相关稳定性下降表示拥挤风险上升，仅为历史结构描述。"
    )
    methods = ["P13"] + (["P14"] if stab is not None else [])
    return build(
        capability=capability_id,
        intent=intent,
        answer=answer,
        data={
            "params": {"n_symbols": n, "q": float(q), "valuation_spread": valuation_spread},
            "capabilities": {
                capability_id: {
                    "methods": methods,
                    "n": n,
                    "rho_down_avg": avg_down,
                    "rho_full_avg": avg_full,
                    "stability": stability_scalar,
                    "valuation_spread": valuation_spread,
                }
            },
        },
        quality_block=_quality(n, MIN_PORTFOLIO, SOURCE_PANEL, "panel_returns"),
        trace_id=trace_id,
    )
