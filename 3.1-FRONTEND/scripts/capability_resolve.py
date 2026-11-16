#!/usr/bin/env python3
"""capability_resolve.py — 能力卡片参数装配（SPEC-54 R2）。

把「资产 + 频率 + 区间」装配成能力所需序列后调用 `l1agg` 能力；
只做装载、对齐、warm-up 截断与派生，**不做任何统计重算**。

用法：
  python3 scripts/capability_resolve.py --capability D-A11 \
      --payload '{"symbol":"BTC","benchmark":"US500","days":750}'
  python3 scripts/capability_resolve.py --capability D-E17 --payload '{"assets":["BTC","ETH"]}'

输出单行 JSON：{ok, code, capability_id, data|reason, quality, meta}
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import sqlite3
import sys
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", ".."))
_L1_DIR = os.path.join(_REPO_ROOT, "54-L1架构能力聚合层")
if _L1_DIR not in sys.path:
    sys.path.insert(0, _L1_DIR)

DB_PATH = os.path.join(_REPO_ROOT, "19-数据访问层", "data", "dreambuddy_core.db")
DEFAULT_SYMBOL = "BTC"
DEFAULT_BENCHMARK = "US500"
DEFAULT_DAYS = 750
FREQ_PERIOD = {"1d": 252, "1w": 52, "1M": 12}
MAX_CUSTOM_POINTS = 5000
MAX_ASSETS = 14

PRICE_CAPS = frozenset(
    {
        "D-A07",
        "D-B08",
        "D-B09",
        "D-E02",
        "D-E03",
        "D-E04",
        "D-E07",
        "D-E10",
        "D-E15",
        "D-G08",
        "D-G09",
    }
)
SERIES_SEQ_CAPS = frozenset({"D-G22", "D-J02", "D-J04", "D-J05"})
SERIES_MAP_CAPS = frozenset({"D-E12", "D-G14", "D-G16", "D-G25", "D-J22", "D-J24"})
VALUE_CAPS = frozenset(
    {
        "D-A02",
        "D-A03",
        "D-A04",
        "D-A05",
        "D-A06",
        "D-A08",
        "D-A09",
        "D-A13",
        "D-A15",
    }
)
PAIR_XY_CAPS = frozenset({"D-A11", "D-A12"})
FORWARD_CAPS = frozenset({"D-E08", "D-G19", "D-G20"})
ASSET_LIST_CAPS = frozenset({"D-E16", "D-E17", "D-E18", "D-E19"})


# ------------------------------------------------------------------ 装载
def _load_symbol(symbol: str, days: int) -> Dict[str, float]:
    from l1agg.align import load_leader

    return load_leader(DB_PATH, symbol, days=days)


def _load_metric(sub_category: str, metric: str, as_of: Optional[str] = None) -> Dict[str, float]:
    """读 fred 类序列：同一天重复行取最后一条。"""
    sql = (
        "SELECT date(timestamp,'unixepoch') AS d, metric_value FROM mm_metrics "
        "WHERE sub_category=? AND metric_name=? AND metric_value IS NOT NULL ORDER BY timestamp"
    )
    with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as conn:
        rows = conn.execute(sql, (sub_category, metric)).fetchall()
    out: Dict[str, float] = {}
    for day, value in rows:
        if day and value is not None and (as_of is None or day <= as_of):
            out[str(day)] = float(value)
    return out


def _load_events(symbol: str, days: int) -> List[Dict[str, Any]]:
    """mm_events → 事件列表（按 symbols 过滤；无匹配符号时退回全部宏观事件）。"""
    cutoff = int(time.time()) - int(days) * 86400
    sql = (
        "SELECT event_time, event_type, title, symbols FROM mm_events "
        "WHERE event_time IS NOT NULL AND event_time >= ? ORDER BY event_time"
    )
    with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as conn:
        rows = conn.execute(sql, (cutoff,)).fetchall()
    matched: List[Dict[str, Any]] = []
    others: List[Dict[str, Any]] = []
    for event_time, event_type, title, symbols in rows:
        item = {
            "event_time": datetime.fromtimestamp(int(event_time), tz=timezone.utc).strftime(
                "%Y-%m-%d"
            ),
            "event_type": event_type or "",
            "title": title or "",
        }
        try:
            names = set(json.loads(symbols or "[]"))
        except (TypeError, ValueError):
            names = set()
        (matched if symbol in names or "*" in names else others).append(item)
    return matched or others


def _common_dates(series_map: Dict[str, Dict[str, float]]) -> List[str]:
    if not series_map:
        return []
    return sorted(set.intersection(*(set(s) for s in series_map.values())))


def _column(series: Dict[str, float], dates: Sequence[str]) -> List[Optional[float]]:
    return [series.get(d) for d in dates]


_PANEL_CACHE: Dict[int, Dict[str, Dict[str, float]]] = {}


def _panel_map(days: int) -> Dict[str, Dict[str, float]]:
    """T0 中经 **kwargs 强制 panel 的能力：默认池 {symbol: {date: close}}（同进程缓存）。"""
    if days in _PANEL_CACHE:
        return _PANEL_CACHE[days]
    from l1agg.leader_registry import DEFAULT_POOL

    panel: Dict[str, Dict[str, float]] = {}
    for asset in list(DEFAULT_POOL)[:MAX_ASSETS]:
        try:
            panel[str(asset)] = _load_symbol(str(asset), days)
        except Exception:  # noqa: BLE001 — 单资产失败不阻断面板
            continue
    _PANEL_CACHE[days] = panel
    return panel


PANEL_CAPS = frozenset(
    {
        "D-G01",
        "D-G02",
        "D-G03",
        "D-G04",
        "D-G05",
        "D-G06",
        "D-G10",
        "D-G11",
        "D-G12",
        "D-G13",
        "D-G15",
        "D-G18",
        "D-G24",
    }
)
SERIES_IMPLICIT = frozenset(
    {
        "D-G07",
        "D-J01",
        "D-J03",
        "D-J06",
        "D-J07",
        "D-J08",
        "D-J12",
        "D-J13",
        "D-J14",
        "D-J15",
        "D-J17",
    }
)
DUAL_IMPLICIT = frozenset({"D-J09", "D-J11", "D-J16", "D-J18", "D-E05", "D-E06", "D-E11"})
# 真正零参（内部自取库/报告）
ZERO_ARG_CAPS = frozenset({"D-E20", "D-K02", "D-K03"})
MATRIX_IMPLICIT = frozenset({"D-J20", "D-J21", "D-J23", "D-J29"})
# 需要外部研究数据，无法从价格派生（按 R5 明示，不伪造）
# 需要外部研究数据（非价格派生）：按 R5 明示缺参，不伪造
USER_INPUT_ONLY: Dict[str, Tuple[List[str], str]] = {
    "D-J25": (["coords"], "需要空间坐标（coords）"),
    "D-J26": (["time", "event"], "需要生存时间与事件标记（time/event）"),
    "D-J27": (["time", "event"], "需要可靠性观测（time/event）"),
    "D-J28": (["effects", "se"], "需要效应量与标准误（effects/se）"),
}

_PANEL_LIST_CACHE: Dict[int, Tuple[List[str], Dict[str, List[float]]]] = {}

# ------------------------------------------------------------------ 观测/缓存（R6）
_CACHE_TTL_S = float(os.environ.get("VISUAL_RESOLVE_CACHE_TTL", "60"))
_CACHE_MAX = 256
_RESULT_CACHE: "OrderedDict[str, Tuple[float, Dict[str, Any]]]" = OrderedDict()

MULTI_ASSET_CAPS = SERIES_MAP_CAPS | ASSET_LIST_CAPS | MATRIX_IMPLICIT | frozenset({"D-G21"})


def capability_tier(capability_id: str) -> str:
    """分档口径：多资产（T2b/T6/矩阵）单列，其余为单资产。"""
    return "multi" if capability_id in MULTI_ASSET_CAPS else "single"


def cache_key(capability_id: str, payload: Dict[str, Any]) -> str:
    """缓存键 = 能力 + payload 规范化哈希（含 symbol/freq/benchmark/assets/args）。"""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()
    return f"{capability_id}:{digest}"


def _cache_get(key: str, now: float) -> Optional[Dict[str, Any]]:
    item = _RESULT_CACHE.get(key)
    if item is None:
        return None
    stored_at, value = item
    if now - stored_at > _CACHE_TTL_S:
        _RESULT_CACHE.pop(key, None)
        return None
    _RESULT_CACHE.move_to_end(key)
    return value


def _cache_put(key: str, value: Dict[str, Any], now: float) -> None:
    _RESULT_CACHE[key] = (now, value)
    _RESULT_CACHE.move_to_end(key)
    while len(_RESULT_CACHE) > _CACHE_MAX:
        _RESULT_CACHE.popitem(last=False)


def clear_cache() -> None:
    _RESULT_CACHE.clear()


def _record_metric(capability_id: str, result: Dict[str, Any], cache_hit: bool) -> None:
    try:
        import resolve_metrics  # 同目录；FAIL-OPEN

        resolve_metrics.record(
            capability_id=capability_id,
            tier=capability_tier(capability_id),
            code=str(result.get("code") or "error"),
            elapsed_ms=int((result.get("meta") or {}).get("elapsed_ms") or 0),
            n=int((result.get("quality") or {}).get("n") or 0),
            cache_hit=cache_hit,
        )
    except Exception:  # noqa: BLE001 — 观测不得影响取数
        return


def _panel_lists(days: int) -> Tuple[List[str], Dict[str, List[float]]]:
    """{symbol: [close...]}，按公共日期轴对齐（G 组 panel 要求 list 形态）。"""
    if days not in _PANEL_LIST_CACHE:
        panel = _panel_map(days)
        common = _common_dates(panel)
        _PANEL_LIST_CACHE[days] = (common, {k: _column(v, common) for k, v in panel.items()})
    return _PANEL_LIST_CACHE[days]


def _implicit_args(
    capability_id: str,
    symbol: str,
    benchmark: str,
    days: int,
    close: List[Optional[float]],
    dates: List[str],
) -> Dict[str, Any]:
    """按能力首位置参数名补隐式入参（v0.5 实测契约）。"""
    if capability_id == "D-K01":
        return {"target": symbol}

    if capability_id in ZERO_ARG_CAPS:
        return {}

    if capability_id == "D-E09":
        return {"values": close}

    if capability_id == "D-J10":
        dual = _implicit_args("D-J09", symbol, benchmark, days, close, dates)
        return {"series": dual["x"], "other": dual["y"]}

    if capability_id in DUAL_IMPLICIT:
        other = _load_symbol(benchmark, days)
        common = _common_dates({symbol: dict(zip(dates, close, strict=False)), benchmark: other})  # type: ignore[arg-type]
        cols, _ = trim(_column(dict(zip(dates, close, strict=False)), common), _column(other, common))  # type: ignore[arg-type]
        if cols is None:
            return {"x": [], "y": []}
        return {"x": cols[0], "y": cols[1]}

    if capability_id in MATRIX_IMPLICIT or capability_id == "D-G21":
        common, columns = _panel_lists(days)
        assets = sorted(columns)
        # 横截面收益矩阵（T-1 行 × N 列）：聚类/回归都用收益，不用价格水平
        rows: List[List[float]] = []
        for i in range(1, len(common)):
            row: List[float] = []
            for asset in assets:
                prev, cur = columns[asset][i - 1], columns[asset][i]
                if prev in (None, 0) or cur is None:
                    row = []
                    break
                row.append(float(cur) / float(prev) - 1.0)
            if row:
                rows.append(row)
        if len(rows) < 2:
            return {"X": rows}
        if capability_id in {"D-J23", "D-J29"}:
            return {"X": rows}
        base_index = assets.index(symbol) if symbol in assets else 0
        if capability_id == "D-G21":
            # factor=当期横截面收益，target=次期横截面收益（T×N，N≥2）
            return {"factor": rows[:-1], "target": rows[1:]}
        # J20/J21：X=当期收益矩阵，y=基准资产次期收益（等长）
        return {"X": rows[:-1], "y": [row[base_index] for row in rows[1:]]}

    if capability_id in SERIES_IMPLICIT:
        return {"series": close}

    if capability_id == "D-J19":
        # groups 是「分组后的数值列表」而不是标签（能力层按 g1/g2 展开调 ANOVA）
        values = [float(v) for v in close if v is not None]
        half = max(1, len(values) // 2)
        return {"groups": [values[:half], values[half:]]}

    return {"panel": _panel_lists(days)[1]}


# ------------------------------------------------------------------ 派生
def momentum_20d(close: Sequence[Optional[float]], window: int = 20) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(close)
    for i in range(window, len(close)):
        prev = close[i - window]
        if prev not in (None, 0) and close[i] is not None:
            out[i] = float(close[i]) / float(prev) - 1.0
    return out


def forward_returns(close: Sequence[Optional[float]], horizon: int = 1) -> List[Optional[float]]:
    from l1agg.align import forward_returns as _fr

    return _fr(list(close), horizon)


def rolling_corr(
    left: Sequence[Optional[float]], right: Sequence[Optional[float]], window: int = 60
) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(left)
    for i in range(window - 1, len(left)):
        xs = left[i - window + 1 : i + 1]
        ys = right[i - window + 1 : i + 1]
        if any(v is None for v in xs) or any(v is None for v in ys):
            continue
        mx = sum(xs) / window
        my = sum(ys) / window
        vx = sum((x - mx) ** 2 for x in xs)
        vy = sum((y - my) ** 2 for y in ys)
        if vx <= 0 or vy <= 0:
            continue
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False))
        out[i] = round(cov / math.sqrt(vx * vy), 6)
    return out


def trim(*columns: Sequence[Optional[float]]) -> Tuple[Optional[List[List[float]]], int]:
    """warm-up 截断：取所有列同时有限的区间，返回 (列组, 截断点数)。"""
    if not columns or not columns[0]:
        return None, 0
    start = 0
    end = len(columns[0])
    for col in columns:
        first = next((i for i, v in enumerate(col) if v is not None), None)
        if first is None:
            return None, len(columns[0])
        start = max(start, first)
        last = next((i for i in range(len(col) - 1, -1, -1) if col[i] is not None), -1)
        end = min(end, last + 1)
    if end - start < 1:
        return None, len(columns[0])
    return [[float(c[i]) for i in range(start, end)] for c in columns], start


def _monthly(series: Dict[str, float]) -> Tuple[List[str], Dict[str, float]]:
    """按自然月取最后一条；返回 (月份列表, 月→值)。"""
    month_map: Dict[str, Tuple[str, float]] = {}
    for day in sorted(series):
        month_map[day[:7]] = (day, series[day])
    months = sorted(month_map)
    return months, {m: month_map[m][1] for m in months}


def _cpi_visible_months(months: Sequence[str], as_of: str) -> List[str]:
    """PIT：月 M 的 CPI 在 (M+1) 月 15 日后可见。"""
    visible = []
    for month in months:
        year, mon = int(month[:4]), int(month[5:7])
        rel_year, rel_month = (year, mon + 1) if mon < 12 else (year + 1, 1)
        if f"{rel_year:04d}-{rel_month:02d}-15" <= as_of:
            visible.append(month)
    return visible


# ------------------------------------------------------------------ 装配
def _result(code: str, capability_id: str, **extra: Any) -> Dict[str, Any]:
    return {"ok": code == "ok", "code": code, "capability_id": capability_id, **extra}


def _run(capability_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    from l1agg.capabilities.stats import run_capability

    return run_capability(capability_id, **args)


def _resolve_impl(capability_id: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from l1agg.capabilities import param_schema
    from l1agg.leader_registry import DEFAULT_POOL

    payload = dict(payload or {})
    schema = param_schema.for_capability(capability_id)
    if schema is None:
        return _result("not_found", capability_id, reason=f"unknown capability: {capability_id}")
    if capability_id in param_schema.UNSUPPORTED:
        return _result("unsupported", capability_id, reason=param_schema.UNSUPPORTED[capability_id])

    started = time.monotonic()
    base = {"reason": None, "meta": {"data_provenance": "pool", "warmup_trimmed": 0}}
    symbol = str(payload.get("symbol") or DEFAULT_SYMBOL).strip().upper()
    benchmark = str(payload.get("benchmark") or DEFAULT_BENCHMARK).strip().upper()
    days = int(payload.get("days") or DEFAULT_DAYS)
    freq = str(payload.get("freq") or "1d")
    trimmed = 0
    n_points = 0

    try:
        # ---- 自定义序列（池外）----
        custom = payload.get("custom_series")
        if custom:
            dates = [str(d) for d in (custom.get("dates") or [])]
            values = custom.get("values") or []
            if (
                not dates
                or len(dates) != len(values)
                or len(dates) > MAX_CUSTOM_POINTS
                or dates != sorted(set(dates))
                or any(v is None or not math.isfinite(float(v)) for v in values)
            ):
                return _result("invalid_params", capability_id, reason="custom_series 不满足约束")
            base["meta"]["data_provenance"] = "custom"
            args: Dict[str, Any] = {"prices": [float(v) for v in values]}
            if capability_id in VALUE_CAPS:
                args = {"values": [float(v) for v in values]}
            if capability_id == "D-A01":
                args = {"values": [float(v) for v in values], "dates": dates}
            n_points = len(values)
            envelope = _run(capability_id, args)
            return _ok(capability_id, envelope, n_points, trimmed, started, base["meta"])

        # ---- 宏观对：D-A10 ----
        if capability_id == "D-A10":
            nominal_raw = _load_metric("DGS10", "value")
            cpi_raw = _load_metric("CPIAUCSL", "value")
            nom_months, nom_map = _monthly(nominal_raw)
            cpi_months, cpi_map = _monthly(cpi_raw)
            as_of = max(nominal_raw) if nominal_raw else ""
            visible = set(_cpi_visible_months(cpi_months, as_of))
            common = [m for m in nom_months if m in visible and m in cpi_map]
            if not common:
                return _result(
                    "sample_insufficient", capability_id, reason="DGS10/CPIAUCSL 无公共可见月份"
                )
            args = {"nominal": [nom_map[m] for m in common], "cpi": [cpi_map[m] for m in common]}
            n_points = len(common)
            envelope = _run(capability_id, args)
            quality = _quality(envelope)
            if quality.get("status") == "partial":
                quality.setdefault("degraded_reason", "pit_alignment_insufficient")
            return _ok(
                capability_id, envelope, n_points, trimmed, started, base["meta"], quality=quality
            )

        # ---- 富输入出口：T6（四种形态，见 SPEC-54 R4）----
        if capability_id in ASSET_LIST_CAPS:
            if capability_id == "D-E19":
                block = payload.get("block")
                if not isinstance(block, dict):
                    return _result(
                        "product_missing",
                        capability_id,
                        reason="需要主览图 lights 块（上游产物，卡片直连不重建）",
                    )
                envelope = _run(capability_id, {"block": block})
                return _ok(capability_id, envelope, 0, trimmed, started, base["meta"])

            if capability_id == "D-E18":
                from visual_overview import _load_flows

                flows = _load_flows(days)
                if not flows:
                    return _result("product_missing", capability_id, reason="etf_flow 无可用资金流")
                envelope = _run(capability_id, {"flows": flows})
                return _ok(capability_id, envelope, len(flows), trimmed, started, base["meta"])

            assets = [str(a).strip().upper() for a in (payload.get("assets") or DEFAULT_POOL)]
            assets = list(dict.fromkeys(assets))[:MAX_ASSETS]
            if not assets:
                return _result("missing_args", capability_id, missing_params=["assets"])
            loaded: Dict[str, Dict[str, float]] = {}
            for asset in assets:
                try:
                    loaded[asset] = _load_symbol(asset, days)
                except Exception:  # noqa: BLE001 — 单资产失败不阻断整体
                    continue
            if not loaded:
                return _result("product_missing", capability_id, reason="所选资产均无可用序列")
            if capability_id == "D-E16":
                envelope = _run(capability_id, {"series": loaded})
                return _ok(capability_id, envelope, len(loaded), trimmed, started, base["meta"])
            common = _common_dates(loaded)
            args = {
                "assets": {
                    asset: {"prices": _column(values, common), "dates": common}
                    for asset, values in loaded.items()
                }
            }
            envelope = _run(capability_id, args)
            return _ok(capability_id, envelope, len(common), trimmed, started, base["meta"])

        series = _load_symbol(symbol, days)
        if not series:
            return _result("sample_insufficient", capability_id, reason=f"{symbol} 无可用序列")

        # ---- 双序列 ----
        if capability_id in PAIR_XY_CAPS or capability_id == "D-E14":
            other = _load_symbol(benchmark if capability_id in PAIR_XY_CAPS else benchmark, days)
            dates = _common_dates({symbol: series, benchmark: other})
            left = _column(series, dates)
            right = _column(other, dates)
            trimmed_cols, trimmed = trim(left, right)
            if trimmed_cols is None:
                return _result("sample_insufficient", capability_id, reason="两序列无公共有效区间")
            if capability_id in PAIR_XY_CAPS:
                args = {"x": trimmed_cols[0], "y": trimmed_cols[1]}
            else:
                factor = rolling_corr(left, right, 60)
                cols, more = trim(factor, left)
                if cols is None:
                    return _result("sample_insufficient", capability_id, reason="滚动相关窗口不足")
                trimmed += more
                args = {"factor": cols[0], "prices": cols[1]}
            n_points = len(args["x"] if "x" in args else args["prices"])
            envelope = _run(capability_id, args)
            return _ok(capability_id, envelope, n_points, trimmed, started, base["meta"])

        dates = sorted(series)
        close = _column(series, dates)

        # ---- 同资产派生对 ----
        if capability_id == "D-E01" or capability_id in FORWARD_CAPS:
            factor = momentum_20d(close)
            if capability_id == "D-E01":
                cols, trimmed = trim(factor, close)
                if cols is None:
                    return _result(
                        "sample_insufficient", capability_id, reason="因子 warm-up 后无有效样本"
                    )
                args = {"factor": cols[0], "prices": cols[1]}
            else:
                forward = forward_returns(close, 1)
                cols, trimmed = trim(factor, forward)
                if cols is None:
                    return _result(
                        "sample_insufficient", capability_id, reason="因子/前瞻收益无有效区间"
                    )
                args = {"factor": cols[0], "forward": cols[1]}
            n_points = len(cols[0])
            envelope = _run(capability_id, args)
            return _ok(capability_id, envelope, n_points, trimmed, started, base["meta"])

        # ---- 外部指标：D-J30 ----
        if capability_id == "D-J30":
            indicator = payload.get("indicator")
            if not indicator:
                return _result("missing_args", capability_id, missing_params=["indicator"])
            series_ind = _load_metric(str(indicator), "value")
            if not series_ind:
                return _result("product_missing", capability_id, reason=f"指标 {indicator} 无数据")
            common = _common_dates({symbol: series, indicator: series_ind})
            cols, trimmed = trim(_column(series_ind, common), _column(series, common))
            if cols is None:
                return _result(
                    "sample_insufficient", capability_id, reason="指标与价格无公共有效区间"
                )
            envelope = _run(capability_id, {"indicator": cols[0], "prices": cols[1]})
            return _ok(capability_id, envelope, len(cols[0]), trimmed, started, base["meta"])

        # ---- 取值序列 / 单序列 ----
        if capability_id in VALUE_CAPS:
            args = {"values": close}
            if capability_id == "D-A08":
                args["period"] = FREQ_PERIOD.get(freq, 252)
        elif capability_id == "D-A01":
            args = {"values": close, "dates": dates}
        elif capability_id in PRICE_CAPS:
            args = {"prices": close}
            if capability_id in {"D-E03", "D-E04"}:
                # 日历/事件能力必须带日期轴；E04 另需 mm_events 事件日
                args["dates"] = dates
                args["symbol"] = symbol
                if capability_id == "D-E04":
                    events = _load_events(symbol, days)
                    if not events:
                        return _result(
                            "product_missing", capability_id, reason="mm_events 无可用事件"
                        )
                    args["events"] = events
        elif capability_id in SERIES_SEQ_CAPS:
            args = {"series": close}
            if capability_id != "D-G22":
                args["dates"] = dates
                args["symbol"] = symbol
        elif capability_id in SERIES_MAP_CAPS:
            assets = [str(a).strip().upper() for a in (payload.get("assets") or DEFAULT_POOL)][
                :MAX_ASSETS
            ]
            loaded = {}
            for asset in assets:
                try:
                    loaded[asset] = _load_symbol(asset, days)
                except Exception:  # noqa: BLE001 — 单资产失败不阻断整体
                    continue
            if not loaded:
                return _result("product_missing", capability_id, reason="多资产均无可用序列")
            if capability_id == "D-G16":
                weights = payload.get("weights")
                if weights is not None:
                    if (
                        len(weights) != len(loaded)
                        or abs(sum(float(w) for w in weights) - 1.0) > 1e-6
                    ):
                        return _result(
                            "invalid_params", capability_id, reason="weights 长度或总和不符合约束"
                        )
            common = _common_dates(loaded)
            args = {"series": {k: _column(v, common) for k, v in loaded.items()}}
            if capability_id != "D-G25":
                args["dates"] = common
            if capability_id == "D-G16" and payload.get("weights") is not None:
                args["weights"] = [float(w) for w in payload["weights"]]
            n_points = len(common)
            envelope = _run(capability_id, args)
            return _ok(capability_id, envelope, n_points, trimmed, started, base["meta"])
        else:
            # T0 隐式入参（v0.5 实测：首位置参数名即 kwarg 名，可按契约直接补）
            unknown = [a["name"] for a in schema["args"] if a["required"]]
            if unknown:
                return _result("missing_args", capability_id, missing_params=unknown)
            if capability_id in USER_INPUT_ONLY:
                missing_params, reason = USER_INPUT_ONLY[capability_id]
                return _result(
                    "missing_args",
                    capability_id,
                    missing_params=list(missing_params),
                    reason=reason,
                )
            try:
                envelope = _run(
                    capability_id,
                    _implicit_args(capability_id, symbol, benchmark, days, close, dates),
                )
            except (TypeError, ValueError) as exc:
                return _result("invalid_params", capability_id, reason=str(exc))
            return _ok(capability_id, envelope, 0, trimmed, started, base["meta"])

        n_points = len(close)
        envelope = _run(capability_id, args)
        return _ok(capability_id, envelope, n_points, trimmed, started, base["meta"])

    except TypeError as exc:
        return _result("missing_args", capability_id, reason=str(exc))
    except Exception as exc:  # noqa: BLE001
        return _result("error", capability_id, reason=f"{type(exc).__name__}: {exc}")


def resolve(capability_id: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """resolve 入口（SPEC-54 R6）：60s 结果缓存 + 逐次观测。

    - 只缓存 `code=ok`：失败结果（缺产物/样本不足）允许下次立即重试，避免缓存故障。
    - 命中缓存时 `meta.cache=hit`，并按命中耗时记录观测（目标 ≤3s）。
    """
    started = time.monotonic()
    normalized = dict(payload or {})
    key = cache_key(capability_id, normalized)
    now = time.monotonic()

    cached = _cache_get(key, now)
    if cached is not None:
        result = copy.deepcopy(cached)
        meta = result.setdefault("meta", {})
        meta["cache"] = "hit"
        meta["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        _record_metric(capability_id, result, cache_hit=True)
        return result

    result = _resolve_impl(capability_id, normalized)
    meta = result.setdefault("meta", {})
    meta["cache"] = "miss"
    if result.get("code") == "ok":
        _cache_put(key, copy.deepcopy(result), now)
    _record_metric(capability_id, result, cache_hit=False)
    return result


def _quality(envelope: Dict[str, Any]) -> Dict[str, Any]:
    quality = envelope.get("quality")
    return dict(quality) if isinstance(quality, dict) else {}


def _ok(
    capability_id: str,
    envelope: Dict[str, Any],
    n_points: int,
    trimmed: int,
    started: float,
    meta: Dict[str, Any],
    quality: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    quality = quality if quality is not None else _quality(envelope)
    degraded = bool(envelope.get("degraded")) or quality.get("status") == "partial"
    code = "ok"
    if envelope.get("ok") is False:
        reason = str((quality or {}).get("degraded_reason") or envelope.get("reason") or "")
        text = reason + " " + str(envelope.get("answer") or "")
        # 上游产物未生成 → product_missing；门禁/样本不足 → sample_insufficient
        missing_product = ("尚未生成", "未生成", "无可用", "无数据", "未提供", "不存在")
        if any(key in reason for key in missing_product):
            code = "product_missing"
        elif ("<" in text) or ("门禁" in text) or ("不足" in text) or ("样本" in text):
            code = "sample_insufficient"
        else:
            code = "error"
    return {
        "ok": code == "ok",
        "code": code,
        "capability_id": capability_id,
        "data": envelope,
        "quality": {**quality, "n": n_points, "degraded": degraded},
        "meta": {
            **meta,
            "warmup_trimmed": trimmed,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        },
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="能力卡片参数装配器")
    parser.add_argument("--capability", required=True)
    parser.add_argument("--payload", default="{}")
    parser.add_argument("--payload-file", dest="payload_file", default="")
    args = parser.parse_args(argv)

    raw = "{}"
    if args.payload_file:
        with open(args.payload_file, "r", encoding="utf-8") as handle:
            raw = handle.read()
    elif args.payload:
        raw = args.payload
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("payload must be object")
    except (json.JSONDecodeError, ValueError) as exc:
        result = _result("invalid_params", args.capability, reason=f"payload: {exc}")
    else:
        try:
            result = resolve(args.capability, payload)
        except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
            result = _result("error", args.capability, reason=f"{type(exc).__name__}: {exc}")

    sys.stdout.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
