"""40/43 约束只读加载 + 仓位钳位（约束只钳位，不进矛盾评分）。

F5 direction_leak_check：constraint 通道只允许方向中性的幅度量（position_band/
leverage_cap/asset_count_cap/long_count_cap/short_count_cap），禁止携带 direction/
net_bias 等方向偏置。发现方向字段时剥离并审计 degraded=direction_leak_check。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STRATEGY_PATH = REPO_ROOT / "40-周期神经网络系统" / "strategy_mapping.json"
DEFAULT_STRATEGIC_PATH = (
    REPO_ROOT / "43-战略承接推演层" / "runtime" / "strategic_extension_signal.json"
)

DEFAULT_BAND = [0, 100]

# F5：禁止进入 constraint 通道的方向字段
_DIRECTIONAL_FIELDS = ("direction", "net_bias", "bias", "sentiment")

# F5：允许的方向中性约束字段
_CONSTRAINT_FIELDS = (
    "leverage_cap",
    "asset_count_cap",
    "long_count_cap",
    "short_count_cap",
)


def _load_json(path: str | Path | None, default_path: Path) -> dict[str, Any]:
    target = Path(path) if path else default_path
    if not target.exists():
        return {}
    return json.loads(target.read_text(encoding="utf-8"))


def _record_degraded(layer: str, source: str, reason: str, detail: str = "") -> None:
    """F4：调用 42 统一降级审计流。导入失败静默忽略。"""
    try:
        sys.path.insert(0, str(REPO_ROOT / "42-神经网络交易协调层"))
        from degraded_events import record_degraded_event

        record_degraded_event(layer, source, reason, detail)
    except Exception:  # noqa: BLE001  审计写入失败不影响主流程
        pass


def _strip_directional_fields(per_asset_class: dict) -> tuple[dict, list[str]]:
    """F5：从 per_asset_class 各组中剥离方向字段，返回 (清理后, 被剥离字段列表)。"""
    stripped: list[str] = []
    cleaned: dict[str, Any] = {}
    for ac, group in per_asset_class.items():
        if not isinstance(group, dict):
            cleaned[ac] = group
            continue
        clean_group = {k: v for k, v in group.items() if k not in _DIRECTIONAL_FIELDS}
        for f in _DIRECTIONAL_FIELDS:
            if f in group:
                stripped.append(f"{ac}.{f}={group[f]!r}")
        cleaned[ac] = clean_group
    return cleaned, stripped


def load_constraints(
    strategy_mapping_path: str | Path | None = None,
    strategic_extension_path: str | Path | None = None,
) -> dict[str, Any]:
    degraded: list[str] = []
    strategy = _load_json(strategy_mapping_path, DEFAULT_STRATEGY_PATH)
    strategic = _load_json(strategic_extension_path, DEFAULT_STRATEGIC_PATH)

    if not strategy:
        degraded.append("strategy_mapping_missing")
        _record_degraded(
            "50",
            "constraint_loader",
            "bridge_closed_using_defaults",
            "strategy_mapping.json missing, using DEFAULT_BAND",
        )
    if not strategic:
        degraded.append("strategic_extension_missing")
        _record_degraded(
            "50",
            "constraint_loader",
            "bridge_closed_using_defaults",
            "strategic_extension_signal.json missing",
        )

    band = strategy.get("strategy_suggestion", {}).get("position_band_pct", DEFAULT_BAND)
    freeze = bool(strategy.get("risk_guards", {}).get("event_window", {}).get("in_window", False))
    confidence = strategy.get("risk_guards", {}).get("effective_confidence")

    # 43 落盘结构：per_asset_class/asset_groups 嵌套在 payload 内；兼容顶层旧格式（payload 优先，顶层回退）
    _payload = strategic.get("payload") if isinstance(strategic.get("payload"), dict) else {}
    per_asset_class = _payload.get("per_asset_class") or strategic.get("per_asset_class") or {}
    asset_groups = _payload.get("asset_groups") or strategic.get("asset_groups") or {}

    # F5：剥离方向字段，审计 direction_leak_check
    per_asset_class, stripped = _strip_directional_fields(per_asset_class)
    if stripped:
        degraded.append("direction_leak_check")
        _record_degraded(
            "50",
            "constraint_loader",
            "direction_leak_check",
            f"stripped directional fields: {', '.join(stripped)}",
        )

    tier_constraints: dict[str, Any] = {}
    for field in _CONSTRAINT_FIELDS:
        for group in per_asset_class.values():
            if isinstance(group, dict) and group.get(field) is not None:
                tier_constraints[field] = group[field]
                break

    return {
        "position_band": band,
        "freeze": freeze,
        "effective_confidence": confidence,
        "per_asset_class": per_asset_class,
        "asset_groups": asset_groups,
        "leverage_cap": tier_constraints.get("leverage_cap"),
        "asset_count_cap": tier_constraints.get("asset_count_cap"),
        "long_count_cap": tier_constraints.get("long_count_cap"),
        "short_count_cap": tier_constraints.get("short_count_cap"),
        "net_bias": None,  # F5：方向字段强制置空，不进约束通道
        "degraded": degraded,
        "direction_leak_check": {
            "stripped_fields": stripped,
            "passed": not stripped,
        },
    }


def clamp_position(constraints: dict[str, Any], raw: float, asset_class: str) -> float:
    band = constraints.get("per_asset_class", {}).get(asset_class, {}).get("position_band")
    if not isinstance(band, (list, tuple)) or len(band) != 2:
        band = constraints.get("position_band", DEFAULT_BAND)
    low, high = float(band[0]), float(band[1])
    return max(low, min(high, float(raw)))
