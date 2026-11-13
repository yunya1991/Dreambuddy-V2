"""shadow 决策占位：聚合 path → 不执行的 50-nn 信号（供审计与后续裁决层消费）。"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from adapters.constraint_loader import clamp_position
from adapters.execution_writer import load_rights, validate_execution

from core.path_synthesis import synthesize_paths

# 组合级/非交易占位符号：不产出 per-symbol 决策（40 域按 base asset 建索引，这类符号无对应意图）
_AGGREGATE_SYMBOLS = {"MULTI", "MACRO", "DEFAULT", "PORTFOLIO"}
# per-symbol 决策有效期（40 域 decision_source.max_age_hours 默认 24h，与其对齐）
_PER_SYMBOL_TTL_HOURS = 24
_BASE_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,12}$")


def _base_symbol(symbol: object) -> str | None:
    """分组键：BTC-USDT-SWAP / BTC/USDT / BTC → BTC；组合级占位符返回 None。"""
    text = str(symbol or "").strip().upper().replace("/", "-")
    base = text.split("-")[0]
    if not _BASE_SYMBOL_RE.match(base or ""):
        return None
    if base in _AGGREGATE_SYMBOLS:
        return None
    return base


def _signed_score(path) -> float:
    if path.direction == "long":
        return path.confidence * path.expected_return
    if path.direction == "short":
        return -path.confidence * path.expected_return
    return 0.0


def make_shadow_decision(
    evidences: list[dict[str, Any]],
    constraints: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = now or datetime.now(timezone.utc)
    paths = synthesize_paths(evidences, now=moment)

    score = sum(_signed_score(p) for p in paths)
    if score > 0:
        direction = "long"
    elif score < 0:
        direction = "short"
    else:
        direction = "neutral"

    confidence = min(1.0, sum(abs(p.confidence * p.expected_return) for p in paths))
    raw_position = 50.0 + 50.0 * score  # 粗映射到 [0,100]，用于约束钳位展示
    asset_class = "crypto_usdt"  # TODO: 由 per-asset 决策补齐
    position_pct = clamp_position(constraints, raw_position, asset_class)

    decision = {
        "signal_id": f"50-nn|shadow|{moment.strftime('%Y%m%dT%H%M%SZ')}",
        "source": "50-nn",
        "ts": moment.isoformat().replace("+00:00", "Z"),
        "symbol": "MULTI",  # 暂为组合级；R1 拆到 per-symbol
        "direction": direction,
        "confidence": round(confidence, 6),
        "horizon": "hours",
        "risk_exposure_hint": 0.0,
        "expires_at": "",
        "mode": "shadow",
        "shadow": True,
        "payload": {
            "path_count": len(paths),
            "score": round(score, 6),
            "position_pct": round(position_pct, 4),
            "constraint_freeze": constraints.get("freeze", False),
            "constraint_degraded": constraints.get("degraded", []),
            "paths": [
                {
                    "path_id": p.path_id,
                    "source": p.source,
                    "direction": p.direction,
                    "confidence": round(p.confidence, 6),
                    "dimension": p.dimension,
                    "horizon": p.horizon,
                    "intent": p.intent,
                }
                for p in paths
            ],
        },
    }
    # G12：shadow 决策同样走执行权校验（fail-closed），
    # 回填 execution_rights / kill_switch / mandate_id 字段。
    validation = validate_execution(decision, load_rights())
    decision["execution"] = {
        "outcome": validation["outcome"],
        "allowed": validation["allowed"],
        "reason": validation["reason"],
    }
    return decision


def build_symbol_decisions(
    evidences: list[dict[str, Any]],
    constraints: dict[str, Any],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """按 base asset 拆分 shadow 决策（40 域 decision_id 回写的最低粒度要求）。

    组合级决策（symbol=MULTI）无法被 40 域 `load_decision_index` 按标的索引，
    导致意图流 decision_id 恒为 null。这里在同一批 path 上按 base asset 再产出
    一组 per-symbol 决策（只做分组聚合，不引入新方向/新置信度推断），供 40 域
    DEC-BCL-06 路径 B 精确映射。组合级决策保持不变。

    fail-open：无可用标的时返回空列表。
    """
    moment = now or datetime.now(timezone.utc)
    try:
        paths = synthesize_paths(evidences, now=moment)
    except Exception:  # noqa: BLE001
        return []

    groups: dict[str, list[Any]] = {}
    for p in paths:
        base = _base_symbol(p.symbol)
        if base is None:
            continue
        groups.setdefault(base, []).append(p)
    if not groups:
        return []

    ts = moment.isoformat().replace("+00:00", "Z")
    expires_at = (
        (moment + timedelta(hours=_PER_SYMBOL_TTL_HOURS)).isoformat().replace("+00:00", "Z")
    )
    rights = load_rights()
    decisions: list[dict[str, Any]] = []
    for symbol, items in sorted(groups.items()):
        score = sum(_signed_score(p) for p in items)
        if score > 0:
            direction = "long"
        elif score < 0:
            direction = "short"
        else:
            direction = "neutral"
        confidence = min(1.0, sum(abs(p.confidence * p.expected_return) for p in items))
        position_pct = clamp_position(
            constraints, 50.0 + 50.0 * score, "crypto_usdt"
        )  # TODO: asset_class 由标的映射表补齐
        decision = {
            "signal_id": f"50-nn|shadow:{symbol}|{moment.strftime('%Y%m%dT%H%M%SZ')}",
            "source": "50-nn",
            "ts": ts,
            "symbol": symbol,
            "direction": direction,
            "confidence": round(confidence, 6),
            "horizon": "hours",
            "risk_exposure_hint": 0.0,
            "expires_at": expires_at,
            "mode": "shadow",
            "shadow": True,
            "payload": {
                "granularity": "per_symbol",
                "path_count": len(items),
                "score": round(score, 6),
                "position_pct": round(position_pct, 4),
                "constraint_freeze": constraints.get("freeze", False),
                "constraint_degraded": constraints.get("degraded", []),
                "paths": [
                    {
                        "path_id": p.path_id,
                        "source": p.source,
                        "direction": p.direction,
                        "confidence": round(p.confidence, 6),
                        "dimension": p.dimension,
                        "horizon": p.horizon,
                        "intent": p.intent,
                    }
                    for p in items
                ],
            },
        }
        validation = validate_execution(decision, rights)
        decision["execution"] = {
            "outcome": validation["outcome"],
            "allowed": validation["allowed"],
            "reason": validation["reason"],
        }
        decisions.append(decision)
    return decisions
