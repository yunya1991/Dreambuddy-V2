# -*- coding: utf-8 -*-
"""D-E16 聚合曲线 + D-E17 类别看板（SPEC-54-L1交易层 §4.3 / §4.4，P0-3）。

只做确定性投影，不读库、不写库、不调 LLM：

  - D-E16：各成员先 rebase 到「最晚的首个可用日 = 100」，再按 `chart_weights`
    线性加权合成；短样本成员剔除并重归一；每点披露 `coverage_ratio`，
    `< 0.8` 标 `partial_members`；**禁止前向填充**。
  - D-E17：按类别分组的固定 19 列看板；组内按 `ret_60` 降序；四轴点亮明细
    只在 D-E19，本看板仅投影 `lights_ref / lit_n / warm_n`（零重算）。

图表权重只影响展示合成（LT-G2），本模块不向任何决策路径回传权重。
"""

from __future__ import annotations

import math
from statistics import pstdev
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..chart_weights import (
    DEFAULT_MIN_ROWS,
    ChartWeights,
    chart_weights_hash,
    resolve_members,
)
from ..chart_weights import (
    load as load_chart_weights,
)
from .envelope import (
    STATUS_EMPTY,
    STATUS_GOOD,
    STATUS_PARTIAL,
    build,
    quality,
    quality_for,
    unavailable,
)
from .visual import build_visual

INTENT_AGGREGATE = "trend_query"
INTENT_BOARD = "cross_check"

REBASE_METHOD = "rebased_100"
COVERAGE_FLOOR = 0.8
EMA_WINDOW = 26
VOL_WINDOW = 60
CORR_WINDOW = 90
RETURN_WINDOWS: Tuple[int, ...] = (20, 60, 120, 250)


# ------------------------------------------------------------ 工具
def _degrade(q: Dict[str, Any], reason: str) -> Dict[str, Any]:
    """把 good 降为 partial 并写降级原因（empty 保持 empty）。"""
    if q.get("status") == STATUS_EMPTY:
        return q
    out = dict(q)
    out["status"] = STATUS_PARTIAL
    out["degraded_reason"] = reason
    return out


def _valid_prices(values: Sequence[Any]) -> List[float]:
    out: List[float] = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            out.append(number)
    return out


def _returns(prices: Sequence[float]) -> List[float]:
    return [
        prices[i + 1] / prices[i] - 1.0 for i in range(len(prices) - 1) if prices[i] not in (0.0,)
    ]


def _pearson(x: Sequence[float], y: Sequence[float]) -> Optional[float]:
    n = min(len(x), len(y))
    if n < 3:
        return None
    xs, ys = list(x[-n:]), list(y[-n:])
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((a - mx) ** 2 for a in xs)
    syy = sum((b - my) ** 2 for b in ys)
    if sxx <= 0.0 or syy <= 0.0:
        return None
    sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys, strict=False))
    return sxy / math.sqrt(sxx * syy)


def _ema(values: Sequence[float], window: int) -> List[Optional[float]]:
    """标准 EMA（首点 = 首值）；样本不足 window 时全 None（不伪造平滑）。"""
    if window < 1 or len(values) < window:
        return [None] * len(values)
    k = 2.0 / (window + 1.0)
    out: List[Optional[float]] = []
    prev: Optional[float] = None
    for value in values:
        prev = value if prev is None else value * k + prev * (1.0 - k)
        out.append(round(prev, 6))
    return out


def _rebase(series: Mapping[str, float], base_date: str) -> Dict[str, float]:
    """取 `base_date` 当日或之后首个观测为 100，其余按比例缩放。"""
    base: Optional[float] = None
    for day in sorted(series):
        if day >= base_date:
            base = float(series[day])
            break
    if base is None or base == 0.0:
        return {}
    return {day: round(float(v) / base * 100.0, 6) for day, v in series.items() if day >= base_date}


