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

保证金前置拦截（开仓，FAIL-OPEN）：
  EXECUTION_MARGIN_PRECHECK   默认 on；off 时完全跳过
  EXECUTION_MARGIN_LEVERAGE   默认 5（与 23 entry_loop 一致）；payload.leverage 优先
  EXECUTION_MARGIN_BUFFER     默认 0.05（可用余额需留出的安全垫）
  EXECUTION_MARGIN_CACHE_SEC  默认 30（余额快照缓存秒数，避免高频查询）
  余额查询失败/无 get_balance → 放行，不改变原有交易语义。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
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
# 硬前置来源：decision_id 必填 + expires_at 过期即拒（23 自进化 / 54-L1 统计方向同为内部出口）
_PRECHECK_SOURCES = ("23-evolution", "l1-chart")


@dataclass
class FinalDecisionSignal:
    """FinalDecisionSignal v1.2 轻量 Python 表示（核心字段 + 执行扩展）。

    与 49-交易框架协议/contracts/final_decision_signal.v1.2.json 对齐；
    v1.2 已把 decision_id/action/pos_side/sl_px/tp_px/sz/reason 登记为顶层执行扩展。
    """

    signal_id: str
    source: str  # 23-evolution / 50-nn / 11-yijing / 6-trading / ...
    symbol: str  # e.g. BTC-USDT-SWAP
    direction: str  # long / short / neutral
    # 来源决策主键（DEC-BCL-07）：执行层落成交时必须回带，供 D1 证据链严格 join。
    # 顶层 decision_id 优先，其次 payload.decision_id；缺失保持 None，禁止伪造。
    decision_id: Optional[str] = None
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
        _payload = d.get("payload") if isinstance(d.get("payload"), dict) else {}
        return cls(
            signal_id=str(d.get("signal_id") or f"sig-{uuid.uuid4().hex[:12]}"),
            source=str(d.get("source") or "unknown"),
            symbol=str(d.get("symbol") or d.get("inst_id") or "MULTI"),
            direction=str(d.get("direction") or "neutral").lower(),
            decision_id=(str(d.get("decision_id") or _payload.get("decision_id") or "") or None),
            confidence=float(d.get("confidence") or 0.0),
            expires_at=str(d.get("expires_at") or ""),
            action=str(d.get("action") or _payload.get("action") or "open").lower(),
            sz=d.get("sz") if d.get("sz") is not None else _payload.get("sz"),
            px=d.get("px") if d.get("px") is not None else _payload.get("px"),
            pos_side=d.get("pos_side") or _payload.get("pos_side"),
            sl_px=d.get("sl_px") if d.get("sl_px") is not None else _payload.get("sl_px"),
            tp_px=d.get("tp_px") if d.get("tp_px") is not None else _payload.get("tp_px"),
            reason=str(d.get("reason") or _payload.get("reason") or ""),
            payload=_payload,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "decision_id": self.decision_id,
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
    rules_evaluated: int = 0  # 本次门禁实际执行的规则数（0 = 空表，异常信号）
    rule_name: str = ""  # 触发拒绝/降级的规则名
    order_result: Optional[Dict[str, Any]] = None
    sltp_result: Optional[Dict[str, Any]] = None  # 主单后自动补的 SL/TP 条件单结果


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

    def cancel_algo_orders(self, inst_id: str = None, **kwargs: Any) -> Dict[str, Any]:
        """撤单必须经 Gateway（不允许透传 raw 绕过审计）。"""
        return self._gateway.cancel_algo_orders(
            inst_id, source=str(kwargs.get("source") or "11-yijing")
        )

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
        # 来源标签：23-evolution / 22-sltp_reconcile / 11-yijing …
        source = str(kwargs.get("source") or "11-yijing")
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
            "signal_id": f"{source}|{uuid.uuid4().hex[:12]}",
            "source": source,
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
        source = str(kwargs.get("source") or "11-yijing")
        # 同时设 SL 和 TP 时按 stop_loss 归类（algo order 会一起下）
        action = "stop_loss" if sl_px is not None else "take_profit"
        return {
            "signal_id": f"{source}-sltp|{uuid.uuid4().hex[:12]}",
            "source": source,
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


class FailClosedOkxClient:
    """执行权威不可用时的只读代理：写操作一律拒绝，绝不回退 raw。

    用于 11/16 等域在 22 Gateway 加载失败时的降级：读操作（持仓/行情）照常透传，
    但下单入口 fail-closed，避免"执行权落 22"被 FAIL-OPEN 旁路破坏。
    """

    _REJECT: Dict[str, Any] = {
        "ok": False,
        "rejected": True,
        "error": "execution_authority_unavailable",
        "reason_code": "EXECUTION_AUTHORITY_UNAVAILABLE",
    }

    def __init__(self, raw_client: Any) -> None:
        object.__setattr__(self, "_raw", raw_client)

    def _reject(self) -> Dict[str, Any]:
        return dict(self._REJECT)

    def place_order(self, **kwargs: Any) -> Dict[str, Any]:
        return self._reject()

    def place_stop_loss_take_profit(self, **kwargs: Any) -> Dict[str, Any]:
        return self._reject()

    def market_open_long(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._reject()

    def market_open_short(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._reject()

    def market_close_long(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._reject()

    def market_close_short(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._reject()

    def reduce_position(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._reject()

    def cancel_algo_orders(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        # 撤掉 SL 等于降低保护，执行权威不可用时必须拒绝
        return self._reject()

    def set_leverage(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        return self._reject()

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_raw"), name)


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


_13_CREATE_GATE: Any = None


def _create_gate() -> Any:
    """通过 13 层工厂构造「带默认规则」的门禁。

    历史缺陷：直接 ``PreTradeGate()`` 得到空注册表，``check()`` 恒 PASS。
    本函数走 ``core.factory.create_gate``，规则数与配置由 13 层统一管理。
    加载失败返回 None（调用方按 fail-closed 处理：开仓拒、平仓放行）。
    """
    global _13_CREATE_GATE
    if _13_CREATE_GATE is not None:
        try:
            return _13_CREATE_GATE()
        except Exception as exc:  # noqa: BLE001
            logger.error("[gate] 13 create_gate 构造失败: %s", exc)
            return None

    _13_str = str(_13_DIR)
    saved_path = list(sys.path)
    sys.path[:] = [p for p in sys.path if p != _13_str]
    sys.path.insert(0, _13_str)

    saved = {k: v for k, v in sys.modules.items() if k == "core" or k.startswith("core.")}
    for k in list(saved):
        del sys.modules[k]
    try:
        from core.factory import create_gate as _factory_create_gate  # noqa: E402

        _13_CREATE_GATE = _factory_create_gate
    except Exception as exc:  # noqa: BLE001
        logger.error("[gate] 13 core.factory 加载失败: %s", exc)
        return None
    finally:
        for k in [k for k in sys.modules if k == "core" or k.startswith("core.")]:
            del sys.modules[k]
        sys.modules.update(saved)
        sys.path[:] = saved_path

    try:
        return _13_CREATE_GATE()
    except Exception as exc:  # noqa: BLE001
        logger.error("[gate] 13 create_gate 构造失败: %s", exc)
        return None


def _rule_audit_fields(check: Any) -> tuple:
    """从 13 RiskCheckResult.details 提取审计字段 (rules_evaluated, rule_name)。"""
    details = getattr(check, "details", None) or {}
    try:
        evaluated = int(details.get("rules_evaluated") or 0)
    except (TypeError, ValueError):
        evaluated = 0
    return evaluated, str(details.get("rule_name") or "")


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
        shadow_only: 只读影子校验模式。True 时仅执行 13 PreTradeGate 判定并落审计，
            永不调用 16 定容 / 22 执行 / 交易所下单。用于 23 自进化域：
            13→16→22→11 链路只属于神经网络系统，23 域保留 13 只读校验不阻断订单。
    """

    def __init__(
        self,
        okx_client: Any = None,
        risk_context: Any = None,
        audit_path: Optional[str | Path] = None,
        capital_allocator: Any = None,
        tee_engine: Any = None,
        shadow_only: bool = False,
        ledger: Any = None,
    ) -> None:
        self._okx = okx_client if okx_client is not None else _PaperOkxClient()
        self._risk_context = risk_context
        self._gate: Any = None  # 懒加载 PreTradeGate
        self._13_load_failed = False
        self._capital_allocator = capital_allocator  # 16 PACA 定容（可选）
        self._tee_engine = tee_engine  # 22 tee_core OrderPort（可选）
        self._shadow_only = bool(shadow_only)
        self._ledger = ledger  # 22 PositionLedger（可选，缺省懒加载）
        self._ledger_ready = ledger is not None

        # decision_id 幂等缓存（进程内，双保险）：同一决策重复提交直接返回首次结果
        self._decision_cache: dict[str, tuple[float, ExecutionResult]] = {}
        self._decision_cache_lock = threading.Lock()
        self._decision_cache_ttl = float(os.getenv("GATEWAY_DECISION_CACHE_TTL_SEC", "3600"))

        # 保证金前置拦截：余额快照缓存 + 本地拒单计数（避免交易所侧连败与无效重试）
        self._margin_balance_cache: tuple[float, Optional[dict]] = (0.0, None)
        self._margin_balance_lock = threading.Lock()
        self._margin_reject_count = 0

        if audit_path is None:
            audit_path = REPO_ROOT / "22-执行引擎中心" / "audit" / "gateway.jsonl"
        self._audit_path = Path(audit_path)
        self._audit_path.parent.mkdir(parents=True, exist_ok=True)
        self._contract_mode = str(os.getenv("EXECUTION_CONTRACT_MODE", "alert")).lower()
        self._contract_audit = self._audit_path.parent / "contract_violations.jsonl"
        self._contract_schema: dict | None = None
        # 22/config/live_symbols.json → inst_id -> asset_class（类级授权用，mtime 缓存）
        self._symbol_class_cache: dict[str, str] | None = None
        self._symbol_class_mtime: float | None = None

    # ── v1.2 契约校验（alert-only，默认不阻断） ──────────────────────
    _CONTRACT_CORE = ("signal_id", "source", "symbol", "direction", "confidence", "expires_at")
    _CONTRACT_V12_TOP = (
        "signal_id",
        "source",
        "ts",
        "symbol",
        "direction",
        "confidence",
        "horizon",
        "risk_exposure_hint",
        "expires_at",
        "mode",
        "payload",
    )
    _CONTRACT_V12_PAYLOAD = (
        "action",
        "position_tier",
        "position_mult",
        "d_star",
        "ri",
        "l4_v",
        "regime",
        "primary_contradiction",
        "contradiction_shift",
        "elastic_result",
        "cross_validation",
        "path",
    )

    def _load_contract_schema(self) -> dict | None:
        if self._contract_schema is not None:
            return self._contract_schema
        try:
            path = REPO_ROOT / "49-交易框架协议" / "contracts" / "final_decision_signal.v1.2.json"
            self._contract_schema = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("[Gateway] 契约 schema 加载失败(FAIL-OPEN): %s", exc)
            self._contract_schema = None
        return self._contract_schema

    def _execution_rights_denied(self, sig: FinalDecisionSignal) -> str:
        """标的级单出口校验（49 §2.7 / 47 execution_rights）。

        只拦开仓；平仓/减仓永远放行（风控优先）。默认开启，可通过
        EXECUTION_RIGHTS_ENFORCE=0 临时关闭。
        """
        if str(os.getenv("EXECUTION_RIGHTS_ENFORCE", "0")).lower() in ("0", "off", "false", "no"):
            if not getattr(self, "_rights_disabled_logged", False):
                logger.info("[Gateway] execution_rights 校验关闭（EXECUTION_RIGHTS_ENFORCE=0）")
                self._rights_disabled_logged = True
            return ""
        if str(sig.action or "").lower() != "open":
            return ""
        rules = self._load_execution_rights()
        if not rules:
            return ""
        symbols = rules.get("symbols") or {}
        classes = rules.get("classes") or {}
        default_outcome = str((rules.get("defaults") or {}).get("outcome") or "paper")
        entry = symbols.get(str(sig.symbol)) if isinstance(symbols, dict) else None
        source = str(sig.source or "")
        outcome = self._resolve_symbol_outcome(sig.symbol, entry, source, classes, default_outcome)

        if outcome == "disabled":
            return f"execution_rights_disabled symbol={sig.symbol}"
        if outcome == "live:50-bypass":
            return (
                ""
                if source == "50-nn"
                else (f"single_outlet_denied symbol={sig.symbol} outcome={outcome} source={source}")
            )
        if outcome == "live:23-gateway":
            return (
                ""
                if source == "23-evolution"
                else (f"single_outlet_denied symbol={sig.symbol} outcome={outcome} source={source}")
            )
        if outcome.startswith("live:11"):
            return (
                ""
                if source.startswith("11-")
                else (f"single_outlet_denied symbol={sig.symbol} outcome={outcome} source={source}")
            )
        return ""

    def _resolve_symbol_outcome(
        self,
        symbol: str,
        entry: dict | None,
        source: str,
        classes: dict,
        default_outcome: str,
    ) -> str:
        """解析顺序：源专属 outcomes > shared_outcomes > 单值 outcome > 类级 > 默认。

        - `outcomes` / `shared_outcomes` 用于多域竞争同一标的（23 与 50）。
        - 类级授权用于已注册但未在顶层 symbols 单列的标的。
        - 未知类别仍落 default（默认 paper），不默认放行 live。
        """
        if isinstance(entry, dict):
            for key in ("outcomes", "shared_outcomes"):
                table = entry.get(key)
                if isinstance(table, dict) and table.get(source):
                    return str(table[source])
            if entry.get("outcome"):
                return str(entry["outcome"])
        asset_class = self._asset_class_of(symbol, entry)
        class_entry = (
            classes.get(asset_class) if isinstance(classes, dict) and asset_class else None
        )
        if isinstance(class_entry, dict) and class_entry.get("outcome"):
            return str(class_entry["outcome"])
        return default_outcome

    def _asset_class_of(self, symbol: str, entry: dict | None = None) -> str:
        """标的资产类别：symbol 条目显式声明 > 22 live_symbols 注册表 > 空。"""
        if isinstance(entry, dict) and entry.get("asset_class"):
            return str(entry["asset_class"])
        mapping = self._load_symbol_classes()
        return str(mapping.get(str(symbol).upper()) or "")

    def _load_symbol_classes(self) -> dict[str, str]:
        """读取 22/config/live_symbols.json 的 inst_id -> asset_class（mtime 缓存）。"""
        path = REPO_ROOT / "22-执行引擎中心" / "config" / "live_symbols.json"
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return {}
        if self._symbol_class_cache is not None and self._symbol_class_mtime == mtime:
            return self._symbol_class_cache
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            symbols = data.get("symbols") if isinstance(data, dict) else {}
            self._symbol_class_cache = {
                str(cfg.get("inst_id") or key).upper(): str(cfg.get("asset_class") or "")
                for key, cfg in (symbols or {}).items()
                if isinstance(cfg, dict)
            }
            self._symbol_class_mtime = mtime
        except (OSError, ValueError) as exc:
            logger.warning("[Gateway] live_symbols 加载失败(FAIL-OPEN): %s", exc)
            self._symbol_class_cache = {}
        return self._symbol_class_cache

    def _shared_outlet_blocked(self, sig: FinalDecisionSignal) -> str:
        """竞争标的的跨域互斥守卫（23/50 shared_outcomes）。

        判定顺序：账本域归属（准）> 交易所持仓（兜底）。
        - 仅拦开仓；平仓/减仓永远放行；
        - 仅本域在持 → 放行（允许加仓/再进场）；
        - 他域在持 → 拒绝 SYMBOL_ALREADY_OPEN，避免同标的双向恶性竞争；
        - 账本无归属但交易所有仓 → 保守拒绝（来源不明者不叠加）；
        - 账本/交易所查询失败 → FAIL-OPEN。
        """
        if str(sig.action or "").lower() != "open":
            return ""
        rules = self._load_execution_rights() or {}
        symbols = rules.get("symbols") or {}
        entry = symbols.get(str(sig.symbol)) if isinstance(symbols, dict) else None
        if not isinstance(entry, dict) or not entry.get("shared_outcomes"):
            return ""

        _src = str(sig.source or "")
        _my_domain = ""
        for _prefix, _dom in (("23", "23"), ("50", "50"), ("11", "11"), ("6-", "6")):
            if _src.startswith(_prefix):
                _my_domain = _dom
                break

        ledger = self._get_ledger()
        _my_side = str(getattr(sig, "pos_side", None) or sig.direction or "").lower()
        if ledger is not None and hasattr(ledger, "active_holders"):
            try:
                _holders = ledger.active_holders(str(sig.symbol)) or []
            except Exception as exc:  # noqa: BLE001 — 查询失败不阻断
                logger.warning("[Gateway] 域归属查询失败(FAIL-OPEN): %s", exc)
                _holders = []
            _others = sorted({h["domain"] for h in _holders if h.get("domain") != _my_domain})
            if _others:
                return (
                    f"symbol_held_by_other_domain symbol={sig.symbol}"
                    f" holders={','.join(_others)}"
                )
            if _my_side:
                _opp = sorted(
                    {
                        f"{h.get('domain') or '?'}:{h.get('pos_side')}"
                        for h in _holders
                        if str(h.get("pos_side") or "").lower() not in ("", _my_side)
                    }
                )
                if _opp:
                    return f"symbol_opposite_side_held symbol={sig.symbol} held={','.join(_opp)}"
            if _holders:
                return ""
        elif ledger is not None and hasattr(ledger, "active_domain_holders"):
            try:
                _owners = ledger.active_domain_holders(
                    str(sig.symbol), getattr(sig, "pos_side", None)
                )
            except Exception:  # noqa: BLE001
                _owners = None
            if _owners:
                _others = sorted({o for o in _owners if o and o != _my_domain})
                if _others:
                    return (
                        f"symbol_held_by_other_domain symbol={sig.symbol}"
                        f" holders={','.join(_others)}"
                    )
                return ""

        # 账本有仓但无域归属（网关外开仓/历史回填）→ 归属不明，保守拒绝叠加
        if ledger is not None and hasattr(ledger, "list_positions"):
            try:
                _raw = {
                    str(p.get("inst_id")): abs(float(p.get("qty") or 0))
                    for p in (ledger.list_positions() or [])
                }
            except Exception:  # noqa: BLE001
                _raw = {}
            if _raw.get(str(sig.symbol), 0.0) > 1e-9:
                return f"symbol_held_by_unknown_domain symbol={sig.symbol}"

        fn = getattr(self._okx, "get_positions", None)
        if not callable(fn):
            return ""
        try:
            data = fn() or {}
        except Exception as exc:  # noqa: BLE001 — 查询失败不阻断
            logger.warning("[Gateway] 竞争持仓查询失败(FAIL-OPEN): %s", exc)
            return ""
        if not data.get("ok"):
            return ""
        for row in data.get("positions") or []:
            _inst = str(row.get("inst_id") or row.get("instId") or "")
            if _inst and _inst != str(sig.symbol):
                continue
            try:
                qty = abs(float(row.get("pos") if "pos" in row else row.get("qty") or 0))
            except (TypeError, ValueError):
                continue
            if qty > 0:
                return f"symbol_already_open symbol={sig.symbol}"
        return ""

    def _load_execution_rights(self) -> dict | None:
        path = REPO_ROOT / "47-MCP管理系统" / "registry" / "execution_rights.json"
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None
        if (
            getattr(self, "_rights_cache", None) is not None
            and getattr(self, "_rights_mtime", None) == mtime
        ):
            return self._rights_cache
        try:
            self._rights_cache = json.loads(path.read_text(encoding="utf-8"))
            self._rights_mtime = mtime
        except (OSError, ValueError) as exc:
            logger.warning("[Gateway] execution_rights 加载失败(FAIL-OPEN): %s", exc)
            self._rights_cache = None
        return self._rights_cache

    def _contract_errors(self, raw: dict) -> list[str]:
        source = str(raw.get("source") or "")
        if source != "23-evolution":
            # 非 23 来源（11-yijing / 50-nn / 6-trading 等）不承担 23 决策契约，
            # 只校验最小订单要素；decision_id/expires_at 属于 23 专属字段。
            core = ("source", "symbol", "direction")
            return [f"missing:{f}" for f in core if f not in raw]
        schema = self._load_contract_schema()
        if schema is not None:
            try:
                import jsonschema
            except ImportError:
                jsonschema = None
            if jsonschema is not None:
                try:
                    jsonschema.validate(instance=raw, schema=schema)
                    return []
                except jsonschema.ValidationError as exc:
                    where = ".".join(str(p) for p in exc.absolute_path) or "$"
                    return [f"{where}: {str(exc.message)[:160]}"]
        errors = [f"missing:{f}" for f in self._CONTRACT_V12_TOP if f not in raw]
        payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
        errors.extend(
            f"missing:payload.{f}" for f in self._CONTRACT_V12_PAYLOAD if f not in payload
        )
        return errors

    def _check_contract(self, raw: dict) -> None:
        """alert-only：记录/告警，永不改变订单结果；block 模式保留。"""
        errors = self._contract_errors(raw)
        if not errors:
            return
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "mode": self._contract_mode,
            "source": str(raw.get("source") or "unknown"),
            "decision_id": raw.get("decision_id") or (raw.get("payload") or {}).get("decision_id"),
            "symbol": raw.get("symbol"),
            "errors": errors[:10],
            "shadow_only": self._shadow_only,
        }
        logger.warning(
            "[Gateway] 契约校验未通过(%s) source=%s decision_id=%s errors=%s",
            self._contract_mode,
            record["source"],
            record["decision_id"],
            errors[:3],
        )
        try:
            self._contract_audit.parent.mkdir(parents=True, exist_ok=True)
            with self._contract_audit.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("[Gateway] 契约违规落盘失败(FAIL-OPEN): %s", exc)

    # ── public API ────────────────────────────────────────────────────
    def submit(self, decision: Dict[str, Any] | FinalDecisionSignal) -> ExecutionResult:
        """提交决策执行（带 decision_id 进程内幂等）。

        Returns:
            ExecutionResult: passed=13是否通过, executed=是否实际下单。
        """
        if isinstance(decision, dict):
            self._check_contract(decision)
        sig = (
            decision
            if isinstance(decision, FinalDecisionSignal)
            else FinalDecisionSignal.from_dict(decision)
        )
        _did = getattr(sig, "decision_id", None)
        if _did:
            _hit = self._cache_get(_did)
            if _hit is not None:
                logger.info("[Gateway] 幂等命中 decision_id=%s，返回首次执行结果", _did)
                return _hit
        result = self._submit_impl(sig)
        if _did and getattr(result, "executed", False):
            self._cache_put(_did, result)
        self._record_ledger(sig, result)
        return result

    # ── 保证金前置拦截（开仓） ────────────────────────────────────────
    def margin_reject_count(self) -> int:
        """进程内「可用保证金不足」本地拒单计数（供运维/指标读取）。"""
        return self._margin_reject_count

    def _available_usdt(self) -> Optional[float]:
        """可用 USDT 余额（带短 TTL 缓存）。查询失败返回 None → FAIL-OPEN。"""
        try:
            cache_sec = float(os.getenv("EXECUTION_MARGIN_CACHE_SEC", "30"))
        except (TypeError, ValueError):
            cache_sec = 30.0
        now = time.time()
        cached_ts, cached = self._margin_balance_cache
        if cached is not None and (now - cached_ts) < cache_sec:
            return cached.get("avail")
        fn = getattr(self._okx, "get_balance", None)
        if not callable(fn):
            return None
        try:
            bal = fn() or {}
        except Exception as exc:  # noqa: BLE001 — 余额查询失败不阻断交易
            logger.debug("[Gateway] margin precheck balance query fail (fail-open): %s", exc)
            return None
        if not bal.get("ok"):
            logger.debug(
                "[Gateway] margin precheck balance unavailable (fail-open): %s", bal.get("error")
            )
            return None
        usdt = (bal.get("assets") or {}).get("USDT") or {}
        avail = float(usdt.get("avail") or 0.0)
        with self._margin_balance_lock:
            self._margin_balance_cache = (now, {"avail": avail})
        return avail

    def _required_margin_usdt(self, sig: FinalDecisionSignal, sz: Any) -> Optional[float]:
        """估算本单所需保证金：notional / leverage（缺省 5×，与 23 entry_loop 一致）。"""
        payload = sig.payload if isinstance(sig.payload, dict) else {}
        notional = float(payload.get("notional_usdt") or 0.0)
        if notional <= 0 and sz is not None:
            _px = float(sig.px or payload.get("price") or 0.0)
            if _px > 0:
                notional = abs(float(sz)) * _px
        if notional <= 0:
            return None
        try:
            leverage = float(payload.get("leverage") or os.getenv("EXECUTION_MARGIN_LEVERAGE", "5"))
        except (TypeError, ValueError):
            leverage = 5.0
        if leverage <= 0:
            leverage = 1.0
        return notional / leverage

    def _precheck_margin(self, sig: FinalDecisionSignal, sz: Any) -> Optional[ExecutionResult]:
        """开仓前可用保证金校验：不足则本地拒单，不下发交易所（避免连败与无效重试）。"""
        if str(os.getenv("EXECUTION_MARGIN_PRECHECK", "on")).strip().lower() in (
            "0",
            "off",
            "false",
            "no",
        ):
            return None
        if sig.action in _CLOSE_ACTIONS:
            return None
        need = self._required_margin_usdt(sig, sz)
        if need is None or need <= 0:
            return None
        avail = self._available_usdt()
        if avail is None:
            return None
        try:
            buffer = float(os.getenv("EXECUTION_MARGIN_BUFFER", "0.05"))
        except (TypeError, ValueError):
            buffer = 0.05
        buffer = min(max(buffer, 0.0), 0.9)
        spendable = avail * (1.0 - buffer)
        if need <= spendable:
            return None
        self._margin_reject_count += 1
        logger.warning(
            "[Gateway] 可用保证金不足，本地拒单 %s %s: need=%.2f avail=%.2f spendable=%.2f (rejects=%d)",
            sig.symbol,
            sig.action,
            need,
            avail,
            spendable,
            self._margin_reject_count,
        )
        return ExecutionResult(
            passed=False,
            executed=False,
            reason=f"insufficient_margin: need={need:.2f} avail={avail:.2f} spendable={spendable:.2f}",
            reason_code="INSUFFICIENT_MARGIN",
        )

    # ── 持仓账本（P2：22 为唯一真相源，NN 与 23 共用） ────────────────
    def _get_ledger(self):
        if self._ledger_ready:
            return self._ledger
        self._ledger_ready = True
        if str(os.getenv("POSITION_LEDGER_ENABLED", "on")).lower() in ("0", "off", "false", "no"):
            self._ledger = None
            return None
        try:
            from position_ledger import PositionLedger

            self._ledger = PositionLedger()
        except Exception as exc:  # noqa: BLE001 — 账本不可用不影响交易
            logger.warning("[Gateway] PositionLedger 初始化失败(FAIL-OPEN): %s", exc)
            self._ledger = None
        return self._ledger

    def _record_ledger(self, sig: FinalDecisionSignal, result: ExecutionResult) -> None:
        """成交后自动落账；部分减仓也会扣减剩余数量并累计已实现盈亏。"""
        try:
            if not getattr(result, "executed", False):
                return
            ledger = self._get_ledger()
            if ledger is None:
                return
            _action = str(sig.action or "").lower()
            _side = str(sig.pos_side or sig.direction or "").lower()
            if _side not in ("long", "short"):
                return
            _expect_side = (
                ("buy" if _side == "long" else "sell")
                if _action == "open"
                else ("sell" if _side == "long" else "buy")
            )
            _fill = self._latest_fill(sig.symbol, _side, side=_expect_side)
            # 成交索引有秒级延迟：开/平/减仓落账前重试，避免 px=0 导致开仓漏账或盈亏失真
            if _fill is None and _action in ("open", "close", "reduce", "reduce_only"):
                for _ in range(2):
                    time.sleep(0.4)
                    _fill = self._latest_fill(sig.symbol, _side, side=_expect_side)
                    if _fill is not None:
                        break
            _order = result.order_result or {}
            _qty = float(
                (_fill or {}).get("fill_sz")
                or _order.get("filled_sz")
                or _order.get("accFillSz")
                or sig.sz
                or 0.0
            )
            _px = float(
                (_fill or {}).get("fill_px")
                or _order.get("avg_px")
                or _order.get("avgPx")
                or _order.get("fillPx")
                or _order.get("px")
                or sig.px
                or 0.0
            )
            if _px <= 0 and _action in ("close", "reduce", "reduce_only"):
                logger.warning(
                    "[Gateway] %s %s 成交价回填失败(px=0)，已实现盈亏记为未知 decision_id=%s",
                    sig.symbol,
                    _action,
                    sig.decision_id,
                )
            if _px <= 0 and _action == "open":
                # 成交索引 lag + 下单响应无均价时，用最新价兜底，避免开仓整笔漏账
                _px = self._last_price(sig.symbol)
                logger.warning(
                    "[Gateway] %s open 成交价缺失，按最新价兜底 px=%.6f decision_id=%s",
                    sig.symbol,
                    _px,
                    sig.decision_id,
                )
            if _action == "open":
                if _qty <= 0:
                    _qty = self._current_position_qty(sig.symbol, _side)
                _rec = ledger.record_fill(
                    inst_id=sig.symbol,
                    pos_side=_side,
                    action="open",
                    qty=_qty,
                    px=_px,
                    source=sig.source,
                    decision_id=str(sig.decision_id or ""),
                    exchange_fill_id=str((_fill or {}).get("trade_id") or ""),
                    fee=float((_fill or {}).get("fee") or 0.0),
                )
                if not (_rec or {}).get("ok"):
                    logger.warning(
                        "[Gateway] %s open 落账被拒: %s decision_id=%s",
                        sig.symbol,
                        (_rec or {}).get("reason"),
                        sig.decision_id,
                    )
            elif _action in ("close", "reduce", "reduce_only"):
                ledger.record_fill(
                    inst_id=sig.symbol,
                    pos_side=_side,
                    action=_action,
                    qty=_qty,
                    px=_px,
                    ratio=1.0 if _action == "close" else None,
                    source=sig.source,
                    decision_id=str(sig.decision_id or ""),
                    exchange_fill_id=str((_fill or {}).get("trade_id") or ""),
                    fee=float((_fill or {}).get("fee") or 0.0),
                    exit_reason=str(sig.reason or ""),
                )
        except Exception as exc:  # noqa: BLE001 — 落账失败不影响已成交订单
            logger.warning("[Gateway] 账本落账失败(FAIL-OPEN): %s", exc)

    def _latest_fill(
        self,
        inst_id: str,
        pos_side: str,
        side: Optional[str] = None,
        max_age_sec: Optional[float] = 120.0,
    ) -> Optional[Dict[str, Any]]:
        """取最近一笔成交。

        side：限定买卖方向（平多=sell / 平空=buy / 开多=buy / 开空=sell）。
        不限定方向时，刚下的平仓单可能还没进成交索引，会误取到开仓成交
        （价格=开仓均价），导致平仓价与已实现盈亏失真。
        """
        fn = getattr(self._okx, "get_recent_fills", None)
        if not callable(fn):
            return None
        try:
            data = fn(inst_id, limit=20) or {}
        except Exception:  # noqa: BLE001
            return None
        _now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        _fills = sorted(data.get("fills") or [], key=lambda f: int(f.get("ts") or 0), reverse=True)
        for f in _fills:
            if str(f.get("pos_side") or "").lower() not in ("", str(pos_side).lower()):
                continue
            if side and str(f.get("side") or "").lower() != side:
                continue
            if float(f.get("fill_px") or 0) <= 0:
                continue
            if max_age_sec is not None:
                _ts = int(f.get("ts") or 0)
                if _ts > 0 and (_now_ms - _ts) > float(max_age_sec) * 1000:
                    continue
            return f
        return None

    def _latest_close_fill(self, inst_id: str, pos_side: str) -> Optional[Dict[str, Any]]:
        """Ghost 平仓落账：取该方向最近一笔真实平仓成交（不限时效）。"""
        _expect_side = "sell" if str(pos_side).lower() == "long" else "buy"
        return self._latest_fill(inst_id, pos_side, side=_expect_side, max_age_sec=None)

    def _last_price(self, inst_id: str) -> float:
        """最新价兜底（成交索引 lag 时用于开仓落账，查询失败返回 0）。"""
        fn = getattr(self._okx, "get_ticker", None)
        if not callable(fn):
            return 0.0
        try:
            data = fn(inst_id) or {}
            if not data.get("ok", True):
                return 0.0
            return float(data.get("last") or 0.0)
        except Exception:  # noqa: BLE001
            return 0.0

    def _current_position_qty(self, inst_id: str, pos_side: str) -> float:
        """开仓数量兜底：直接读交易所持仓（单位与合约 sz 一致）。"""
        fn = getattr(self._okx, "get_positions", None)
        if not callable(fn):
            return 0.0
        try:
            data = fn(inst_id) or {}
            for p in data.get("positions") or []:
                if str(p.get("pos_side") or "").lower() == pos_side:
                    return float(p.get("pos") or 0.0)
        except Exception:  # noqa: BLE001
            return 0.0
        return 0.0

    def get_position(self, inst_id: str, pos_side: str) -> Optional[Dict[str, Any]]:
        """供 23/16 读取 22 账本（11 只读）。"""
        ledger = self._get_ledger()
        return ledger.get_position(inst_id, pos_side) if ledger is not None else None

    def list_positions(self) -> list[Dict[str, Any]]:
        ledger = self._get_ledger()
        return ledger.list_positions() if ledger is not None else []

    def list_effective_positions(
        self, max_heartbeat_age_seconds: float = 300.0
    ) -> list[Dict[str, Any]]:
        """容量/闸门唯一读口径；心跳过期时账本内部回退 raw 持仓。"""
        ledger = self._get_ledger()
        if ledger is None:
            return []
        return ledger.list_effective_positions(max_heartbeat_age_seconds)

    def get_cooldown(self, inst_id: str) -> Optional[Dict[str, Any]]:
        """最近一次全平记录（含 close_ts/exit_reason/realized_pnl）。"""
        ledger = self._get_ledger()
        return ledger.get_cooldown(inst_id) if ledger is not None else None

    def is_in_cooldown(self, inst_id: str, cooldown_sec: float) -> bool:
        """开仓侧冷却查询：距上次全平不足 cooldown_sec 即禁止再开。"""
        row = self.get_cooldown(inst_id)
        if not row or cooldown_sec <= 0:
            return False
        try:
            _close_ts = datetime.fromisoformat(
                str(row["close_ts"]).replace("Z", "+00:00")
            ).timestamp()
        except (KeyError, TypeError, ValueError):
            return False
        return (datetime.now(timezone.utc).timestamp() - _close_ts) < float(cooldown_sec)

    def close_ghost_position(
        self,
        inst_id: str,
        pos_side: str,
        exit_px: float = 0.0,
        source: str = "23-evolution",
        exit_reason: str = "ghost_exchange_flat",
        domain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """交易所已无持仓但账本仍开着：按幽灵价全平，避免每轮重复告警。

        exit_reason 区分归因：
        - ``exchange_sltp``：取到交易所真实成交价，属 SL/TP 正常回填；
        - ``ghost_exchange_flat``：无成交可回填，需人工核对。
        仅在 operand 所属域份额内平仓（P1 一标的一域）；旧库无域子账时回退全账平仓。
        """
        ledger = self._get_ledger()
        if ledger is None:
            return {"ok": False, "reason": "ledger_disabled"}
        row = ledger.get_position(inst_id, pos_side)
        if not row:
            return {"ok": False, "reason": "no_position"}
        _px = float(exit_px or row.get("avg_entry") or 0)
        _dom = str(domain or "").strip().lower()
        if _dom:
            out = ledger.close_position(
                _dom,
                inst_id,
                pos_side,
                float(row["qty"]),
                px=_px,
                source=source,
                exit_reason=exit_reason,
            )
            if out.get("ok"):
                return out
        return ledger.apply_partial_close(
            inst_id=inst_id,
            pos_side=pos_side,
            qty=float(row["qty"]),
            px=_px,
            ratio=1.0,
            source=source,
            exit_reason=exit_reason,
        )

    def list_domain_positions(self, domain: str | None = None) -> list[Dict[str, Any]]:
        """域子账只读视图（供 23/15 读取归属与状态，不直接读 positions 原表）。"""
        ledger = self._get_ledger()
        if ledger is None:
            return []
        return ledger.list_domain_positions(domain)

    def list_breaks(self, state: str = "OPEN", limit: int = 100) -> list[Dict[str, Any]]:
        ledger = self._get_ledger()
        return ledger.list_breaks(state=state, limit=limit) if ledger is not None else []

    def reconcile_ledger(self, source: str = "22-reconciled") -> Dict[str, Any]:
        """存量仓一次性对账回填：交易所持仓 → 22 账本（幂等，不覆盖真实流水）。"""
        ledger = self._get_ledger()
        if ledger is None:
            return {"ok": False, "reason": "ledger_disabled"}
        fn = getattr(self._okx, "get_positions", None)
        if not callable(fn):
            return {"ok": False, "reason": "okx_get_positions_missing"}
        data = fn() or {}
        rows = data.get("positions") or []
        items = [
            {
                "inst_id": r.get("inst_id"),
                "pos_side": r.get("pos_side"),
                "qty": r.get("pos"),
                "avg_entry": r.get("avg_px"),
            }
            for r in rows
        ]
        # 连续两轮确认缺失才平掉账本行，避免 OKX 持仓快照瞬时不全导致假幽灵仓。
        present = {(str(i["inst_id"]), str(i["pos_side"])) for i in items}
        misses: Dict[Any, int] = getattr(self, "_ghost_misses", {})
        for _k in list(misses):
            if _k in present:
                misses.pop(_k, None)

        def _ghost_confirm(inst_id: str, pos_side: str) -> bool:
            _k = (str(inst_id), str(pos_side))
            _n = misses.get(_k, 0) + 1
            misses[_k] = _n
            return _n >= 2

        self._ghost_misses = misses
        out = ledger.reconcile(
            items,
            source=source,
            fill_lookup=self._latest_close_fill,
            ghost_confirm=_ghost_confirm,
        )
        # P0-5：成功对账即刷新 verified 与心跳，供闸门安全读取 effective 视图
        try:
            ledger.mark_verified(items)
            ledger.heartbeat()
        except Exception as exc:
            logger.warning("[Gateway] 账本 verified/heartbeat 写入失败(FAIL-OPEN): %s", exc)
        logger.info(
            "[Gateway] 账本对账回填 source=%s inserted=%s updated=%s closed=%s skipped=%s",
            source,
            out.get("inserted"),
            out.get("updated"),
            out.get("closed"),
            out.get("skipped"),
        )
        return out

    def cancel_algo_orders(self, inst_id: str = None, source: str = "11-yijing") -> Dict[str, Any]:
        """撤销未触发的 SL/TP 条件单（写操作唯一入口）。

        收口原因：撤掉 SL 会直接降低保护，必须与下单同源可审计，
        不能让调用方通过 ``__getattr__`` 透传到 raw client。
        """
        # 影子模式（23 域 dry-run）绝不允许真的撤掉交易所保护单，只落审计
        if self._shadow_only:
            result: Dict[str, Any] = {
                "ok": True,
                "shadow": True,
                "inst_id": inst_id,
                "msg": "shadow_only_no_cancel",
            }
            self._audit_cancel(inst_id, source, result)
            return result
        fn = getattr(self._okx, "cancel_algo_orders", None)
        if not callable(fn):
            return {"ok": False, "error": "cancel_algo_orders_unsupported"}
        try:
            result = fn(inst_id) if inst_id else fn()
        except Exception as exc:  # noqa: BLE001 — 执行异常不外抛，落审计后返回
            result = {"ok": False, "error": f"cancel_algo_exc:{exc}"}
        self._audit_cancel(inst_id, source, result)
        return result

    def _audit_cancel(self, inst_id: Optional[str], source: str, result: Dict[str, Any]) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "signal_id": f"cancel-algo|{uuid.uuid4().hex[:12]}",
            "action": "cancel_algo",
            "source": source,
            "symbol": inst_id or "MULTI",
            "executed": bool(result.get("ok")),
            "cancelled": result.get("cancelled"),
            "total": result.get("total"),
            "reason": result.get("error") or result.get("msg") or "",
        }
        try:
            with open(self._audit_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning("cancel audit write failed: %s", exc)

    # ── P2-2：域限额预占（并发防超限） ────────────────────────────────
    _RESERVE_DOMAINS = ("11", "6")

    def _order_notional(self, sig: FinalDecisionSignal, sz: Any, px: Any) -> float:
        payload = sig.payload if isinstance(sig.payload, dict) else {}
        notional = float(payload.get("notional_usdt") or 0.0)
        if notional > 0:
            return abs(notional)
        _px = float(px or sig.px or payload.get("price") or 0.0)
        if _px > 0 and sz is not None:
            return abs(float(sz)) * _px
        return 0.0

    def _reserve_domain_quota(
        self, sig: FinalDecisionSignal, sz: Any, px: Any
    ) -> tuple[Optional[str], Optional[ExecutionResult]]:
        """开仓前按 domain_registry 限额预占；超限返回拒单。

        仅对声明了 `max_notional` 且经 gateway 开仓的域生效（11/6）；
        23 走 subpool/probe 个数限额（LedgerGuards），50 走 drop-copy 并网，均不预占。
        FAIL-OPEN：账本不可用或配置缺失时不阻断下单。
        """
        if str(sig.action or "").lower() in _CLOSE_ACTIONS:
            return None, None
        from position_ledger import domain_of  # 局部导入，保持 FAIL-OPEN

        dom = domain_of(sig.source)
        if dom not in self._RESERVE_DOMAINS:
            return None, None
        ledger = self._get_ledger()
        if ledger is None:
            return None, None
        try:
            limits = ledger.domain_limits(dom) or {}
            max_notional = float(limits.get("max_notional") or 0.0)
            if max_notional <= 0:
                return None, None
            notional = self._order_notional(sig, sz, px)
            if notional <= 0:
                return None, None
            side = str(sig.pos_side or sig.direction or "").lower()
            out = ledger.reserve(
                dom,
                sig.symbol,
                side,
                notional,
                decision_id=str(sig.decision_id or ""),
                limit_notional=max_notional,
                include_domain_positions=True,
            )
        except Exception as exc:  # noqa: BLE001 — 预占失败不改变交易语义
            logger.warning("[Gateway] 域限额预占异常(FAIL-OPEN): %s", exc)
            return None, None
        if out.get("ok"):
            return str(out.get("reservation_id") or ""), None
        reason = (
            f"domain_limit_exceeded domain={dom} held={out.get('held')} "
            f"notional={notional:.2f} max={max_notional:.2f}"
        )
        logger.warning("[Gateway] 域限额拒绝: %s", reason)
        return None, ExecutionResult(
            passed=False,
            executed=False,
            reason=reason,
            reason_code="DOMAIN_LIMIT_EXCEEDED",
        )

    def _settle_reservation(self, reservation_id: Optional[str], consumed: bool) -> None:
        if not reservation_id:
            return
        ledger = self._get_ledger()
        if ledger is None:
            return
        try:
            ledger.release(reservation_id, state="consumed" if consumed else "released")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Gateway] 预占释放失败(FAIL-OPEN): %s", exc)

    def _submit_impl(self, sig: FinalDecisionSignal) -> ExecutionResult:
        # 只读影子校验：仅跑 13 判定并落审计，绝不执行（23 自进化域专用）
        if self._shadow_only:
            return self._submit_shadow(sig)

        # 标的级单出口（47 execution_rights）：只拦开仓，平仓永远放行
        _rights_deny = self._execution_rights_denied(sig)
        if _rights_deny:
            result = ExecutionResult(
                passed=False,
                executed=False,
                reason=_rights_deny,
                reason_code="EXECUTION_RIGHTS_DENIED",
            )
            logger.warning("[Gateway] 执行权拒绝: %s", _rights_deny)
            self._audit(sig, result)
            return result

        # 竞争标的跨域单出口：已有持仓则拒绝再次开仓（23/50 shared_outcomes）
        _shared_deny = self._shared_outlet_blocked(sig)
        if _shared_deny:
            result = ExecutionResult(
                passed=False,
                executed=False,
                reason=_shared_deny,
                reason_code="SYMBOL_ALREADY_OPEN",
            )
            logger.warning("[Gateway] 单出口占用拒绝: %s", _shared_deny)
            self._audit(sig, result)
            return result

        # 内部决策出口（23-evolution / l1-chart）：decision_id 必填 + expires_at 过期即拒
        if sig.source in _PRECHECK_SOURCES:
            _pre = self._precheck_decision(sig)
            if _pre is not None:
                self._audit(sig, _pre)
                return _pre

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
        # 仅 close/reduce 类允许越过 13 入场拒绝；stop_loss/take_profit 仍按原规则
        _is_hard_close = sig.action in ("close", "reduce", "reduce_only")

        # 13 加载失败 → fail-closed：开仓拒，平仓放行
        modules = _load_13_modules()
        if modules is not None and self._gate is None:
            # 必须走 13 工厂（带默认规则）；直接 PreTradeGate() 会得到空表 → 风控空转
            self._gate = _create_gate()

        if modules is None or self._gate is None:
            self._13_load_failed = True
            reason_prefix = (
                "risk_module_unavailable" if modules is None else "risk_gate_init_failed"
            )
            if is_close:
                order_result = self._place_order(sig)
                result = ExecutionResult(
                    passed=True,
                    executed=self._order_succeeded(order_result),
                    reason=f"{reason_prefix}_close_allowed",
                    reason_code=f"{reason_prefix.upper()}_CLOSE_ALLOWED",
                    order_result=order_result,
                )
            else:
                result = ExecutionResult(
                    passed=False,
                    executed=False,
                    reason=f"{reason_prefix}_open_rejected",
                    reason_code=f"{reason_prefix.upper()}_OPEN_REJECTED",
                )
            self._audit(sig, result)
            return result

        _, Signal, RiskContext, Direction = modules
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
            _evaluated, _rule = _rule_audit_fields(check)
            if _is_hard_close:
                # 平仓/减仓永不被入场风控阻断（否则会产生无法退出的风险敞口）
                logger.warning(
                    "[T13] 平仓动作忽略 13 拒绝并放行: %s %s reason=%s",
                    sig.symbol,
                    sig.action,
                    getattr(check, "message", ""),
                )
            else:
                result = ExecutionResult(
                    passed=False,
                    executed=False,
                    reason=str(getattr(check, "message", "")),
                    reason_code=str(getattr(check.reason_code, "value", check.reason_code)),
                    position_modifier=float(getattr(check, "position_modifier", 1.0) or 1.0),
                    rules_evaluated=_evaluated,
                    rule_name=_rule,
                )
                self._audit(sig, result)
                return result

        # 通过 → 执行下单（应用 13 position_modifier + 16 PACA 定容）
        position_modifier = (
            1.0 if _is_hard_close else float(getattr(check, "position_modifier", 1.0) or 1.0)
        )
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

        # sz 兜底：23 等内部出口只给 notional_usdt，若 16 定容未给出张数，
        # 必须按合约面值换算张数，否则 OKX 直接回 "Parameter sz error"（开仓全灭）。
        if final_sz is None and sig.action not in _CLOSE_ACTIONS:
            final_sz = self._fallback_sz(sig)
            if final_sz is None or final_sz <= 0:
                result = ExecutionResult(
                    passed=True,
                    executed=False,
                    reason="sz_unavailable: no allocator size and notional→contracts failed",
                    reason_code="SZ_UNAVAILABLE",
                )
                self._audit(sig, result)
                return result

        # SL/TP 兜底：23 侧 price=0 时顶层 sl_px/tp_px 为空，但 payload 带 sl_pct/tp_pct。
        _sl_px, _tp_px = (
            self._fallback_sltp(sig)
            if sig.action not in _CLOSE_ACTIONS
            else (
                sig.sl_px,
                sig.tp_px,
            )
        )

        sig_for_exec = sig
        if (final_sz != sig.sz) or (_sl_px != sig.sl_px) or (_tp_px != sig.tp_px):
            # 用兜底后的 sz / SL-TP 替换（不修改原 sig 对象）
            import dataclasses as _dc

            sig_for_exec = _dc.replace(sig, sz=final_sz, sl_px=_sl_px, tp_px=_tp_px)

        _margin_deny = self._precheck_margin(sig_for_exec, final_sz)
        if _margin_deny is not None:
            self._audit(sig, _margin_deny)
            return _margin_deny

        # P2-2 域限额预占：成功才下单，按成交结果消费/释放
        _resv_id, _resv_deny = self._reserve_domain_quota(sig_for_exec, final_sz, sig_for_exec.px)
        if _resv_deny is not None:
            self._audit(sig, _resv_deny)
            return _resv_deny

        order_result = self._place_order(sig_for_exec, position_modifier=position_modifier)
        executed = self._order_succeeded(order_result)
        self._settle_reservation(_resv_id, executed)

        # 主单成功后自动补 SL/TP（BCRM 风控原逻辑的 Gateway 等价实现）
        # - take_profit/stop_loss 动作本身就是 SL/TP 类，跳过
        # - close 类动作（平仓/减仓）执行后已无仓位，跳过
        # - open 类且 sig 带 sl_px/tp_px → 调 place_stop_loss_take_profit 补条件单
        sltp_result: Optional[Dict[str, Any]] = None
        if (
            executed
            and sig.action not in ("stop_loss", "take_profit")
            and sig.action not in ("close", "reduce", "reduce_only")
            and (sig_for_exec.sl_px is not None or sig_for_exec.tp_px is not None)
        ):
            sltp_result = self._place_attached_sltp(sig_for_exec)
            if not sltp_result.get("ok", True):
                logger.warning(
                    "[T13] attached SL/TP failed for %s %s (pos_side=%s): %s",
                    sig.action,
                    sig.symbol,
                    sig.pos_side,
                    sltp_result,
                )

        _evaluated, _rule = _rule_audit_fields(check)
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
            rules_evaluated=_evaluated,
            rule_name=_rule,
            order_result=order_result,
            sltp_result=sltp_result,
        )
        self._audit(sig, result)
        return result

    # ── internals ─────────────────────────────────────────────────────
    @staticmethod
    def _precheck_decision(sig: FinalDecisionSignal) -> Optional[ExecutionResult]:
        """内部出口硬前置（`23-evolution` / `l1-chart`）：decision_id 必填；expires_at 过期即拒。

        无法解析 expires_at 时 fail-open（不阻断），由 13 风控继续兜底。
        """
        if not sig.decision_id:
            return ExecutionResult(
                passed=False,
                executed=False,
                reason=f"{sig.source} 决策缺少 decision_id，禁止执行",
                reason_code="MISSING_DECISION_ID",
            )
        if sig.expires_at:
            try:
                _dt = datetime.fromisoformat(str(sig.expires_at).replace("Z", "+00:00"))
                if _dt.tzinfo is None:
                    _dt = _dt.replace(tzinfo=timezone.utc)
                if _dt < datetime.now(timezone.utc):
                    return ExecutionResult(
                        passed=False,
                        executed=False,
                        reason=f"{sig.source} 决策已过期: {sig.expires_at}",
                        reason_code="SIGNAL_EXPIRED",
                    )
            except (TypeError, ValueError):
                pass
        return None

    def _cache_get(self, decision_id: str) -> Optional[ExecutionResult]:
        with self._decision_cache_lock:
            item = self._decision_cache.get(decision_id)
            if item is None:
                return None
            ts, result = item
            if time.time() - ts > self._decision_cache_ttl:
                self._decision_cache.pop(decision_id, None)
                return None
            return result

    def _cache_put(self, decision_id: str, result: ExecutionResult) -> None:
        with self._decision_cache_lock:
            if len(self._decision_cache) > 4096:
                _now = time.time()
                self._decision_cache = {
                    k: v
                    for k, v in self._decision_cache.items()
                    if _now - v[0] <= self._decision_cache_ttl
                }
            self._decision_cache[decision_id] = (time.time(), result)

    def _submit_shadow(self, sig: FinalDecisionSignal) -> ExecutionResult:
        """只读影子校验：只跑 13 PreTradeGate 判定并落审计，绝不调用 16/22/交易所。

        用于 23 自进化域：13→16→22→11 链路只属于神经网络系统，23 域下单
        不经过该链路，但保留 13 判定用于审计与对照，不阻断真实订单。
        """
        if sig.direction == "neutral":
            result = ExecutionResult(
                passed=False,
                executed=False,
                reason="neutral_no_execution",
                reason_code="SHADOW_NEUTRAL_NO_EXECUTION",
            )
            self._audit(sig, result, shadow_only=True)
            return result

        modules = _load_13_modules()
        if modules is not None and self._gate is None:
            self._gate = _create_gate()

        if modules is None or self._gate is None:
            self._13_load_failed = True
            reason = (
                "shadow_risk_module_unavailable（真实链路会 fail-closed 拒开仓）"
                if modules is None
                else "shadow_risk_gate_init_failed（真实链路会 fail-closed 拒开仓）"
            )
            result = ExecutionResult(
                passed=False,
                executed=False,
                reason=reason,
                reason_code=(
                    "SHADOW_RISK_MODULE_UNAVAILABLE"
                    if modules is None
                    else "SHADOW_RISK_GATE_INIT_FAILED"
                ),
            )
            self._audit(sig, result, shadow_only=True)
            return result

        _, Signal, RiskContext, Direction = modules
        ctx = (
            self._risk_context
            if self._risk_context is not None
            else RiskContext(total_equity=10000.0)
        )
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
        try:
            check = self._gate.check(signal, ctx)
        except Exception as exc:  # noqa: BLE001 — 只读校验异常不影响真实下单
            result = ExecutionResult(
                passed=False,
                executed=False,
                reason=f"shadow_check_exception:{exc}",
                reason_code="SHADOW_CHECK_EXCEPTION",
            )
            self._audit(sig, result, shadow_only=True)
            return result

        passed = bool(getattr(check, "passed", False))
        _code = str(getattr(check.reason_code, "value", check.reason_code))
        _evaluated, _rule = _rule_audit_fields(check)
        result = ExecutionResult(
            passed=passed,
            executed=False,
            reason=f"shadow_only:{getattr(check, 'message', '')}",
            reason_code=f"SHADOW_{_code}",
            position_modifier=float(getattr(check, "position_modifier", 1.0) or 1.0),
            rules_evaluated=_evaluated,
            rule_name=_rule,
        )
        self._audit(sig, result, shadow_only=True)
        return result

    def _place_attached_sltp(self, sig: FinalDecisionSignal) -> Dict[str, Any]:
        """主单成功后自动补 SL/TP 条件单。

        等价于原始 okx_client.execute_bcrm_signal 里 "开仓成功 → 补 SL/TP" 的逻辑。
        用 raw client 的 place_stop_loss_take_profit —— OKX algo 条件单原生接口，
        不经过 tee execute_market_compat（tee 只管市价主单）。
        任一参数缺失时 FAIL-OPEN 返回 {"ok": False, ...}，不影响主单 executed 状态。
        """
        if sig.sl_px is None and sig.tp_px is None:
            return {"ok": False, "error": "no_sl_tp_px", "reason": "sl_px and tp_px both None"}
        fn = getattr(self._okx, "place_stop_loss_take_profit", None)
        if not callable(fn):
            return {"ok": False, "error": "place_stop_loss_take_profit_not_found"}
        pos_side = sig.pos_side or ("long" if sig.direction == "long" else "short")
        try:
            return fn(
                inst_id=sig.symbol,
                pos_side=pos_side,
                stop_loss_px=float(sig.sl_px) if sig.sl_px is not None else 0,
                take_profit_px=float(sig.tp_px) if sig.tp_px is not None else 0,
                reason=f"auto_sltp_after_{sig.action}:{sig.signal_id}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[T13] attached SL/TP exception: %s", exc)
            return {"ok": False, "error": f"place_sltp_exc:{exc}"}

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

    def _fallback_sz(self, sig: FinalDecisionSignal) -> Optional[float]:
        """16 定容未给张数时，用 payload.notional_usdt 按合约面值换算张数。

        换算复用 okx_client._usdt_to_sz（已按 lotSz 对齐），保证 sz 一定是交易所
        可接受的最小单位，避免 "Parameter sz error"。
        """
        try:
            notional = float((sig.payload or {}).get("notional_usdt") or 0.0)
        except (TypeError, ValueError):
            return None
        if notional <= 0:
            return None

        fn = getattr(self._okx, "_usdt_to_sz", None)
        if not callable(fn):
            return None
        try:
            sz = float(fn(sig.symbol, notional) or 0.0)
        except Exception as exc:  # noqa: BLE001 — 兜底失败不影响上层审计
            logger.debug("[T13] fallback sz exception: %s", exc)
            return None
        return sz if sz > 0 else None

    def _fallback_sltp(self, sig: FinalDecisionSignal) -> tuple[Optional[float], Optional[float]]:
        """顶层缺 sl_px/tp_px 时，用 payload.sl_pct/tp_pct + 最新价补齐。"""
        if sig.sl_px is not None and sig.tp_px is not None:
            return sig.sl_px, sig.tp_px
        payload = sig.payload or {}
        try:
            sl_pct = float(payload.get("sl_pct") or 0.0)
            tp_pct = float(payload.get("tp_pct") or 0.0)
        except (TypeError, ValueError):
            return sig.sl_px, sig.tp_px
        if sl_pct <= 0 and tp_pct <= 0:
            return sig.sl_px, sig.tp_px

        px = float(sig.px or 0.0)
        if px <= 0:
            ticker_fn = getattr(self._okx, "get_ticker", None)
            if callable(ticker_fn):
                try:
                    ticker = ticker_fn(sig.symbol) or {}
                    if ticker.get("ok", True):
                        px = float(ticker.get("last") or 0.0)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[T13] fallback sltp ticker exception: %s", exc)
        if px <= 0:
            return sig.sl_px, sig.tp_px

        _long = sig.direction == "long"
        sl_px = sig.sl_px
        if sl_px is None and sl_pct > 0:
            sl_px = round(px * (1 - sl_pct) if _long else px * (1 + sl_pct), 8)
        tp_px = sig.tp_px
        if tp_px is None and tp_pct > 0:
            tp_px = round(px * (1 + tp_pct) if _long else px * (1 - tp_pct), 8)
        return sl_px, tp_px

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
                # 23 域出口：条件单同样打标签，便于按域审计
                _sltp_tag = sig.payload.get("tag") or (
                    "evo23" if sig.source == "23-evolution" else None
                )
                if _sltp_tag and self._accepts_kwarg(fn, "tag"):
                    kwargs["tag"] = str(_sltp_tag)
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
        # 23 域出口：交易所侧打标签，便于按域审计（客户端不支持时自动跳过）
        _tag = sig.payload.get("tag") or ("evo23" if sig.source == "23-evolution" else None)
        if _tag and self._accepts_kwarg(self._okx.place_order, "tag"):
            kwargs["tag"] = str(_tag)
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

    @staticmethod
    def _accepts_kwarg(fn: Any, name: str) -> bool:
        """检测底层方法是否接受指定关键字参数（含 **kwargs）。"""
        import inspect

        try:
            params = inspect.signature(fn).parameters
        except (TypeError, ValueError):
            return False
        return name in params or any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
        )

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

    def _audit(
        self,
        sig: FinalDecisionSignal,
        result: ExecutionResult,
        shadow_only: bool = False,
    ) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "signal_id": sig.signal_id,
            "decision_id": sig.decision_id,
            "source": sig.source,
            "symbol": sig.symbol,
            "direction": sig.direction,
            "action": sig.action,
            "confidence": sig.confidence,
            "sz": sig.sz,
            "sl_px": sig.sl_px,
            "tp_px": sig.tp_px,
            "notional_usdt": sig.payload.get("notional_usdt"),
            "tier": sig.payload.get("tier"),
            "domain": sig.payload.get("domain"),
            "risk_decision": "allow" if result.passed else "reject",
            "executed": result.executed,
            "reason_code": result.reason_code,
            "reason": result.reason,
            "position_modifier": result.position_modifier,
            # 门禁可追溯性：rules_evaluated=0 表示门禁空表（异常），需重点告警
            "rules_evaluated": result.rules_evaluated,
            "rule_name": result.rule_name,
        }
        if shadow_only:
            record["shadow_only"] = True
        try:
            with open(self._audit_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning("audit write failed: %s", exc)
