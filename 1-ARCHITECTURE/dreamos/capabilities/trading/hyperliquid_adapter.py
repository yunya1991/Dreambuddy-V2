"""HyperliquidClient adapter for 14-V15 compatibility.

Bridges the interface gap between 14-V15's expected client interface
(place_order) and HyperliquidClient's actual interface (open_long/open_short).

14-V15 expects:
    client.place_order(inst_id, side, sz, td_mode, pos_side) -> {"ok": bool, "data": {...}}

HyperliquidClient provides:
    client.open_long(coin, usdt_amount, leverage, tag) -> {"ok": bool, ...}
    client.open_short(coin, usdt_amount, leverage, tag) -> {"ok": bool, ...}
"""
from __future__ import annotations

from typing import Any, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class HyperliquidV15Adapter:
    """Adapter that makes HyperliquidClient compatible with 14-V15's client interface."""

    def __init__(self, hyperliquid_client):
        """Initialize adapter with HyperliquidClient instance.

        Args:
            hyperliquid_client: Instance of HyperliquidClient from aster_spot.py
        """
        self._client = hyperliquid_client
        self._default_leverage = 5

    def place_order(
        self,
        inst_id: str,
        side: str,
        sz: float,
        td_mode: str = "isolated",
        pos_side: str = "long",
        **kwargs
    ) -> Dict[str, Any]:
        """Adapt 14-V15's place_order to HyperliquidClient.

        Supports two order types:
        - Market order (default): uses open_long/open_short with IOC slippage
        - Limit order (ord_type='limit'): uses limit_order with GTC for grid addon
        - Reduce-only: supports close_position for partial/full close

        Args:
            inst_id: Instrument ID (e.g., "BTC-USDT-SWAP")
            side: "buy" or "sell"
            sz: Order size (contracts)
            td_mode: Trading mode (ignored, Hyperliquid uses isolated)
            pos_side: "long" or "short"
            **kwargs: ord_type ('limit'/'market'), px (limit price),
                     reduce_only (bool), tag (str), reason (str)

        Returns:
            Dict with "ok" and "data" keys matching 14-V15's expected format
        """
        coin = inst_id.split("-")[0] if "-" in inst_id else inst_id
        ord_type = kwargs.get("ord_type", "market")
        limit_px = kwargs.get("px")
        reduce_only = kwargs.get("reduce_only", False)
        tag = kwargs.get("tag", "v15")

        # Determine direction
        is_long = (side == "buy" and pos_side == "long") or (side == "sell" and pos_side == "short")
        is_buy = side == "buy"

        try:
            if ord_type == "limit" and limit_px and limit_px > 0:
                # Limit order (GTC) — for addon grid orders
                result = self._client.limit_order(
                    coin, is_buy, sz, limit_px,
                    leverage=self._default_leverage,
                    reduce_only=reduce_only,
                    tag=tag,
                )
            elif reduce_only:
                # Reduce-only market order — for position close
                result = self._client.market_order(
                    coin, is_buy, sz,
                    leverage=1,
                    reduce_only=True,
                    tag=tag,
                )
            else:
                # Market order — for initial position open
                px = self._client.get_mid_price(coin)
                usdt_amount = sz * px / self._default_leverage
                if is_long:
                    result = self._client.open_long(coin, usdt_amount, self._default_leverage, tag=tag)
                else:
                    result = self._client.open_short(coin, usdt_amount, self._default_leverage, tag=tag)

            # Adapt return format to 14-V15's expected format
            # 14-V15 extracts ord_id via: r.get('ord_id') or r.get('raw',{}).get('data',[{}])[0].get('ordId')
            # So we need ord_id at top level + raw.data[0].ordId for fallback
            if result.get("ok"):
                # Extract ord_id from response
                ord_id = result.get("ord_id", "")
                if not ord_id:
                    filled = result.get("filled", {})
                    if "resting" in filled:
                        ord_id = filled["resting"].get("oid", "")
                    elif "filled" in filled:
                        ord_id = filled["filled"].get("oid", "")
                return {
                    "ok": True,
                    "ord_id": ord_id,
                    "data": {
                        "order_id": ord_id,
                        "ord_id": ord_id,
                        "coin": coin,
                        "side": side,
                        "sz": sz,
                        "price": limit_px or result.get("px", 0),
                    },
                    "raw": {"data": [{"ordId": ord_id}]},
                }
            else:
                return {
                    "ok": False,
                    "error": result.get("error", "unknown_error"),
                    "data": {},
                    "raw": result.get("raw", {}),
                }

        except Exception as e:
            logger.error(f"Hyperliquid order failed: {e}")
            return {"ok": False, "error": str(e), "data": {}}

    def get_pending_orders(self, inst_id: str) -> Dict[str, Any]:
        """Adapt get_pending_orders to HyperliquidClient's get_open_orders.

        14-V15 uses this to check addon grid order status.
        """
        try:
            coin = inst_id.split("-")[0] if "-" in inst_id else inst_id
            orders = self._client.get_open_orders(coin)
            # Convert to 14-V15's expected format
            # Hyperliquid API returns: side as "A"(ask/sell) or "B"(bid/buy) string,
            # limitPx/sz as strings, oid as int
            formatted = []
            for o in orders:
                raw_side = o.get("side", "")
                # "A" = ask = sell, "B" = bid = buy
                side = "buy" if raw_side == "B" else "sell"
                # limitPx for limit orders, triggerPx for trigger orders
                px_str = o.get("limitPx") or o.get("triggerPx") or "0"
                sz_str = o.get("sz") or o.get("origSz") or "0"
                formatted.append({
                    "ord_id": o.get("oid", ""),
                    "inst_id": inst_id,
                    "side": side,
                    "sz": float(sz_str),
                    "px": float(px_str),
                    "ord_type": "limit" if o.get("limitPx") else "trigger",
                    "reduce_only": o.get("reduceOnly", False),
                    "state": "live",
                    "raw": o,
                })
            return {"ok": True, "data": formatted}
        except Exception as e:
            logger.error(f"Failed to get pending orders: {e}")
            return {"ok": True, "data": []}

    def get_order(self, inst_id: str, ord_id: str) -> Dict[str, Any]:
        """Adapt get_order to HyperliquidClient's get_open_orders.

        14-V15 uses this to check individual order status.
        """
        try:
            coin = inst_id.split("-")[0] if "-" in inst_id else inst_id
            orders = self._client.get_open_orders(coin)
            for o in orders:
                if str(o.get("oid")) == str(ord_id):
                    return {
                        "ok": True,
                        "data": {
                            "ord_id": o.get("oid", ""),
                            "inst_id": inst_id,
                            "state": o.get("orderStatus", "live"),
                            "sz": float(o.get("sz", "0")),
                            "px": float(o.get("limitPx", 0)) if o.get("limitPx") else float(o.get("triggerPx", 0)),
                            "raw": o,
                        }
                    }
            # Order not found in open orders — likely already filled or cancelled
            return {"ok": True, "data": {"ord_id": ord_id, "state": "not_found"}}
        except Exception as e:
            logger.error(f"Failed to get order: {e}")
            return {"ok": True, "data": {}}

    def cancel_order(self, inst_id: str, ord_id: str) -> Dict[str, Any]:
        """Cancel a single order (14-V15 expects this for grid management).

        14-V15 calls client.cancel_order(inst_id, ord_id) to cancel
        individual addon grid orders.
        """
        try:
            coin = inst_id.split("-")[0] if "-" in inst_id else inst_id
            result = self._client.cancel_order(coin, int(ord_id))
            return {"ok": result.get("ok", False), "data": result}
        except Exception as e:
            logger.error(f"Failed to cancel order: {e}")
            return {"ok": False, "error": str(e)}

    def place_stop_loss_take_profit(
        self,
        inst_id: str = None,
        sl_price: Optional[float] = None,
        tp_price: Optional[float] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Adapt place_stop_loss_take_profit to HyperliquidClient's set_tpsl_orders.

        14-V15 calls this with inst_id, sl_price, tp_price.
        HyperliquidClient.set_tpsl_orders needs coin, stop_loss_price, take_profit_price.
        """
        coin = inst_id.split("-")[0] if inst_id and "-" in inst_id else (inst_id or "")

        # 14-V15 passes TP/SL via various parameter names:
        #   stop_loss_px / take_profit_px (used in _sync_tp_sl_orders)
        #   stop_loss_price / take_profit_price (alternative)
        #   sl / tp (shorthand)
        if not sl_price:
            sl_price = (kwargs.get("stop_loss_px") or kwargs.get("stop_loss_price")
                        or kwargs.get("sl"))
        if not tp_price:
            tp_price = (kwargs.get("take_profit_px") or kwargs.get("take_profit_price")
                        or kwargs.get("tp"))

        if not sl_price and not tp_price:
            return {"ok": False, "error": "no_sl_or_tp_provided"}

        try:
            result = self._client.set_tpsl_orders(
                coin,
                stop_loss_price=sl_price if (sl_price and sl_price > 0) else None,
                take_profit_price=tp_price if (tp_price and tp_price > 0) else None,
                is_market=True
            )
            return {"ok": result.get("ok", False), "data": result}
        except Exception as e:
            logger.error(f"Failed to set TP/SL: {e}")
            return {"ok": False, "error": str(e)}

    def cancel_algo_orders(self, inst_id: str = None, **kwargs) -> Dict[str, Any]:
        """Cancel only TP/SL orders (reduceOnly=true), preserve addon grid orders.

        14-V15 calls this to cancel old TP/SL trigger orders
        before placing new ones. Previously this cancelled ALL orders
        including addon grid limit orders, causing addon grids to disappear.
        Now only cancels reduceOnly=true orders (TP/SL), preserving
        reduceOnly=false addon grid orders.
        """
        try:
            coin = inst_id.split("-")[0] if inst_id and "-" in inst_id else (inst_id or "")
            orders = self._client.get_open_orders(coin)
            cancelled = 0
            preserved = 0
            for o in orders:
                oid = o.get("oid")
                is_reduce_only = o.get("reduceOnly", False)
                if is_reduce_only:
                    # TP/SL order → cancel it
                    self._client.cancel_order(coin, oid)
                    cancelled += 1
                else:
                    # Addon grid order → preserve
                    preserved += 1
            logger.info(f"cancel_algo_orders({coin}): cancelled={cancelled} TP/SL, preserved={preserved} addon grid")
            return {"ok": True, "data": {"cancelled": cancelled, "preserved": preserved}}
        except Exception as e:
            logger.error(f"Failed to cancel algo orders: {e}")
            return {"ok": False, "error": str(e)}

    def get_balance(self) -> Dict[str, Any]:
        """Adapt get_balance to HyperliquidClient's get_account.

        14-V15's capital_manager calls client.get_balance() to get
        account equity, available balance, and used margin.

        Returns:
            Dict with ok, total_eq, avail_balance, used_margin
        """
        try:
            acct = self._client.get_account()
            total_eq = float(acct.get("margin", 0))
            avail_balance = float(acct.get("available", 0))
            used_margin = total_eq - avail_balance
            return {
                "ok": True,
                "total_eq": round(total_eq, 2),
                "avail_balance": round(avail_balance, 2),
                "used_margin": round(max(0, used_margin), 2),
            }
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            return {"ok": False, "total_eq": 0, "avail_balance": 0, "used_margin": 0}

    def get_all_positions(self) -> Dict[str, Any]:
        """Adapt get_all_positions to HyperliquidClient's get_account."""
        try:
            acct = self._client.get_account()
            positions = acct.get("positions", {})

            # Convert to 14-V15's expected format
            formatted_positions = []
            for coin, pos in positions.items():
                formatted_positions.append({
                    "inst_id": f"{coin}-USDT-SWAP",
                    "coin": coin,
                    "size": pos.get("size", 0),
                    "entry_price": pos.get("entry_price", 0),
                    "unrealized_pnl": pos.get("unrealized_pnl", 0),
                })

            return {"ok": True, "data": formatted_positions}
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return {"ok": False, "error": str(e), "data": []}
