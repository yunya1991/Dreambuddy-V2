"""TradeExecutionGateway — 统一交易执行入口（P0 / AC-1 / AC-6）。

收口所有 live/paper 下单路径，强制经 13-通用风控模块 PreTradeGate 校验：
  decision → 13 PreTradeGate.check() → 16 定容上限 → 22 tee/raw 执行
                                  └→ reject → 阻断（fail-closed）

fail-closed 语义：
  - 13 模块加载失败 / check 抛异常 → 开仓请求 reject，平仓/减仓请求 allow
  - neutral 方向 → 不下单（13 Direction 无 neutral 枚举）

零侵入：不修改 13 层任何文件；通过 sys.path 隔离加载 13 层模块
（与 50-NN主矛盾评估器/adapters/risk_gate_adapter.py 同构）。

NFR-4 依赖倒置：本模块不 import 任何策略层的 concrete OkxClient；
调用方负责构造 raw_client（real/paper/mock）并通过构造器注入。
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
_13_DIR = REPO_ROOT / "13-通用风控模块"

logger = logging.getLogger("trade_execution_gateway")

# 平仓/减仓动作白名单（13 不可用时仍允许执行，避免持仓裸奔）
_CLOSE_ACTIONS = {"close", "reduce", "reduce_only", "take_profit", "stop_loss"}


@dataclass
class FinalDecisionSignal:
    """FinalDecisionSignal v1.1 轻量 Python 表示（核心字段 + 执行扩展）。

    与 49-交易框架协议/contracts/final_decision_signal.v1.1.json 对齐。
    执行扩展字段（sz/px/pos_side/action）由调用方填充，不进 49 契约。
    """

    signal_id: str
    source: str  # 23-evolution / 50-nn / 11-yijing / 6-trading / ...
    symbol: str  # e.g. BTC-USDT-SWAP
    direction: str  # long / short / neutral
    confidence: float = 0.0
    expires_at: str = ""
    # ── 执行扩展 ──────────────────────────────────────────────
    action: str = "open"  # open / close / reduce / stop_loss / take_profit
    sz: Optional[float] = None
    px: Optional[float] = None
    pos_side: Optional[str] = None  # long / short / net
    sl_px: Optional[float] = None  # 止损价（algo order）
    tp_px: Optional[float] = None  # 止盈价（algo order）
    reason: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FinalDecisionSignal":
        return cls(
            signal_id=str(d.get("signal_id") or f"sig-{uuid.uuid4().hex[:12]}"),
            source=str(d.get("source") or "unknown"),
            symbol=str(d.get("symbol") or d.get("inst_id") or "MULTI"),
            direction=str(d.get("direction") or "neutral").lower(),
            confidence=float(d.get("confidence") or 0.0),
            expires_at=str(d.get("expires_at") or ""),
            action=str(d.get("action") or "open").lower(),
            sz=d.get("sz"),
            px=d.get("px"),
            pos_side=d.get("pos_side"),
            sl_px=d.get("sl_px"),
            tp_px=d.get("tp_px"),
            reason=str(d.get("reason") or ""),
            payload=d.get("payload") if isinstance(d.get("payload"), dict) else {},
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "source": self.source,
            "symbol": self.symbol,
            "direction": self.direction,
            "confidence": self.confidence,
            "expires_at": self.expires_at,
            "action": self.action,
            "sz": self.sz,
            "px": self.px,
            "pos_side": self.pos_side,
            "reason": self.reason,
        }


@dataclass
class ExecutionResult:
    passed: bool  # 13 风控是否通过
    executed: bool  # 是否实际下单
    reason: str
    reason_code: str
    position_modifier: float = 1.0
    order_result: Optional[Dict[str, Any]] = None


class RiskGatedOkxClient:
    """OkxClient 代理：所有下单入口都路由到 Gateway。

    高层开平仓/减仓必须显式拦截；若透传 raw 的绑定方法，其内部
    ``self.place_order()`` 会绕过代理。只有非交易方法/属性透传 raw_client。
    Gateway 内部持有 raw_client 引用，因此不会触发递归。

    用法：
        raw = OKXSimulatedClient(...)
        gateway = TradeExecutionGateway(okx_client=raw)
        client = RiskGatedOkxClient(raw, gateway)
        # client.place_order(...) 自动经 13 风控
    """

    def __init__(self, raw_client: Any, gateway: TradeExecutionGateway) -> None:
        object.__setattr__(self, "_raw", raw_client)
        object.__setattr__(self, "_gateway", gateway)

    # ── 拦截的交易方法 ────────────────────────────────────────────────
    def place_order(self, **kwargs: Any) -> Dict[str, Any]:
        return self._route_order(kwargs)

    def place_stop_loss_take_profit(self, **kwargs: Any) -> Dict[str, Any]:
        return self._submit_decision(self._sltp_kwargs_to_decision(kwargs))

    def market_open_long(
        self, inst_id: str = None, usdt_amount: float = None, reason: str = ""
    ) -> Dict[str, Any]:
        return self._market_open("long", inst_id, usdt_amount, reason)

    def market_open_short(
        self, inst_id: str = None, usdt_amount: float = None, reason: str = ""
    ) -> Dict[str, Any]:
        return self._market_open("short", inst_id, usdt_amount, reason)

    def market_close_long(self, inst_id: str = None, reason: str = "") -> Dict[str, Any]:
        return self._market_close("long", inst_id, reason)

    def market_close_short(self, inst_id: str = None, reason: str = "") -> Dict[str, Any]:
        return self._market_close("short", inst_id, reason)

    def reduce_position(
        self,
        inst_id: str = None,
        pos_side: str = "long",
        reduce_ratio: float = 0.5,
        reason: str = "",
    ) -> Dict[str, Any]:
        inst_id = inst_id or self._raw.cfg["default_inst_id"]
        reduce_ratio = max(0.01, min(reduce_ratio, 1.0))
        full_sz, error = self._position_sz(inst_id, pos_side, f"无 {pos_side} 持仓可减仓")
        if error is not None:
            return error
        reduce_sz = int(full_sz * reduce_ratio)
        if reduce_sz < 1:
            return {
                "ok": False,
                "error": f"减仓数量不足（持仓 {full_sz}，减仓比例 {reduce_ratio}）",
            }
        result = self._route_order(
            {
                "inst_id": inst_id,
                "side": "sell" if pos_side == "long" else "buy",
                "ord_type": "market",
                "sz": reduce_sz,
                "pos_side": pos_side,
                "td_mode": "isolated",
                "reason": reason or f"bcrm_reduce_{int(reduce_ratio * 100)}pct",
            },
            action="reduce",
        )
        result["reduce_ratio"] = reduce_ratio
        result["original_pos"] = full_sz
        result["reduce_sz"] = reduce_sz
        result["remaining_pos"] = full_sz - reduce_sz
        return result

    # ── 高层方法必须显式路由，不能透传 raw 的绑定方法 ─────────────────
    def _market_open(
        self, pos_side: str, inst_id: Optional[str], usdt_amount: Optional[float], reason: str
    ) -> Dict[str, Any]:
        inst_id = inst_id or self._raw.cfg["default_inst_id"]
        usdt_amount = usdt_amount or self._raw.cfg["default_usdt_amount"]
        sz = self._raw._usdt_to_sz(inst_id, usdt_amount)
        return self._route_order(
            {
                "inst_id": inst_id,
                "side": "buy" if pos_side == "long" else "sell",
                "ord_type": "market",
                "sz": sz,
                "pos_side": pos_side,
                "td_mode": "isolated",
                "reason": reason or f"bcrm_reasoning_open_{pos_side}",
            }
        )

    def _market_close(self, pos_side: str, inst_id: Optional[str], reason: str) -> Dict[str, Any]:
        inst_id = inst_id or self._raw.cfg["default_inst_id"]
        sz, error = self._position_sz(inst_id, pos_side, f"no {pos_side} position to close")
        if error is not None:
            return error
        return self._route_order(
            {
                "inst_id": inst_id,
                "side": "sell" if pos_side == "long" else "buy",
                "ord_type": "market",
                "sz": sz,
                "pos_side": pos_side,
                "td_mode": "isolated",
                "reason": reason or f"bcrm_reasoning_close_{pos_side}",
            }
        )

    def _position_sz(
        self, inst_id: str, pos_side: str, not_found_error: str
    ) -> tuple[Any, Optional[Dict[str, Any]]]:
        pos_data = self._raw.get_positions(inst_id)
        if not pos_data.get("ok"):
            return None, pos_data
        matched = [p for p in pos_data["positions"] if p["pos_side"] == pos_side and p["pos"] > 0]
        if not matched:
            return None, {"ok": False, "error": not_found_error}
        return matched[0]["pos"], None

    def _route_order(self, kwargs: Dict[str, Any], action: Optional[str] = None) -> Dict[str, Any]:
        decision = self._order_kwargs_to_decision(kwargs)
        if action is not None:
            decision["action"] = action
        return self._submit_decision(decision)

    def _submit_decision(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        result = self._gateway.submit(decision)
        if not result.executed:
            if result.passed and result.order_result is not None:
                return result.order_result
            return {
                "ok": False,
                "rejected": True,
                "reason": result.reason,
                "reason_code": result.reason_code,
            }
        return result.order_result or {"ok": False, "error": "no_order_result"}

    # ── 非交易方法/属性透传 ────────────────────────────────────────────
    def __getattr__(self, name: str) -> Any:
        return getattr(self._raw, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in ("_raw", "_gateway", "place_order", "place_stop_loss_take_profit"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._raw, name, value)

    # ── 转换辅助 ──────────────────────────────────────────────────────
    @staticmethod
    def _order_kwargs_to_decision(kwargs: Dict[str, Any]) -> Dict[str, Any]:
        inst_id = kwargs.get("inst_id", "MULTI")
        side = str(kwargs.get("side", "")).lower()
        pos_side = str(kwargs.get("pos_side", "")).lower()
        # 方向判定：pos_side 优先（long/short）；否则从 side 推断
        if pos_side in ("long", "short"):
            direction = pos_side
        else:
            direction = "long" if side == "buy" else "short"
        # 动作判定：side 与 pos_side 同向→开仓，反向→平仓
        if pos_side and side:
            same = (side == "buy" and pos_side == "long") or (
                side == "sell" and pos_side == "short"
            )
            action = "open" if same else "close"
        else:
            action = "open"
        decision: Dict[str, Any] = {
            "signal_id": f"11-yijing|{uuid.uuid4().hex[:12]}",
            "source": "11-yijing",
            "symbol": inst_id,
            "direction": direction,
            "confidence": 0.5,
            "action": action,
            "sz": kwargs.get("sz"),
            "px": kwargs.get("px") if kwargs.get("px") is not None else kwargs.get("price"),
            "pos_side": pos_side or None,
            "reason": str(kwargs.get("reason", "")),
        }
        return decision

    @staticmethod
    def _sltp_kwargs_to_decision(kwargs: Dict[str, Any]) -> Dict[str, Any]:
        pos_side = str(kwargs.get("pos_side", "long")).lower()
        sl_px = kwargs.get("stop_loss_px")
        tp_px = kwargs.get("take_profit_px")
        # 同时设 SL 和 TP 时按 stop_loss 归类（algo order 会一起下）
        action = "stop_loss" if sl_px is not None else "take_profit"
        return {
            "signal_id": f"11-yijing-sltp|{uuid.uuid4().hex[:12]}",
            "source": "11-yijing",
            "symbol": kwargs.get("inst_id", "MULTI"),
            "direction": pos_side if pos_side in ("long", "short") else "long",
            "confidence": 0.5,
            "action": action,
            "sz": kwargs.get("sz"),
            "sl_px": sl_px,
            "tp_px": tp_px,
            "pos_side": pos_side,
            "reason": str(kwargs.get("reason", "")),
        }


class _PaperOkxClient:
    """默认 paper 占位客户端：当调用方未注入 okx_client 时使用。

    所有下单返回 dry_run=True，不产生真实成交，保证 Gateway 可独立测试。
    """

    def place_order(self, **kwargs: Any) -> Dict[str, Any]:
        return {"ok": True, "dry_run": True, "order_id": f"paper-{uuid.uuid4().hex[:8]}", **kwargs}


_13_MODULES: Optional[tuple] = None


def _load_13_modules() -> Optional[tuple]:
    """按需加载 13 层模块（PreTradeGate / Signal / RiskContext / Direction）。

    包名隔离：11/12/13/16/50 层都用顶层 core 包名，加载 13 层前：
      1. 将 13 目录强制移到 sys.path[0]（避免被其他模块的 core 抢占）
      2. 临时摘除 sys.modules 中的 core.*，加载后恢复
    失败返回 None（调用方据此 fail-closed）。
    """
    global _13_MODULES
    if _13_MODULES is not None:
        return _13_MODULES

    # 强制 13 目录位于 sys.path 最前，确保 core 解析到 13 的 core 包
    _13_str = str(_13_DIR)
    saved_path = list(sys.path)
    sys.path[:] = [p for p in sys.path if p != _13_str]
    sys.path.insert(0, _13_str)

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
        sys.path[:] = saved_path


class TradeExecutionGateway:
    """统一交易执行入口。

    Args:
        okx_client: 交易所客户端（real/paper/mock），需暴露 place_order(**kwargs)。
            None 时使用 _PaperOkxClient（仅用于测试/降级）。
        risk_context: 13 RiskContext 实例；None 时默认 total_equity=10000。
        audit_path: 审计日志 JSONL 路径；None 时写入 22-执行引擎中心/audit/gateway.jsonl。
        capital_allocator: 16 CapitalAllocatorComponent 实例（PACA 定容）；
            None 时跳过 16 定容，使用调用方 sz。FAIL-OPEN。
        tee_engine: 22 tee_core TradingEngine 实例（OrderPort）；
            None 时直接调用 okx_client.place_order。FAIL-OPEN。
    """

    def __init__(
        self,
        okx_client: Any = None,
        risk_context: Any = None,
        audit_path: Optional[str | Path] = None,
        capital_allocator: Any = None,
        tee_engine: Any = None,
    ) -> None:
        self._okx = okx_client if okx_client is not None else _PaperOkxClient()
        self._risk_context = risk_context
        self._gate: Any = None  # 懒加载 PreTradeGate
        self._13_load_failed = False
        self._capital_allocator = capital_allocator  # 16 PACA 定容（可选）
        self._tee_engine = tee_engine  # 22 tee_core OrderPort（可选）

        if audit_path is None:
            audit_path = REPO_ROOT / "22-执行引擎中心" / "audit" / "gateway.jsonl"
        self._audit_path = Path(audit_path)
        self._audit_path.parent.mkdir(parents=True, exist_ok=True)

    # ── public API ────────────────────────────────────────────────────
    def submit(self, decision: Dict[str, Any] | FinalDecisionSignal) -> ExecutionResult:
        """提交决策执行。

        Returns:
            ExecutionResult: passed=13是否通过, executed=是否实际下单。
        """
        sig = (
            decision
            if isinstance(decision, FinalDecisionSignal)
            else FinalDecisionSignal.from_dict(decision)
        )

        # neutral 不进执行链
        if sig.direction == "neutral":
            result = ExecutionResult(
                passed=False,
                executed=False,
                reason="neutral_no_execution",
                reason_code="NEUTRAL_NO_EXECUTION",
            )
            self._audit(sig, result)
            return result

        is_close = sig.action in _CLOSE_ACTIONS

        # 13 加载失败 → fail-closed：开仓拒，平仓放行
        modules = _load_13_modules()
        if modules is None:
            self._13_load_failed = True
            if is_close:
                order_result = self._place_order(sig)
                result = ExecutionResult(
                    passed=True,
                    executed=self._order_succeeded(order_result),
                    reason="risk_module_unavailable_close_allowed",
                    reason_code="RISK_MODULE_UNAVAILABLE_CLOSE_ALLOWED",
                    order_result=order_result,
                )
            else:
                result = ExecutionResult(
                    passed=False,
                    executed=False,
                    reason="risk_module_unavailable_open_rejected",
                    reason_code="RISK_MODULE_UNAVAILABLE_OPEN_REJECTED",
                )
            self._audit(sig, result)
            return result

        PreTradeGate, Signal, RiskContext, Direction = modules
        if self._gate is None:
            self._gate = PreTradeGate()
        ctx = (
            self._risk_context
            if self._risk_context is not None
            else RiskContext(total_equity=10000.0)
        )

        # 映射到 13 Signal
        direction = Direction.LONG if sig.direction == "long" else Direction.SHORT
        signal = Signal(
            coin=sig.symbol,
            direction=direction,
            confidence=sig.confidence,
            strategy=sig.source,
            metadata={
                "signal_id": sig.signal_id,
                "action": sig.action,
                "reason": sig.reason,
                "expires_at": sig.expires_at,
            },
        )

        # 13 风控校验（异常 fail-closed）
        try:
            check = self._gate.check(signal, ctx)
        except Exception as exc:
            if is_close:
                order_result = self._place_order(sig)
                result = ExecutionResult(
                    passed=True,
                    executed=self._order_succeeded(order_result),
                    reason=f"risk_gate_exception_close_allowed:{exc}",
                    reason_code="RISK_GATE_EXCEPTION_CLOSE_ALLOWED",
                    order_result=order_result,
                )
            else:
                result = ExecutionResult(
                    passed=False,
                    executed=False,
                    reason=f"risk_gate_exception_open_rejected:{exc}",
                    reason_code="RISK_GATE_EXCEPTION_OPEN_REJECTED",
                )
            self._audit(sig, result)
            return result

        if not check.passed:
            result = ExecutionResult(
                passed=False,
                executed=False,
                reason=str(getattr(check, "message", "")),
                reason_code=str(getattr(check.reason_code, "value", check.reason_code)),
                position_modifier=float(getattr(check, "position_modifier", 1.0) or 1.0),
            )
            self._audit(sig, result)
            return result

        # 通过 → 执行下单（应用 13 position_modifier + 16 PACA 定容）
        position_modifier = float(getattr(check, "position_modifier", 1.0) or 1.0)
        # T13: 16 capital_allocator 定容（13→16→22 管道）
        # 16 输出的是 USDT 金额建议，必须按合约面值换算成张数，且只做上限约束：
        # 直接用它覆盖 sz 会把仓位放大 (px × ct_val) 倍。
        final_sz = sig.sz
        try:
            if self._capital_allocator is not None:
                _equity = float(getattr(ctx, "total_equity", 10000.0) or 10000.0)
                _cap_sz = self._allocator_cap_sz(sig, _equity)
                if _cap_sz is not None and _cap_sz > 0:
                    final_sz = _cap_sz if sig.sz is None else min(float(sig.sz), _cap_sz)
        except Exception as _paca_exc:  # noqa: BLE001 — 16 定容 FAIL-OPEN
            logger.debug("[T13] capital_allocator sizing fail, use caller sz: %s", _paca_exc)

        sig_for_exec = sig
        if final_sz != sig.sz:
            # 用 16 定容后的 sz 替换（不修改原 sig 对象）
            import dataclasses as _dc

            sig_for_exec = _dc.replace(sig, sz=final_sz)

        order_result = self._place_order(sig_for_exec, position_modifier=position_modifier)
        executed = self._order_succeeded(order_result)
        result = ExecutionResult(
            passed=True,
            executed=executed,
            reason=(
                str(getattr(check, "message", "all_gates_passed"))
                if executed
                else str(order_result.get("error") or "order_failed")
            ),
            reason_code=(
                str(getattr(check.reason_code, "value", "PASS")) if executed else "ORDER_FAILED"
            ),
            position_modifier=position_modifier,
            order_result=order_result,
        )
        self._audit(sig, result)
        return result

    # ── internals ─────────────────────────────────────────────────────
    def _allocator_cap_sz(self, sig: FinalDecisionSignal, equity: float) -> Optional[float]:
        """把 16 的 USDT 建议换算为合约张数上限。

        换算: sz = equity × final_position_pct / (px × ct_val × ct_mult)
        任一环节缺失（无合约面值 / 无价格）返回 None，调用方保持原 sz（FAIL-OPEN）。
        """
        advice = self._capital_allocator.get_allocation_advice(
            coin=sig.symbol,
            source_tag=sig.source,
            equity=equity,
        )
        if not isinstance(advice, dict) or advice.get("final_position_pct") is None:
            return None
        pct = float(advice["final_position_pct"])
        if not 0.0 < pct <= 1.0:
            return None

        px = sig.px
        if px is None:
            ticker_fn = getattr(self._okx, "get_ticker", None)
            if not callable(ticker_fn):
                return None
            px = float((ticker_fn(sig.symbol) or {}).get("last") or 0.0) or None
        if not px:
            return None

        ct_val, ct_mult = 1.0, 1.0
        instrument_fn = getattr(self._okx, "get_instrument", None)
        contract_fn = getattr(self._okx, "get_contract_info", None)
        if callable(instrument_fn):
            info = instrument_fn(sig.symbol) or {}
            if not info.get("ok", True):
                return None
            ct_val = float(info.get("ct_val") or 1.0)
            ct_mult = float(info.get("ct_mult") or 1.0)
        elif callable(contract_fn):
            _lot_sz, ct_val = contract_fn(sig.symbol)
            ct_val = float(ct_val or 1.0)
        # 两个方法都没有时按 1:1 面值处理（现货语义）

        contract_value = float(px) * ct_val * ct_mult
        if contract_value <= 0:
            return None
        return (equity * pct) / contract_value

    @staticmethod
    def _order_succeeded(order_result: Dict[str, Any]) -> bool:
        return not (isinstance(order_result, dict) and order_result.get("ok", True) is False)

    def _place_order(
        self, sig: FinalDecisionSignal, position_modifier: float = 1.0
    ) -> Dict[str, Any]:
        """调用底层交易所下单。

        - stop_loss / take_profit 动作且设置了 sl_px/tp_px → place_stop_loss_take_profit
        - 其他 → place_order（side：long→buy, short→sell；平仓时反向）
        sz 按 position_modifier 缩放。
        """
        sz = sig.sz
        if sz is not None and position_modifier != 1.0:
            sz = float(sz) * position_modifier

        # SL/TP algo 单（条件单，属于平仓管理类，13 不可用时仍允许）
        if sig.action in ("stop_loss", "take_profit") and (
            sig.sl_px is not None or sig.tp_px is not None
        ):
            fn = getattr(self._okx, "place_stop_loss_take_profit", None)
            if callable(fn):
                kwargs: Dict[str, Any] = {
                    "inst_id": sig.symbol,
                    "pos_side": sig.pos_side or ("long" if sig.direction == "long" else "short"),
                    "stop_loss_px": sig.sl_px,
                    "take_profit_px": sig.tp_px,
                    "reason": sig.reason or f"{sig.source}:{sig.signal_id}",
                }
                if sz is not None:
                    kwargs["sz"] = sz
                try:
                    return fn(**kwargs)
                except Exception as exc:
                    return {"ok": False, "error": f"place_sltp_exc:{exc}", "dry_run": False}

        side = "buy" if sig.direction == "long" else "sell"
        if sig.action in _CLOSE_ACTIONS:
            side = "sell" if sig.direction == "long" else "buy"

        kwargs = {
            "inst_id": sig.symbol,
            "side": side,
            "ord_type": "market" if sig.px is None else "limit",
            "pos_side": sig.pos_side or ("long" if sig.direction == "long" else "short"),
            "reason": sig.reason or f"{sig.source}:{sig.signal_id}",
        }
        if sz is not None:
            kwargs["sz"] = sz
        if sig.px is not None:
            # 适配不同客户端的价格参数名（OKXSimulatedClient=px, OKXCLI=price）
            price_key = self._detect_price_key()
            kwargs[price_key] = sig.px

        # T13: 22 tee_core 由 Gateway 独占持有，其 client 必须是 raw client。
        # shadow 只记录决策差异、不接管成交，必须继续走 raw 下单，
        # 否则真实订单会被吞掉（executed=True 但交易所无单）。
        _tee_compat = getattr(self._tee_engine, "execute_market_compat", None)
        _tee_shadow = bool(getattr(self._tee_engine, "shadow_mode", False))
        if callable(_tee_compat) and sz is not None:
            try:
                _tee_result = _tee_compat(
                    inst_id=sig.symbol,
                    side=side,
                    sz=sz,
                    td_mode=kwargs.get("td_mode", "isolated"),
                    pos_side=kwargs["pos_side"],
                    leverage=sig.payload.get("leverage"),
                    tag=sig.source,
                    reason=sig.reason,
                    ord_type=kwargs["ord_type"],
                    px=sig.px,
                )
                if (
                    not _tee_shadow
                    and isinstance(_tee_result, dict)
                    and _tee_result.get("ok") is True
                ):
                    return _tee_result
            except Exception as _tee_exc:  # noqa: BLE001 — tee_core FAIL-OPEN → okx_client
                logger.debug("[T13] tee_engine execute fail, fallback to okx_client: %s", _tee_exc)

        try:
            return self._okx.place_order(**kwargs)
        except Exception as exc:
            return {"ok": False, "error": f"place_order_exc:{exc}", "dry_run": False}

    def _detect_price_key(self) -> str:
        """检测底层 place_order 接受的价格参数名（px 或 price）。"""
        import inspect

        try:
            sig = inspect.signature(self._okx.place_order)
            if "price" in sig.parameters and "px" not in sig.parameters:
                return "price"
        except (TypeError, ValueError):
            pass
        return "px"

    def _audit(self, sig: FinalDecisionSignal, result: ExecutionResult) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "signal_id": sig.signal_id,
            "source": sig.source,
            "symbol": sig.symbol,
            "direction": sig.direction,
            "action": sig.action,
            "confidence": sig.confidence,
            "risk_decision": "allow" if result.passed else "reject",
            "executed": result.executed,
            "reason_code": result.reason_code,
            "reason": result.reason,
            "position_modifier": result.position_modifier,
        }
        try:
            with open(self._audit_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning("audit write failed: %s", exc)