# ------------------------------------------------------------ D-E16 聚合曲线
def aggregate_block(
    series: Mapping[str, Mapping[str, float]],
    *,
    weights: Any = None,
    min_rows: Optional[int] = None,
    mode: Optional[str] = None,
    source: Optional[str] = None,
    stale: Optional[Mapping[str, float]] = None,
    proxies: Optional[Mapping[str, bool]] = None,
    ema_window: int = EMA_WINDOW,
) -> Dict[str, Any]:
    """产出 D-E16 能力块（`gate` 恒为 ok；不可画时由调用方转 unavailable）。"""
    cfg: Optional[ChartWeights] = weights if isinstance(weights, ChartWeights) else None
    raw_weights = cfg.members if cfg is not None else (weights or {})
    cleaned: Dict[str, Dict[str, float]] = {}
    for symbol, values in (series or {}).items():
        if not isinstance(values, Mapping):
            continue
        points = {
            str(day): float(value)
            for day, value in values.items()
            if value is not None and math.isfinite(float(value))
        }
        if points:
            cleaned[str(symbol)] = points

    sample_n = {symbol: len(points) for symbol, points in cleaned.items()}
    resolved = resolve_members(
        raw_weights,
        sample_n,
        min_rows=min_rows,
        mode=mode,
        source=source,
    )
    active: Dict[str, float] = {
        symbol: float(weight)
        for symbol, weight in (resolved.get("weights") or {}).items()
        if float(weight) > 0.0 and symbol in cleaned
    }
    if not active:
        return {
            "gate": "insufficient_history",
            "methods": ["I02"],
            "reason": "no_member_with_history",
            "meta": {
                "smoothing": {"method": "EMA", "window": int(ema_window)},
                "n": 0,
                "chart_weights": {},
                "chart_weights_hash": "",
                "chart_weights_source": resolved.get("chart_weights_source", ""),
                "chart_weights_mode": resolved.get("chart_weights_mode", ""),
                "weights_degraded": True,
                "members": [],
                "flags": list(resolved.get("flags") or []),
            },
        }

    base_date = max(min(cleaned[symbol]) for symbol in active)
    rebased = {symbol: _rebase(cleaned[symbol], base_date) for symbol in active}
    rebased = {symbol: values for symbol, values in rebased.items() if values}
    active = {symbol: weight for symbol, weight in active.items() if symbol in rebased}
    if not active:
        return {
            "gate": "insufficient_history",
            "methods": ["I02"],
            "reason": "no_observation_at_base_date",
            "meta": {"n": 0, "smoothing": {"method": "EMA", "window": int(ema_window)}},
        }

    total_weight = sum(active.values())
    weights_norm = {symbol: weight / total_weight for symbol, weight in active.items()}

    dates = sorted({day for values in rebased.values() for day in values})
    stale = stale or {}
    proxies = proxies or {}
    threshold = int(
        min_rows if min_rows is not None else (cfg.min_rows if cfg else DEFAULT_MIN_ROWS)
    )

    points: List[Dict[str, Any]] = []
    for day in dates:
        present = {symbol: values[day] for symbol, values in rebased.items() if day in values}
        if not present:
            continue
        coverage = sum(weights_norm[symbol] for symbol in present)
        agg = sum(weights_norm[symbol] * value for symbol, value in present.items())
        points.append(
            {
                "date": day,
                "agg": round(agg, 6),
                "members": {symbol: round(value, 6) for symbol, value in present.items()},
                "coverage_ratio": round(coverage, 6),
                "partial_members": coverage < COVERAGE_FLOOR - 1e-9,
            }
        )
    if not points:
        return {
            "gate": "insufficient_history",
            "methods": ["I02"],
            "reason": "no_aligned_points",
            "meta": {"n": 0, "smoothing": {"method": "EMA", "window": int(ema_window)}},
        }

    ema_path = _ema([point["agg"] for point in points], int(ema_window))
    for point, smoothed in zip(points, ema_path, strict=False):
        point["ema26"] = smoothed

    members_meta = []
    for symbol, weight in weights_norm.items():
        n = int(sample_n.get(symbol, 0))
        members_meta.append(
            {
                "symbol": symbol,
                "weight": round(weight, 6),
                "n": n,
                "stale_ratio": round(float(stale.get(symbol, 0.0) or 0.0), 6),
                "proxy": bool(proxies.get(symbol, False)),
                "status": "available" if n >= threshold else "insufficient_history",
            }
        )
    members_meta.sort(key=lambda item: (-item["weight"], item["symbol"]))

    min_coverage = min(point["coverage_ratio"] for point in points)
    meta = {
        "smoothing": {"method": "EMA", "window": int(ema_window)},
        "unit": "rebased_index",
        "normalize": REBASE_METHOD,
        "base_date": base_date,
        "n": len(points),
        "chart_weights": {symbol: round(weight, 6) for symbol, weight in weights_norm.items()},
        "chart_weights_hash": chart_weights_hash(weights_norm),
        "chart_weights_source": resolved.get("chart_weights_source", ""),
        "chart_weights_mode": resolved.get("chart_weights_mode", ""),
        "weights_degraded": bool(resolved.get("weights_degraded")),
        "pruned": bool(resolved.get("pruned")),
        "dropped": list(resolved.get("dropped") or []),
        "members": members_meta,
        "coverage_floor": COVERAGE_FLOOR,
        "min_coverage": round(min_coverage, 6),
        "partial_points": sum(1 for point in points if point["partial_members"]),
        "min_rows": threshold,
        "flags": list(resolved.get("flags") or []),
    }
    return {
        "gate": "ok",
        "methods": ["I02"],
        "points": points,
        "meta": meta,
        "summary": {
            "base_date": base_date,
            "last_agg": points[-1]["agg"],
            "min_coverage": round(min_coverage, 6),
            "n_members": len(members_meta),
        },
    }


