# -*- coding: utf-8 -*-
"""图表权重（SPEC-54-L1交易层 §4.1 / §4.3 / B-LT3，P0-2）。

单一事实源：`config/chart_weights.yaml`。本模块只做「读 + 校验 + 归一 + 指纹 +
短样本裁剪」，**不参与任何决策计算**：

  - `chart_weights`：D-E16 聚合曲线 / D-E17 类别排序的展示合成权重（默认 on）；
  - `light_weights`：`lights.strength` 的四轴合成权重（默认 on）；
  - 与 `l1agg/trading/weights.py` 的交易轴权重（axis_weights）三权分立，
    字段名、配置段、hash 域三者互不共用（LT-G2）。

校验分层（§4.3 规则 5）：加载期 fail-closed（范围/和为 1 越界抛错）；
运行期非法 → 降级等权 + `weights_degraded=true`（展示层 FAIL-OPEN）。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional

import yaml

_DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "chart_weights.yaml",
)

CHART_WEIGHTS_VERSION = "cw-1.0.0"
LIGHT_AXES = ("trend", "inertia", "cycle", "foresight")
MODES = ("on", "off")
SOURCES = ("config", "ui", "equal")
DEFAULT_MIN_ROWS = 250
_EPS = 1e-9


class ChartWeightsError(ValueError):
    """图表权重非法（越界/和不为 1/结构缺字段/越界注入决策层）。"""


@dataclass(frozen=True)
class ChartWeights:
    version: str
    mode: str
    source: str
    members: Dict[str, float]
    views: Dict[str, float]
    light_weights: Dict[str, float]
    thresholds: Dict[str, float]
    calibrated_at: str = ""
    min_weight: float = 0.0
    max_weight: float = 0.60
    sum_tolerance: float = 1e-6
    min_rows: int = DEFAULT_MIN_ROWS
    updated: str = ""

    @property
    def enabled(self) -> bool:
        return self.mode == "on"

    def hash(self) -> str:
        """`chart_weights_hash`（只覆盖成员权重，滑块调参即变）。"""
        return chart_weights_hash(self.members)

    def light_hash(self) -> str:
        """`light_weights_hash`（含阈值，阈值重标定即变）。"""
        return light_weights_hash(self.light_weights, self.thresholds)

    def meta(self) -> Dict[str, Any]:
        return {
            "chart_weights_version": self.version,
            "chart_weights_source": self.source,
            "chart_weights_mode": self.mode,
            "chart_weights_hash": self.hash(),
            "light_weights_hash": self.light_hash(),
            "thresholds_uncalibrated": not bool(self.calibrated_at),
        }


# ------------------------------------------------------------ 指纹（域分离）
def _hash_blob(domain: str, payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(f"{domain}|{blob}".encode("utf-8")).hexdigest()


def chart_weights_hash(members: Mapping[str, float]) -> str:
    material = {str(k): round(float(v), 6) for k, v in members.items()}
    return _hash_blob("chart", material)


def light_weights_hash(
    axes: Mapping[str, float], thresholds: Optional[Mapping[str, Any]] = None
) -> str:
    material = {axis: round(float(axes.get(axis, 0.0)), 6) for axis in LIGHT_AXES}
    bounds = {
        "lit_pct": round(float((thresholds or {}).get("lit_pct", 0.70)), 6),
        "warm_pct": round(float((thresholds or {}).get("warm_pct", 0.40)), 6),
    }
    return _hash_blob("light", {"axes": material, "thresholds": bounds})


# ------------------------------------------------------------ 归一 / 校验
def normalize(raw: Mapping[str, float]) -> Dict[str, float]:
    """simplex 归一（负值截 0；全 0 报错，不静默造权重）。"""
    shifted = {str(k): max(0.0, float(v)) for k, v in raw.items()}
    total = sum(shifted.values())
    if total <= _EPS:
        raise ChartWeightsError("权重和必须 > 0，禁止空/全零权重")
    return {k: round(v / total, 6) for k, v in shifted.items()}


def validate_weights(
    name: str,
    weights: Mapping[str, float],
    *,
    min_weight: float = 0.0,
    max_weight: float = 0.60,
    tolerance: float = 1e-6,
    require_unit_sum: bool = True,
) -> None:
    """范围 + 和校验；不合法直接抛错（加载期 fail-closed）。"""
    if not weights:
        raise ChartWeightsError(f"{name} 为空")
    total = 0.0
    for key, value in weights.items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ChartWeightsError(f"{name}.{key} 不是数值: {value!r}") from None
        if not math.isfinite(number):
            raise ChartWeightsError(f"{name}.{key} 非有限值: {value!r}")
        if number < min_weight - tolerance or number > max_weight + tolerance:
            raise ChartWeightsError(f"{name}.{key}={number} 越界 [{min_weight}, {max_weight}]")
        total += number
    if require_unit_sum and abs(total - 1.0) > tolerance:
        raise ChartWeightsError(f"{name} 权重和 {total:.6f} ≠ 1（容差 {tolerance}）")


# ------------------------------------------------------------ 加载
def load(
    path: Optional[str] = None,
    *,
    source: str = "config",
    mode: Optional[str] = None,
    override_members: Optional[Mapping[str, float]] = None,
    validate: bool = True,
) -> ChartWeights:
    """加载图表权重；`override_members` 供前端滑块（source 应为 `ui`）。"""
    if source not in SOURCES:
        raise ChartWeightsError(f"source 非法: {source}（允许 {SOURCES}）")
    target = path or _DEFAULT_PATH
    if not os.path.exists(target):
        raise ChartWeightsError(f"图表权重配置不存在: {target}")
    with open(target, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    constraints = dict(raw.get("constraints") or {})
    min_weight = float(constraints.get("min_weight", 0.0))
    max_weight = float(constraints.get("max_weight", 0.60))
    tolerance = float(constraints.get("sum_tolerance", 1e-6))

    members = dict(override_members or raw.get("chart_weights") or {})
    views = dict(raw.get("views") or {})
    light = dict(raw.get("light_weights") or {})
    thresholds = dict(raw.get("thresholds") or {})

    resolved_mode = str(mode or raw.get("mode") or "on")
    if resolved_mode not in MODES:
        raise ChartWeightsError(f"mode 非法: {resolved_mode}（允许 {MODES}）")

    if validate:
        validate_weights(
            "chart_weights",
            members,
            min_weight=min_weight,
            max_weight=max_weight,
            tolerance=tolerance,
        )
        validate_weights("views", views, min_weight=0.0, max_weight=1.0, tolerance=tolerance)
        missing = [axis for axis in LIGHT_AXES if axis not in light]
        if missing:
            raise ChartWeightsError(f"light_weights 缺少轴: {missing}")
        validate_weights(
            "light_weights",
            {axis: light[axis] for axis in LIGHT_AXES},
            min_weight=0.0,
            max_weight=1.0,
            tolerance=tolerance,
        )
        lit = float(thresholds.get("lit_pct", 0.70))
        warm = float(thresholds.get("warm_pct", 0.40))
        if not 0.0 <= warm <= lit <= 1.0:
            raise ChartWeightsError(f"阈值非法: 需 0 ≤ warm_pct ≤ lit_pct ≤ 1（{warm}/{lit}）")

    return ChartWeights(
        version=str(raw.get("version") or CHART_WEIGHTS_VERSION),
        mode=resolved_mode,
        source=source,
        members={str(k): round(float(v), 6) for k, v in members.items()},
        views={str(k): round(float(v), 6) for k, v in views.items()},
        light_weights={axis: round(float(light.get(axis, 0.0)), 6) for axis in LIGHT_AXES},
        thresholds={
            "lit_pct": float(thresholds.get("lit_pct", 0.70)),
            "warm_pct": float(thresholds.get("warm_pct", 0.40)),
        },
        calibrated_at=str(thresholds.get("calibrated_at") or ""),
        min_weight=min_weight,
        max_weight=max_weight,
        sum_tolerance=tolerance,
        min_rows=int(constraints.get("min_rows", DEFAULT_MIN_ROWS)),
        updated=str(raw.get("updated") or ""),
    )


# ------------------------------------------------------------ 短样本裁剪（§4.3 规则 3）
def prune_short_members(
    members: Mapping[str, float],
    sample_n: Mapping[str, int],
    *,
    min_rows: int = DEFAULT_MIN_ROWS,
) -> Dict[str, Any]:
    """`n < min_rows` 的成员权重置 0 并标记；剩余权重重归一。"""
    kept_raw: Dict[str, float] = {}
    dropped: List[Dict[str, Any]] = []
    for symbol, weight in members.items():
        n = int(sample_n.get(symbol, 0) or 0)
        if n < int(min_rows):
            dropped.append(
                {
                    "symbol": symbol,
                    "weight": round(float(weight), 6),
                    "n": n,
                    "reason": "insufficient_history",
                }
            )
            continue
        kept_raw[symbol] = float(weight)

    if not kept_raw:
        return {
            "weights": {},
            "dropped": dropped,
            "pruned": bool(dropped),
            "degraded": True,
            "reason": "all_members_insufficient",
        }
    return {
        "weights": normalize(kept_raw),
        "dropped": dropped,
        "pruned": bool(dropped),
        "degraded": False,
        "reason": "",
    }


def _equal(keys: Iterable[str]) -> Dict[str, float]:
    symbols = list(keys)
    if not symbols:
        return {}
    share = round(1.0 / len(symbols), 6)
    weights = dict.fromkeys(symbols, share)
    drift = round(1.0 - share * len(symbols), 6)
    if symbols and abs(drift) > 0:
        weights[symbols[0]] = round(weights[symbols[0]] + drift, 6)
    return weights


# ------------------------------------------------------------ 运行期解析（D-E16 输入）
def resolve_members(
    weights: Any,
    sample_n: Mapping[str, int],
    *,
    min_rows: Optional[int] = None,
    mode: Optional[str] = None,
    source: Optional[str] = None,
) -> Dict[str, Any]:
    """产出聚合曲线要用的成员权重 + 指纹 + 降级标记（FAIL-OPEN）。

    - `mode=off` → 等权（回滚档），`source=equal`；
    - 权重非法（空/负/非有限）→ 降级等权 + `weights_degraded=true`；
    - `n < min_rows` 的成员权重置 0 + `insufficient_history`，剩余重归一；
    - 全部成员都短样本 → 等权 + `weights_degraded=true`（图形仍需可画）。
    """
    cfg = weights if isinstance(weights, ChartWeights) else None
    members: Mapping[str, float] = cfg.members if cfg is not None else dict(weights or {})
    resolved_mode = mode or (cfg.mode if cfg is not None else "on")
    resolved_source = source or (cfg.source if cfg is not None else "config")
    threshold = int(
        min_rows if min_rows is not None else (cfg.min_rows if cfg else DEFAULT_MIN_ROWS)
    )

    out: Dict[str, Any] = {
        "members": [],
        "dropped": [],
        "weights": {},
        "chart_weights_hash": "",
        "chart_weights_source": resolved_source,
        "chart_weights_mode": resolved_mode,
        "weights_degraded": False,
        "pruned": False,
        "flags": [],
    }

    if resolved_mode != "on":
        out["weights"] = _equal(members)
        out["chart_weights_source"] = "equal"
        out["flags"].append("chart_weights_off")
        out["chart_weights_hash"] = chart_weights_hash(out["weights"])
        out["members"] = [
            {"symbol": s, "weight": w, "n": int(sample_n.get(s, 0) or 0), "status": "equal"}
            for s, w in out["weights"].items()
        ]
        return out

    try:
        validate_weights(
            "chart_weights",
            members,
            min_weight=float(cfg.min_weight if cfg else 0.0),
            max_weight=float(cfg.max_weight if cfg else 0.60),
            tolerance=float(cfg.sum_tolerance if cfg else 1e-6),
        )
    except ChartWeightsError as exc:
        out["weights"] = _equal(members)
        out["chart_weights_source"] = "equal"
        out["weights_degraded"] = True
        out["flags"].extend(["chart_weights_degraded", str(exc)])
        out["chart_weights_hash"] = chart_weights_hash(out["weights"])
        out["members"] = [
            {"symbol": s, "weight": w, "n": int(sample_n.get(s, 0) or 0), "status": "equal"}
            for s, w in out["weights"].items()
        ]
        return out

    pruned = prune_short_members(members, sample_n, min_rows=threshold)
    out["dropped"] = pruned["dropped"]
    out["pruned"] = pruned["pruned"]
    if pruned["degraded"]:
        out["weights"] = _equal(members)
        out["chart_weights_source"] = "equal"
        out["weights_degraded"] = True
        out["flags"].append(pruned["reason"])
    else:
        out["weights"] = pruned["weights"]
    out["chart_weights_hash"] = chart_weights_hash(out["weights"])
    out["members"] = [
        {
            "symbol": symbol,
            "weight": weight,
            "n": int(sample_n.get(symbol, 0) or 0),
            "status": "active",
        }
        for symbol, weight in out["weights"].items()
    ]
    return out


# ------------------------------------------------------------ LT-G2：越界注入拦截
_FORBIDDEN_KEYS = ("chart_weights", "chart_weights_hash", "light_weights", "light_weights_hash")


def assert_no_chart_weights(payload: Any, path: str = "") -> None:
    """递归断言决策层入参/信号字段不含图表权重（LT-G2）。"""
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            name = str(key)
            here = f"{path}.{name}" if path else name
            if name in _FORBIDDEN_KEYS:
                raise ChartWeightsError(f"决策层禁止出现图表权重字段: {here}")
            assert_no_chart_weights(value, here)
    elif isinstance(payload, (list, tuple)):
        for index, item in enumerate(payload):
            assert_no_chart_weights(item, f"{path}[{index}]")


def main(argv=None) -> int:  # pragma: no cover - 手工排查用
    import argparse

    parser = argparse.ArgumentParser(description="图表权重校验")
    parser.add_argument("--path", default=None)
    args = parser.parse_args(argv)
    cfg = load(args.path)
    print(
        json.dumps(
            {
                "ok": True,
                "version": cfg.version,
                "mode": cfg.mode,
                "members": len(cfg.members),
                "sum": round(sum(cfg.members.values()), 6),
                **cfg.meta(),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
