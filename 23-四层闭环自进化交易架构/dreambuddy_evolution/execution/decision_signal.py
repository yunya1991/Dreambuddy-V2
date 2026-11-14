"""FinalDecisionSignal 生产器 + 22 网关提交器（23 独立执行出口）。

职责边界（SPEC M1）：
- 23 决定方向 / 置信度 / 名义仓位 / SL-TP 提示 / decision_id / expires_at；
- 22-执行引擎中心 TradeExecutionGateway 是唯一执行者（13 风控 → 16 定容 → 交易所）；
- 本模块不 import 任何交易所客户端，网关由调用方注入，便于单测与后续 23 直连。

decision_id 必填（22 网关对 source=23-evolution 强校验），expires_at 过期即拒。
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .outbox import STATE_SUBMITTING, SUCCESS_STATES

logger = logging.getLogger(__name__)

SOURCE = "23-evolution"

_RUNTIME_DIR = Path(__file__).resolve().parents[2] / "runtime"
_TTL_MIN = float(os.getenv("EVOLUTION_SIGNAL_TTL_MIN", "15"))

# tier 分层 SL/TP（与 11 执行侧原逻辑对齐：ATR 倍数 + 硬下限）
_TIER_SL_ATR_MULT = {"probe": 4.0, "standard": 4.5, "trend": 5.0}
_TIER_TP_PCT = {"probe": 0.12, "standard": 0.135, "trend": 0.15}
_SL_FLOOR_PCT = 0.04
_TP_FLOOR_PCT = 0.12


def _utc_now(now: datetime | None = None) -> datetime:
    if now is not None:
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_decision_id(symbol: str, action: str, ts: datetime) -> str:
    return f"dec-23-{symbol}-{action}-{ts.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"


def compute_sl_tp_pct(
    tier: str = "standard",
    atr_pct: float = 0.0,
    sl_floor_pct: float = _SL_FLOOR_PCT,
    tp_floor_pct: float = _TP_FLOOR_PCT,
) -> tuple[float, float]:
    """按 tier + ATR 计算 SL/TP 价格间距（小数，如 0.045=4.5%）。

    atr_pct <= 0 时只返回硬下限，保证低波环境不被扫损。
    """
    _tier = str(tier or "standard").lower()
    _atr = max(0.0, float(atr_pct or 0.0))
    _mult = _TIER_SL_ATR_MULT.get(_tier, _TIER_SL_ATR_MULT["standard"])
    _tp = _TIER_TP_PCT.get(_tier, _TIER_TP_PCT["standard"])
    sl_pct = max(float(sl_floor_pct), _atr * _mult) if _atr > 0 else float(sl_floor_pct)
    tp_pct = max(float(tp_floor_pct), _tp)
    return round(sl_pct, 6), round(tp_pct, 6)


def build_entry_decision(
    symbol: str,
    direction: str,
    confidence: float,
    notional_usdt: float,
    tier: str = "standard",
    price: float = 0.0,
    atr_pct: float = 0.0,
    sl_pct: float | None = None,
    tp_pct: float | None = None,
    reason: str = "",
    source_tag: str = "",
    strategy: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """构造 23 域开仓 FinalDecisionSignal。

    direction: long / short；notional_usdt 为 23 决策后的目标名义仓位。
    price > 0 时补 sl_px/tp_px；否则由执行侧按 px 兜底。
    """
    _dir = "long" if str(direction).lower() in ("long", "buy", "up") else "short"
    _ts = _utc_now(now)
    _did = _new_decision_id(symbol, "open", _ts)
    _sl_pct_calc, _tp_pct_calc = compute_sl_tp_pct(tier, atr_pct)
    _sl = float(sl_pct) if sl_pct is not None else _sl_pct_calc
    _tp = float(tp_pct) if tp_pct is not None else _tp_pct_calc
    _px = float(price or 0.0)

    sl_px: float | None = None
    tp_px: float | None = None
    if _px > 0:
        if _dir == "long":
            sl_px = round(_px * (1.0 - _sl), 8)
            tp_px = round(_px * (1.0 + _tp), 8)
        else:
            sl_px = round(_px * (1.0 + _sl), 8)
            tp_px = round(_px * (1.0 - _tp), 8)

    return {
        "signal_id": f"{SOURCE}|{_did}",
        "decision_id": _did,
        "source": SOURCE,
        "symbol": str(symbol),
        "direction": _dir,
        "confidence": float(confidence or 0.0),
        "expires_at": _iso(_ts + timedelta(minutes=_TTL_MIN)),
        "action": "open",
        "pos_side": _dir,
        "sl_px": sl_px,
        "tp_px": tp_px,
        "reason": reason or f"23-evolution open {symbol} {_dir}",
        "payload": {
            "decision_id": _did,
            "domain": "23",
            "tag": "evo23",
            "notional_usdt": float(notional_usdt or 0.0),
            "tier": str(tier),
            "sl_pct": _sl,
            "tp_pct": _tp,
            "atr_pct": float(atr_pct or 0.0),
            "source_tag": str(source_tag or ""),
            "strategy": str(strategy or ""),
        },
    }


def build_exit_decision(
    symbol: str,
    direction: str,
    sz: float | None = None,
    notional_usdt: float = 0.0,
    reduce_ratio: float = 1.0,
    reason: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """构造 23 域平仓/减仓 FinalDecisionSignal。

    direction 表示「待平的持仓方向」（long/short），action 由 reduce_ratio 决定。
    """
    _dir = "long" if str(direction).lower() in ("long", "buy", "up") else "short"
    _ratio = max(0.0, min(float(reduce_ratio or 1.0), 1.0))
    _action = "close" if _ratio >= 0.999 else "reduce"
    _ts = _utc_now(now)
    _did = _new_decision_id(symbol, _action, _ts)
    return {
        "signal_id": f"{SOURCE}|{_did}",
        "decision_id": _did,
        "source": SOURCE,
        "symbol": str(symbol),
        "direction": _dir,
        "confidence": 1.0,
        "expires_at": _iso(_ts + timedelta(minutes=_TTL_MIN)),
        "action": _action,
        "pos_side": _dir,
        "sz": sz,
        "reason": reason or f"23-evolution {_action} {symbol} {_dir}",
        "payload": {
            "decision_id": _did,
            "domain": "23",
            "tag": "evo23",
            "notional_usdt": float(notional_usdt or 0.0),
            "reduce_ratio": _ratio,
        },
    }


class EvolutionSignalDispatcher:
    """把 23 决策提交给 22 执行网关，并落本地决策审计。

    gateway 需提供 ``submit(dict) -> ExecutionResult``（22 TradeExecutionGateway）。
    gateway=None 时只记录决策并返回失败，便于离线/单测环境。
    """

    def __init__(
        self,
        gateway: Any = None,
        runtime_dir: str | Path | None = None,
        outbox: Any = None,
    ) -> None:
        self._gateway = gateway
        self._runtime_dir = Path(runtime_dir) if runtime_dir else _RUNTIME_DIR
        # outbox=None → 不做持久化幂等（仅 22 网关进程内缓存兜底）
        self._outbox = outbox

    def _append_audit(self, record: dict[str, Any]) -> None:
        try:
            self._runtime_dir.mkdir(parents=True, exist_ok=True)
            path = self._runtime_dir / "execution_decisions.jsonl"
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:  # noqa: BLE001 — 审计失败不阻断交易
            logger.debug("[FO] execution decision audit write fail: %s", e)

    def dispatch(self, decision: dict[str, Any]) -> dict[str, Any]:
        """提交决策；返回归一化结果（ok/executed/reason/reason_code/order_result）。"""
        _did = decision.get("decision_id")
        self._append_audit(
            {
                "ts": _iso(_utc_now()),
                "stage": "submit",
                "decision_id": _did,
                "symbol": decision.get("symbol"),
                "direction": decision.get("direction"),
                "action": decision.get("action"),
                "notional_usdt": (decision.get("payload") or {}).get("notional_usdt"),
                "gateway_present": self._gateway is not None,
                "outbox_present": self._outbox is not None,
            }
        )

        if self._gateway is None:
            return {
                "ok": False,
                "executed": False,
                "reason": "no_gateway_injected",
                "reason_code": "NO_GATEWAY",
                "decision_id": _did,
            }

        if self._outbox is not None and _did:
            try:
                _gate = self._outbox_gate(str(_did), decision)
            except Exception as e:  # noqa: BLE001 — outbox 异常 FAIL-OPEN，回退直提
                logger.warning("[23-evolution] outbox gate fail (fail-open): %s", e)
                _gate = None
            if _gate is not None:
                return _gate

        return self._submit_now(decision)

    def _outbox_gate(self, decision_id: str, decision: dict[str, Any]) -> dict[str, Any] | None:
        """抢占提交权。返回 dict 表示短路（重复/在途/重试耗尽），None 表示可提交。"""
        _status = self._outbox.enqueue(decision)
        if _status == "duplicate":
            _row = self._outbox.get(decision_id) or {}
            _state = str(_row.get("state") or "")
            if _state in SUCCESS_STATES:
                _cached = _row.get("result") if isinstance(_row.get("result"), dict) else {}
                return {
                    "ok": True,
                    "passed": True,
                    "executed": True,
                    "cached": True,
                    "reason": f"duplicate_decision_{_state}",
                    "reason_code": "DUPLICATE_DECISION",
                    "order_result": _cached.get("order_result"),
                    "sltp_result": _cached.get("sltp_result"),
                    "decision_id": decision_id,
                }
            if _state == STATE_SUBMITTING:
                return {
                    "ok": False,
                    "passed": False,
                    "executed": False,
                    "reason": "decision_in_flight",
                    "reason_code": "IN_FLIGHT",
                    "decision_id": decision_id,
                }

        if not self._outbox.try_acquire(decision_id):
            _row = self._outbox.get(decision_id) or {}
            return {
                "ok": False,
                "passed": False,
                "executed": False,
                "reason": f"outbox_retry_exhausted:{_row.get('state')}",
                "reason_code": "RETRY_EXHAUSTED",
                "attempts": _row.get("attempts"),
                "decision_id": decision_id,
            }
        return None

    def _submit_now(self, decision: dict[str, Any]) -> dict[str, Any]:
        _did = decision.get("decision_id")
        try:
            result = self._gateway.submit(decision)
        except Exception as e:  # noqa: BLE001 — 网关异常视为执行失败（fail-closed 语义）
            logger.warning("[23-evolution] gateway submit exception: %s", e)
            self._mark_failed(_did, f"gateway_exception:{e}")
            return {
                "ok": False,
                "executed": False,
                "reason": f"gateway_exception:{e}",
                "reason_code": "GATEWAY_EXCEPTION",
                "decision_id": _did,
            }

        executed = bool(getattr(result, "executed", False))
        out = {
            "ok": executed,
            "passed": bool(getattr(result, "passed", False)),
            "executed": executed,
            "reason": str(getattr(result, "reason", "")),
            "reason_code": str(getattr(result, "reason_code", "")),
            "order_result": getattr(result, "order_result", None),
            "sltp_result": getattr(result, "sltp_result", None),
            "decision_id": _did,
        }
        if executed:
            self._mark_submitted(_did, out)
        else:
            self._mark_failed(_did, out["reason"] or out["reason_code"] or "not_executed")
        return out

    def _mark_submitted(self, decision_id: Any, result: dict[str, Any]) -> None:
        if self._outbox is None or not decision_id:
            return
        try:
            self._outbox.mark_submitted(str(decision_id), result)
        except Exception as e:  # noqa: BLE001 — 落库失败不阻断已成交订单
            logger.debug("[23-evolution] outbox mark_submitted fail: %s", e)

    def _mark_failed(self, decision_id: Any, error: str) -> None:
        if self._outbox is None or not decision_id:
            return
        try:
            self._outbox.mark_failed(str(decision_id), error)
        except Exception as e:  # noqa: BLE001
            logger.debug("[23-evolution] outbox mark_failed fail: %s", e)
