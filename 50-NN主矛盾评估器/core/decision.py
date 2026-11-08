# R3-01: FinalDecisionSignal v1（50 SPEC，source=50-nn）。
#
# 整合 R2 成果：path 合成 + 4 维裁决 + Dominance 主导者 + 约束钳位 + 执行权校验。
# 纯函数：不读文件、不写状态；执行权校验由调用方传入 rights/mandate/kill_switch。
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from adapters.constraint_loader import clamp_position, load_constraints
from adapters.execution_writer import validate_execution
from core.dominance import resolve_dominance
from core.path_synthesis import synthesize_paths
from core.w4 import adjudicate


def make_decision(
    evidences: list[dict[str, Any]],
    symbol: str = "MULTI",
    asset_class: str = "crypto_usdt",
    constraints: dict[str, Any] | None = None,
    rights: dict[str, Any] | None = None,
    mandate: str | None = None,
    kill_switch: bool | None = None,
    reconciliation: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    # 50 决策主入口：evidence -> path -> w4 裁决 -> dominance -> 约束钳位 -> 执行权校验。
    moment = now or datetime.now(timezone.utc)
    if constraints is None:
        constraints = load_constraints()
    # 1) path 合成（含去重/多子池聚合/bus 择一）
    paths = synthesize_paths(evidences, now=moment)
    # 2) 4 维裁决
    w4 = adjudicate(paths, reconciliation)
    # 3) Dominance（同 horizon 成对支配 + Copeland）
    dominance = resolve_dominance(paths)
    # 4) 方向与置信度：w4 force 主导，dominance leader 辅助标注
    direction = w4["direction"]
    confidence = w4["total"]
    # 5) 约束钳位（只钳位，不进矛盾评分）
    raw_position = 50.0 + 50.0 * (confidence if direction == "long" else -confidence if direction == "short" else 0.0)
    position_pct = clamp_position(constraints, raw_position, asset_class)
    # 6) 组装决策信号
    decision = {
        "signal_id": f"50-nn|{moment.strftime(chr(37) + chr(89) + chr(37) + chr(109) + chr(37) + chr(100) + chr(84) + chr(37) + chr(72) + chr(37) + chr(77) + chr(37) + chr(83) + chr(90))}",
        "source": "50-nn",
        "ts": moment.isoformat().replace("+00:00", "Z"),
        "symbol": symbol,
        "asset_class": asset_class,
        "direction": direction,
        "confidence": round(confidence, 6),
        "horizon": "hours",
        "position_pct": round(position_pct, 4),
        "mode": "shadow",
        "shadow": True,
        "payload": {
            "w4": w4,
            "dominance": {
                "overall_leader": dominance["overall_leader"],
                "overall_fallback_argmax": dominance["overall_fallback_argmax"],
            },
            "constraint_freeze": constraints.get("freeze", False),
            "constraint_degraded": constraints.get("degraded", []),
            "path_count": len(paths),
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
    # 7) 执行权校验（fail-closed：kill-switch/execution_rights/Mandate）
    validation = validate_execution(
        decision,
        rights if rights is not None else {},
        mandate=mandate,
        kill_switch=kill_switch,
    )
    decision["execution"] = {
        "outcome": validation["outcome"],
        "allowed": validation["allowed"],
        "reason": validation["reason"],
    }
    return decision
