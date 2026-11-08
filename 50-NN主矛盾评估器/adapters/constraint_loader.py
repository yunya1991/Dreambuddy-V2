"""40/43 约束只读加载 + 仓位钳位（约束只钳位，不进矛盾评分）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STRATEGY_PATH = REPO_ROOT / "40-周期神经网络系统" / "strategy_mapping.json"
DEFAULT_STRATEGIC_PATH = (
    REPO_ROOT / "43-战略承接推演层" / "runtime" / "strategic_extension_signal.json"
)

DEFAULT_BAND = [0, 100]


def _load_json(path: str | Path | None, default_path: Path) -> dict[str, Any]:
    target = Path(path) if path else default_path
    if not target.exists():
        return {}
    return json.loads(target.read_text(encoding="utf-8"))


def load_constraints(
    strategy_mapping_path: str | Path | None = None,
    strategic_extension_path: str | Path | None = None,
) -> dict[str, Any]:
    degraded: list[str] = []
    strategy = _load_json(strategy_mapping_path, DEFAULT_STRATEGY_PATH)
    strategic = _load_json(strategic_extension_path, DEFAULT_STRATEGIC_PATH)

    if not strategy:
        degraded.append("strategy_mapping_missing")
    if not strategic:
        degraded.append("strategic_extension_missing")

    band = strategy.get("strategy_suggestion", {}).get("position_band_pct", DEFAULT_BAND)
    freeze = bool(strategy.get("risk_guards", {}).get("event_window", {}).get("in_window", False))
    confidence = strategy.get("risk_guards", {}).get("effective_confidence")

    per_asset_class = strategic.get("per_asset_class", {}) or {}
    leverage_cap = None
    for group in per_asset_class.values():
        if isinstance(group, dict) and group.get("leverage_cap"):
            leverage_cap = group["leverage_cap"]
            break

    return {
        "position_band": band,
        "freeze": freeze,
        "effective_confidence": confidence,
        "per_asset_class": per_asset_class,
        "leverage_cap": leverage_cap,
        "degraded": degraded,
    }


def clamp_position(constraints: dict[str, Any], raw: float, asset_class: str) -> float:
    band = constraints.get("per_asset_class", {}).get(asset_class, {}).get("position_band")
    if not isinstance(band, (list, tuple)) or len(band) != 2:
        band = constraints.get("position_band", DEFAULT_BAND)
    low, high = float(band[0]), float(band[1])
    return max(low, min(high, float(raw)))
