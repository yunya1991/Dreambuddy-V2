# R3-01: FinalDecisionSignal v1（50 SPEC，source=50-nn）。
#
# 整合 R2 成果：path 合成 + 4 维裁决 + Dominance 主导者 + 约束钳位 + 执行权校验。
# 纯函数：不读文件、不写状态；执行权校验由调用方传入 rights/mandate/kill_switch。
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path as FsPath
from typing import Any

from adapters.constraint_loader import clamp_position, load_constraints
from adapters.execution_writer import validate_execution

from core.dominance import resolve_dominance
from core.mappings import profile_for_trigger
from core.path_synthesis import Path, synthesize_paths
from core.trigger_flap import check_trigger_flap
from core.w4 import adjudicate

# M3-2：决策落盘路径（50/runtime/decisions.jsonl）
_DECISIONS_PATH = FsPath(__file__).resolve().parents[1] / "runtime" / "decisions.jsonl"


def record_decision(decision: dict[str, Any]) -> None:
    """将决策追加到 decisions.jsonl（M3-2，fail-open）。

    为 G4（PIT≥200 决策）提供数据底座。任何 IO 异常静默忽略。
    """
    try:
        _DECISIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_DECISIONS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(decision, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


# M4-6: regime_overlay intent 权重调整（SPEC-M3 §2.2）
_REGIME_BOOST = 1.1  # 匹配 regime 的 intent 置信度 ×1.1
_REGIME_PENALTY = 0.9  # 冲突 intent 置信度 ×0.9


def _apply_regime_overlay(paths: list[Path], regime_overlay: str) -> list[Path]:
    """micro_led 链路叠加主周期判定策略类。

    - trend：trend intent 升权、reversal 降权
    - range：reversal 升权、trend 降权
    - unknown/其他：不调整
    """
    if regime_overlay not in ("trend", "range"):
        return paths
    adjusted: list[Path] = []
    for p in paths:
        factor = 1.0
        if regime_overlay == "trend":
            if p.intent == "trend":
                factor = _REGIME_BOOST
            elif p.intent == "reversal":
                factor = _REGIME_PENALTY
        else:  # range
            if p.intent == "reversal":
                factor = _REGIME_BOOST
            elif p.intent == "trend":
                factor = _REGIME_PENALTY
        if factor != 1.0:
            adjusted.append(replace(p, confidence=round(p.confidence * factor, 8)))
        else:
            adjusted.append(p)
    return adjusted


def _extract_trigger(evidences: list[dict[str, Any]]) -> str:
    """从 evidences 中提取 trigger（macro_led/micro_led），取首个有效值。"""
    for ev in evidences:
        t = ev.get("trigger")
        if not t and isinstance(ev.get("payload"), dict):
            t = ev["payload"].get("trigger")
        if isinstance(t, str) and t.strip().lower() in ("macro_led", "micro_led"):
            return t.strip().lower()
    return "default"


def _extract_regime_overlay(evidences: list[dict[str, Any]]) -> str:
    """从 evidences 中提取 regime_overlay（trend/range/unknown）。"""
    for ev in evidences:
        payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
        ro = ev.get("regime_overlay") or payload.get("regime_overlay")
        if isinstance(ro, str) and ro.strip().lower() in ("trend", "range"):
            return ro.strip().lower()
    return "unknown"


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
    mode: str = "shadow",
) -> dict[str, Any]:
    # 50 决策主入口：evidence -> path -> w4 裁决 -> dominance -> 约束钳位 -> 执行权校验。
    # mode: shadow（默认，仅审计）/ live（需 execution_rights + Mandate + kill-switch 同时放行）
    moment = now or datetime.now(timezone.utc)
    if constraints is None:
        constraints = load_constraints()

    # M4-5/M4-7：提取 trigger 并做防振荡裁决
    proposed_trigger = _extract_trigger(evidences)
    flap = check_trigger_flap(symbol, proposed_trigger, now=moment)
    trigger = flap.trigger
    weight_profile = profile_for_trigger(trigger)

    # M4-6：提取 regime_overlay（micro_led 链路叠加主周期策略类）
    regime_overlay = _extract_regime_overlay(evidences)

    # 1) path 合成（含去重/多子池聚合/bus 择一）
    paths = synthesize_paths(evidences, now=moment)
    # M4-6：regime_overlay 调整 intent 权重
    paths = _apply_regime_overlay(paths, regime_overlay)
    # 2) 4 维裁决
    w4 = adjudicate(paths, reconciliation)
    # 3) Dominance（同 horizon 成对支配 + Copeland）
    dominance = resolve_dominance(paths)
    # 4) 方向与置信度：w4 force 主导，dominance leader 辅助标注
    direction = w4["direction"]
    confidence = w4["total"]
    # 5) 约束钳位（只钳位，不进矛盾评分）
    raw_position = 50.0 + 50.0 * (
        confidence if direction == "long" else -confidence if direction == "short" else 0.0
    )
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
        "mode": mode,
        "shadow": mode != "live",
        "trigger": trigger,
        "regime_overlay": regime_overlay,
        "weight_profile": weight_profile,
        "payload": {
            "w4": w4,
            "dominance": {
                "overall_leader": dominance["overall_leader"],
                "overall_fallback_argmax": dominance["overall_fallback_argmax"],
            },
            "constraint_freeze": constraints.get("freeze", False),
            "constraint_degraded": constraints.get("degraded", []),
            "path_count": len(paths),
            "proposed_trigger": proposed_trigger,
            "trigger_flap": {
                "locked": flap.locked,
                "switches_in_window": flap.switches_in_window,
                "reason": flap.reason,
            },
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
    # M3-2：决策落盘（fail-open，为 G4 PIT 数据底座积累）
    record_decision(decision)
    return decision
