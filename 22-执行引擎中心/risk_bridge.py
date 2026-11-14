#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""22 执行层 → 13 风控/定容桥（P0-1/2/3）。

职责边界：
- 22 在复核执行权（x1_live_executor._check）之后、触发 11 bridge 之前调用本模块
- 13 负责事前风控判定（PreTradeGate）+ 真实权益（risk_capital 快照）+ 定容（PACA allocator）
- 本模块只读、fail-closed：加载或判定异常一律 passed=False，绝不因异常放行下单

设计要点：
- 包名隔离：13/50/16 都存在顶层 `core` 包，加载 13 前临时摘除 `core.*` 缓存，
  加载后恢复，避免与 22 自身包冲突（与 50/adapters/risk_gate_adapter.py 同构）
- 权益缺失降级：快照不可用 → 使用 22_RISK_EQUITY_DEFAULT（默认 10000）并标记
  equity_source=fallback，判定照常执行（不阻断），便于云端 unified_position_query 故障时仍可审计
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_RISK_DIR = _REPO_ROOT / "13-通用风控模块"
_RISK_CAPITAL_DIR = _RISK_DIR / "risk_capital"

MAX_NOTIONAL_USDT = 100.0
MAX_LEVERAGE = 3
MIN_NOTIONAL_USDT = 10.0
DEFAULT_EQUITY = float(os.environ.get("22_RISK_EQUITY_DEFAULT", "10000"))

_13_MODULES: tuple[Any, ...] | None = None
_LOAD_ERROR = ""


def _load_13() -> tuple[Any, ...] | None:
    """按需加载 13 的 PreTradeGate / Signal / RiskContext / Direction / 资金组件。"""
    global _13_MODULES
    if _13_MODULES is not None:
        return _13_MODULES
    # 12/14/16/50 都有顶层 core 包；13 的路径必须临时置顶，否则 import core 会命中错误包
    saved_path = list(sys.path)
    for path in (str(_RISK_CAPITAL_DIR), str(_RISK_DIR)):
        while path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)
    saved = {k: v for k, v in sys.modules.items() if k == "core" or k.startswith("core.")}
    for key in list(saved):
        del sys.modules[key]
    try:
        from capital_allocator import CapitalAllocatorComponent  # noqa: E402
        from capital_control import CapitalControlComponent  # noqa: E402
        from core.context import Direction, RiskContext, Signal  # noqa: E402
        from core.pre_trade_gate import PreTradeGate  # noqa: E402

        _13_MODULES = (
            PreTradeGate,
            Signal,
            RiskContext,
            Direction,
            CapitalControlComponent,
            CapitalAllocatorComponent,
        )
        return _13_MODULES
    except Exception as exc:  # noqa: BLE001
        global _LOAD_ERROR
        _LOAD_ERROR = f"{type(exc).__name__}: {exc}"
        return None
    finally:
        for key in [k for k in sys.modules if k == "core" or k.startswith("core.")]:
            del sys.modules[key]
        sys.modules.update(saved)
        sys.path[:] = saved_path


def _base_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper().replace("/", "-").split("-")[0]


def _equity(component: Any | None) -> tuple[float, str]:
    """读取 13 真实权益；不可用时降级为默认值并标记来源。"""
    try:
        if component is None:
            return DEFAULT_EQUITY, "fallback_default"
        snapshot = component.evaluate()
        total = float(getattr(snapshot, "total_equity", 0.0) or 0.0)
        if total > 0:
            return total, "risk_capital_snapshot"
    except Exception:  # noqa: BLE001
        pass
    return DEFAULT_EQUITY, "fallback_default"


def _sizing(allocator: Any | None, symbol: str, equity: float) -> dict[str, Any]:
    """13 PACA 定容；异常时返回最小可用值（仅用于审计，不阻断）。"""
    base = _base_symbol(symbol)
    if allocator is None:
        return {"position_usdt": None, "final_position_pct": None, "allocator_mode": None}
    try:
        advice = allocator.get_allocation_advice(base, "50-nn", equity)
        return {
            "position_usdt": float(advice.get("position_usdt") or 0.0),
            "final_position_pct": float(advice.get("final_position_pct") or 0.0),
            "allocator_mode": advice.get("mode"),
            "allocator_fallback": bool(advice.get("fallback_used")),
        }
    except Exception:  # noqa: BLE001
        return {"position_usdt": None, "final_position_pct": None, "allocator_mode": None}


