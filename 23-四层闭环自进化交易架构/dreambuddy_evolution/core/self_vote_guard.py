"""B-08 / DEC-10: 23 自票上限与独立矛盾证据复核（shadow）.

23 既是策略参与者又是最终仲裁者。本模块检测“自票占比过高且缺少外部独立
证据”的风险，输出 shadow 诊断与可选审计，不改变 production 裁决。

自票来源（23 内部生成）:
  l2_gene / synthesized / deep_reasoning / trend_following / grid_trading
外部来源:
  bcrm / bdsm / strategic
未知来源按外部处理（保守：不让未知来源被当成自票）。
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

METHOD_VERSION = "self-vote-guard-v1"
DEFAULT_CAP_RATIO = 0.6
DEFAULT_MIN_EXTERNAL_CONFIDENCE = 0.5

SELF_SOURCES = frozenset(
    {"l2_gene", "synthesized", "deep_reasoning", "trend_following", "grid_trading"}
)
EXTERNAL_SOURCES = frozenset({"bcrm", "bdsm", "strategic"})


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, _num(value)))


def _source(path: dict) -> str:
    return str(path.get("source", "")).strip().lower()


def _direction(path: dict) -> str:
    direction = str(path.get("direction", "neutral")).strip().lower()
    return direction if direction in ("long", "short", "neutral") else "neutral"


def _confidence(path: dict) -> float:
    return _clamp(path.get("confidence", 0.0))


def record_self_vote_audit(payload: dict, path: str | os.PathLike | None = None) -> bool:
    """追加一条 JSONL 审计；未配置路径/异常时 FAIL-OPEN 返回 False."""
    try:
        target = path or os.environ.get("SELF_VOTE_AUDIT_PATH")
        if not target:
            return False
        target_path = Path(target)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        record = {"ts": time.time(), "method": METHOD_VERSION, **payload}
        with open(target_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("[SelfVoteGuard] audit fail-open: %s", exc)
        return False


def compute_self_vote_shadow(
    paths: Any,
    primary_contradiction: Any = None,
    *,
    enabled: bool = False,
    cap_ratio: float | None = None,
    min_external_confidence: float | None = None,
    audit_path: str | os.PathLike | None = None,
) -> dict | None:
    """计算自票 shadow；关闭返回 None；异常/非法输入 FAIL-OPEN."""
    if not enabled:
        return None
    if not isinstance(paths, (list, tuple)):
        return {
            "available": False,
            "shadow_only": True,
            "method": METHOD_VERSION,
            "reason": "no_paths",
        }
    valid_paths = [path for path in paths if isinstance(path, dict)]
    if not valid_paths:
        return {
            "available": False,
            "shadow_only": True,
            "method": METHOD_VERSION,
            "reason": "no_valid_paths",
        }

    primary = primary_contradiction if isinstance(primary_contradiction, dict) else {}
    primary_direction = str(primary.get("direction", "neutral")).strip().lower()
    if primary_direction not in ("long", "short"):
        primary_direction = "neutral"

    cap = _clamp(
        cap_ratio if cap_ratio is not None else DEFAULT_CAP_RATIO, 0.0, 1.0
    )
    min_external = _clamp(
        min_external_confidence
        if min_external_confidence is not None
        else DEFAULT_MIN_EXTERNAL_CONFIDENCE,
        0.0,
        1.0,
    )

    self_paths = [path for path in valid_paths if _source(path) in SELF_SOURCES]
    external_paths = [path for path in valid_paths if _source(path) not in SELF_SOURCES]
    self_confidence = sum(_confidence(path) for path in self_paths)
    external_confidence = sum(_confidence(path) for path in external_paths)
    total_confidence = self_confidence + external_confidence
    self_vote_ratio = self_confidence / total_confidence if total_confidence > 0 else 0.0

    independent_evidence = False
    if primary_direction in ("long", "short"):
        independent_evidence = any(
            _direction(path) == primary_direction
            and _confidence(path) >= min_external
            for path in external_paths
        )

    would_cap = (
        primary_direction in ("long", "short")
        and self_vote_ratio > cap
        and not independent_evidence
    )
    primary_path = max(valid_paths, key=_confidence)
    reasons = []
    if would_cap:
        reasons.append("self_vote_ratio_above_cap")
        reasons.append("no_independent_external_evidence")
    elif primary_direction in ("long", "short") and not independent_evidence:
        reasons.append("no_independent_external_evidence")
    if primary_direction == "neutral":
        reasons.append("primary_direction_neutral")

    shadow = {
        "available": True,
        "shadow_only": True,
        "method": METHOD_VERSION,
        "primary_direction": primary_direction,
        "primary_source": _source(primary_path),
        "paths_total": len(valid_paths),
        "self_path_count": len(self_paths),
        "external_path_count": len(external_paths),
        "self_confidence": round(self_confidence, 6),
        "external_confidence": round(external_confidence, 6),
        "self_vote_ratio": round(self_vote_ratio, 6),
        "cap_ratio": round(cap, 6),
        "min_external_confidence": round(min_external, 6),
        "independent_evidence": independent_evidence,
        "would_cap": would_cap,
        "reasons": reasons,
        "self_sources": sorted({_source(path) for path in self_paths}),
        "external_sources": sorted({_source(path) for path in external_paths}),
    }
    if audit_path:
        record_self_vote_audit(shadow, audit_path)
    return shadow