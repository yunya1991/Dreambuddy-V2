# -*- coding: utf-8 -*-
"""L1-C 批量回放 + 按类复盘表（SPEC-54-L1交易层 §6.1 / §6.2，P1-2）。

边界（硬约束）：
  - 批量**只做逐标的回放与汇总**，不合并成组合信号、不产 `signal`（§6.1）；
  - 同一 `(标的, iso_week)` 内权重口径冻结（B-LT10，由 `replay`/`weight_switch` 保证），
    本模块不另算权重，只汇总 `replay_key`；
  - 复盘表按 40 层 `class` 聚合（SSoT = `leader_registry.class_of`），只读 `comparison`
    这类内部记录，**不外发**（ADR-V14）；本模块不建信封、不进 public `data`；
  - 失败隔离：单标的样本不足只标 `skipped`，不中断整批；不伪造指标；
  - 不读生产库、不写库（`db_path` 缺省时纯内存；传入时只读 `comparison`）。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from ..direction_rule import DEFAULT_PARAMS, params_hash
from ..leader_registry import class_of as _class_of
from . import comparison as comparison_mod
from . import weight_switch
from .paper_replay import DEFAULT_WARMUP, replay

BATCH_METRIC_KEYS: Sequence[str] = (
    "symbol",
    "bars",
    "n_entries",
    "win_rate",
    "avg_ret",
    "cum_ret",
    "turnover",
)

# §6.2 复盘表固定 6 列（顺序不可变）
REVIEW_COLUMNS: List[Dict[str, str]] = [
    {"key": "class", "label": "类别", "type": "string"},
    {"key": "n", "label": "样本数", "type": "number"},
    {"key": "win_rate", "label": "胜率", "type": "percent"},
    {"key": "avg_ret", "label": "平均收益", "type": "percent"},
    {"key": "avg_hold_bars", "label": "平均持有根数", "type": "number"},
    {"key": "scored_at", "label": "打分时间", "type": "date"},
]

_UNBOUND = "unbound"


def _last_date(dates: Optional[Sequence[Any]]) -> Optional[str]:
    if not dates:
        return None
    value = dates[-1]
    return None if value is None else str(value)


def _symbol_class(symbol: str) -> str:
    return _class_of(symbol) or _UNBOUND


def batch_replay(
    series: Mapping[str, Mapping[str, Any]],
    *,
    warmup: int = DEFAULT_WARMUP,
    notional_usdt: float = 1000.0,
    params: Optional[Mapping[str, Any]] = None,
    weights_mode: Optional[str] = None,
    db_path: Optional[str] = None,
    risk: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """逐标的回放并汇总 `batch_metrics`（不合并组合信号）。"""
    rows: List[Dict[str, Any]] = []
    replay_keys: Dict[str, str] = {}
    mode = weight_switch.resolve_mode(weights_mode)
    for symbol, payload in dict(series or {}).items():
        data = dict(payload or {})
        try:
            result = replay(
                data.get("prices") or (),
                symbol=str(symbol),
                dates=data.get("dates"),
                highs=data.get("highs"),
                lows=data.get("lows"),
                warmup=int(data.get("warmup") or warmup),
                notional_usdt=notional_usdt,
                params=params,
                weights_mode=mode,
                db_path=db_path,
            )
        except (ValueError, TypeError, KeyError) as exc:
            rows.append(
                {
                    "symbol": str(symbol),
                    "class": _symbol_class(str(symbol)),
                    "as_of": _last_date(data.get("dates")),
                    "status": "skipped",
                    "reason": str(exc)[:160],
                    "bars": None,
                    "n_entries": None,
                    "win_rate": None,
                    "avg_ret": None,
                    "cum_ret": None,
                    "turnover": None,
                    "replay_key": None,
                }
            )
            continue

        metrics = dict(result.get("metrics") or {})
        replay_keys[str(symbol)] = str(result.get("replay_key") or "")
        rows.append(
            {
                "symbol": str(symbol),
                "class": _symbol_class(str(symbol)),
                "as_of": _last_date(data.get("dates")),
                "status": "ok",
                "reason": None,
                "bars": metrics.get("bars"),
                "n_entries": metrics.get("n_entries"),
                "win_rate": metrics.get("win_rate"),
                "avg_ret": metrics.get("avg_ret"),
                "cum_ret": metrics.get("cum_ret"),
                "turnover": metrics.get("turnover"),
                "replay_key": result.get("replay_key"),
            }
        )

    n_ok = sum(1 for row in rows if row["status"] == "ok")
    flags: List[str] = ["no_portfolio_signal"]
    if n_ok != len(rows):
        flags.append(f"batch_skipped:{len(rows) - n_ok}")
    if mode != "off":
        flags.append(f"weights_mode_{mode}")
    return {
        "capability": "D-BATCH",
        "batch_metrics": rows,
        "n_symbols": len(rows),
        "n_ok": n_ok,
        "n_skipped": len(rows) - n_ok,
        "replay_keys": replay_keys,
        "params_hash": params_hash(dict(params or DEFAULT_PARAMS)),
        "weights_mode": mode,
        "warmup": int(warmup),
        "risk": dict(risk or {}),
        "flags": flags,
    }


def review_table(
    rows: Optional[Sequence[Mapping[str, Any]]] = None,
    *,
    db_path: Optional[str] = None,
    limit: int = 500,
    class_resolver: Optional[Callable[[str], Optional[str]]] = None,
) -> Dict[str, Any]:
    """按 `class` 聚合 `comparison` → 复盘表（6 列固定；未打分行不计入分母）。"""
    source = (
        list(rows) if rows is not None else comparison_mod.list_comparisons(db_path, limit=limit)
    )
    resolve = class_resolver or _symbol_class

    buckets: Dict[str, Dict[str, Any]] = {}
    n_pending = 0
    hold_bars_missing = 0
    for row in source:
        realized = row.get("realized_ret")
        if realized is None:
            n_pending += 1
            continue
        try:
            ret = float(realized)
        except (TypeError, ValueError):
            n_pending += 1
            continue
        name = resolve(str(row.get("symbol") or "")) or _UNBOUND
        bucket = buckets.setdefault(
            name,
            {"n": 0, "wins": 0, "sum_ret": 0.0, "hold": [], "scored_at": None},
        )
        bucket["n"] += 1
        bucket["wins"] += 1 if ret > 0 else 0
        bucket["sum_ret"] += ret
        hold = row.get("hold_bars")
        if hold is None:
            hold_bars_missing += 1
        else:
            try:
                bucket["hold"].append(float(hold))
            except (TypeError, ValueError):
                hold_bars_missing += 1
        scored_at = row.get("scored_at")
        if scored_at is not None and (
            bucket["scored_at"] is None or str(scored_at) > str(bucket["scored_at"])
        ):
            bucket["scored_at"] = str(scored_at)

    out: List[Dict[str, Any]] = []
    for name, bucket in buckets.items():
        average = bucket["sum_ret"] / bucket["n"]
        out.append(
            {
                "class": name,
                "n": bucket["n"],
                "win_rate": round(bucket["wins"] / bucket["n"], 6),
                "avg_ret": round(average, 8),
                "avg_hold_bars": (
                    round(sum(bucket["hold"]) / len(bucket["hold"]), 6) if bucket["hold"] else None
                ),
                "scored_at": bucket["scored_at"],
            }
        )
    out.sort(key=lambda item: (-item["n"], item["class"]))
    flags: List[str] = []
    if n_pending:
        flags.append(f"unscored_rows:{n_pending}")
    if hold_bars_missing:
        flags.append(f"hold_bars_missing:{hold_bars_missing}")
    return {
        "capability": "D-REVIEW",
        "columns": [dict(col) for col in REVIEW_COLUMNS],
        "rows": out,
        "n_rows": len(out),
        "n_scored": sum(item["n"] for item in out),
        "n_pending": n_pending,
        "hold_bars_missing": hold_bars_missing,
        "flags": flags,
    }


__all__ = [
    "BATCH_METRIC_KEYS",
    "REVIEW_COLUMNS",
    "batch_replay",
    "review_table",
]
