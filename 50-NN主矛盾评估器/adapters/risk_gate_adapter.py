# R3-02: 13 层风控接线适配器（50 决策 -> 13 PreTradeGate，paper 模式，fail-closed）。
#
# 零侵入：不修改 13 层任何文件；通过 sys.path 注入加载 13 层模块。
# neutral 决策不进执行链（13 层 Direction 无 neutral 枚举）。
# 任何异常 fail-closed：返回 passed=False，不执行。
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
_13_DIR = REPO_ROOT / "13-通用风控模块"


_13_MODULES: tuple[Any, Any, Any, Any] | None = None


def _load_13_modules() -> tuple[Any, Any, Any, Any] | None:
    # 按需加载 13 层模块（PreTradeGate/Signal/RiskContext/Direction）；失败返回 None。
    # 包名隔离：50/13/16 层都用顶层 core 包名，加载 13 层前临时摘除 core.*
    # 缓存，加载后恢复原状，避免与 50/16 层 core 包冲突（已创建的类对象不受影响）。
    global _13_MODULES
    if _13_MODULES is not None:
        return _13_MODULES
    if str(_13_DIR) not in sys.path:
        sys.path.insert(0, str(_13_DIR))
    saved = {k: v for k, v in sys.modules.items() if k == "core" or k.startswith("core.")}
    for k in list(saved):
        del sys.modules[k]
    try:
        from core.context import Direction, RiskContext, Signal  # noqa: E402
        from core.pre_trade_gate import PreTradeGate  # noqa: E402
        _13_MODULES = (PreTradeGate, Signal, RiskContext, Direction)
        return _13_MODULES
    except Exception:
        return None
    finally:
        for k in [k for k in sys.modules if k == "core" or k.startswith("core.")]:
            del sys.modules[k]
        sys.modules.update(saved)


def check_decision(
    decision: dict[str, Any],
    gate: Any | None = None,
    context: Any | None = None,
) -> dict[str, Any]:
    # 50 决策 -> 13 层 PreTradeGate.check（paper 模式）。
    # 返回 {passed, reason, position_modifier, source}；异常 fail-closed。
    direction = str(decision.get("direction") or "neutral")
    if direction == "neutral":
        return {"passed": False, "reason": "neutral_no_execution", "reason_code": "NEUTRAL_NO_EXECUTION", "position_modifier": 1.0, "source": "13-pre-trade-gate"}
    modules = _load_13_modules()
    if modules is None:
        return {"passed": False, "reason": "risk_module_load_failed", "reason_code": "RISK_MODULE_LOAD_FAILED", "position_modifier": 1.0, "source": "13-pre-trade-gate"}
    PreTradeGate, Signal, RiskContext, Direction = modules
    try:
        if gate is None:
            gate = PreTradeGate()
        if context is None:
            context = RiskContext(total_equity=10000.0)
        signal = Signal(
            coin=str(decision.get("symbol") or "MULTI"),
            direction=Direction.LONG if direction == "long" else Direction.SHORT,
            confidence=float(decision.get("confidence") or 0.0),
            strategy="50-nn",
            metadata={
                "signal_id": decision.get("signal_id"),
                "position_pct": decision.get("position_pct"),
                "execution_outcome": (decision.get("execution") or {}).get("outcome"),
                "shadow": decision.get("shadow", True),
            },
        )
        result = gate.check(signal, context)
        return {
            "passed": bool(result.passed),
            "reason": str(result.message or ""),
            "reason_code": str(getattr(result.reason_code, "value", "")),
            "position_modifier": float(getattr(result, "position_modifier", 1.0) or 1.0),
            "source": "13-pre-trade-gate",
        }
    except Exception as exc:
        return {"passed": False, "reason": f"risk_gate_exception:{exc}", "reason_code": "RISK_GATE_EXCEPTION", "position_modifier": 1.0, "source": "13-pre-trade-gate"}