def aggregate_curve(
    series: Mapping[str, Mapping[str, float]],
    *,
    weights: Any = None,
    min_rows: Optional[int] = None,
    mode: Optional[str] = None,
    source: Optional[str] = None,
    stale: Optional[Mapping[str, float]] = None,
    proxies: Optional[Mapping[str, bool]] = None,
    ema_window: int = EMA_WINDOW,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """D-E16 信封：多成员加权聚合曲线（先 rebase 后加权，禁止前向填充）。"""
    cfg: Optional[ChartWeights] = weights if isinstance(weights, ChartWeights) else None
    if cfg is None and not weights:
        cfg = load_chart_weights()
    block = aggregate_block(
        series,
        weights=cfg if cfg is not None else weights,
        min_rows=min_rows,
        mode=mode,
        source=source,
        stale=stale,
        proxies=proxies,
        ema_window=ema_window,
    )
    if block.get("gate") != "ok":
        return unavailable(
            capability="D-E16",
            intent=INTENT_AGGREGATE,
            reason=f"聚合曲线不可用（{block.get('reason') or 'no_history'}）",
            trace_id=trace_id,
        )

    meta = block["meta"]
    min_rows_used = int(
        min_rows if min_rows is not None else (cfg.min_rows if cfg else DEFAULT_MIN_ROWS)
    )
    q = quality_for(
        int(meta["n"]),
        min_n=min_rows_used,
        span=[block["points"][0]["date"], block["points"][-1]["date"]],
        sources=["market.candles"],
        align_method="utc_daily_close",
        timezone="UTC",
    )
    if meta.get("pruned"):
        q = _degrade(q, "members_pruned")
    if meta.get("weights_degraded"):
        q = _degrade(q, "chart_weights_degraded")
    if meta.get("partial_points"):
        q = _degrade(q, "partial_members")
    if meta.get("min_coverage", 1.0) < COVERAGE_FLOOR:
        q = _degrade(q, "coverage_below_floor")

    head = (
        f"{len(meta['members'])} 个成员按图表权重合成，"
        f"基期 {meta['base_date']}=100，覆盖度最低 {meta['min_coverage']:.2f}，"
        f"图宽 {meta['n']} 点。"
    )
    tail = (
        "样本或覆盖度不足已降级披露，不做前向填充。"
        if q["status"] != STATUS_GOOD
        else "全部成员参与加权，无前向填充。"
    )
    answer = f"{head}{tail}历史统计，不代表未来。"

    payload = {"capabilities": {"D-E16": block}, "params": {"min_n": min_rows_used}}
    return build(
        capability="D-E16",
        intent=INTENT_AGGREGATE,
        answer=answer,
        data=payload,
        quality_block=q,
        trace_id=trace_id,
        visual=build_visual(capability="D-E16", data=payload, quality_block=q),
    )


# ------------------------------------------------------------ D-E17 类别看板
def _role_of(asset: Mapping[str, Any], symbol: str) -> str:
    role = str(asset.get("role") or "").strip()
    if role in ("leader", "co_leader", "member"):
        return role
    return "member" if symbol else "member"


def _asset_row(
    symbol: str,
    asset: Mapping[str, Any],
    *,
    min_rows: int,
    light_ref: str,
    corr_window: int,
    vol_window: int,
    windows: Sequence[int],
) -> Dict[str, Any]:
    prices = _valid_prices(asset.get("prices") or ())
    n = len(prices)
    rets = _returns(prices)
    view = str(asset.get("view") or asset.get("class") or "未分类")
    role = _role_of(asset, symbol)
    threshold = int(asset.get("min_rows") or min_rows)
    if n <= 0:
        status = "missing"
        reason = "no_history"
    elif n < threshold:
        status = "partial"
        reason = "history_lt_min_rows"
    else:
        status = "available"
        reason = None

    row: Dict[str, Any] = {
        "class": view,
        "symbol": symbol,
        "label": str(asset.get("label") or symbol),
        "role": role,
        "last": round(prices[-1], 6) if prices else None,
    }
    for window in windows:
        if n > window and prices[-1 - window] != 0.0:
            row[f"ret_{window}"] = round(prices[-1] / prices[-1 - window] - 1.0, 6)
        else:
            row[f"ret_{window}"] = None

    if len(rets) >= vol_window:
        row["vol_60"] = round(pstdev(rets[-vol_window:]) * math.sqrt(252.0), 6)
    else:
        row["vol_60"] = None

    peak: Optional[float] = None
    worst = 0.0
    for price in prices:
        peak = price if peak is None or price > peak else peak
        if peak:
            worst = max(worst, 1.0 - price / peak)
    row["mdd"] = round(worst, 6) if prices else None

    adx14: Optional[float] = None
    highs = asset.get("highs")
    lows = asset.get("lows")
    if highs is not None and lows is not None:
        from .stats import _call  # 延迟导入，避免聚合层与统计层循环依赖

        out = _call(
            "I32",
            {"high": _valid_prices(highs), "low": _valid_prices(lows), "close": prices},
        )
        if out["gate"] == "ok":
            adx14 = out["result"].get("adx")
    row["adx14"] = round(adx14, 6) if adx14 is not None else None

    corr: Optional[float] = None
    leader_prices = asset.get("leader_prices")
    if leader_prices is not None:
        other = _valid_prices(leader_prices)
        rho = _pearson(_returns(other)[-corr_window:], rets[-corr_window:])
        if rho is not None:
            corr = rho
    row["corr_to_leader_90d"] = round(corr, 6) if corr is not None else None

    row["lights_ref"] = light_ref
    row["lit_n"] = int(asset.get("lit_n") or 0)
    row["warm_n"] = int(asset.get("warm_n") or 0)
    row["n"] = n
    row["stale_ratio"] = round(float(asset.get("stale_ratio") or 0.0), 6)
    row["status"] = status
    row["degraded_reason"] = reason
    return row


def class_board(
    assets: Mapping[str, Mapping[str, Any]],
    *,
    min_rows: int = DEFAULT_MIN_ROWS,
    light_ref: str = "",
    windows: Sequence[int] = RETURN_WINDOWS,
    vol_window: int = VOL_WINDOW,
    corr_window: int = CORR_WINDOW,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """D-E17 信封：按类别分组的固定列看板（组内 `ret_60` 降序）。

    每个资产入参：`prices`（必填）、可选 `dates/ highs/ lows/ leader_prices/
    label/ view/ role/ lit_n/ warm_n/ stale_ratio/ min_rows`。
    点亮明细不在此重算（LT-AC4 / ADR-V13），只用入参计数与 `lights_ref`。
    """
    if not assets:
        return unavailable(
            capability="D-E17",
            intent=INTENT_BOARD,
            reason="看板无资产入参",
            trace_id=trace_id,
        )
    try:
        from ..asset_pool import load as load_asset_pool

        view_order = tuple(load_asset_pool().views())
    except Exception:  # pragma: no cover - 配置缺失时按首次出现顺序
        view_order = ()
    if not light_ref:
        try:
            light_ref = load_chart_weights().light_hash()
        except Exception:  # pragma: no cover
            light_ref = ""

    rows = [
        _asset_row(
            symbol,
            asset,
            min_rows=int(min_rows),
            light_ref=light_ref,
            corr_window=corr_window,
            vol_window=vol_window,
            windows=windows,
        )
        for symbol, asset in assets.items()
    ]
    order = {view: index for index, view in enumerate(view_order)}
    rows.sort(
        key=lambda row: (
            order.get(row["class"], len(order)),
            row["class"],
            -row["ret_60"] if row["ret_60"] is not None else math.inf,
            row["symbol"],
        )
    )

    available = sum(1 for row in rows if row["status"] == "available")
    partial = len(rows) - available
    q = quality(
        status=STATUS_GOOD if partial == 0 else STATUS_PARTIAL,
        sample_n=len(rows),
        span=None,
        degraded_reason=None if partial == 0 else "member_partial",
        sources=["market.candles"],
        align_method="utc_daily_close",
        timezone="UTC",
    )
    classes = []
    for row in rows:
        if row["class"] not in classes:
            classes.append(row["class"])
    answer = (
        f"类别看板覆盖 {len(classes)} 类 / {len(rows)} 标的，"
        f"{available} 个样本达标、{partial} 个样本不足已标降级；"
        f"排序口径为组内 ret_60 降序。历史统计，不代表未来。"
    )
    block = {
        "gate": "ok",
        "methods": ["F14", "D20"],
        "rows": rows,
        "meta": {
            "groups": ["class", "role"],
            "sort": "ret_60_desc",
            "windows": list(windows),
            "lights_ref": light_ref,
            "n_available": available,
            "n_partial": partial,
        },
    }
    payload = {"capabilities": {"D-E17": block}, "params": {"min_n": int(min_rows)}}
    return build(
        capability="D-E17",
        intent=INTENT_BOARD,
        answer=answer,
        data=payload,
        quality_block=q,
        trace_id=trace_id,
        visual=build_visual(capability="D-E17", data=payload, quality_block=q),
    )
