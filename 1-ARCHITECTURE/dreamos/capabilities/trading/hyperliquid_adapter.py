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
        """Adapt 14-V15's place_order to HyperliquidClient's open_long/open_short.

        Args:
            inst_id: Instrument ID (e.g., "BTC-USDT-SWAP")
            side: "buy" or "sell"
            sz: Order size (contracts)
            td_mode: Trading mode (ignored, Hyperliquid uses isolated)
            pos_side: "long" or "short"
            **kwargs: Additional arguments (ignored)

        Returns:
            Dict with "ok" and "data" keys matching 14-V15's expected format
        """
        # Extract coin from inst_id (e.g., "BTC-USDT-SWAP" -> "BTC")
        coin = inst_id.split("-")[0] if "-" in inst_id else inst_id

        # Convert size to USDT amount
        # 14-V15's sz is in contracts, HyperliquidClient needs USDT amount
        # We need to get current price to convert
        try:
            px = self._client.get_mid_price(coin)
            usdt_amount = sz * px / self._default_leverage
        except Exception as e:
            logger.error(f"Failed to get mid price for {coin}: {e}")
            return {"ok": False, "error": f"price_fetch_failed: {e}"}

        # Determine direction
        is_long = (side == "buy" and pos_side == "long") or (side == "sell" and pos_side == "short")

        try:
            if is_long:
                result = self._client.open_long(coin, usdt_amount, self._default_leverage, tag="v15")
            else:
                result = self._client.open_short(coin, usdt_amount, self._default_leverage, tag="v15")

            # Adapt return format to 14-V15's expected format
            if result.get("ok"):
                return {
                    "ok": True,
                    "data": {
                        "order_id": result.get("order_id", ""),
                        "coin": coin,
                        "side": side,
                        "sz": sz,
                        "usdt_amount": usdt_amount,
                        "price": px,
                    }
                }
            else:
                return {
                    "ok": False,
                    "error": result.get("error", "unknown_error"),
                    "data": {}
                }

        except Exception as e:
            logger.error(f"Hyperliquid order failed: {e}")
            return {"ok": False, "error": str(e), "data": {}}

    def get_pending_orders(self, inst_id: str) -> Dict[str, Any]:
        """Adapt get_pending_orders (14-V15 expects this for grid addon status).

        HyperliquidClient doesn't have direct pending orders query,
        return empty list for now.
        """
        return {"ok": True, "data": []}

    def get_order(self, inst_id: str, ord_id: str) -> Dict[str, Any]:
        """Adapt get_order (14-V15 expects this for order status).

        HyperliquidClient doesn't have direct order query,
        return empty dict for now.
        """
        return {"ok": True, "data": {}}

    def place_stop_loss_take_profit(
        self,
        inst_id: str,
        sl_price: Optional[float] = None,
        tp_price: Optional[float] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Adapt place_stop_loss_take_profit to HyperliquidClient's set_tpsl_orders."""
        coin = inst_id.split("-")[0] if "-" in inst_id else inst_id

        try:
            result = self._client.set_tpsl_orders(
                coin,
                stop_loss_price=sl_price,
                take_profit_price=tp_price,
                is_market=True
            )
            return {"ok": result.get("ok", False), "data": result}
        except Exception as e:
            logger.error(f"Failed to set TP/SL: {e}")
            return {"ok": False, "error": str(e)}

    def cancel_algo_orders(self, inst_id: str = None, **kwargs) -> Dict[str, Any]:
        """Adapt cancel_algo_orders to HyperliquidClient's cancel_all_tpsl.

        14-V15 calls this to cancel old TP/SL trigger orders
        before placing new ones.
        """
        try:
            result = self._client.cancel_all_tpsl()
            return {"ok": True, "data": result}
        except Exception as e:
            logger.error(f"Failed to cancel algo orders: {e}")
            return {"ok": False, "error": str(e)}

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
