# -*- coding: utf-8 -*-
"""动态权重的实盘切换层（SPEC-54 §4.13 / ADR-V18/V19 / L1D-08 切换）。

三档灰度（**默认 off**，非法值 fail-closed 直接抛，不静默降级）：

  off     不计算动态权重；`decide` 用静态先验 40/25/20/15，与引入动态权重前**字节一致**
  shadow  计算并落库（`weights_hash` / `axis_weights` / `weight_sources`），但**不注入**
          `decide`：在不改变交易行为的前提下积累「动态 vs 静态」对照证据
  on      计算并注入 `decide`；等权否决门未过（`weight_fallback=true`）时**不注入**，
          继续用静态先验并记录旗标——生产基线是静态先验，证据不足时不得改权

切换优先级：调用方显式参数 > 环境变量 `L1_DYNAMIC_WEIGHTS` > `config/weights.yaml` > off。

跨运行状态：`previous_weights` / `last_effective_date` 从 `trading.db.signal` 中该
`symbol` 最新一条带权重的记录读取（`axis_weights` 归一化后作为上期权重）；同一 ISO 周内
权重完全冻结（`W-MON` 再平衡），与 `weights.dynamic_weights` 的冻结口径一致。

`oos_excess_series` 用**已实现标签**构造等权对照：逐样本
`excess_j = fwd_j × Σ_i (w_prev_i − 0.25) × unit_axis_i,j`，即「上期权重相对等权的
加权分数 × 已实现收益」。只喂 `weights.oos_gate`，不参与打分，也不引入任何前视。
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Mapping, Optional, Sequence

import yaml

from . import store, weights

MODES = ("off", "shadow", "on")
DEFAULT_MODE = "off"
SWITCH_ENV = "L1_DYNAMIC_WEIGHTS"
CONFIG_FILE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "config", "weights.yaml")
)
DEFAULT_WINDOW = weights.WINDOW
DEFAULT_MIN_LABELS = weights.MIN_OBS
AXES = weights.AXES
_CONFIG_CACHE: Dict[Any, Dict[str, Any]] = {}


class WeightSwitchError(ValueError):
    """开关/配置取值非法（fail-closed）。"""


# ---------------- 开关 ----------------


def normalize_mode(value: Any) -> str:
    """归一化模式名；未知取值直接抛 `WeightSwitchError`。"""
    mode = str(value).strip().lower()
    if mode not in MODES:
        raise WeightSwitchError(f"未知权重模式 {value!r}，允许 {list(MODES)}")
    return mode


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """读 `config/weights.yaml`；文件缺失回落 off（缺省即关闭），取值非法抛错。

    按 `(路径, mtime)` 缓存：回放主循环每根都要取开关，不能每根重读 YAML。
    """
    target = path or CONFIG_FILE
    cfg: Dict[str, Any] = {
        "mode": DEFAULT_MODE,
        "window": DEFAULT_WINDOW,
        "min_labels": DEFAULT_MIN_LABELS,
    }
    try:
        stamp = os.path.getmtime(target)
    except OSError:
        return cfg
    cached = _CONFIG_CACHE.get((target, stamp))
    if cached is not None:
        return dict(cached)
    with open(target, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    block = raw.get("weights", raw) if isinstance(raw, Mapping) else {}
    if not isinstance(block, Mapping):
        raise WeightSwitchError("weights 配置必须是映射")
    if block.get("mode") is not None:
        cfg["mode"] = normalize_mode(block["mode"])
    if block.get("window") is not None:
        cfg["window"] = max(1, int(block["window"]))
    if block.get("min_labels") is not None:
        cfg["min_labels"] = max(3, int(block["min_labels"]))
    _CONFIG_CACHE[(target, stamp)] = dict(cfg)
    return cfg


def resolve_mode(
    explicit: Optional[str] = None,
    *,
    environ: Optional[Mapping[str, str]] = None,
    config_path: Optional[str] = None,
) -> str:
    """显式参数 > 环境变量 > 配置文件 > off。"""
    if explicit is not None:
        return normalize_mode(explicit)
    env = (environ if environ is not None else os.environ).get(SWITCH_ENV)
    if env:
        return normalize_mode(env)
    return load_config(config_path)["mode"]


# ---------------- 跨运行状态 ----------------


def load_state(symbol: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """从 `signal` 表恢复上期权重与生效日；无记录/库不存在 → `source="none"`。"""
    out: Dict[str, Any] = {
        "previous_weights": None,
        "last_effective_date": None,
        "weights_version": None,
        "weight_fallback": False,
        "source": "none",
    }
    target = store.resolve_db(db_path)
    if not os.path.exists(target):
        return out
    conn = store.connect(target)
    try:
        row = conn.execute(
            "SELECT axis_weights, weights_effective_date, weights_version, flags FROM signal "
            "WHERE symbol = ? AND axis_weights IS NOT NULL "
            "ORDER BY as_of DESC, id DESC LIMIT 1",
            (str(symbol),),
        ).fetchone()
    except sqlite3.OperationalError:
        return out
    finally:
        conn.close()
    if row is None:
        return out
    raw = row["axis_weights"]
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        flags = json.loads(row["flags"]) if isinstance(row["flags"], str) else row["flags"]
    except (TypeError, json.JSONDecodeError):
        return out
    if not isinstance(parsed, Mapping):
        return out
    prior = {axis: float(parsed[axis]) for axis in AXES if parsed.get(axis) is not None}
    total = sum(prior.values())
    if len(prior) != len(AXES) or total <= 0:
        return out
    out.update(
        previous_weights={axis: prior[axis] / total for axis in AXES},
        last_effective_date=row["weights_effective_date"],
        weights_version=row["weights_version"],
        weight_fallback="weight_fallback" in (flags or []),
        source="db",
    )
    return out


# ---------------- 等权对照 ----------------


def oos_excess_series(
    axis_values: Mapping[str, Sequence[float]],
    forward_returns: Sequence[float],
    previous_weights: Optional[Mapping[str, float]],
    *,
    window: int = DEFAULT_WINDOW,
) -> List[float]:
    """相对等权的逐样本超额（只用已实现标签）；`previous_weights` 缺省 → 空列表。"""
    if not previous_weights:
        return []
    fwd = [float(v) for v in (forward_returns or [])]
    if not fwd:
        return []
    lengths = [len(fwd)] + [
        len(axis_values.get(axis) or []) for axis in AXES if axis_values.get(axis)
    ]
    size = min(lengths)
    if size <= 0:
        return []
    start = max(0, size - int(window))
    delta = {
        axis: float(previous_weights.get(axis, weights.EQUAL_WEIGHTS[axis]))
        - weights.EQUAL_WEIGHTS[axis]
        for axis in AXES
    }
    out: List[float] = []
    for j in range(start, size):
        score = sum(
            delta[axis] * float((axis_values.get(axis) or [0.0] * size)[j]) for axis in AXES
        )
        out.append(round(score * fwd[j], 10))
    return out


# ---------------- 解析与注入 ----------------


def resolve_weights(
    axis_values: Optional[Mapping[str, Sequence[float]]] = None,
    forward_returns: Optional[Sequence[float]] = None,
    *,
    mode: Optional[str] = None,
    as_of: Optional[str] = None,
    previous_weights: Optional[Mapping[str, float]] = None,
    last_effective_date: Optional[str] = None,
    replay_locked: bool = False,
    uncertainty: Optional[float] = None,
    oos_excess: Optional[Sequence[float]] = None,
    previous_fallback: Optional[bool] = None,
    window: Optional[int] = None,
    min_obs: Optional[int] = None,
    config_path: Optional[str] = None,
) -> Dict[str, Any]:
    """按开关解析本次权重；输出在 `weights.dynamic_weights` 之上补 `mode` / `inject`。

    冻结周（同 ISO 周）连**注入判定**一起冻结：`previous_fallback` 为上周再平衡的
    否决结果，避免「上周被等权否决、本周冻结却按优化权重注入」的错位。
    """
    cfg = load_config(config_path)
    resolved_mode = resolve_mode(mode, config_path=config_path)
    enabled = resolved_mode in ("shadow", "on")
    result = weights.dynamic_weights(
        axis_values,
        forward_returns,
        enabled=enabled,
        oos_excess=oos_excess,
        previous_weights=previous_weights,
        window=int(window or cfg["window"]),
        min_obs=int(min_obs or cfg["min_labels"]),
        as_of=as_of,
        last_effective_date=last_effective_date,
        replay_locked=replay_locked,
        uncertainty=uncertainty,
    )
    inject = resolved_mode == "on" and not result["weight_fallback"]
    if result["frozen"] and previous_fallback is not None:
        result["weight_fallback"] = bool(previous_fallback)
        if result["weight_fallback"]:
            result["flags"] = sorted(set(list(result["flags"]) + ["weight_fallback"]))
        inject = resolved_mode == "on" and not result["weight_fallback"]
    result["mode"] = resolved_mode
    result["inject"] = inject
    result["inject_axis_weights"] = (
        {axis: float(result["weights"][axis]) for axis in AXES} if inject else None
    )
    return result


def apply_to_params(
    params: Optional[Mapping[str, Any]], resolved: Mapping[str, Any]
) -> Dict[str, Any]:
    """把解析结果注入 `direction_rule` 参数（`params_hash` 随之变化，可回放）。"""
    base = dict(params or {})
    injected = resolved.get("inject_axis_weights")
    if resolved.get("inject") and isinstance(injected, Mapping):
        base["axis_weights"] = {axis: float(injected[axis]) for axis in AXES}
    return base


def recorded_weights(resolved: Mapping[str, Any]) -> Dict[str, Any]:
    """落库/续状态用的权重：`off` 与「否决期」一律记静态先验。

    否决期记静态先验（而不是等权零假设），否则下一周的等权对照退化为
    「等权 vs 等权 = 全 0」，`oos_gate` 永远过不了——动态权重被永久锁死。
    `shadow` 与 `on` 记同一口径，差别只在是否注入 `decide`。
    """
    fallback = bool(resolved.get("weight_fallback")) and not bool(resolved.get("frozen"))
    if resolved.get("mode") == "off" or fallback:
        axis = {axis: float(weights.STATIC_WEIGHTS[axis]) for axis in AXES}
        axis["gap"] = float((resolved.get("axis_weights") or {}).get("gap") or 0.0)
        return {
            "weights": dict(weights.STATIC_WEIGHTS),
            "axis_weights": axis,
            "weights_hash": weights.weights_hash(weights.STATIC_WEIGHTS),
        }
    return {
        "weights": dict(resolved["weights"]),
        "axis_weights": dict(resolved["axis_weights"]),
        "weights_hash": resolved["weights_hash"],
    }


__all__ = [
    "AXES",
    "CONFIG_FILE",
    "DEFAULT_MIN_LABELS",
    "DEFAULT_MODE",
    "DEFAULT_WINDOW",
    "MODES",
    "SWITCH_ENV",
    "WeightSwitchError",
    "apply_to_params",
    "load_config",
    "load_state",
    "normalize_mode",
    "oos_excess_series",
    "recorded_weights",
    "resolve_mode",
    "resolve_weights",
]
