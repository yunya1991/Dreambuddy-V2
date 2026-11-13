"""执行引擎域路由客户端（自 11 域迁入）。

包含两个 OkxClient 包装器：
    - DomainTaggedOkxClient：23 自进化域下单通道（evo23 标签 + 只读影子校验）
    - DomainRoutedOkxClient：按交易域在 NN 客户端与 23 客户端之间路由

依赖边界：本模块只依赖传入的 client / gateway 对象，不 import 11 的任何模块，
保证依赖方向为 11 → 22 → 13。
"""

from __future__ import annotations

import time
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
    """23 域下单客户端：raw client + evo23 标签 + 13 只读影子校验。

    - 所有下单方法注入 OKX tag=evo23、reason 前缀 [23域]
    - 下单前先调 shadow gateway 跑 13 定审并落审计，**不阻断订单**
    - 非交易方法透传给 raw client
    """

    def __init__(
        self,
        raw: Any,
        shadow_gateway: Any = None,
        okx_tag: str = EVOLUTION_OKX_TAG,
        domain_tag: str = EVOLUTION_DOMAIN_TAG,
    ) -> None:
        object.__setattr__(self, "_raw", raw)
        object.__setattr__(self, "_shadow_gw", shadow_gateway)
        object.__setattr__(self, "_okx_tag", okx_tag)
        object.__setattr__(self, "_domain_tag", domain_tag)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_raw"), name)

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
        return self._raw.market_open_long(
            inst_id, usdt_amount=usdt_amount, reason=tag_reason(reason), tag=self._okx_tag
        )

    def market_open_short(
        self, inst_id: str = None, usdt_amount: float = None, reason: str = "", **kwargs: Any
    ) -> Dict:
        self._shadow_check("open", inst_id, "short", reason)
        return self._raw.market_open_short(
            inst_id, usdt_amount=usdt_amount, reason=tag_reason(reason), tag=self._okx_tag
        )

    def market_close_long(self, inst_id: str = None, reason: str = "", **kwargs: Any) -> Dict:
        self._shadow_check("close", inst_id, "long", reason)
        return self._raw.market_close_long(inst_id, reason=tag_reason(reason), tag=self._okx_tag)

    def market_close_short(self, inst_id: str = None, reason: str = "", **kwargs: Any) -> Dict:
        self._shadow_check("close", inst_id, "short", reason)
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
        self._shadow_check(
            "close" if kwargs.get("reduce_only") else "open",
            kwargs.get("inst_id"),
            _pos_side,
            str(kwargs.get("reason") or ""),
            kwargs.get("sz"),
        )
        kwargs["tag"] = self._okx_tag
        kwargs["reason"] = tag_reason(str(kwargs.get("reason") or ""))
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
