# -*- coding: utf-8 -*-
"""L1-D 纸面回放（SPEC-54 §4.7 / L1D-05）。

流程：逐根收盘 → D-E15 统计事实 → `rule_inputs` → 动态权重（可选）→
`direction_rule.decide` → `exit_rule.evaluate` → 纸面账本。**下一根收盘成交**
（避免同根收盘信息的当日执行偏差）。

判定口径：
  - 只做纸面，不触达 22 与任何交易所；`notional_usdt` 仅用于换手统计；
  - `turnover = 2 × 开仓次数 / 参与根数`（每次开平各算一次名义额）；
  - 同一输入 → 同一 `replay_key`（signals 规范哈希），即「同一 `as_of` 可重放」；
  - `persist_signals()` 写 `trading.db`，`UNIQUE(as_of,symbol,rule_version)` 保证重放不重复落库。

动态权重（§4.13 / L1D-08 切换）：`weights_mode=None` 时按
`weight_switch.resolve_mode()` 取开关（默认 `off`，行为与本文件引入前一致）；
`shadow` 只算不注入，`on` 过等权否决门后注入 `decide`。轴值一律用**单位权重**
（`axis_weights=1`）计算，避免注入后的加权分数反过来污染 IC 估计。
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import sqlite3
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..capabilities import stats
from ..direction_rule import DEFAULT_PARAMS, _sign, decide, params_hash
from . import exit_rule, rule_inputs, weight_switch
from .store import append_signal

DEFAULT_WARMUP = 250


def _date_text(value: Any, fallback: int) -> str:
    if isinstance(value, _dt.datetime):
        return value.date().isoformat()
    if isinstance(value, _dt.date):
        return value.isoformat()
    if value is None:
        return f"bar-{fallback}"
    return str(value)[:19]


def _slope_signs(slope_table: Optional[Sequence[Mapping[str, Any]]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for row in slope_table or []:
        window = row.get("window")
        slope = row.get("slope")
        out[str(window)] = _sign(slope)
    return out


def _adx_band(adx14: Optional[float]) -> Optional[str]:
    if adx14 is None:
        return None
    value = float(adx14)
    if value < 20.0:
        return "lt20"
    return "20to25" if value < 25.0 else "gt25"


def replay(
    prices: Sequence[Any],
    *,
    symbol: str,
    dates: Optional[Sequence[Any]] = None,
    highs: Optional[Sequence[Any]] = None,
    lows: Optional[Sequence[Any]] = None,
    warmup: int = DEFAULT_WARMUP,
    notional_usdt: float = 1000.0,
    params: Optional[Mapping[str, Any]] = None,
    weights_mode: Optional[str] = None,
    weight_state: Optional[Mapping[str, Any]] = None,
    weights_locked: bool = False,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """3 个月级回放：返回 signals / trades / metrics / weights / replay_key。

    `db_path` 仅在 `weight_state` 缺省时用于恢复上期权重（跨运行不丢周度冻结）。
    """
    px = [float(v) for v in prices]
    if len(px) < warmup + 2:
        raise ValueError(f"样本不足以回放：需要 ≥{warmup + 2} 根，实际 {len(px)}")
    p = dict(params or DEFAULT_PARAMS)
    ds = list(dates) if dates is not None else []
    hs = [float(v) for v in highs] if highs is not None else None
    ls = [float(v) for v in lows] if lows is not None else None

    mode = weight_switch.resolve_mode(weights_mode)
    track_weights = mode != "off"
    state = dict(weight_state or {})
    if not state and track_weights and db_path is not None:
        state = weight_switch.load_state(symbol, db_path)
    prev_w: Optional[Dict[str, float]] = state.get("previous_weights")
    last_eff: Optional[str] = state.get("last_effective_date")
    prev_fb: Optional[bool] = state.get("weight_fallback")
    unit_params = dict(p)
    unit_params["axis_weights"] = {
        "trend": 1.0,
        "adx": 1.0,
        "inertia": 1.0,
        "coherence": 1.0,
        "gap": 0.0,
    }
    axis_hist: Dict[str, List[float]] = {axis: [] for axis in weight_switch.AXES}
    fwd_hist: List[float] = []
    pending_units: Optional[Dict[str, float]] = None
    n_updates = n_frozen = n_fallback = 0
    last_weights: Dict[str, Any] = {}

    signals: List[Dict[str, Any]] = []
    trades: List[Dict[str, Any]] = []
    position = 0
    entry_px = 0.0
    entry_i = 0
    entry_as_of = ""
    low_bars = 0
    pending: Optional[Dict[str, Any]] = None
    n_entries = 0

    def _close(i: int, reason: str) -> None:
        nonlocal position, entry_px
        ret = (px[i] / entry_px - 1.0) * position if entry_px else 0.0
        trades.append(
            {
                "side": "long" if position > 0 else "short",
                "entry_as_of": entry_as_of,
                "exit_as_of": _date_text(ds[i] if i < len(ds) else None, i),
                "entry_px": round(entry_px, 8),
                "exit_px": round(px[i], 8),
                "ret": round(ret, 8),
                "reason": reason,
            }
        )
        position = 0
        entry_px = 0.0

    for i in range(warmup, len(px)):
        window_px = px[: i + 1]
        window_ds = ds[: i + 1] if ds else None
        window_highs = hs[: i + 1] if hs is not None else None
        window_lows = ls[: i + 1] if ls is not None else None
        env = stats.trend(window_px, dates=window_ds, highs=window_highs, lows=window_lows)
        caps = (env.get("data") or {}).get("capabilities") or {}
        inputs = rule_inputs.build_inputs(caps)
        as_of = _date_text(ds[i] if i < len(ds) else None, i)

        # 0) 动态权重：单位轴值（不随注入权重变化）+ 已实现标签 → 解析本期权重
        units: Optional[Dict[str, float]] = None
        if track_weights:
            units = dict(decide(inputs, unit_params, as_of=as_of, symbol=symbol)["axes"])
        if pending_units is not None:
            fwd_hist.append(px[i] / px[i - 1] - 1.0)
            for axis in weight_switch.AXES:
                axis_hist[axis].append(float(pending_units.get(axis, 0.0)))
        excess = None
        if track_weights and prev_w is not None and fwd_hist:
            excess = weight_switch.oos_excess_series(axis_hist, fwd_hist, prev_w)
        resolved = weight_switch.resolve_weights(
            axis_hist if track_weights else None,
            fwd_hist if track_weights else None,
            mode=mode,
            as_of=as_of,
            previous_weights=prev_w,
            last_effective_date=last_eff,
            replay_locked=weights_locked,
            oos_excess=excess,
            previous_fallback=prev_fb,
        )
        record = decide(
            inputs,
            weight_switch.apply_to_params(p, resolved),
            as_of=as_of,
            symbol=symbol,
        )
        recorded = weight_switch.recorded_weights(resolved)
        if track_weights:
            n_updates += 0 if resolved["frozen"] else 1
            n_frozen += 1 if resolved["frozen"] else 0
            n_fallback += 1 if resolved["weight_fallback"] else 0
            if not resolved["frozen"]:
                prev_w = dict(recorded["weights"])
                last_eff = resolved["weights_effective_date"]
                prev_fb = bool(resolved["weight_fallback"])
        pending_units = units
        last_weights = {
            "axis_weights": recorded["axis_weights"],
            "weights_hash": recorded["weights_hash"],
            "weights_version": resolved["weights_version"],
            "weights_effective_date": resolved["weights_effective_date"],
            "weight_fallback": resolved["weight_fallback"],
            "weight_sources": resolved["weight_sources"],
            "rebalance": resolved["rebalance"],
            "frozen": resolved["frozen"],
        }
        adx14 = ((caps.get("D-E15") or {}).get("adx") or {}).get("adx")

        # 1) 上一根收盘产生的动作，在本根收盘执行
        if pending is not None:
            action = pending["action"]
            if action in ("close", "flip") and position != 0:
                _close(i, pending.get("reason") or "flip")
            if action in ("open", "flip"):
                position = int(pending["direction"])
                entry_px = px[i]
                entry_i = i
                entry_as_of = _date_text(ds[i] if i < len(ds) else None, i)
                n_entries += 1
                low_bars = 0
            pending = None

        # 2) 用本根 signal 决定下一根的动作
        if position != 0:
            outcome = exit_rule.evaluate(
                position,
                total=record["total"],
                duration_bars=i - entry_i,
                low_bars=low_bars,
                adx14=adx14,
                ema_order=record["ema_order"],
                params=p,
            )
            low_bars = outcome["low_bars"]
            if outcome["exit"]:
                pending = {"action": "close", "reason": outcome["reason"]}
            elif _sign(record["direction"]) == -position:
                pending = {"action": "flip", "direction": record["direction"]}
        elif record["direction"] != 0:
            pending = {"action": "open", "direction": record["direction"]}

        flags = list(record["flags"])
        if track_weights:
            flags = sorted(set(flags + [f"dynamic_weights_{mode}"] + list(resolved["flags"])))
        signals.append(
            {
                "as_of": as_of,
                "symbol": symbol,
                "direction": record["direction"],
                "strength": record["strength"],
                "band": record["band"],
                "total": record["total"],
                "ema_order": record["ema_order"],
                "flags": flags,
                "slope_signs": _slope_signs(inputs.get("slope_table")),
                "adx_band": _adx_band(adx14),
                "adx14": adx14,
                "rule_version": record["rule_version"],
                "params_hash": record["params_hash"],
                "seasonality": record["seasonality"],
                "inputs_snapshot": record["inputs_snapshot"],
                "weights_version": resolved["weights_version"],
                "weights_hash": recorded["weights_hash"],
                "weights_effective_date": resolved["weights_effective_date"],
                "axis_weights": recorded["axis_weights"],
                "weight_sources": resolved["weight_sources"],
            }
        )

    closed = [t for t in trades if t["ret"] is not None]
    wins = [t for t in closed if t["ret"] > 0]
    bars = len(signals)
    metrics = {
        "bars": bars,
        "n_signals": len(signals),
        "n_entries": n_entries,
        "n_closed": len(closed),
        "n_open": 1 if position != 0 else 0,
        "n_long": sum(1 for t in closed if t["side"] == "long"),
        "n_short": sum(1 for t in closed if t["side"] == "short"),
        "wins": len(wins),
        "win_rate": round(len(wins) / len(closed), 6) if closed else None,
        "avg_ret": round(sum(t["ret"] for t in closed) / len(closed), 8) if closed else None,
        "cum_ret": round(sum(t["ret"] for t in closed), 8),
        "turnover": round(2.0 * n_entries / bars, 6) if bars else 0.0,
        "notional_usdt": float(notional_usdt),
    }
    payload = {
        "symbol": symbol,
        "bars": bars,
        "signals": signals,
        "trades": trades,
        "metrics": metrics,
        "params_hash": params_hash(p),
        "rule_version": p["version"],
        "weights": {
            "mode": mode,
            "rebalance": last_weights.get("rebalance"),
            "axis_weights": last_weights.get("axis_weights"),
            "weights_hash": last_weights.get("weights_hash"),
            "weights_effective_date": last_weights.get("weights_effective_date"),
            "n_updates": n_updates,
            "n_frozen": n_frozen,
            "n_fallback": n_fallback,
        },
    }
    payload["replay_key"] = hashlib.sha256(
        json.dumps(
            [
                {k: s[k] for k in ("as_of", "direction", "strength", "total", "params_hash")}
                for s in signals
            ],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return payload


def persist_signals(result: Mapping[str, Any], db_path: Optional[str] = None) -> Dict[str, int]:
    """把回放信号写入 `trading.db`；重复 `as_of` 只跳过不报错（可断点重放）。"""
    inserted = duplicates = 0
    for row in result.get("signals") or []:
        try:
            append_signal(
                {
                    "as_of": row["as_of"],
                    "symbol": row["symbol"],
                    "rule_version": row["rule_version"],
                    "params_hash": row["params_hash"],
                    "direction": row["direction"],
                    "strength": row["strength"],
                    "slope_signs": row.get("slope_signs"),
                    "adx_band": row.get("adx_band"),
                    "ema_order": row.get("ema_order"),
                    "flags": row.get("flags"),
                    "seasonality": row.get("seasonality"),
                    "inputs_snapshot": row.get("inputs_snapshot"),
                    "weights_version": row.get("weights_version"),
                    "weights_hash": row.get("weights_hash"),
                    "weights_effective_date": row.get("weights_effective_date"),
                    "axis_weights": row.get("axis_weights"),
                    "weight_sources": row.get("weight_sources"),
                },
                db_path,
            )
            inserted += 1
        except sqlite3.IntegrityError:
            duplicates += 1
    return {"inserted": inserted, "duplicates": duplicates}


__all__ = ["DEFAULT_WARMUP", "persist_signals", "replay"]
