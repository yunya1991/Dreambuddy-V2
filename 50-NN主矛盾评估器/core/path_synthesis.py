"""evidence → path 合成（50 SPEC §4.1a，R0-07）。

只做纯函数：不读文件、不写状态，便于 differential harness 复用。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from core.mappings import (
    DEFAULT_DIMENSION,
    DEFAULT_TTL_HOURS,
    DEFAULT_WEIGHT,
    SOURCE_DIM_MAP,
    SOURCE_TF_MAP,
    SOURCE_TTL_HOURS,
    SOURCE_WEIGHT_MAP,
    VALID_DIMENSIONS,
    intent_of,
    normalize_horizon,
    normalize_source,
    role_of,
)

HORIZON_FACTOR = {"minutes": 0.25, "hours": 0.5, "days": 0.75, "weeks": 1.0}
HORIZON_PERSISTENCE = {"minutes": 0.25, "hours": 0.5, "days": 0.75, "weeks": 1.0}

DIRECTION_ALIASES = {
    "buy": "long",
    "sell": "short",
    "flat": "neutral",
    "wait": "neutral",
    "none": "neutral",
}


@dataclass(frozen=True)
class Path:
    path_id: str
    source: str
    symbol: str
    direction: str
    confidence: float
    expected_return: float
    resistance: float
    continuation_score: float
    dimension: str
    horizon: str
    intent: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _parse_ts(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_direction(value: object) -> str:
    direction = str(value or "").strip().lower()
    return DIRECTION_ALIASES.get(direction, direction)


def _freshness(
    evidence: dict[str, Any], now: datetime, source: str = ""
) -> tuple[float, list[str]]:
    degraded: list[str] = []
    expires = _parse_ts(evidence.get("expires_at"))
    if evidence.get("expires_at") is None:
        return 1.0, ["missing_expires_at"]
    if expires is None:
        return 1.0, ["invalid_expires_at"]
    if expires <= now:
        return 0.0, degraded

    started = _parse_ts(evidence.get("ts"))
    if started is None:
        return 1.0, ["missing_ts"]
    total = (expires - started).total_seconds()
    if total <= 0:
        return 1.0, ["invalid_ttl"]
    bus_freshness = _clamp((expires - now).total_seconds() / total)

    # F3（SPEC-M1 M8）：源数据年龄校验——总线新鲜不代表源数据新鲜。
    # payload 携带 state_generated_at/updated_at 时按源 TTL 指数衰减；超 2×TTL 丢弃。
    payload = evidence.get("payload") if isinstance(evidence.get("payload"), dict) else {}
    state_ts = _parse_ts(payload.get("state_generated_at") or payload.get("updated_at"))
    if state_ts is None:
        return bus_freshness, degraded
    ttl_hours = SOURCE_TTL_HOURS.get(source, DEFAULT_TTL_HOURS)
    age_hours = (now - state_ts).total_seconds() / 3600.0
    if age_hours < 0:
        age_hours = 0.0
    if age_hours > 2.0 * ttl_hours:
        return 0.0, ["source_stale"]
    source_freshness = math.exp(-age_hours / ttl_hours)
    return min(bus_freshness, source_freshness), degraded


def _dimension(source: str, hint: object, degraded: list[str]) -> str:
    value = str(hint or "").strip().upper()
    if value in VALID_DIMENSIONS:
        return value
    mapped = SOURCE_DIM_MAP.get(source)
    if mapped is None:
        degraded.append("source_unmapped")
        return DEFAULT_DIMENSION
    return mapped


def _horizon(source: str, value: object, degraded: list[str]) -> str:
    horizon = normalize_horizon(value)
    if value is not None and str(value).strip().lower() != horizon:
        degraded.append("horizon_defaulted")
    if not value:
        return SOURCE_TF_MAP.get(source, horizon)
    return horizon


def _continuation(
    intent: str,
    confidence: float,
    raw_confidence: float,
    payload: dict[str, Any],
    horizon: str,
    degraded: list[str],
) -> float:
    if intent == "reversal":
        trend_confidence = payload.get("trend_confidence")
        if trend_confidence is None:
            degraded.append("trend_confidence_missing")
            trend_confidence = raw_confidence
        return _clamp(1.0 - float(trend_confidence))
    if intent == "event_shock":
        return _clamp(confidence)
    return _clamp(confidence * HORIZON_PERSISTENCE[horizon])


def _aggregate_subpools(subpools: list, fallback_direction: str) -> tuple[float, str]:
    # R2-01（SPEC §4.8）：同源多子池未在 11 侧聚合时，50 加权聚合并按 1-dispersion 打折。
    items: list[tuple[str, float, float]] = []
    for sp in subpools:
        if not isinstance(sp, dict):
            continue
        conf = _clamp(float(sp.get("confidence") or 0.0))
        if conf <= 0:
            continue
        d = normalize_direction(sp.get("direction"))
        if d not in ("long", "short"):
            continue
        w = float(sp.get("weight") or 0.0)
        if w < 0:
            w = 0.0
        items.append((d, conf, w))
    if not items:
        return 0.0, fallback_direction
    weights = [w for _, _, w in items]
    total_w = sum(weights)
    if total_w <= 0:
        weights = [1.0] * len(items)
        total_w = float(len(items))
    signed = [conf if d == "long" else -conf for d, conf, _ in items]
    mean = sum(w * v for w, v in zip(weights, signed, strict=False)) / total_w
    dispersion = sum(w * abs(v - mean) for w, v in zip(weights, signed, strict=False)) / total_w
    confidence = _clamp(abs(mean) * (1.0 - _clamp(dispersion)))
    if mean > 0:
        direction = "long"
    elif mean < 0:
        direction = "short"
    else:
        direction = "neutral"
    return confidence, direction


def synthesize_paths(
    evidences: Iterable[dict[str, Any]],
    now: datetime | None = None,
    conflict_penalty: float = 0.0,
) -> list[Path]:
    """把 42/内部 evidence 合成为可裁决 path；同源同维度同 horizon 去重。"""
    moment = now or datetime.now(timezone.utc)
    winners: dict[tuple[str, str, str, str], Path] = {}
    counts: dict[tuple[str, str, str, str], int] = {}

    for evidence in evidences:
        if not isinstance(evidence, dict):
            continue
        source = normalize_source(evidence.get("source"))
        role = role_of(source)
        if role in ("constraint", "self_mirror"):
            continue

        raw_confidence = _clamp(float(evidence.get("confidence") or 0.0))
        if raw_confidence <= 0:
            continue

        direction = normalize_direction(evidence.get("direction"))
        if direction not in ("long", "short", "neutral"):
            continue

        freshness, degraded = _freshness(evidence, moment, source)
        if freshness <= 0:
            continue
        if role == "unknown":
            degraded.append("source_unmapped")

        horizon = _horizon(source, evidence.get("horizon"), degraded)
        payload = evidence.get("payload") if isinstance(evidence.get("payload"), dict) else {}
        # R2-01：同源多子池未聚合时，50 侧加权聚合并按 1-dispersion 打折（SPEC §4.8）
        subpools = payload.get("subpools")
        if isinstance(subpools, list) and subpools:
            raw_confidence, direction = _aggregate_subpools(subpools, direction)
            if raw_confidence <= 0:
                continue
        penalty = _clamp(float(payload.get("conflict_penalty", conflict_penalty)), 0.0, 1.0)

        confidence = _clamp(raw_confidence * freshness * (1.0 - penalty))
        if confidence <= 0:
            continue

        dimension = _dimension(source, evidence.get("dimension_hint"), degraded)
        intent = intent_of(source, evidence.get("intent"))
        symbol = str(evidence.get("symbol") or evidence.get("asset_class") or "")
        path_id = f"ev:{source}:{symbol}:{dimension}:{horizon}:{intent}"

        path = Path(
            path_id=path_id,
            source=source,
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            expected_return=_clamp(confidence * HORIZON_FACTOR[horizon]),
            resistance=_clamp(1.0 - confidence),
            continuation_score=_continuation(
                intent, confidence, raw_confidence, payload, horizon, degraded
            ),
            dimension=dimension,
            horizon=horizon,
            intent=intent,
            metadata={
                "evidence_id": evidence.get("evidence_id"),
                "provenance": evidence.get("provenance", "42-bus"),
                "granularity": evidence.get("granularity"),
                "weight": SOURCE_WEIGHT_MAP.get(source, DEFAULT_WEIGHT),
                "degraded": sorted(set(degraded)),
            },
        )

        key = (source, symbol, dimension, horizon)
        counts[key] = counts.get(key, 0) + 1
        current = winners.get(key)
        if current is None:
            winners[key] = path
        else:
            # R2-01（SPEC §4.8）：11-bdsm 42 版与内部 bridge 同源时，bus 新鲜取 bus，严禁双票。
            # freshness<=0 的证据已被过滤，存活的 bus 证据必然新鲜。
            new_bus = path.metadata.get("provenance") == "42-bus"
            cur_bus = current.metadata.get("provenance") == "42-bus"
            if new_bus and not cur_bus:
                winners[key] = path
            elif cur_bus and not new_bus:
                pass  # bus 已占位，bridge 让位
            elif path.confidence > current.confidence:
                winners[key] = path

    result = []
    for key, path in winners.items():
        metadata = dict(path.metadata)
        metadata["dedup_count"] = counts[key]
        result.append(
            Path(
                path_id=path.path_id,
                source=path.source,
                symbol=path.symbol,
                direction=path.direction,
                confidence=path.confidence,
                expected_return=path.expected_return,
                resistance=path.resistance,
                continuation_score=path.continuation_score,
                dimension=path.dimension,
                horizon=path.horizon,
                intent=path.intent,
                metadata=metadata,
            )
        )

    # F2（SPEC-M1 M3）：权重按 source 归一——path 有效权重 = source_weight / 该源当批 path 数，
    # 消除"币数放大"（如 26 条 bcrm-tactical path 总权重 9.10 压垮裁决），单 path 权重截断 [0,1]。
    per_source: dict[str, int] = {}
    for path in result:
        per_source[path.source] = per_source.get(path.source, 0) + 1
    normalized: list[Path] = []
    for path in result:
        raw_weight = float(path.metadata.get("weight") or 0.0)
        effective = _clamp(raw_weight / max(per_source[path.source], 1))
        metadata = dict(path.metadata)
        metadata["weight_raw"] = raw_weight
        metadata["weight"] = effective
        metadata["source_path_count"] = per_source[path.source]
        normalized.append(
            Path(
                path_id=path.path_id,
                source=path.source,
                symbol=path.symbol,
                direction=path.direction,
                confidence=path.confidence,
                expected_return=path.expected_return,
                resistance=path.resistance,
                continuation_score=path.continuation_score,
                dimension=path.dimension,
                horizon=path.horizon,
                intent=path.intent,
                metadata=metadata,
            )
        )
    return sorted(normalized, key=lambda item: (-item.confidence, item.path_id))
