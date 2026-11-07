"""B-02 / DEC-12: 成对支配解析器（shadow）.

对候选路径做两两比较，输出可解释 dominance 矩阵与 Copeland 主导者。
生产选择仍为 argmax；本模块只用于 shadow 对比，不改变 `optimal_path`。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

METHOD_VERSION = "pairwise-dominance-v1"

# 解释性权重（总和 1.0）
_ALIGNMENT_WEIGHT = 0.45
_STRENGTH_WEIGHT = 0.30
_CONTINUATION_WEIGHT = 0.15
_CONFIDENCE_WEIGHT = 0.10


def _clamp(value: Any, lo: float = -1.0, hi: float = 1.0) -> float:
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _path_id(path: dict, index: int) -> str:
    return str(path.get("path_id") or f"path_{index}")


def _direction(path: dict) -> str:
    direction = str(path.get("direction", "neutral")).lower()
    return direction if direction in ("long", "short", "neutral") else "neutral"


def _production_score(path: dict) -> float:
    if "score" in path:
        return _num(path.get("score"))
    return (
        _num(path.get("expected_return"))
        * _num(path.get("confidence"))
        * (1.0 - _num(path.get("resistance")))
    )


def _normalized_scores(paths: list[dict]) -> list[float]:
    raw = [_production_score(path) for path in paths]
    if not raw:
        return []
    low, high = min(raw), max(raw)
    if high - low <= 1e-12:
        return [0.5 for _ in raw]
    return [(value - low) / (high - low) for value in raw]


def _alignment(path: dict, primary_direction: str) -> float:
    if primary_direction not in ("long", "short"):
        return 0.0
    direction = _direction(path)
    if direction == primary_direction:
        return 1.0
    if direction == "neutral":
        return 0.0
    return -1.0


def _pair_delta(
    left: dict,
    right: dict,
    *,
    norm_left: float,
    norm_right: float,
    primary_direction: str,
) -> tuple[float, dict]:
    alignment_delta = _alignment(left, primary_direction) - _alignment(right, primary_direction)
    strength_delta = norm_left - norm_right
    continuation_delta = _clamp(_num(left.get("continuation_score"), 0.5)) - _clamp(
        _num(right.get("continuation_score"), 0.5)
    )
    confidence_delta = _clamp(_num(left.get("confidence"))) - _clamp(_num(right.get("confidence")))
    delta = (
        _ALIGNMENT_WEIGHT * alignment_delta
        + _STRENGTH_WEIGHT * strength_delta
        + _CONTINUATION_WEIGHT * continuation_delta
        + _CONFIDENCE_WEIGHT * confidence_delta
    )
    return _clamp(delta), {
        "alignment_delta": round(alignment_delta, 6),
        "strength_delta": round(strength_delta, 6),
        "continuation_delta": round(continuation_delta, 6),
        "confidence_delta": round(confidence_delta, 6),
    }


def resolve(
    paths: Any,
    primary_contradiction: Any = None,
    production_path_id: str | None = None,
) -> dict | None:
    """成对支配解析；非法/空输入返回 None（FAIL-OPEN）。"""
    if not isinstance(paths, (list, tuple)):
        return None
    valid_paths = [path for path in paths if isinstance(path, dict)]
    if not valid_paths:
        return None

    primary = primary_contradiction if isinstance(primary_contradiction, dict) else {}
    primary_direction = str(primary.get("direction", "neutral")).lower()
    if primary_direction not in ("long", "short"):
        primary_direction = "neutral"

    ids = [_path_id(path, index) for index, path in enumerate(valid_paths)]
    by_id = dict(zip(ids, valid_paths))  # noqa: B905
    norms = _normalized_scores(valid_paths)
    matrix: dict[str, dict[str, float]] = {path_id: {} for path_id in ids}
    pairwise: list[dict] = []
    copeland: dict[str, int] = dict.fromkeys(ids, 0)
    total: dict[str, float] = dict.fromkeys(ids, 0.0)

    for left_index, left in enumerate(valid_paths):
        for right_index in range(left_index + 1, len(valid_paths)):
            right = valid_paths[right_index]
            delta, reasons = _pair_delta(
                left,
                right,
                norm_left=norms[left_index],
                norm_right=norms[right_index],
                primary_direction=primary_direction,
            )
            matrix[ids[left_index]][ids[right_index]] = round(delta, 6)
            matrix[ids[right_index]][ids[left_index]] = round(-delta, 6)
            total[ids[left_index]] += delta
            total[ids[right_index]] -= delta

            if delta > 0:
                winner = ids[left_index]
                copeland[ids[left_index]] += 1
                copeland[ids[right_index]] -= 1
            elif delta < 0:
                winner = ids[right_index]
                copeland[ids[right_index]] += 1
                copeland[ids[left_index]] -= 1
            else:
                winner = None
            pairwise.append(
                {
                    "a": ids[left_index],
                    "b": ids[right_index],
                    "winner": winner,
                    "delta": round(delta, 6),
                    "reasons": reasons,
                }
            )

    dominant = sorted(
        ids,
        key=lambda path_id: (
            -copeland[path_id],
            -total[path_id],
            -_production_score(by_id[path_id]),
            path_id,
        ),
    )[0]

    return {
        "method": METHOD_VERSION,
        "shadow_only": True,
        "primary_direction": primary_direction,
        "primary_contradiction": primary,
        "paths": [
            {
                "path_id": path_id,
                "source": by_id[path_id].get("source"),
                "direction": _direction(by_id[path_id]),
                "score": round(_production_score(by_id[path_id]), 6),
                "norm_strength": round(norms[index], 6),
            }
            for index, path_id in enumerate(ids)
        ],
        "matrix": matrix,
        "pairwise": pairwise,
        "copeland": copeland,
        "dominant_path_id": dominant,
        "production_path_id": production_path_id,
        "agreement": production_path_id == dominant,
    }


def resolve_shadow(
    paths: Any,
    *,
    primary_contradiction: Any = None,
    production_path_id: str | None = None,
    enabled: bool = False,
) -> dict | None:
    """按开关运行 shadow 解析；关闭时返回 None，异常 FAIL-OPEN。"""
    if not enabled:
        return None
    try:
        return resolve(
            paths,
            primary_contradiction=primary_contradiction,
            production_path_id=production_path_id,
        )
    except Exception as exc:  # noqa: BLE001 — shadow 层 FAIL-OPEN
        logger.debug("[DominanceShadow] fail-open: %s", exc)
        return {
            "method": METHOD_VERSION,
            "shadow_only": True,
            "error": f"{type(exc).__name__}: {exc}",
        }
