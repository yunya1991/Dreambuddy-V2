"""shadow 决策占位：聚合 path → 不执行的 50-nn 信号（供审计与后续裁决层消费）。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from adapters.constraint_loader import clamp_position

from core.path_synthesis import synthesize_paths
from adapters.execution_writer import load_rights, validate_execution


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
