"""factor_priors_provider.py — SPEC-M4 M4-2：50 侧先验 overlay 适配层。

职责：开关判定 → 先验读取 → 新鲜度/样本量门禁 → 系数预注册校验 → overlay 应用 → 审计块。
纪律：
  - FAIL-OPEN：任何异常都回退原始 paths，不中断决策。
  - 默认关闭：`ENABLE_50_FACTOR_PRIORS_OVERLAY` 未设或非真值时等价 coef=0。
  - 禁止运行时自适应调系数：只接受预注册候选集，非法值回落默认并审计。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path as FsPath
from typing import Any

from core.factor_priors_overlay import (
    FACTOR_PREFIX_DIM_MAP,
    MIN_N_SAMPLES,
    apply_factor_priors_overlay,
)
from core.path_synthesis import Path

logger = logging.getLogger(__name__)

REPO_ROOT = FsPath(__file__).resolve().parents[2]
DEFAULT_PRIORS_PATH = REPO_ROOT / "40-周期神经网络系统" / "factor_contradiction_priors.json"

ENABLE_ENV = "ENABLE_50_FACTOR_PRIORS_OVERLAY"
COEF_ENV = "FACTOR_PRIORS_COEF"

# SPEC-M4 §5.1 预注册常量
COEF_DEFAULT = 0.10
COEF_CANDIDATES = (0.0, 0.05, 0.10, 0.15, 0.20)
COEF_CEILING = 0.20
STALE_DAYS = 7

_TRUE_VALUES = {"1", "true", "yes", "on"}


def is_overlay_enabled() -> bool:
    """开关默认关闭；只有显式真值才启用。"""
    return str(os.getenv(ENABLE_ENV, "")).strip().lower() in _TRUE_VALUES


def resolve_coef() -> tuple[float, str]:
    """返回 (系数, 来源)。来源：default / candidate / rejected。"""
    raw = os.getenv(COEF_ENV)
    if raw is None or not str(raw).strip():
        return COEF_DEFAULT, "default"
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return COEF_DEFAULT, "rejected"
    if value not in COEF_CANDIDATES or value > COEF_CEILING:
        return COEF_DEFAULT, "rejected"
    return value, "candidate"


def _parse_ts(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _is_stale(generated_at: object, now: datetime) -> bool:
    """缺失/不可解析/超期均视为陈旧（SPEC-M4 §2.3）。"""
    parsed = _parse_ts(generated_at)
    if parsed is None:
        return True
    return (now - parsed) > timedelta(days=STALE_DAYS)


def _count_unmapped(factors: dict[str, Any]) -> int:
    count = 0
    for name, cfg in (factors or {}).items():
        if not isinstance(cfg, dict):
            continue
        prefix = str(name or "").split(".", 1)[0].strip().lower()
        if prefix not in FACTOR_PREFIX_DIM_MAP:
            count += 1
    return count


def _load_priors(target: FsPath) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("priors 根节点不是 dict")
    fdp = data.get("factor_direction_priors")
    fdp = fdp if isinstance(fdp, dict) else {}
    factors = fdp.get("factors")
    return data, factors if isinstance(factors, dict) else {}, fdp


def _base_audit(target: FsPath, total_paths: int) -> dict[str, Any]:
    return {
        "enabled": False,
        "coef": 0.0,
        "coef_source": "disabled",
        "priors_path": str(target),
        "priors_generated_at": None,
        "priors_schema_version": None,
        # 48 40_feedback.json 的 data_version；50 直读 40 产物时无法获得，保持 null
        "priors_data_version": None,
        "priors_n_samples": None,
        "unmapped_factor_count": 0,
        "modulated_paths": 0,
        "total_paths": total_paths,
        "modulation_rate": 0.0,
        "degraded": [],
    }


def maybe_apply_factor_priors_overlay(
    paths: list[Path],
    now: datetime | None = None,
    priors_path: str | FsPath | None = None,
) -> tuple[list[Path], dict[str, Any]]:
    """按 SPEC-M4 应用 40 因子方向先验 overlay，返回 (paths, 审计块)。"""
    items = [p for p in paths if isinstance(p, Path)]
    target = FsPath(priors_path) if priors_path else DEFAULT_PRIORS_PATH
    audit = _base_audit(target, len(items))

    if not is_overlay_enabled():
        return items, audit

    audit["enabled"] = True
    coef, coef_source = resolve_coef()
    audit["coef"] = coef
    audit["coef_source"] = coef_source

    try:
        data, factors, fdp = _load_priors(target)
    except FileNotFoundError:
        audit["degraded"].append("missing_priors")
        return items, audit
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("50 先验读取失败（降级）: %s %s", target, exc)
        audit["degraded"].append("missing_priors")
        return items, audit

    generated_at = data.get("generated_at")
    n_samples = fdp.get("n_samples")
    audit["priors_generated_at"] = generated_at
    audit["priors_schema_version"] = data.get("schema_version")
    audit["priors_n_samples"] = n_samples

    moment = now or datetime.now(timezone.utc)
    if _is_stale(generated_at, moment):
        audit["degraded"].append("stale_priors")
        return items, audit

    try:
        insufficient = n_samples is None or int(n_samples) < MIN_N_SAMPLES
    except (TypeError, ValueError):
        insufficient = True
    if insufficient:
        audit["degraded"].append("insufficient_samples")
        return items, audit

    if not factors:
        audit["degraded"].append("empty_factors")
        return items, audit

    audit["unmapped_factor_count"] = _count_unmapped(factors)
    try:
        adjusted = apply_factor_priors_overlay(items, factors, coef)
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("50 先验 overlay 失败（回退原始 paths）: %s", exc)
        audit["degraded"].append("overlay_error")
        return items, audit

    modulated = sum(
        1
        for before, after in zip(items, adjusted, strict=False)
        if before.confidence != after.confidence
    )
    audit["modulated_paths"] = modulated
    audit["modulation_rate"] = round(modulated / len(items), 4) if items else 0.0
    return adjusted, audit
