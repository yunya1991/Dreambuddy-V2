"""执行引擎域路由客户端（自 11 域迁入）。

包含两个 OkxClient 包装器：
    - DomainTaggedOkxClient：23 自进化域下单通道（evo23 标签 + 只读影子校验）
    - DomainRoutedOkxClient：按交易域在 NN 客户端与 23 客户端之间路由

依赖边界：本模块只依赖传入的 client / gateway 对象，不 import 11 的任何模块，
保证依赖方向为 11 → 22 → 13。
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

# 交易域标签：13→16→22→11 执行链路只属于神经网络系统；23 自进化域经 11 下单
# 不走该链路，但必须带 "23域" 标签，用于与神经网络系统做区分对照。
EVOLUTION_DOMAIN_TAG = "23域"
EVOLUTION_OKX_TAG = "evo23"  # OKX order tag 仅允许字母/数字且 ≤16 字符，中文无法写入
NN_OKX_TAG = "yijingsim"  # 神经网络系统沿用默认标签


def tag_reason(reason: str, domain_tag: str = EVOLUTION_DOMAIN_TAG) -> str:
    """给下单 reason 加域前缀（幂等），保证审计/日志可区分交易域。"""
    prefix = f"[{domain_tag}]"
    _r = str(reason or "")
    return _r if _r.startswith(prefix) else f"{prefix}{_r}"


def shadow_decision(action: str, inst_id: str, pos_side: str, reason: str, sz: Any = None) -> dict:
    """构造 13 只读影子校验用的决策（source 固定 23-evolution）。"""
    _pos_side = str(pos_side or "").lower()
    direction = _pos_side if _pos_side in ("long", "short") else "long"
    return {
        "signal_id": f"23-evolution|{int(time.time() * 1000)}",
        "source": "23-evolution",
        "symbol": str(inst_id or "MULTI"),
        "direction": direction,
        "confidence": 0.5,
        "action": action,
        "sz": sz,
        "pos_side": _pos_side or None,
        "reason": tag_reason(reason),
    }


class DomainTaggedOkxClient:
    """23 域下单客户端：evo23 标签 + [23域] reason + 22 Gateway 唯一执行。

    - 注入 OKX tag=evo23、reason 前缀 [23域]
    - 传入 ``gateway`` 时：所有写操作提交 22 TradeExecutionGateway（13→16→22→raw），
      不再直连 raw；``decision_id`` / ``expires_at`` 缺失时按 23 域兜底规则补齐
    - 仅传 ``shadow_gateway`` 时：保留旧的 13 只读影子校验 + raw 直连（回滚用）
    - 非交易方法透传给 raw client
    """

    def __init__(
        self,
        raw: Any,
        shadow_gateway: Any = None,
        okx_tag: str = EVOLUTION_OKX_TAG,
        domain_tag: str = EVOLUTION_DOMAIN_TAG,
        gateway: Any = None,
    ) -> None:
        object.__setattr__(self, "_raw", raw)
        object.__setattr__(self, "_shadow_gw", shadow_gateway)
        object.__setattr__(self, "_okx_tag", okx_tag)
        object.__setattr__(self, "_domain_tag", domain_tag)
        object.__setattr__(self, "_gateway", gateway)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_raw"), name)

    # ── 执行权：有 gateway 时必须经 gateway ──────────────────────────
    def _submit_via_gateway(
        self,
        action: str,
        inst_id: Any,
        pos_side: str,
        reason: str,
        sz: Any = None,
        *,
        decision_id: Any = None,
        expires_at: Any = None,
        px: Any = None,
        sl_px: Any = None,
        tp_px: Any = None,
    ) -> Any:
        gw = object.__getattribute__(self, "_gateway")
        if gw is None:
            return None
        decision = shadow_decision(action, inst_id, pos_side, reason, sz)
        decision["source"] = "23-evolution"
        decision["decision_id"] = (
            str(decision_id)
            if decision_id
            else (f"dec-23-{inst_id or 'MULTI'}-{action}-{uuid.uuid4().hex[:8]}")
        )
        decision["expires_at"] = (
            str(expires_at) if expires_at else datetime.now(timezone.utc).isoformat()
        )
        decision["px"] = px
        decision["sl_px"] = sl_px
        decision["tp_px"] = tp_px
        decision["payload"] = {
            "tag": object.__getattribute__(self, "_okx_tag"),
            "domain": "23",
        }
        try:
            res = gw.submit(decision)
        except Exception as exc:  # noqa: BLE001 — 网关异常 fail-closed
            return {"ok": False, "error": f"gateway_exc:{exc}"}
        if not getattr(res, "executed", False):
            if getattr(res, "passed", False) and getattr(res, "order_result", None) is not None:
                return res.order_result
            return {
                "ok": False,
                "rejected": True,
                "error": str(getattr(res, "reason", "rejected")),
                "reason_code": str(getattr(res, "reason_code", "")),
                "decision_id": decision["decision_id"],
            }
        out = dict(getattr(res, "order_result", None) or {})
        out.setdefault("ok", True)
        out["decision_id"] = decision["decision_id"]
        out["sltp_result"] = getattr(res, "sltp_result", None)
        return out

    def _usdt_to_sz(self, inst_id: Any, usdt_amount: Any) -> Any:
        if usdt_amount is None:
            return None
        fn = getattr(object.__getattribute__(self, "_raw"), "_usdt_to_sz", None)
        if callable(fn):
            try:
                return fn(inst_id, float(usdt_amount))
            except Exception:  # noqa: BLE001 — 换算失败交给网关拒单
                return None
        return None

    def _shadow_check(
        self, action: str, inst_id: Any, pos_side: str, reason: str, sz: Any = None
    ) -> None:
        gw = object.__getattribute__(self, "_shadow_gw")
        if gw is None:
            return
        try:
            gw.submit(shadow_decision(action, inst_id, pos_side, reason, sz))
        except Exception:
            pass  # 只读校验失败不影响真实下单

    def market_open_long(
        self, inst_id: str = None, usdt_amount: float = None, reason: str = "", **kwargs: Any
    ) -> Dict:
        self._shadow_check("open", inst_id, "long", reason)
        _via = self._submit_via_gateway(
            "open",
            inst_id,
            "long",
            reason,
            self._usdt_to_sz(inst_id, usdt_amount),
            decision_id=kwargs.get("decision_id"),
            expires_at=kwargs.get("expires_at"),
        )
        if _via is not None:
            return _via
        return self._raw.market_open_long(
            inst_id, usdt_amount=usdt_amount, reason=tag_reason(reason), tag=self._okx_tag
        )

    def market_open_short(
        self, inst_id: str = None, usdt_amount: float = None, reason: str = "", **kwargs: Any
    ) -> Dict:
        self._shadow_check("open", inst_id, "short", reason)
        _via = self._submit_via_gateway(
            "open",
            inst_id,
            "short",
            reason,
            self._usdt_to_sz(inst_id, usdt_amount),
            decision_id=kwargs.get("decision_id"),
            expires_at=kwargs.get("expires_at"),
        )
        if _via is not None:
            return _via
        return self._raw.market_open_short(
            inst_id, usdt_amount=usdt_amount, reason=tag_reason(reason), tag=self._okx_tag
        )

    def market_close_long(self, inst_id: str = None, reason: str = "", **kwargs: Any) -> Dict:
        self._shadow_check("close", inst_id, "long", reason)
        _via = self._submit_via_gateway(
            "close",
            inst_id,
            "long",
            reason,
            kwargs.get("sz"),
            decision_id=kwargs.get("decision_id"),
            expires_at=kwargs.get("expires_at"),
        )
        if _via is not None:
            return _via
        return self._raw.market_close_long(inst_id, reason=tag_reason(reason), tag=self._okx_tag)

    def market_close_short(self, inst_id: str = None, reason: str = "", **kwargs: Any) -> Dict:
        self._shadow_check("close", inst_id, "short", reason)
        _via = self._submit_via_gateway(
            "close",
            inst_id,
            "short",
            reason,
            kwargs.get("sz"),
            decision_id=kwargs.get("decision_id"),
            expires_at=kwargs.get("expires_at"),
        )
        if _via is not None:
            return _via
        return self._raw.market_close_short(inst_id, reason=tag_reason(reason), tag=self._okx_tag)

    def reduce_position(
        self,
        inst_id: str = None,
        pos_side: str = "long",
        reduce_ratio: float = 0.5,
        reason: str = "",
        **kwargs: Any,
    ) -> Dict:
        self._shadow_check("reduce", inst_id, pos_side, reason)
        _via = self._submit_via_gateway(
            "reduce",
            inst_id,
            pos_side,
            reason,
            kwargs.get("sz"),
            decision_id=kwargs.get("decision_id"),
            expires_at=kwargs.get("expires_at"),
        )
        if _via is not None:
            return _via
        return self._raw.reduce_position(
            inst_id,
            pos_side=pos_side,
            reduce_ratio=reduce_ratio,
            reason=tag_reason(reason),
            tag=self._okx_tag,
        )

    def place_stop_loss_take_profit(
        self,
        inst_id: str = None,
        pos_side: str = "long",
        stop_loss_px: float = 0,
        take_profit_px: float = 0,
        sz: float = None,
        reason: str = "",
        **kwargs: Any,
    ) -> Dict:
        action = "stop_loss" if stop_loss_px else "take_profit"
        self._shadow_check(action, inst_id, pos_side, reason, sz)
        _via = self._submit_via_gateway(
            action,
            inst_id,
            pos_side,
            reason,
            sz,
            decision_id=kwargs.get("decision_id"),
            expires_at=kwargs.get("expires_at"),
            sl_px=stop_loss_px or None,
            tp_px=take_profit_px or None,
        )
        if _via is not None:
            return _via
        return self._raw.place_stop_loss_take_profit(
            inst_id=inst_id,
            pos_side=pos_side,
            stop_loss_px=stop_loss_px,
            take_profit_px=take_profit_px,
            sz=sz,
            reason=tag_reason(reason),
            tag=self._okx_tag,
        )

    def place_order(self, **kwargs: Any) -> Dict:
        _pos_side = str(kwargs.get("pos_side") or "").lower()
        _reason = str(kwargs.get("reason") or "")
        _action = "close" if kwargs.get("reduce_only") else "open"
        if kwargs.get("reduce_only") and kwargs.get("pos_side"):
            # 减仓语义：与持仓方向相反的 reduce_only 单
            _action = "reduce"
        self._shadow_check(_action, kwargs.get("inst_id"), _pos_side, _reason, kwargs.get("sz"))
        _via = self._submit_via_gateway(
            _action,
            kwargs.get("inst_id"),
            _pos_side,
            _reason,
            kwargs.get("sz"),
            decision_id=kwargs.get("decision_id"),
            expires_at=kwargs.get("expires_at"),
            px=kwargs.get("px") if kwargs.get("px") is not None else kwargs.get("price"),
        )
        if _via is not None:
            return _via
        kwargs["tag"] = self._okx_tag
        kwargs["reason"] = tag_reason(_reason)
        return self._raw.place_order(**kwargs)


class DomainRoutedOkxClient:
    """按交易域路由下单。

    - 23 自进化域（显式 domain="23" 或持仓 source_tag=evolution）→ evo client（raw + evo23）
    - 其他（神经网络系统）→ 13→16→22→11 链路的 RiskGatedOkxClient
    """

    def __init__(
        self,
        nn_client: Any,
        evo_client: Any,
        is_evolution_position: Any = None,
    ) -> None:
        object.__setattr__(self, "_nn", nn_client)
        object.__setattr__(self, "_evo", evo_client)
        object.__setattr__(self, "_is_evo_pos", is_evolution_position)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_nn"), name)

    def _pick(self, domain: Any, inst_id: Any) -> Any:
        if str(domain or "").strip().lower() in ("23", "23域", "evolution"):
            return object.__getattribute__(self, "_evo")
        fn = object.__getattribute__(self, "_is_evo_pos")
        if callable(fn) and inst_id:
            try:
                if fn(inst_id):
                    return object.__getattribute__(self, "_evo")
            except Exception:
                pass
        return object.__getattribute__(self, "_nn")

    @staticmethod
    def _split(kwargs: dict) -> tuple:
        _kw = dict(kwargs)
        return _kw.pop("domain", None), _kw

    def market_open_long(
        self, inst_id: str = None, usdt_amount: float = None, reason: str = "", **kwargs: Any
    ) -> Dict:
        domain, _kw = self._split(kwargs)
        return self._pick(domain, inst_id).market_open_long(
            inst_id, usdt_amount=usdt_amount, reason=reason, **_kw
        )

    def market_open_short(
        self, inst_id: str = None, usdt_amount: float = None, reason: str = "", **kwargs: Any
    ) -> Dict:
        domain, _kw = self._split(kwargs)
        return self._pick(domain, inst_id).market_open_short(
            inst_id, usdt_amount=usdt_amount, reason=reason, **_kw
        )

    def market_close_long(self, inst_id: str = None, reason: str = "", **kwargs: Any) -> Dict:
        domain, _kw = self._split(kwargs)
        return self._pick(domain, inst_id).market_close_long(inst_id, reason=reason, **_kw)

    def market_close_short(self, inst_id: str = None, reason: str = "", **kwargs: Any) -> Dict:
        domain, _kw = self._split(kwargs)
        return self._pick(domain, inst_id).market_close_short(inst_id, reason=reason, **_kw)

    def reduce_position(
        self,
        inst_id: str = None,
        pos_side: str = "long",
        reduce_ratio: float = 0.5,
        reason: str = "",
        **kwargs: Any,
    ) -> Dict:
        domain, _kw = self._split(kwargs)
        return self._pick(domain, inst_id).reduce_position(
            inst_id, pos_side=pos_side, reduce_ratio=reduce_ratio, reason=reason, **_kw
        )

    def place_stop_loss_take_profit(
        self,
        inst_id: str = None,
        pos_side: str = "long",
        stop_loss_px: float = 0,
        take_profit_px: float = 0,
        sz: float = None,
        reason: str = "",
        **kwargs: Any,
    ) -> Dict:
        domain, _kw = self._split(kwargs)
        return self._pick(domain, inst_id).place_stop_loss_take_profit(
            inst_id=inst_id,
            pos_side=pos_side,
            stop_loss_px=stop_loss_px,
            take_profit_px=take_profit_px,
            sz=sz,
            reason=reason,
            **_kw,
        )

    def place_order(self, **kwargs: Any) -> Dict:
        domain, _kw = self._split(kwargs)
        return self._pick(domain, _kw.get("inst_id")).place_order(**_kw)


__all__ = [
    "EVOLUTION_DOMAIN_TAG",
    "EVOLUTION_OKX_TAG",
    "NN_OKX_TAG",
    "DomainRoutedOkxClient",
    "DomainTaggedOkxClient",
    "shadow_decision",
    "tag_reason",
]