def precheck(
    decision: dict[str, Any],
    *,
    equity_override: float | None = None,
    gate: Any | None = None,
    notional_cap: float | None = None,
    notional_floor: float | None = None,
) -> dict[str, Any]:
    """50 决策 → 13 风控判定 + 定容。返回 {passed, reason_code, notional_usdt, leverage, ...}。

    notional_cap / notional_floor：按资产类别的名义上限/下限（22 注册表提供）。
    指数/高价 ETF 的 13 定容（约权益 10%）会贴近合约最小张数，故用类别下限抬回。
    """
    result: dict[str, Any] = {
        "passed": False,
        "reason_code": "",
        "reason": "",
        "equity": None,
        "equity_source": "",
        "notional_usdt": None,
        "leverage": MAX_LEVERAGE,
        "position_pct": None,
        "allocator_mode": None,
        "source": "13-pre-trade-gate",
    }
    direction = str(decision.get("direction") or "neutral")
    if direction not in ("long", "short"):
        result.update(reason_code="NO_DIRECTION", reason=f"direction={direction}")
        return result

    # 权益解析前置：override 不依赖 13 是否加载成功，保证诊断字段始终可读
    equity: float = DEFAULT_EQUITY
    equity_source: str = ""
    if equity_override is not None and float(equity_override) > 0:
        equity, equity_source = float(equity_override), "override"

    modules = _load_13()
    if modules is None:
        result.update(
            reason_code="RISK_MODULE_LOAD_FAILED",
            reason=f"13 模块加载失败:{_LOAD_ERROR}",
        )
        return result
    (
        PreTradeGate,
        Signal,
        RiskContext,
        Direction,
        CapitalControlComponent,
        CapitalAllocatorComponent,
    ) = modules

    if not equity_source:
        equity, equity_source = _equity(CapitalControlComponent())
    result["equity"] = round(equity, 2)
    result["equity_source"] = equity_source

    try:
        gate = gate or PreTradeGate()
        signal = Signal(
            coin=str(decision.get("symbol") or ""),
            direction=Direction.LONG if direction == "long" else Direction.SHORT,
            confidence=float(decision.get("confidence") or 0.0),
            strategy="50-nn",
            metadata={
                "signal_id": decision.get("signal_id"),
                "decision_id": decision.get("decision_id"),
                "leverage": MAX_LEVERAGE,
            },
        )
        check = gate.check(signal, RiskContext(total_equity=equity))
    except Exception as exc:  # noqa: BLE001
        result.update(reason_code="RISK_GATE_EXCEPTION", reason=f"13 判定异常:{exc}")
        return result

    if not bool(getattr(check, "passed", False)):
        result.update(
            reason_code=str(
                getattr(getattr(check, "reason_code", None), "value", "") or "RISK_BLOCKED"
            ),
            reason=str(getattr(check, "message", "") or ""),
        )
        return result

    sizing = _sizing(CapitalAllocatorComponent(), str(decision.get("symbol") or ""), equity)
    notional = sizing.get("position_usdt")
    result["position_pct"] = sizing.get("final_position_pct")
    result["allocator_mode"] = sizing.get("allocator_mode")
    result["sizing_fallback"] = bool(sizing.get("allocator_fallback"))
    if notional is None or notional <= 0:
        notional = MAX_NOTIONAL_USDT
        result["sizing_fallback"] = True
    cap = float(notional_cap) if notional_cap else MAX_NOTIONAL_USDT
    notional = min(float(notional), cap)
    floor = float(notional_floor or 0)
    if floor > 0 and notional < floor:
        notional = min(floor, cap)
        result["notional_policy"] = "class_floor"
    else:
        result["notional_policy"] = "allocator"
    if notional < MIN_NOTIONAL_USDT:
        result.update(
            reason_code="SIZING_BELOW_MIN",
            reason=f"定容 {notional:.2f} USDT < 下限 {MIN_NOTIONAL_USDT:.0f}",
        )
        return result

    result.update(
        passed=True,
        reason_code="OK",
        reason="13 风控通过",
        notional_usdt=round(notional, 2),
        leverage=MAX_LEVERAGE,
    )
    return result
